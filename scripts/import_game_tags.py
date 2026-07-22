"""
ゲームのサウンドトラックを Last.fm で検索し、
アルバムタグを集計して game_tags テーブルに保存する。

検索順:
  1. album.search でゲームタイトルに一致するアルバムを探し、最上位のタグを取得
  2. それも失敗 → games.tags_locked = TRUE をセットしてスキップ（以後の日次バッチで再試行しない）

MusicBrainz は精度が低いため廃止済み。

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
    url = f"{UPSTASH_REDIS_URL}/del/{'/'.join(keys)}"
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        print(f"キャッシュクリア: {resp.json().get('result', '?')} 件削除")
    except Exception as e:
        print(f"キャッシュクリア失敗（無視）: {e}")

# mood_tags.name → Last.fm タグ名キーワードのマッピング（小文字で部分一致）
KEYWORD_MAP: dict[str, list[str]] = {
    "orchestral":  ["orchestral", "orchestra", "symphonic", "classical", "philharmonic", "cinematic orchestral"],
    "dark":        ["dark", "ominous", "sinister", "horror", "eerie", "dark ambient"],
    "ambient":     ["ambient", "atmospheric", "soundscape", "drone", "space ambient"],
    "upbeat":      ["upbeat", "happy", "cheerful", "fun", "lighthearted", "uplifting", "playful"],
    "chiptune":    ["chiptune", "8-bit", "chip music", "chiptunes", "8bit", "bitpop"],
    "jazz":        ["jazz", "blues", "jazz fusion", "bossa nova", "swing", "bebop"],
    "electronic":  ["electronic", "electronica", "synth", "synthwave", "electro", "techno", "edm", "dance"],
    "acoustic":    ["acoustic", "piano", "guitar", "unplugged", "fingerpicking"],
    "epic":        ["epic", "cinematic", "heroic", "majestic", "triumphant", "grandiose"],
    "melancholic": ["melancholic", "melancholy", "sad", "emotional", "nostalgic", "bittersweet", "somber", "wistful"],
    "relaxing":    ["relaxing", "relaxation", "calm", "chill", "peaceful", "soothing", "mellow", "lo-fi"],
    "intense":     ["intense", "aggressive", "energetic", "adrenaline", "action", "battle", "tension", "fast"],
    "folk":        ["folk", "world music", "ethnic", "traditional", "celtic", "tribal", "acoustic folk"],
    "metal":       ["metal", "heavy metal", "hard rock", "progressive rock", "power metal", "doom metal"],
    "vocal":       ["vocal", "vocals", "singer", "singing", "choir", "choral", "a cappella"],
}

MIN_TAG_COUNT = 1


# ── Last.fm API ───────────────────────────────────────────────────────────────

def _lastfm_album_search(query: str, game_title: str) -> tuple[str, str] | None:
    """album.search でタイトル一致するアルバムを返す。"""
    time.sleep(LFM_WAIT)
    resp = requests.get(LASTFM_BASE, params={
        "method": "album.search",
        "album": query,
        "api_key": LASTFM_API_KEY,
        "format": "json",
        "limit": 5,
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
        if title_lower in name.lower() or name.lower() in title_lower:
            return name, artist
    return None


def search_album(game_title: str) -> tuple[str, str] | None:
    """album.search でゲームタイトルに一致するアルバムを探す。
    "ゲーム名 ost" → "ゲーム名" の順で試す。
    Returns (album_name, artist_name) or None。
    """
    for query in [game_title, f"{game_title} ost"]:
        result = _lastfm_album_search(query, game_title)
        if result:
            return result
    return None


def fetch_album_tags(album: str, artist: str) -> list[dict]:
    """Last.fm album.getTopTags でアルバムタグを取得。"""
    time.sleep(LFM_WAIT)
    resp = requests.get(LASTFM_BASE, params={
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
    tagged_game_ids: list[str] = []
    tagged_tag_ids: list[str] = []
    locked_titles: list[str] = []

    for i, game in enumerate(games, 1):
        title = game["title"]
        print(f"[{i}/{len(games)}] {title}")

        album_match = search_album(title)
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
        if not mapped:
            top = [t["name"] for t in tags[:5]]
            print(f"  → ムードタグにマッチせず（タグ例: {top}）→ locked")
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
        tag_names = [
            next((n for n, d in mood_tag_index.items() if d["id"] == tid), tid)
            for tid, _ in mapped
        ]
        print(f"  → タグ付与: {', '.join(tag_names)}")
        tagged_game_ids.append(game["id"])
        tagged_tag_ids.extend(tid for tid, _ in mapped)
        total_tagged += 1
        print()

    print(f"完了 — タグ付与: {total_tagged} 件, locked 追加: {total_locked} 件")
    if locked_titles:
        print("  locked ゲーム（再試行するには tags_locked=FALSE に更新）:")
        for t in locked_titles:
            print(f"    - {t}")

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
