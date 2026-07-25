"""
ゲームのサウンドトラックを Last.fm で検索し、
アルバムタグを集計して game_tags テーブルに保存する。

検索順:
  1. album.search("ゲーム名") / ("ゲーム名 ost") / ("ゲーム名 soundtrack") で一致するアルバムを探す
  2. 見つからなければ、作曲家名を組み込んで再検索
     ("ゲーム名 作曲家名") / ("ゲーム名 ost 作曲家名") を各作曲家で試す
  3. それも失敗 → games.tags_locked = TRUE をセットしてスキップ（以後の日次バッチで再試行しない）

使い方:
  python3 scripts/import_game_tags.py [--limit 200] [--overwrite]

  --overwrite を指定すると tags_locked フラグを無視して全ゲームを再試行する。

依存:
  pip install requests python-dotenv supabase
"""

import argparse
import os
import time
import requests
from dotenv import load_dotenv
from collections import Counter

load_dotenv(dotenv_path=".env")

try:
    from supabase import create_client
except ImportError:
    print("pip install requests python-dotenv supabase")
    raise SystemExit(1)

LASTFM_API_KEY = os.environ["LASTFM_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
UPSTASH_REDIS_URL = os.environ.get("UPSTASH_REDIS_URL", "")
UPSTASH_REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_TOKEN", "")

db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
LASTFM_BASE = "https://ws.audioscrobbler.com/2.0/"
LFM_WAIT = 0.3

http = requests.Session()
http.headers.update({"User-Agent": "GameMusicDiscovery/0.1.0 (hobby project)"})


# ── キャッシュクリア ──────────────────────────────────────────────────────────

def clear_cache(tagged_game_ids: list[str], tagged_tag_ids: list[str]) -> None:
    """タグ更新後に関連する Redis キャッシュを削除する。"""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return
    headers = {"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}
    keys = []
    for gid in tagged_game_ids:
        keys.append(f"games:detail:{gid}")
        keys.append(f"games:similar:{gid}:8")
    for tid in tagged_tag_ids:
        for limit in (20, 50, 100):
            keys.append(f"games:list:{tid}:{limit}")
    for limit in (20, 50, 100):
        keys.append(f"games:list:all:{limit}")

    if not keys:
        return
    # POST body で送信（キーが多いと GET URL が長すぎて失敗するため）
    try:
        resp = http.post(
            f"{UPSTASH_REDIS_URL}/",
            headers=headers,
            json=["del"] + keys,
            timeout=5,
        )
        print(f"キャッシュクリア: {resp.json().get('result', '?')} 件削除")
    except Exception as e:
        print(f"キャッシュクリア失敗（無視）: {e}")

# mood_tags.name → Last.fm タグ名キーワードのマッピング（小文字で部分一致）
KEYWORD_MAP: dict[str, list[str]] = {
    "orchestral":  ["orchestral", "orchestra", "symphonic", "classical", "philharmonic", "cinematic orchestral"],
    "dark":        ["dark", "ominous", "sinister", "horror", "eerie", "dark ambient", "industrial", "gothic"],
    "ambient":     ["ambient", "atmospheric", "soundscape", "drone", "space ambient", "new age", "new-age"],
    "upbeat":      ["upbeat", "happy", "cheerful", "fun", "lighthearted", "uplifting", "playful", "pop"],
    "chiptune":    ["chiptune", "8-bit", "chip music", "chiptunes", "8bit", "bitpop", "game boy", "tracker"],
    "jazz":        ["jazz", "blues", "jazz fusion", "bossa nova", "swing", "bebop"],
    "electronic":  ["electronic", "electronica", "synth", "synthwave", "electro", "techno", "edm", "dance",
                    "trance", "drum and bass", "dnb", "drum & bass", "dubstep", "future bass", "house"],
    "acoustic":    ["acoustic", "piano", "guitar", "unplugged", "fingerpicking", "strings"],
    "epic":        ["epic", "cinematic", "heroic", "majestic", "triumphant", "grandiose"],
    "melancholic": ["melancholic", "melancholy", "sad", "emotional", "nostalgic", "bittersweet", "somber", "wistful",
                    "post-rock", "shoegaze"],
    "relaxing":    ["relaxing", "relaxation", "calm", "chill", "peaceful", "soothing", "mellow", "lo-fi", "meditation"],
    "intense":     ["intense", "aggressive", "energetic", "adrenaline", "action", "battle", "tension", "fast"],
    "folk":        ["folk", "world music", "ethnic", "traditional", "celtic", "tribal", "acoustic folk", "country", "western"],
    "metal":       ["metal", "heavy metal", "hard rock", "progressive rock", "power metal", "doom metal",
                    "rock", "j-rock", "alternative rock", "prog rock", "grunge", "punk"],
    "vocal":        ["vocal", "vocals", "singer", "singing", "choir", "choral", "a cappella", "j-pop", "k-pop"],
    "instrumental": ["instrumental", "instrumental music"],
}

MIN_TAG_COUNT = 1

# アルバム名に含まれていれば「OSTと判断できる」キーワード
_OST_NAME_KEYWORDS = (
    "soundtrack", "ost", "original score", "original soundtrack",
    "game music", "music from", "video game", "bgm",
)


# ── Last.fm API ───────────────────────────────────────────────────────────────

def _lastfm_album_search(
    query: str,
    game_title: str,
    known_composers: list[str] | None = None,
) -> tuple[str, str] | None:
    """album.search でタイトル一致するアルバムを返す。

    誤マッチ対策として、タイトル一致したアルバムに対して以下のいずれかを要求する:
      1. クエリ自体に "ost" / "soundtrack" が含まれる（絞り込み済み）
      2. アルバム名に _OST_NAME_KEYWORDS のいずれかが含まれる
      3. アルバムのアーティスト名が known_composers のいずれかと部分一致する
    いずれも満たさない場合、非ゲームアルバムへの誤マッチとみなしてスキップする。
    """
    query_has_ost = any(kw in query.lower() for kw in ("ost", "soundtrack"))
    composers_lower = [c.lower() for c in (known_composers or [])]

    time.sleep(LFM_WAIT)
    resp = http.get(LASTFM_BASE, params={
        "method": "album.search",
        "album": query,
        "api_key": LASTFM_API_KEY,
        "format": "json",
        "limit": 15,
    }, timeout=10)
    if not resp.ok:
        return None
    data = resp.json()
    if "error" in data:
        return None
    albums = data.get("results", {}).get("albummatches", {}).get("album", []) or []
    title_lower = game_title.lower()
    for album in albums:
        name = album.get("name", "")
        artist = album.get("artist", "")
        if not (title_lower in name.lower() or name.lower() in title_lower):
            continue

        # 条件1: クエリに ost/soundtrack が含まれる → 採用
        if query_has_ost:
            return name, artist

        # 条件2: アルバム名に OST キーワードが含まれる → 採用
        if any(kw in name.lower() for kw in _OST_NAME_KEYWORDS):
            return name, artist

        # 条件3: アーティスト名が既知の作曲家と部分一致 → 採用
        artist_lower = artist.lower()
        if composers_lower and any(
            c in artist_lower or artist_lower in c for c in composers_lower
        ):
            return name, artist

        # いずれも満たさない → 誤マッチの可能性があるためスキップ
        print(f"  [誤マッチ候補スキップ] '{name}' / '{artist}' — OST 未確認・作曲家不一致")
    return None


def search_album(game_title: str, known_composers: list[str] | None = None) -> tuple[str, str] | None:
    """album.search でゲームタイトルに一致するアルバムを探す。
    "ゲーム名" → "ゲーム名 ost" → "ゲーム名 soundtrack" の順で試す。
    known_composers は誤マッチ判定に使用する。
    Returns (album_name, artist_name) or None。
    """
    for query in [game_title, f"{game_title} ost", f"{game_title} soundtrack"]:
        result = _lastfm_album_search(query, game_title, known_composers)
        if result:
            return result
    return None


def get_game_composers(game_id: str) -> list[str]:
    """ゲームに紐付く作曲家名リストを返す（重複除去済み）。"""
    track_rows = (
        db.table("tracks").select("id").eq("game_id", game_id).execute().data or []
    )
    if not track_rows:
        return []
    track_ids = [r["id"] for r in track_rows]
    tc_rows = (
        db.table("track_composers")
        .select("composer_id")
        .in_("track_id", track_ids)
        .execute()
        .data or []
    )
    if not tc_rows:
        return []
    composer_ids = list({r["composer_id"] for r in tc_rows})
    c_rows = (
        db.table("composers")
        .select("name")
        .in_("id", composer_ids)
        .execute()
        .data or []
    )
    return [r["name"] for r in c_rows]


def search_album_with_composers(game_title: str, composer_names: list[str]) -> tuple[str, str] | None:
    """作曲家名を検索クエリに加えて album.search を再試行する。
    "ゲーム名 作曲家名" → "ゲーム名 ost 作曲家名" の順で各作曲家を試す。
    Returns (album_name, artist_name) or None。
    """
    for composer in composer_names:
        for query in [f"{game_title} {composer}", f"{game_title} ost {composer}"]:
            result = _lastfm_album_search(query, game_title, composer_names)
            if result:
                return result
    return None


def fetch_album_tags(album: str, artist: str) -> list[dict]:
    """Last.fm album.getTopTags でアルバムタグを取得。"""
    time.sleep(LFM_WAIT)
    resp = http.get(LASTFM_BASE, params={
        "method": "album.getTopTags",
        "album": album,
        "artist": artist,
        "api_key": LASTFM_API_KEY,
        "format": "json",
        "autocorrect": "1",
    }, timeout=10)
    if not resp.ok:
        return []
    data = resp.json()
    if "error" in data:
        return []
    tags = data.get("toptags", {}).get("tag", []) or []
    return [t for t in tags if t.get("name", "").lower() not in ("all",)]


# ── タグ集計・マッピング ───────────────────────────────────────────────────────

def map_to_mood_tags(tag_list: list[dict], mood_tag_index: dict[str, dict]) -> list[tuple[str, float]]:
    """Last.fm タグを mood_tags にマッピング。Returns: [(tag_id, confidence), ...]"""
    if not tag_list:
        return []

    counter: Counter = Counter()
    for t in tag_list:
        name = t.get("name", "").lower().strip()
        count = int(t.get("count", 1))
        if name and count >= MIN_TAG_COUNT:
            counter[name] = count

    if not counter:
        return []

    max_score = max(counter.values()) or 1
    matched: dict[str, float] = {}

    for lfm_name, score in counter.items():
        confidence = max(0.1, min(1.0, score / max_score))
        for mood_name, keywords in KEYWORD_MAP.items():
            if mood_name not in mood_tag_index:
                continue
            if any(kw in lfm_name or lfm_name in kw for kw in keywords):
                tag_id = mood_tag_index[mood_name]["id"]
                if tag_id not in matched or confidence > matched[tag_id]:
                    matched[tag_id] = confidence

    return list(matched.items())


def get_unmatched_tags(tag_list: list[dict]) -> list[str]:
    """KEYWORD_MAP にマッチしなかった Last.fm タグ名を返す（count >= MIN_TAG_COUNT のもの）。
    CI ログで「どのタグが取りこぼされているか」を把握するために使う。
    """
    result = []
    for t in tag_list:
        name_lower = t.get("name", "").lower().strip()
        if not name_lower or name_lower in ("all",):
            continue
        if int(t.get("count", 1)) < MIN_TAG_COUNT:
            continue
        matched_any = any(
            any(kw in name_lower or name_lower in kw for kw in keywords)
            for keywords in KEYWORD_MAP.values()
        )
        if not matched_any:
            result.append(t.get("name", name_lower))
    return result


# ── DB 操作 ───────────────────────────────────────────────────────────────────

def get_games_without_tags(limit: int, overwrite: bool) -> list[dict]:
    """タグ付け対象ゲームを取得。

    tags_locked=FALSE かつ未タグのゲームのみを対象とする。
    全件 locked 済みまたはタグ登録済みの場合は空リストを返してスキップする。
    overwrite=True の場合は locked フラグを無視して全ゲームを返す。
    """
    if overwrite:
        return (
            db.table("games")
            .select("id, title")
            .limit(limit)
            .execute()
            .data or []
        )

    tagged_ids = {
        row["game_id"]
        for row in (db.table("game_tags").select("game_id").execute().data or [])
    }

    unlocked = (
        db.table("games")
        .select("id, title")
        .eq("tags_locked", False)
        .execute()
        .data or []
    )
    return [g for g in unlocked if g["id"] not in tagged_ids][:limit]


def lock_game_tags(game_id: str) -> None:
    """tags_locked = TRUE をセット。以後の日次バッチでスキップされる。"""
    db.table("games").update({"tags_locked": True}).eq("id", game_id).execute()


# ── メインループ ───────────────────────────────────────────────────────────────

def run(limit: int, overwrite: bool) -> None:
    mood_tags_rows = db.table("mood_tags").select("id, name").execute().data or []
    mood_tag_index: dict[str, dict] = {row["name"]: row for row in mood_tags_rows}
    print(f"mood_tags: {len(mood_tag_index)} 件ロード済み\n")

    games = get_games_without_tags(limit, overwrite)

    if not games:
        print("タグ付け対象のゲームがありません。")
        return

    print(f"{len(games)} 件のゲームにタグを付与します...\n")
    total_tagged = 0
    total_locked = 0
    total_composer_fallback = 0
    tagged_game_ids: list[str] = []
    tagged_tag_ids: list[str] = []
    locked_titles: list[str] = []
    global_unmatched: Counter = Counter()

    for i, game in enumerate(games, 1):
        title = game["title"]
        print(f"[{i}/{len(games)}] {title}")

        composers = get_game_composers(game["id"])
        album_match = search_album(title, composers)
        if not album_match:
            if composers:
                print(f"  作曲家フォールバック: {', '.join(composers)}")
                album_match = search_album_with_composers(title, composers)
                if album_match:
                    total_composer_fallback += 1
        if not album_match:
            print("  → Last.fm アルバム見つからず → locked")
            lock_game_tags(game["id"])
            locked_titles.append(title)
            total_locked += 1
            print()
            continue

        album_name, artist_name = album_match
        tags = fetch_album_tags(album_name, artist_name)
        if not tags:
            print(f"  → アルバム '{album_name}' タグなし → locked")
            lock_game_tags(game["id"])
            locked_titles.append(title)
            total_locked += 1
            print()
            continue

        print(f"  アルバム: '{album_name}' / '{artist_name}'")

        mapped = map_to_mood_tags(tags, mood_tag_index)
        unmatched = get_unmatched_tags(tags)
        if unmatched:
            global_unmatched.update(unmatched)

        if not mapped:
            print(f"  → ムードタグにマッチせず → locked")
            if unmatched:
                print(f"     未マッチタグ: {unmatched[:10]}")
            lock_game_tags(game["id"])
            locked_titles.append(title)
            total_locked += 1
            print()
            continue

        rows = [
            {"game_id": game["id"], "tag_id": tid, "confidence": conf, "added_by": "system"}
            for tid, conf in mapped
        ]
        db.table("game_tags").upsert(rows, on_conflict="game_id,tag_id").execute()
        # is_discoverable は trg_discoverable_on_game_tags トリガーが自動更新するため不要
        tag_names = [
            next((n for n, d in mood_tag_index.items() if d["id"] == tid), tid)
            for tid, _ in mapped
        ]
        print(f"  → タグ付与: {', '.join(tag_names)}")
        tagged_game_ids.append(game["id"])
        tagged_tag_ids.extend(tid for tid, _ in mapped)
        total_tagged += 1
        print()

    print(f"完了 — タグ付与: {total_tagged} 件（作曲家フォールバック: {total_composer_fallback} 件）, locked 追加: {total_locked} 件")
    if locked_titles:
        print("  locked ゲーム（再試行するには tags_locked=FALSE に更新）:")
        for t in locked_titles:
            print(f"    - {t}")

    if global_unmatched:
        print("\n  ── 未マッチ Last.fm タグ Top 15（KEYWORD_MAP 拡充の参考に）──")
        for tag_name, count in global_unmatched.most_common(15):
            print(f"    {count:3d}回  {tag_name}")

    if tagged_game_ids:
        clear_cache(tagged_game_ids, list(set(tagged_tag_ids)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ゲームサントラのアルバムタグを Last.fm から取得して game_tags に保存"
    )
    parser.add_argument("--limit", type=int, default=200,
                        help="処理するゲーム数 (デフォルト: 200)")
    parser.add_argument("--overwrite", action="store_true",
                        help="locked フラグを無視して全ゲームを再試行する")
    args = parser.parse_args()
    run(args.limit, args.overwrite)
