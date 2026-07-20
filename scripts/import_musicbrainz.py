"""
MusicBrainz からゲーム × 作曲家データを取得して Supabase に投入するスクリプト。

MusicBrainz API: https://musicbrainz.org/doc/MusicBrainz_API
- 利用規約: 商用・非商用問わず無料で利用可
- レート制限: 1リクエスト/秒（User-Agent 必須）
- ゲームのサウンドトラックは work.type = "Soundtrack" で検索可能

使い方:
  python scripts/import_musicbrainz.py --limit 100

依存:
  pip install musicbrainzngs python-dotenv supabase
"""

import argparse
import time
import os
from dotenv import load_dotenv

load_dotenv()

try:
    import musicbrainzngs
    from supabase import create_client
except ImportError:
    print("依存ライブラリが不足しています。以下を実行してください:")
    print("  pip install musicbrainzngs python-dotenv supabase")
    raise SystemExit(1)

musicbrainzngs.set_useragent(
    "GameMusicDiscovery",
    "0.1.0",
    "https://github.com/your-org/search-game-service",  # OSS公開後に更新
)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def fetch_game_releases(limit: int = 100) -> list[dict]:
    """ビデオゲームのリリースを MusicBrainz から取得（ページネーション対応）"""
    all_releases = []
    batch = 25  # MusicBrainz API の 1 回あたり上限
    offset = 0
    while len(all_releases) < limit:
        fetch_count = min(batch, limit - len(all_releases))
        results = musicbrainzngs.search_releases(
            query='type:album AND secondarytype:soundtrack',
            limit=fetch_count,
            offset=offset,
        )
        releases = results.get("release-list", [])
        if not releases:
            break
        all_releases.extend(releases)
        offset += len(releases)
        time.sleep(1.1)
    return all_releases


def upsert_composer(artist: dict) -> str | None:
    """作曲家を DB に upsert して ID を返す"""
    mbid = artist.get("id")
    name = artist.get("name") or artist.get("sort-name")
    if not mbid or not name:
        return None

    result = db.table("composers").upsert(
        {"musicbrainz_id": mbid, "name": name},
        on_conflict="musicbrainz_id",
    ).execute()
    return result.data[0]["id"] if result.data else None


def upsert_game(release: dict) -> str | None:
    """ゲーム（リリース）を DB に upsert して ID を返す"""
    title = release.get("title")
    mbid = release.get("id")
    if not title:
        return None

    date = release.get("date", "")
    release_year = int(date[:4]) if date and len(date) >= 4 and date[:4].isdigit() else None

    result = db.table("games").upsert(
        {
            "title": title,
            "musicbrainz_release_id": mbid,
            "vgmdb_album_id": None,  # 後で VGMdb と紐付け
            "release_year": release_year,
        },
        on_conflict="musicbrainz_release_id",
    ).execute()
    return result.data[0]["id"] if result.data else None


def import_releases(limit: int = 100):
    print(f"MusicBrainz からゲームサントラを最大 {limit} 件取得します...")
    releases = fetch_game_releases(limit)
    print(f"{len(releases)} 件取得")

    imported_games = 0
    imported_composers = 0

    for release in releases:
        game_id = upsert_game(release)
        if not game_id:
            continue
        imported_games += 1

        for credit in release.get("artist-credit", []):
            if not isinstance(credit, dict):
                continue
            artist = credit.get("artist")
            if not artist:
                continue
            composer_id = upsert_composer(artist)
            if composer_id:
                imported_composers += 1

        time.sleep(1.1)  # レート制限: 1リクエスト/秒

    print(f"完了 — ゲーム: {imported_games} 件, 作曲家: {imported_composers} 件")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    import_releases(args.limit)
