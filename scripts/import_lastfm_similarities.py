"""
Last.fm から作曲家間の類似度データを取得して composer_similarities テーブルに保存。

使い方:
  python3 scripts/import_lastfm_similarities.py [--limit N]

  --limit N : 処理する作曲家数の上限（未指定時は全件）。
              類似度データが未登録の作曲家（OST スクレイプで新規追加されたもの）を優先する。

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

LASTFM_API_KEY = os.environ["LASTFM_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
LASTFM_BASE = "https://ws.audioscrobbler.com/2.0/"

http = requests.Session()
http.headers.update({"User-Agent": "GameMusicDiscovery/0.1.0 (hobby project)"})


def fetch_similar_artists(artist_name: str) -> list[dict]:
    """Last.fm から類似アーティストを取得（最大 10 件）"""
    resp = http.get(LASTFM_BASE, params={
        "method": "artist.getSimilar",
        "artist": artist_name,
        "limit": 10,
        "autocorrect": 1,
        "api_key": LASTFM_API_KEY,
        "format": "json",
    }, timeout=10)
    if not resp.ok:
        return []
    data = resp.json()
    if "error" in data:
        return []
    return data.get("similarartists", {}).get("artist", [])


def get_all_composers() -> list[dict]:
    result = db.table("composers").select("id, name, lastfm_name").execute()
    return result.data or []


def get_composer_by_name(name: str, composers: list[dict]) -> dict | None:
    name_lower = name.lower()
    for c in composers:
        if (c.get("lastfm_name") or c["name"]).lower() == name_lower:
            return c
    return None


def run(limit: int | None = None):
    composers = get_all_composers()
    if not composers:
        print("作曲家データがありません。先に import_steam_soundtracks.py を実行してください。")
        return

    # 類似度データ未登録の作曲家を優先してソート
    existing_ids = {
        row["composer_id_a"]
        for row in (db.table("composer_similarities").select("composer_id_a").execute().data or [])
    }
    composers.sort(key=lambda c: c["id"] in existing_ids)
    if limit:
        composers = composers[:limit]

    print(f"{len(composers)} 件の作曲家について類似度を取得します（未登録優先）...")
    inserted = 0
    skipped = 0

    for composer in composers:
        search_name = composer.get("lastfm_name") or composer["name"]
        similar_artists = fetch_similar_artists(search_name)

        if not similar_artists:
            skipped += 1
            time.sleep(0.3)
            continue

        rows = []
        for similar in similar_artists:
            match = get_composer_by_name(similar["name"], composers)
            if not match:
                continue
            if match["id"] == composer["id"]:
                continue
            score = float(similar.get("match", 0))
            # (a, b) と (b, a) の両方向を保存（PKは (a,b) なので順序固定）
            id_a, id_b = sorted([composer["id"], match["id"]])
            rows.append({
                "composer_id_a": id_a,
                "composer_id_b": id_b,
                "score": score,
                "source": "lastfm",
            })

        if rows:
            db.table("composer_similarities").upsert(
                rows,
                on_conflict="composer_id_a,composer_id_b",
            ).execute()
            inserted += len(rows)

        time.sleep(0.3)  # Last.fm レート制限（5 req/sec 以内）

    print(f"完了 — 類似度レコード: {inserted} 件保存, {skipped} 件スキップ（Last.fm にデータなし）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Last.fm から作曲家間類似度を取得して composer_similarities に保存"
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="処理する作曲家数の上限（デフォルト: 全件）")
    args = parser.parse_args()
    run(args.limit)
