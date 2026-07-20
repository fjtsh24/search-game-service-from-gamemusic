"""
YouTube Data API v3 でゲームサントラの VideoID を取得して tracks テーブルに保存。

2フェーズで実行:
  Phase 1（既存トラック補完）:
    tracks.youtube_video_id が NULL のレコードを対象に VideoID を検索・UPDATE。
    import_steam_soundtracks.py が作曲家リンク付きで作成したトラックもここで補完される。

  Phase 2（新規トラック作成）:
    tracks レコードが存在しないゲームに対して新規トラックを INSERT する。

--limit は YouTube API 呼び出しの合計上限（Phase 1 + Phase 2 で共有）。

YouTube Data API は 1 クエリ = 100 units / 1 日の無料枠 = 10,000 units。
毎日 GitHub Actions で実行し、100 件 = 10,000 units 以内に収める。

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
WAIT = 0.1  # YouTube API クォータ節約（単純な sleep で十分）


def search_youtube(query: str) -> str | None:
    """YouTube で検索して上位 1 件の videoId を返す"""
    resp = requests.get(YOUTUBE_SEARCH_URL, params={
        "part": "id",
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
    return items[0]["id"].get("videoId")


# ── Phase 1: 既存トラックへの VideoID 補完 ────────────────────────────────────

def get_tracks_without_video_id(limit: int) -> list[dict]:
    """youtube_video_id が未設定の tracks を、ゲームタイトル付きで取得する"""
    rows = (
        db.table("tracks")
        .select("id, title, game_id, games(id, title)")
        .is_("youtube_video_id", "null")
        .limit(limit)
        .execute()
        .data or []
    )
    return rows


def fill_existing_tracks(limit: int) -> int:
    """Phase 1: youtube_video_id=null のトラックに VideoID を UPDATE する。
    処理件数を返す。"""
    tracks = get_tracks_without_video_id(limit)
    if not tracks:
        print("[Phase 1] 補完対象のトラックはありません。")
        return 0

    print(f"[Phase 1] youtube_video_id が未設定のトラック {len(tracks)} 件を補完します...")
    done = 0
    for track in tracks:
        game_title = (track.get("games") or {}).get("title") or track.get("title", "")
        query = f"{game_title} soundtrack"
        video_id = search_youtube(query)

        if video_id:
            db.table("tracks").update({"youtube_video_id": video_id}).eq("id", track["id"]).execute()
            print(f"  OK: {game_title} → {video_id}")
            done += 1
        else:
            print(f"  NG: {game_title}")

        time.sleep(WAIT)

    print(f"[Phase 1] 完了 — {done}/{len(tracks)} 件に VideoID を設定")
    return len(tracks)


# ── Phase 2: トラック未作成ゲームへの新規トラック作成 ─────────────────────────

def get_games_without_tracks(limit: int) -> list[dict]:
    """tracks レコードが 1 件もないゲームを取得する"""
    all_games = db.table("games").select("id, title").limit(limit * 3).execute().data or []
    existing_game_ids = {
        row["game_id"]
        for row in (db.table("tracks").select("game_id").execute().data or [])
    }
    result = [g for g in all_games if g["id"] not in existing_game_ids]
    return result[:limit]


def create_tracks_for_new_games(limit: int) -> int:
    """Phase 2: tracks が存在しないゲームに新規トラックを INSERT する。
    処理件数を返す。"""
    if limit <= 0:
        print("[Phase 2] 残り枠がないためスキップ。")
        return 0

    games = get_games_without_tracks(limit)
    if not games:
        print("[Phase 2] 新規トラック作成対象のゲームはありません。")
        return 0

    print(f"[Phase 2] tracks 未作成のゲーム {len(games)} 件を処理します...")
    found = 0
    not_found = 0

    for game in games:
        title = game["title"]
        query = f"{title} soundtrack"
        video_id = search_youtube(query)

        if video_id:
            db.table("tracks").insert({
                "game_id": game["id"],
                "title": f"{title} Soundtrack",
                "youtube_video_id": video_id,
                "track_number": 1,
            }).execute()
            print(f"  OK: {title} → {video_id}")
            found += 1
        else:
            print(f"  NG: {title}")
            not_found += 1

        time.sleep(WAIT)

    print(f"[Phase 2] 完了 — 作成: {found} 件, 未取得: {not_found} 件")
    return len(games)


# ── メイン ────────────────────────────────────────────────────────────────────

def run(limit: int, phase: str) -> None:
    print(f"YouTube VideoID 取得 (上限: {limit} 件 / phase: {phase})")
    print(f"消費クォータ目安: 最大 {limit * 100} units\n")

    remaining = limit

    if phase in ("1", "all"):
        used = fill_existing_tracks(remaining)
        remaining -= used
        print()

    if phase in ("2", "all"):
        create_tracks_for_new_games(remaining)

    print(f"\n全処理完了。YouTube API 消費クォータ: 約 {limit * 100} units（最大）")


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
