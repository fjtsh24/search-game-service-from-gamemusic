"""
Steam サウンドトラックを「高評価率」でフィルタして取得し、
作曲家情報を MusicBrainz から補完して DB に登録する。

検索方針:
  - Steam Soundtracks カテゴリ（category1=57）をレビュー数降順で広く取得
  - Steam appreviews API でサントラ自身のレビュースコアを確認
  - --min-score (デフォルト 8 = Very Positive 80%以上) を満たすものだけ採用
  - レビュー数が少なすぎる（< 10件）ものは除外（スコアが不安定なため）
  - 合格したものをスコア降順で並べ直してから DB に登録

スコア対応表（Steam appreviews API の review_score フィールド）:
  9 = Overwhelmingly Positive (95%+)
  8 = Very Positive (80-94%)      ← デフォルト
  7 = Mostly Positive  (70-79%)
  6 = Mixed            (40-69%)
  ...

修正点（2026-07-20）:
  - sort_by=Reviews_DESC（件数順）から高評価率フィルタ方式に変更
  - tracks / track_composers を作成するよう修正（作曲家とゲームの紐付け）
  - Steam CDN から cover_image_url を設定

使い方:
  python3 scripts/import_steam_soundtracks.py [--limit 200] [--min-score 8]

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
    "https://github.com/fjtsh24/search-game-service-from-gamemusic",
)

STEAM_SEARCH_URL = "https://store.steampowered.com/search/results/"
STEAM_REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
STEAM_WAIT = 1.2
MB_WAIT = 1.2
PAGE_SIZE = 25
MIN_REVIEW_COUNT = 10       # これ以下のレビュー数はスコアが不安定なためスキップ
MAX_CANDIDATE_RATIO = 5     # limit * N 件を候補として最大探索

SCORE_LABELS = {
    9: "Overwhelmingly Positive",
    8: "Very Positive",
    7: "Mostly Positive",
    6: "Mixed",
    5: "Mostly Negative",
}

http = requests.Session()
http.headers.update({"User-Agent": "GameMusicDiscovery/0.1.0 (hobby project)"})


# ── Steam API ─────────────────────────────────────────────────────────────────

def fetch_soundtrack_page(start: int) -> list[dict]:
    """Steam Soundtracks カテゴリをレビュー数降順で 25 件取得。"""
    time.sleep(STEAM_WAIT)
    resp = http.get(STEAM_SEARCH_URL, params={
        "category1": "57",
        "sort_by": "Reviews_DESC",
        "json": "1",
        "start": start,
        "count": PAGE_SIZE,
    }, timeout=15)
    resp.raise_for_status()

    results = []
    for item in resp.json().get("items", []):
        m = re.search(r"/apps/(\d+)/", item.get("logo", ""))
        if m:
            results.append({
                "appid": int(m.group(1)),
                "title": item.get("name", "").strip(),
            })
    return results


def fetch_review_score(appid: int) -> tuple[int, int, int]:
    """Steam appreviews API でサントラ自身のレビュースコアを取得。

    Returns:
        (review_score 0-9,  total_positive,  total_reviews)
    """
    time.sleep(STEAM_WAIT)
    try:
        resp = http.get(
            STEAM_REVIEWS_URL.format(appid=appid),
            params={"json": "1", "language": "all", "num_per_page": "0", "purchase_type": "all"},
            timeout=10,
        )
        resp.raise_for_status()
        qs = resp.json().get("query_summary", {})
        return (
            int(qs.get("review_score", 0)),
            int(qs.get("total_positive", 0)),
            int(qs.get("total_reviews", 0)),
        )
    except Exception:
        return 0, 0, 0


def steam_cover_url(appid: int) -> str:
    """Steam CDN のヘッダー画像 URL（API 不要）。"""
    return f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg"


# ── MusicBrainz ───────────────────────────────────────────────────────────────

def search_mb_releases(game_title: str) -> list[dict]:
    """ゲームタイトルでサントラリリースを検索。タイトルが部分一致しない結果は除外。"""
    time.sleep(MB_WAIT)
    try:
        result = musicbrainzngs.search_releases(
            query=f'"{game_title}" secondarytype:soundtrack',
            limit=5,
        )
        title_lower = game_title.lower()
        return [
            r for r in result.get("release-list", [])
            if title_lower in r.get("title", "").lower()
            or r.get("title", "").lower() in title_lower
        ]
    except Exception:
        return []


# ── DB 操作 ───────────────────────────────────────────────────────────────────

def upsert_game(title: str, steam_app_id: int, cover_image_url: str, mb_release_id: str | None) -> str | None:
    """ゲームを upsert して game_id を返す。"""
    existing = db.table("games").select("id").eq("steam_app_id", steam_app_id).execute().data
    if existing:
        db.table("games").update({
            "title": title,
            "cover_image_url": cover_image_url,
            **({"musicbrainz_release_id": mb_release_id} if mb_release_id else {}),
        }).eq("steam_app_id", steam_app_id).execute()
        return existing[0]["id"]

    payload: dict = {"title": title, "steam_app_id": steam_app_id, "cover_image_url": cover_image_url}
    if mb_release_id:
        payload["musicbrainz_release_id"] = mb_release_id
    result = db.table("games").insert(payload).execute()
    return result.data[0]["id"] if result.data else None


def get_or_create_track(game_id: str, title: str) -> str | None:
    """ゲームの代表トラックを返す。なければ作成する。"""
    rows = db.table("tracks").select("id").eq("game_id", game_id).limit(1).execute().data
    if rows:
        return rows[0]["id"]
    result = db.table("tracks").insert({
        "game_id": game_id,
        "title": f"{title} Soundtrack",
        "track_number": 1,
    }).execute()
    return result.data[0]["id"] if result.data else None


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


def link_composer_to_track(composer_id: str, track_id: str) -> None:
    db.table("track_composers").upsert(
        {"track_id": track_id, "composer_id": composer_id, "is_primary": True},
        on_conflict="track_id,composer_id",
    ).execute()


# ── メインループ ───────────────────────────────────────────────────────────────

def run(limit: int, min_score: int) -> None:
    label = SCORE_LABELS.get(min_score, f"score>={min_score}")
    print(f"Steam サウンドトラック（{label} 以上）を最大 {limit} 件取得します")
    print(f"最大 {limit * MAX_CANDIDATE_RATIO} 件を候補としてスキャンします\n")

    # ── フェーズ 1: 候補収集とスコアフィルタリング ───────────────────────────
    qualified: list[dict] = []
    start = 0
    scanned = 0
    max_scan = limit * MAX_CANDIDATE_RATIO

    while len(qualified) < limit and scanned < max_scan:
        page = fetch_soundtrack_page(start)
        if not page:
            print("検索結果の末尾に達しました")
            break

        for item in page:
            if len(qualified) >= limit or scanned >= max_scan:
                break

            scanned += 1
            score, pos, total = fetch_review_score(item["appid"])

            if total < MIN_REVIEW_COUNT:
                print(f"  skip  {item['title'][:45]:<45}  reviews={total} (少なすぎ)")
                continue

            pct = round(pos / total * 100) if total else 0
            tag = SCORE_LABELS.get(score, f"score={score}")
            status = "✓" if score >= min_score else "✗"
            print(f"  {status}  {item['title'][:45]:<45}  {tag} ({pct}% / {total}件)")

            if score >= min_score:
                qualified.append({**item, "score": score, "pct": pct})

        start += PAGE_SIZE
        print(f"  → スキャン {scanned} 件 / 合格 {len(qualified)} 件\n")

    # スコア降順→肯定率降順でソート
    qualified.sort(key=lambda x: (-x["score"], -x["pct"]))
    targets = qualified[:limit]
    print(f"合格 {len(qualified)} 件のうち上位 {len(targets)} 件を DB に登録します\n")

    # ── フェーズ 2: DB 登録 ───────────────────────────────────────────────────
    imported = 0
    composers_linked = 0

    for i, item in enumerate(targets, 1):
        appid = item["appid"]
        title = item["title"]
        print(f"[{i}/{len(targets)}] {title} (appid={appid}  {SCORE_LABELS.get(item['score'],'')} {item['pct']}%)")

        # MusicBrainz で作曲家検索
        mb_releases = search_mb_releases(title)
        mb_release_id: str | None = None
        composer_ids: list[str] = []

        if mb_releases:
            release = mb_releases[0]
            mb_release_id = release.get("id")
            for credit in release.get("artist-credit", []):
                if not isinstance(credit, dict):
                    continue
                artist = credit.get("artist")
                if artist:
                    cid = upsert_composer(artist)
                    if cid:
                        composer_ids.append(cid)
            print(f"  MusicBrainz: 作曲家 {len(composer_ids)} 件")
        else:
            print("  MusicBrainz: 該当なし")

        # ゲーム登録
        game_id = upsert_game(title, appid, steam_cover_url(appid), mb_release_id)
        if not game_id:
            print("  DB 登録失敗、スキップ")
            continue

        # 代表トラック作成 → 作曲家を紐付け
        if composer_ids:
            track_id = get_or_create_track(game_id, title)
            if track_id:
                for cid in composer_ids:
                    link_composer_to_track(cid, track_id)
                composers_linked += len(composer_ids)
                print(f"  track_composers: {len(composer_ids)} 件紐付け")

        imported += 1
        print()

    print(f"完了 — ゲーム: {imported} 件, 作曲家紐付け: {composers_linked} 件")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Steam 高評価サウンドトラックを DB に登録する"
    )
    parser.add_argument("--limit", type=int, default=200,
                        help="登録するゲーム数 (デフォルト: 200)")
    parser.add_argument("--min-score", type=int, default=8,
                        help="Steam レビュースコアの最小値 1-9 (デフォルト: 8 = Very Positive 80%%以上)")
    args = parser.parse_args()
    run(args.limit, args.min_score)
