"""
YouTube Data API v3 でゲームサントラの VideoID を取得して tracks テーブルに保存。

2フェーズで実行:
  Phase 1（既存トラック補完）:
    tracks.youtube_video_id が NULL のレコードを対象に VideoID を検索・UPDATE。
    動画が見つからなかった場合は games.youtube_locked = TRUE をセットし、以後スキップ。

  Phase 2（新規トラック作成）:
    tracks レコードが存在しないゲームに対して新規トラックを INSERT する。
    youtube_locked=TRUE のゲームはスキップ。

--limit は YouTube API 呼び出しの合計上限（Phase 1 + Phase 2 で共有）。

YouTube Data API は 1 クエリ = 100 units / 1 日の無料枠 = 10,000 units。
毎日 GitHub Actions で実行し、20 件 = 2,000 units に抑えて枠の余裕を確保する。

使い方:
  python3 scripts/import_youtube_video_ids.py [--limit 100] [--phase 1|2|all]

依存:
  pip install requests python-dotenv supabase
"""

import argparse
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

try:
    from supabase import create_client
except ImportError:
    print("pip install requests python-dotenv supabase")
    raise SystemExit(1)

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
WAIT = 0.1

http = requests.Session()
http.headers.update({"User-Agent": "GameMusicDiscovery/0.1.0 (hobby project)"})


def _title_matches(game_title: str, video_title: str) -> bool:
    """ゲームタイトルのキーワードが動画タイトルに含まれるか検証する。
    ASCII文字のみで判定し、非ASCII（日中韓など）タイトルはスキップ（常にTrue）。
    """
    import re
    ascii_words = re.findall(r"[a-zA-Z0-9]{4,}", game_title)
    if not ascii_words:
        return True  # 非ASCII タイトルは検証スキップ
    video_lower = video_title.lower()
    matched = sum(1 for w in ascii_words if w.lower() in video_lower)
    return matched >= max(1, len(ascii_words) // 2)


def search_youtube(query: str, game_title: str = "") -> str | None:
    """YouTube で検索して上位 1 件の videoId を返す。
    game_title が指定された場合、動画タイトルとのキーワードマッチを検証する。
    """
    resp = http.get(YOUTUBE_SEARCH_URL, params={
        "part": "id,snippet",
        "q": query,
        "type": "video",
        "maxResults": 1,
        "key": YOUTUBE_API_KEY,
    }, timeout=10)

    if resp.status_code != 200:
        print(f"  YouTube API エラー: {resp.status_code} {resp.text[:100]}")
        return None

    items = resp.json().get("items", [])
    if not items:
        return None

    item = items[0]
    video_id = item["id"].get("videoId")
    if not video_id:
        return None

    if game_title:
        video_title = item.get("snippet", {}).get("title", "")
        if not _title_matches(game_title, video_title):
            print(f"  SKIP（タイトル不一致）: 動画='{video_title}'")
            return None

    return video_id


def lock_youtube(game_id: str) -> None:
    """youtube_locked = TRUE をセット。以後の日次バッチでスキップされる。"""
    db.table("games").update({"youtube_locked": True}).eq("id", game_id).execute()


# ── Phase 1: 既存トラックへの VideoID 補完 ────────────────────────────────────

def get_tracks_without_video_id(limit: int) -> list[dict]:
    """youtube_video_id が未設定かつ youtube_locked でないトラックを取得する。"""
    rows = (
        db.table("tracks")
        .select("id, title, game_id, games(id, title, youtube_locked)")
        .is_("youtube_video_id", "null")
        .limit(limit * 2)
        .execute()
        .data or []
    )
    # youtube_locked=TRUE のゲームのトラックは除外
    unlocked = [r for r in rows if not (r.get("games") or {}).get("youtube_locked")]
    return unlocked[:limit]


def fill_existing_tracks(limit: int) -> tuple[int, int, list[str]]:
    """Phase 1: youtube_video_id=null のトラックに VideoID を UPDATE する。
    Returns: (処理件数, locked追加件数, locked_titles)
    """
    tracks = get_tracks_without_video_id(limit)
    if not tracks:
        print("[Phase 1] 補完対象のトラックはありません。")
        return 0, 0, []

    print(f"[Phase 1] youtube_video_id が未設定のトラック {len(tracks)} 件を補完します...")
    done = 0
    locked_count = 0
    locked_titles: list[str] = []

    for track in tracks:
        game_title = (track.get("games") or {}).get("title") or track.get("title", "")
        game_id = track.get("game_id", "")
        query = f"{game_title} soundtrack"
        video_id = search_youtube(query, game_title=game_title)

        if video_id:
            db.table("tracks").update({"youtube_video_id": video_id}).eq("id", track["id"]).execute()
            db.table("games").update({"is_discoverable": True}).eq("id", game_id).execute()
            print(f"  OK: {game_title} → {video_id}")
            done += 1
        else:
            print(f"  NG (locked): {game_title}")
            lock_youtube(game_id)
            locked_titles.append(game_title)
            locked_count += 1

        time.sleep(WAIT)

    print(f"[Phase 1] 完了 — {done}/{len(tracks)} 件に VideoID を設定, locked 追加: {locked_count} 件")
    return len(tracks), locked_count, locked_titles


# ── Phase 2: トラック未作成ゲームへの新規トラック作成 ─────────────────────────

def get_games_without_tracks(limit: int) -> list[dict]:
    """tracks レコードが 1 件もなく youtube_locked でないゲームを取得する。"""
    all_games = (
        db.table("games")
        .select("id, title")
        .eq("youtube_locked", False)
        .limit(limit * 3)
        .execute()
        .data or []
    )
    existing_game_ids = {
        row["game_id"]
        for row in (db.table("tracks").select("game_id").execute().data or [])
    }
    result = [g for g in all_games if g["id"] not in existing_game_ids]
    return result[:limit]


def create_tracks_for_new_games(limit: int) -> tuple[int, int, list[str]]:
    """Phase 2: tracks が存在しないゲームに新規トラックを INSERT する。
    Returns: (処理件数, locked追加件数, locked_titles)
    """
    if limit <= 0:
        print("[Phase 2] 残り枠がないためスキップ。")
        return 0, 0, []

    games = get_games_without_tracks(limit)
    if not games:
        print("[Phase 2] 新規トラック作成対象のゲームはありません。")
        return 0, 0, []

    print(f"[Phase 2] tracks 未作成のゲーム {len(games)} 件を処理します...")
    found = 0
    locked_count = 0
    locked_titles: list[str] = []

    for game in games:
        title = game["title"]
        query = f"{title} soundtrack"
        video_id = search_youtube(query, game_title=title)

        if video_id:
            db.table("tracks").insert({
                "game_id": game["id"],
                "title": f"{title} Soundtrack",
                "youtube_video_id": video_id,
                "track_number": 1,
            }).execute()
            db.table("games").update({"is_discoverable": True}).eq("id", game["id"]).execute()
            print(f"  OK: {title} → {video_id}")
            found += 1
        else:
            print(f"  NG (locked): {title}")
            lock_youtube(game["id"])
            locked_titles.append(title)
            locked_count += 1

        time.sleep(WAIT)

    print(f"[Phase 2] 完了 — 作成: {found} 件, locked 追加: {locked_count} 件")
    return len(games), locked_count, locked_titles


# ── メイン ────────────────────────────────────────────────────────────────────

def run(limit: int, phase: str) -> None:
    print(f"YouTube VideoID 取得 (上限: {limit} 件 / phase: {phase})")
    print(f"消費クォータ目安: 最大 {limit * 100} units\n")

    remaining = limit
    total_locked = 0
    all_locked_titles: list[str] = []

    if phase in ("1", "all"):
        used, locked, titles = fill_existing_tracks(remaining)
        remaining -= used
        total_locked += locked
        all_locked_titles.extend(titles)
        print()

    if phase in ("2", "all"):
        _, locked, titles = create_tracks_for_new_games(remaining)
        total_locked += locked
        all_locked_titles.extend(titles)

    print(f"\n全処理完了。YouTube API 消費クォータ: 約 {limit * 100} units（最大）")
    if all_locked_titles:
        print(f"locked 追加合計: {total_locked} 件（再試行するには youtube_locked=FALSE に更新）")
        for t in all_locked_titles:
            print(f"  - {t}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="YouTube VideoID をゲームサントラに付与する（毎日バッチ向け）"
    )
    parser.add_argument("--limit", type=int, default=100,
                        help="YouTube API 呼び出し上限 (デフォルト: 100 = 10,000 units)")
    parser.add_argument("--phase", choices=["1", "2", "all"], default="all",
                        help="実行フェーズ: 1=既存補完, 2=新規作成, all=両方 (デフォルト: all)")
    args = parser.parse_args()
    run(args.limit, args.phase)
