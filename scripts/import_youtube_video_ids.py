"""
YouTube Data API v3 でゲームサントラ / トラック別の VideoID を取得して保存する。

モード:
  --mode games  (デフォルト)
    games.youtube_video_id が NULL かつ youtube_locked=FALSE のゲームを対象に
    OST 全体の動画を検索して UPDATE する。

  --mode tracks
    tracks.youtube_video_id が NULL のトラックを対象に、
    「ゲーム名 トラック名」で YouTube 検索して UPDATE する。
    汎用的なトラック名（"Track 1" 等）はスキップ。
    両方のキーワードが動画タイトルに含まれるか厳格に検証する。

YouTube Data API は 1 クエリ = 100 units / 1 日の無料枠 = 10,000 units。
  - games モード: 日次 20 件 = 2,000 units
  - tracks モード: 日次 10 件 = 1,000 units
  合計 3,000 units/日 で余裕を保つ。

使い方:
  python3 scripts/import_youtube_video_ids.py [--limit N] [--mode games|tracks]

依存:
  pip install requests python-dotenv supabase
"""

import argparse
import os
import re
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


_GENERIC_TRACK_RE = re.compile(
    r"^(track|music|bgm|theme|song|se|sfx|jingle|ost|stage|area|level|field|battle|boss)[\s_\-]?\d*\.?$",
    re.IGNORECASE,
)


def _is_generic_track_title(title: str) -> bool:
    """汎用的すぎて YouTube 検索に使えないトラック名なら True。"""
    t = title.strip()
    return len(t) < 4 or bool(_GENERIC_TRACK_RE.match(t))


def _track_title_matches(track_title: str, video_title: str) -> bool:
    """トラック名のキーワードが動画タイトルに含まれるか検証する。"""
    words = re.findall(r"[a-zA-Z0-9぀-鿿가-힯]{2,}", track_title)
    if not words:
        return False
    video_lower = video_title.lower()
    matched = sum(1 for w in words if w.lower() in video_lower)
    return matched >= max(1, len(words) // 2)


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


def get_tracks_without_video(limit: int) -> list[dict]:
    """tracks.youtube_video_id が未設定のトラックをゲームタイトル付きで取得する。"""
    rows = (
        db.table("tracks")
        .select("id, title, games(id, title)")
        .is_("youtube_video_id", "null")
        .order("created_at", desc=False)
        .limit(limit * 5)  # 汎用名フィルタ後に limit 件残るよう多めに取得
        .execute()
        .data or []
    )
    # 汎用的なトラック名（"Track 1" 等）は検索精度が低いのでスキップ
    filtered = [r for r in rows if r.get("games") and not _is_generic_track_title(r["title"])]
    return filtered[:limit]


def run_games(limit: int) -> None:
    print(f"YouTube VideoID 取得 — ゲーム OST モード (上限: {limit} 件)")
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


def run_tracks(limit: int) -> None:
    """tracks.youtube_video_id を曲名＋ゲーム名で YouTube 検索して設定する。

    クォータ節約のため limit は小さく（デフォルト 10）。
    汎用的なトラック名は精度が低いため除外する。
    マッチ検証: ゲーム名キーワード OR トラック名キーワードが動画タイトルに含まれること。
    """
    print(f"YouTube VideoID 取得 — トラックモード (上限: {limit} 件)")
    print(f"消費クォータ目安: 最大 {limit * 100} units\n")

    tracks = get_tracks_without_video(limit)
    if not tracks:
        print("対象トラックはありません。")
        return

    print(f"{len(tracks)} 件を処理します...\n")
    done = 0

    for track in tracks:
        game_title = track["games"]["title"]
        track_title = track["title"]
        query = f"{game_title} {track_title}"

        resp = http.get(YOUTUBE_SEARCH_URL, params={
            "part": "id,snippet",
            "q": query,
            "type": "video",
            "maxResults": 3,
            "key": YOUTUBE_API_KEY,
        }, timeout=10)

        video_id = None
        if resp.status_code == 200:
            for item in resp.json().get("items", []):
                vid = item["id"].get("videoId")
                video_title = item.get("snippet", {}).get("title", "")
                # ゲーム名 AND トラック名の両方が動画タイトルに含まれるか検証
                if vid and _title_matches(game_title, video_title) and _track_title_matches(track_title, video_title):
                    video_id = vid
                    break

        if video_id:
            db.table("tracks").update({"youtube_video_id": video_id}).eq("id", track["id"]).execute()
            print(f"  OK: [{game_title}] {track_title} → {video_id}")
            done += 1
        else:
            print(f"  NG: [{game_title}] {track_title}")

        time.sleep(WAIT)

    print(f"\n完了 — {done}/{len(tracks)} 件に VideoID を設定")
    print(f"消費クォータ: 約 {len(tracks) * 100} units")


def run(limit: int, mode: str) -> None:
    if mode == "tracks":
        run_tracks(limit)
    else:
        run_games(limit)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="YouTube VideoID をゲーム OST またはトラック単位で付与する（毎日バッチ向け）"
    )
    parser.add_argument("--limit", type=int, default=100,
                        help="YouTube API 呼び出し上限 (デフォルト: 100 = 10,000 units)")
    parser.add_argument("--mode", choices=["games", "tracks"], default="games",
                        help="games: ゲーム OST 動画（デフォルト）/ tracks: トラック別動画")
    args = parser.parse_args()
    run(args.limit, args.mode)
