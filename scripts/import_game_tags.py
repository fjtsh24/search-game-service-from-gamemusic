"""
ゲームのサウンドトラック内の個別トラックを Last.fm で検索し、
トラックレベルのタグを集計して game_tags テーブルに保存する。

精度の考え方:
  - 作曲家タグ（artist.getTopTags）: 作曲家の全活動の集計 → ゲーム固有の精度が低い
  - トラックタグ（track.getTopTags）: そのゲームの曲を実際に聴いた Last.fm ユーザーが付けたタグ
    → ゲーム固有の音楽ムードを反映する

フォールバック順:
  1. MusicBrainz release があるゲーム → track listing 取得 → 各トラックの Last.fm タグ集計
  2. MusicBrainz なしゲーム → "{title} Soundtrack" で Last.fm album 検索 → album タグ
  3. それも失敗 → スキップ（作曲家タグは使わない）

注意:
  - Last.fm のインディーゲームカバレッジは限られる。人気タイトルほど精度が上がる。
  - MusicBrainz データが入っているゲームのみフル精度。

使い方:
  python3 scripts/import_game_tags.py [--limit 200] [--overwrite]

依存:
  pip install requests python-dotenv supabase musicbrainzngs
"""

import argparse
import os
import time
import requests
from dotenv import load_dotenv
from collections import Counter

load_dotenv(dotenv_path=".env")

try:
    import musicbrainzngs
    from supabase import create_client
except ImportError:
    print("pip install requests python-dotenv supabase musicbrainzngs")
    raise SystemExit(1)

LASTFM_API_KEY = os.environ["LASTFM_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
LASTFM_BASE = "https://ws.audioscrobbler.com/2.0/"
MB_WAIT = 1.2
LFM_WAIT = 0.3

musicbrainzngs.set_useragent(
    "GameMusicDiscovery", "0.1.0",
    "https://github.com/fjtsh24/search-game-service-from-gamemusic",
)

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

MAX_TRACKS_PER_GAME = 5   # MusicBrainz から取得するトラック数の上限
MIN_TAG_COUNT = 1          # 集計タグの最低出現回数


# ── Last.fm API ───────────────────────────────────────────────────────────────

def fetch_track_tags(track_title: str, artist_name: str) -> list[dict]:
    """Last.fm track.getTopTags でトラック固有のタグを取得。"""
    time.sleep(LFM_WAIT)
    resp = requests.get(LASTFM_BASE, params={
        "method": "track.getTopTags",
        "track": track_title,
        "artist": artist_name,
        "api_key": LASTFM_API_KEY,
        "format": "json",
        "autocorrect": "1",
    }, timeout=10)
    if not resp.ok:
        return []
    data = resp.json()
    # エラーレスポンス（{"error": 6, "message": "..."}）を除外
    if "error" in data:
        return []
    return data.get("toptags", {}).get("tag", []) or []


def fetch_album_tags(album: str, artist: str) -> list[dict]:
    """Last.fm album.getTopTags でアルバムタグを取得（フォールバック）。"""
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
    return data.get("toptags", {}).get("tag", []) or []


# ── MusicBrainz API ───────────────────────────────────────────────────────────

def get_release_tracks(mbid: str) -> list[tuple[str, str]]:
    """MusicBrainz リリースからトラック一覧と artist credit を取得。
    Returns: [(track_title, artist_name), ...]
    """
    time.sleep(MB_WAIT)
    try:
        result = musicbrainzngs.get_release_by_id(mbid, includes=["recordings", "artist-credits"])
        tracks_out: list[tuple[str, str]] = []
        for medium in result.get("release", {}).get("medium-list", []):
            for track in medium.get("track-list", []):
                rec = track.get("recording", {})
                title = rec.get("title", "")
                credits = rec.get("artist-credit", [])
                artist = ""
                for c in credits:
                    if isinstance(c, dict):
                        artist = c.get("artist", {}).get("name", "") or artist
                        break
                if title:
                    tracks_out.append((title, artist))
        return tracks_out[:MAX_TRACKS_PER_GAME]
    except Exception:
        return []


# ── タグ集計 ─────────────────────────────────────────────────────────────────

def aggregate_tags(all_tags: list[list[dict]]) -> Counter:
    """複数トラックのタグリストを集計して Counter で返す。"""
    counter: Counter = Counter()
    for tag_list in all_tags:
        for t in tag_list:
            name = t.get("name", "").lower().strip()
            count = int(t.get("count", 1))
            if name and count > 0:
                counter[name] += count
    return counter


def map_to_mood_tags(tag_counter: Counter, mood_tag_index: dict[str, dict]) -> list[tuple[str, float]]:
    """集計タグを mood_tags にマッピング。Returns: [(tag_id, confidence), ...]"""
    if not tag_counter:
        return []

    max_score = max(tag_counter.values()) or 1
    matched: dict[str, float] = {}

    for lfm_name, score in tag_counter.items():
        if score < MIN_TAG_COUNT:
            continue
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

def get_games_without_tags(limit: int) -> list[dict]:
    """game_tags が 0 件のゲームを取得。"""
    all_games = (
        db.table("games")
        .select("id, title, musicbrainz_release_id, tracks(track_composers(composers(name)))")
        .limit(limit * 2)
        .execute()
        .data or []
    )
    tagged_ids = {
        row["game_id"]
        for row in (db.table("game_tags").select("game_id").execute().data or [])
    }
    result = [g for g in all_games if g["id"] not in tagged_ids]
    return result[:limit]


def get_first_composer_name(game: dict) -> str | None:
    for track in (game.get("tracks") or []):
        for tc in (track.get("track_composers") or []):
            composer = tc.get("composers")
            if composer and composer.get("name"):
                return composer["name"]
    return None


# ── メインループ ───────────────────────────────────────────────────────────────

def run(limit: int, overwrite: bool) -> None:
    mood_tags_rows = db.table("mood_tags").select("id, name").execute().data or []
    mood_tag_index: dict[str, dict] = {row["name"]: row for row in mood_tags_rows}
    print(f"mood_tags: {len(mood_tag_index)} 件ロード済み\n")

    if overwrite:
        games = (
            db.table("games")
            .select("id, title, musicbrainz_release_id, tracks(track_composers(composers(name)))")
            .limit(limit)
            .execute()
            .data or []
        )
    else:
        games = get_games_without_tags(limit)

    if not games:
        print("タグ付け対象のゲームがありません。")
        return

    print(f"{len(games)} 件のゲームにタグを付与します...\n")
    total_tagged = 0
    total_skipped = 0

    for i, game in enumerate(games, 1):
        title = game["title"]
        mbid = game.get("musicbrainz_release_id")
        composer_name = get_first_composer_name(game)
        print(f"[{i}/{len(games)}] {title}")

        tag_counter: Counter = Counter()

        # ── ルート 1: MusicBrainz リリース → 個別トラックタグ ─────────────────
        if mbid:
            release_tracks = get_release_tracks(mbid)
            if release_tracks:
                print(f"  MusicBrainz: {len(release_tracks)} トラック取得")
                for track_title, track_artist in release_tracks:
                    artist = track_artist or composer_name or "Various Artists"
                    tags = fetch_track_tags(track_title, artist)
                    tag_counter.update(
                        {t["name"].lower(): int(t.get("count", 1)) for t in tags}
                    )
                if tag_counter:
                    print(f"  → トラックタグ集計: {len(tag_counter)} 種")

        # ── ルート 2: album.getTopTags（フォールバック）──────────────────────
        if not tag_counter and composer_name:
            tags = fetch_album_tags(f"{title} Soundtrack", composer_name)
            if tags:
                tag_counter.update({t["name"].lower(): int(t.get("count", 1)) for t in tags})
                print(f"  → アルバムタグ: {len(tag_counter)} 種")

        if not tag_counter:
            print("  → Last.fm データなし、スキップ")
            total_skipped += 1
            print()
            continue

        # mood_tags にマッピングして保存
        mapped = map_to_mood_tags(tag_counter, mood_tag_index)
        if not mapped:
            top_tags = [k for k, _ in tag_counter.most_common(5)]
            print(f"  → ムードタグにマッチせず（Last.fm タグ例: {top_tags}）")
            total_skipped += 1
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
        total_tagged += 1
        print()

    print(f"完了 — タグ付与: {total_tagged} 件, スキップ: {total_skipped} 件")
    print(f"注: Last.fm のインディーゲームカバレッジは限られます。MusicBrainz データ付きゲームほど精度が上がります。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ゲームサントラのトラックタグを Last.fm から取得して game_tags に保存"
    )
    parser.add_argument("--limit", type=int, default=200,
                        help="処理するゲーム数 (デフォルト: 200)")
    parser.add_argument("--overwrite", action="store_true",
                        help="既にタグがあるゲームも上書きする")
    args = parser.parse_args()
    run(args.limit, args.overwrite)
