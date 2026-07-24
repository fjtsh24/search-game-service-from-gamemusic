"""
YouTube Data API v3 でゲームサントラの VideoID を取得して games テーブルに保存。

games.youtube_video_id が NULL かつ youtube_locked=FALSE のゲームを対象に
OST 全体の動画を検索して UPDATE する。

YouTube Data API は 1 クエリ = 100 units / 1 日の無料枠 = 10,000 units。
毎日 GitHub Actions で実行し、20 件 = 2,000 units に抑えて枠の余裕を確保する。

使い方:
  python3 scripts/import_youtube_video_ids.py [--limit 100]

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


def get_games_without_video(limit: int) -> list[dict]:
    """games.youtube_video_id が未設定かつ youtube_locked でないゲームを取得する。"""
    return (
        db.table("games")
        .select("id, title")
        .is_("youtube_video_id", "null")
        .eq("youtube_locked", False)
        .limit(limit)
        .execute()
        .data or []
    )


def run(limit: int) -> None:
    print(f"YouTube VideoID 取得 (上限: {limit} 件)")
    print(f"消費クォータ目安: 最大 {limit * 100} units\n")

    games = get_games_without_video(limit)
    if not games:
        print("対象ゲームはありません。")
        return

    print(f"{len(games)} 件を処理します...\n")
    done = 0
    locked_titles: list[str] = []

    for game in games:
        title = game["title"]
        query = f"{title} soundtrack"
        video_id = search_youtube(query, game_title=title)

        if video_id:
            db.table("games").update({"youtube_video_id": video_id}).eq("id", game["id"]).execute()
            print(f"  OK: {title} → {video_id}")
            done += 1
        else:
            db.table("games").update({"youtube_locked": True}).eq("id", game["id"]).execute()
            print(f"  NG (locked): {title}")
            locked_titles.append(title)

        time.sleep(WAIT)

    print(f"\n完了 — {done}/{len(games)} 件に VideoID を設定")
    print(f"消費クォータ: 約 {len(games) * 100} units")
    if locked_titles:
        print(f"locked 追加: {len(locked_titles)} 件（再試行するには youtube_locked=FALSE に更新）")
        for t in locked_titles:
            print(f"  - {t}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="YouTube VideoID をゲームの OST 動画として付与する（毎日バッチ向け）"
    )
    parser.add_argument("--limit", type=int, default=100,
                        help="YouTube API 呼び出し上限 (デフォルト: 100 = 10,000 units)")
    args = parser.parse_args()
    run(args.limit)
