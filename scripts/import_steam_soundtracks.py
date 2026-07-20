"""
Steam のサントラ DLC を人気順（レビュー数降順）で取得し、
作曲家情報を MusicBrainz から補完して DB に登録する。

負荷対策:
  - Steam API 呼び出し間: 2 秒ウェイト
  - MusicBrainz API 呼び出し間: 1.2 秒ウェイト（規約: 1req/sec 以内）
  - 1 実行あたりの処理件数は --limit で制限（デフォルト 50）

使い方:
  python3 scripts/import_steam_soundtracks.py --limit 50

依存:
  pip install requests python-dotenv supabase musicbrainzngs
"""

import argparse
import re
import time
import os
import requests
from dotenv import load_dotenv

load_dotenv()

try:
    import musicbrainzngs
    from supabase import create_client
except ImportError:
    print("pip install requests python-dotenv supabase musicbrainzngs")
    raise SystemExit(1)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

musicbrainzngs.set_useragent(
    "GameMusicDiscovery", "0.1.0",
    "https://github.com/your-org/search-game-service",
)

STEAM_SEARCH_URL = "https://store.steampowered.com/search/results/"
STEAM_WAIT = 2.0       # Steam API 間のウェイト（秒）
MB_WAIT = 1.2          # MusicBrainz API 間のウェイト（秒）
PAGE_SIZE = 25         # Steam 検索 API の固定ページサイズ

session = requests.Session()
session.headers.update({"User-Agent": "GameMusicDiscovery/0.1.0 (hobby project)"})


# ── Steam API ────────────────────────────────────────────────────────────────

def fetch_steam_soundtrack_page(start: int) -> list[dict]:
    """Steam のサウンドトラックカテゴリ（category1=57）からゲームをレビュー数順で取得。

    レスポンスの items は親ゲームを直接返す（DLC→親ゲーム変換不要）。
    1ページあたり常に 25 件固定で返る。
    """
    resp = session.get(STEAM_SEARCH_URL, params={
        "category1": "57",   # Steam の "Soundtracks" カテゴリ
        "sort_by": "Reviews_DESC",
        "json": "1",
        "start": start,
        "count": PAGE_SIZE,
    }, timeout=15)
    resp.raise_for_status()
    items = resp.json().get("items", [])

    results = []
    for item in items:
        logo = item.get("logo", "")
        m = re.search(r"/apps/(\d+)/", logo)
        if not m:
            continue
        results.append({
            "appid": int(m.group(1)),
            "title": item.get("name", "").strip(),
        })
    return results


# ── MusicBrainz ──────────────────────────────────────────────────────────────

def search_mb_releases(game_title: str) -> list[dict]:
    """ゲームタイトルでサントラリリースを検索。タイトルが一致しない結果は除外する。"""
    time.sleep(MB_WAIT)
    try:
        result = musicbrainzngs.search_releases(
            query=f'"{game_title}" secondarytype:soundtrack',
            limit=5,
        )
        releases = result.get("release-list", [])
        title_lower = game_title.lower()
        # MB のリリースタイトルにゲームタイトルが含まれる場合のみ採用
        confident = [
            r for r in releases
            if title_lower in r.get("title", "").lower()
            or r.get("title", "").lower() in title_lower
        ]
        return confident
    except Exception:
        return []


def upsert_composer(artist: dict) -> str | None:
    mbid = artist.get("id")
    name = artist.get("name") or artist.get("sort-name")
    if not mbid or not name:
        return None
    result = db.table("composers").upsert(
        {"musicbrainz_id": mbid, "name": name},
        on_conflict="musicbrainz_id",
    ).execute()
    return result.data[0]["id"] if result.data else None


# ── DB upsert ────────────────────────────────────────────────────────────────

def upsert_game(title: str, steam_app_id: int, mb_release_id: str | None = None) -> str | None:
    # 1. steam_app_id で既存レコードを探す
    rows = (db.table("games").select("id").eq("steam_app_id", steam_app_id).execute().data or [])
    if rows:
        payload = {"title": title}
        if mb_release_id:
            payload["musicbrainz_release_id"] = mb_release_id
        db.table("games").update(payload).eq("steam_app_id", steam_app_id).execute()
        return rows[0]["id"]

    # 2. musicbrainz_release_id で既存レコードを探す（MusicBrainz 由来で登録済みの場合）
    if mb_release_id:
        mb_rows = (db.table("games").select("id").eq("musicbrainz_release_id", mb_release_id).execute().data or [])
        if mb_rows:
            db.table("games").update({"title": title, "steam_app_id": steam_app_id}).eq(
                "musicbrainz_release_id", mb_release_id
            ).execute()
            return mb_rows[0]["id"]

    # 3. 新規挿入
    payload = {"title": title, "steam_app_id": steam_app_id}
    if mb_release_id:
        payload["musicbrainz_release_id"] = mb_release_id
    result = db.table("games").insert(payload).execute()
    return result.data[0]["id"] if result.data else None


# ── メインループ ──────────────────────────────────────────────────────────────

def run(limit: int = 200):
    print(f"Steam サウンドトラックカテゴリ（レビュー数順）を最大 {limit} 件処理します...")
    processed = 0
    start = 0

    while processed < limit:
        print(f"\n[Steam 検索] start={start}")
        time.sleep(STEAM_WAIT)

        games = fetch_steam_soundtrack_page(start)
        if not games:
            print("これ以上結果がありません。")
            break

        for item in games:
            if processed >= limit:
                break

            print(f"\n  [{processed + 1}/{limit}] {item['title']} (appid={item['appid']})")

            # MusicBrainz でサントラ・作曲家を検索
            mb_releases = search_mb_releases(item["title"])
            mb_release_id = None
            composers_added = 0

            if mb_releases:
                release = mb_releases[0]
                mb_release_id = release.get("id")
                for credit in release.get("artist-credit", []):
                    if not isinstance(credit, dict):
                        continue
                    artist = credit.get("artist")
                    if artist:
                        upsert_composer(artist)
                        composers_added += 1
                print(f"    MusicBrainz: リリース発見、作曲家 {composers_added} 件")
            else:
                print("    MusicBrainz: 該当なし")

            # DB に登録
            game_id = upsert_game(item["title"], item["appid"], mb_release_id)
            if game_id:
                print(f"    DB登録完了: game_id={game_id}")

            processed += 1

        start += PAGE_SIZE

    print(f"\n完了 — {processed} 件処理しました")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50,
                        help="処理する最大件数（デフォルト: 50）")
    args = parser.parse_args()
    run(args.limit)
