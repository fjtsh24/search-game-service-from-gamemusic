"""
YouTube Data API v3 でゲームサントラの VideoID を取得して tracks テーブルに保存。

ゲームタイトル + "soundtrack" で検索し、上位1件の VideoID を保存する。
1 ゲーム = 1 代表トラック（MVP の最小構成）。

使い方:
  python3 scripts/import_youtube_video_ids.py [--limit 50]

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


def search_youtube(query: str) -> str | None:
    """YouTube で検索して上位1件の videoId を返す"""
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


def get_games_without_tracks(limit: int) -> list[dict]:
    """tracks レコードがないゲームを取得"""
    all_games = db.table("games").select("id, title").limit(limit * 2).execute().data or []
    existing_game_ids = {
        row["game_id"]
        for row in (db.table("tracks").select("game_id").execute().data or [])
    }
    result = [g for g in all_games if g["id"] not in existing_game_ids]
    return result[:limit]


def run(limit: int = 50):
    games = get_games_without_tracks(limit)
    if not games:
        print("全ゲームに tracks が登録済みです。")
        return

    print(f"{len(games)} 件のゲームの VideoID を取得します...")
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
            }).execute()
            print(f"  OK: {title} → {video_id}")
            found += 1
        else:
            print(f"  NG: {title}")
            not_found += 1

        time.sleep(0.1)  # API クォータ節約

    print(f"\n完了 — 取得: {found} 件, 未取得: {not_found} 件")
    print(f"YouTube API の消費クォータ: 約 {len(games) * 100} units")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50,
                        help="取得するゲーム数（デフォルト: 50）")
    args = parser.parse_args()
    run(args.limit)
