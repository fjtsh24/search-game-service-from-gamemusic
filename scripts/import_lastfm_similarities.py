"""
Last.fm から作曲家間の類似度データを取得して composer_similarities テーブルに保存。

2段構えで処理する:
  1. 取得: composers.lastfm_similar_fetched_at が NULL の作曲家について
     artist.getSimilar を叩き、応答を composer_similar_artists にそのままキャッシュする。
     データが無かった作曲家も fetched_at を記録するので、翌日以降は対象から外れる。
  2. 突合: キャッシュ全体を現在の composers と名前で突合し、両端が自前の作曲家に
     なるペアを composer_similarities に反映する（Last.fm へのリクエストは発生しない）。

キャッシュを挟むのは、composer_similarities が両端とも自前 composers のペアしか
持てず、応答の大半（実測 947 件中 9 割）が捨てられてしまうため。名前のまま残して
おけば、後から作曲家が追加されたときに Last.fm を叩き直さずに突合できる。

使い方:
  python3 scripts/import_lastfm_similarities.py [--limit N] [--overwrite]

  --limit N   : 1回に取得する作曲家数の上限（未指定時は未取得の全件）
  --overwrite : 取得済みの作曲家も再取得する

依存:
  pip install requests python-dotenv supabase
"""

import argparse
import os
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from composer_matching import build_similarity_pairs

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
    """全作曲家を取得する（PostgREST の 1 リクエスト上限を超えてもページングする）。"""
    out: list[dict] = []
    offset = 0
    while True:
        page = (
            db.table("composers")
            .select("id, name, lastfm_name, lastfm_similar_fetched_at")
            .order("created_at", desc=False)
            .range(offset, offset + 999)
            .execute()
            .data or []
        )
        out.extend(page)
        if len(page) < 1000:
            return out
        offset += 1000


def _cache_similar_artists(composer_id: str, similar_artists: list[dict]) -> None:
    """Last.fm の応答をそのまま composer_similar_artists に保存する。

    composer_similarities は両端が自前 composers のペアしか持てないため、応答の大半が
    そのままでは捨てられる。名前のままキャッシュしておけば、後から作曲家が追加された
    ときに Last.fm を叩き直さずに突合できる。
    """
    rows = []
    seen: set[str] = set()
    for similar in similar_artists:
        name = (similar.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            score = float(similar.get("match", 0))
        except (TypeError, ValueError):
            continue
        rows.append({
            "composer_id": composer_id,
            "similar_name": name,
            "score": max(0.0, min(1.0, score)),
        })
    if rows:
        db.table("composer_similar_artists").upsert(
            rows, on_conflict="composer_id,similar_name"
        ).execute()


def resolve_similarities(composers: list[dict]) -> int:
    """キャッシュ済みの類似アーティスト名を現在の composers と突合して
    composer_similarities に反映する。Last.fm へのリクエストは発生しない。

    新しい作曲家が追加されたときは、過去に取得済みの応答の中にその名前が
    含まれていることがあるため、毎回キャッシュ全体を突合し直す。
    """
    cached: list[dict] = []
    offset = 0
    while True:
        page = (
            db.table("composer_similar_artists")
            .select("composer_id, similar_name, score")
            .range(offset, offset + 999)
            .execute()
            .data or []
        )
        cached.extend(page)
        if len(page) < 1000:
            break
        offset += 1000

    rows = build_similarity_pairs(cached, composers)
    if rows:
        db.table("composer_similarities").upsert(
            rows, on_conflict="composer_id_a,composer_id_b"
        ).execute()
    return len(rows)


def run(limit: int | None = None, overwrite: bool = False) -> None:
    composers = get_all_composers()
    if not composers:
        print("作曲家データがありません。先に import_steam_soundtracks.py を実行してください。")
        return

    # 未取得（lastfm_similar_fetched_at が NULL）の作曲家だけを対象にする。
    # Last.fm にデータが無い作曲家も取得済みとして記録するので、同じ作曲家を
    # 毎日問い合わせ直すことはない。
    pending = composers if overwrite else [
        c for c in composers if not c.get("lastfm_similar_fetched_at")
    ]
    targets = pending[:limit] if limit else pending

    if not targets:
        print(f"取得対象の作曲家はありません（全 {len(composers)} 人が取得済み）。")
    else:
        print(
            f"{len(targets)} 件の作曲家について類似度を取得します"
            f"（全 {len(composers)} 人 / 未取得 {len(pending)} 人）..."
        )

    fetched = 0
    empty = 0
    for composer in targets:
        search_name = composer.get("lastfm_name") or composer["name"]
        similar_artists = fetch_similar_artists(search_name)

        if similar_artists:
            _cache_similar_artists(composer["id"], similar_artists)
            fetched += len(similar_artists)
        else:
            empty += 1

        # 結果の有無に関わらず「問い合わせた」ことを記録する
        db.table("composers").update({
            "lastfm_similar_fetched_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", composer["id"]).execute()

        time.sleep(0.3)  # Last.fm レート制限（5 req/sec 以内）

    # 新規取得分に加え、過去のキャッシュも現在の作曲家一覧と突合し直す
    pairs = resolve_similarities(composers)

    print(
        f"完了 — 類似アーティスト {fetched} 件をキャッシュ"
        f"（Last.fm にデータなし {empty} 人）、"
        f"composer_similarities に {pairs} ペアを反映"
    )



if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Last.fm から作曲家間類似度を取得して composer_similarities に保存"
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="1回に取得する作曲家数の上限（デフォルト: 未取得の全件）")
    parser.add_argument("--overwrite", action="store_true", default=False,
                        help="lastfm_similar_fetched_at が設定済みの作曲家も再取得する")
    args = parser.parse_args()
    run(args.limit, overwrite=args.overwrite)
