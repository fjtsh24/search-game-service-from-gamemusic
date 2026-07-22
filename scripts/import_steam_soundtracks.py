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

修正点（2026-07-20 #2）:
  - games.steam_app_id にサントラDLCのappidではなくゲーム本体のappidを保存するよう修正
  - appdetails API で fullgame.appid を取得して親ゲームを特定
  - カバー画像もゲーム本体の header.jpg を使用（サービスの目的に合致）

使い方:
  python3 scripts/import_steam_soundtracks.py [--limit 200] [--min-score 8]
  python3 scripts/import_steam_soundtracks.py --backfill [--limit 30]
    --backfill: Steam検索をせず、DBの既存ゲームで説明文（ja/zh）が欠損しているものを補完する

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
    from supabase import create_client
except ImportError:
    print("pip install requests python-dotenv supabase")
    raise SystemExit(1)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

STEAM_SEARCH_URL = "https://store.steampowered.com/search/results/"
STEAM_REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
STEAM_APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAM_WAIT = 1.2
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


_OST_KEYWORDS = ("soundtrack", " ost", "original score", "music pack", "sound pack")

def _title_looks_like_standalone_ost(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _OST_KEYWORDS)


def fetch_parent_game_appid(soundtrack_appid: int, title: str) -> int:
    """サントラ商品のappidからゲーム本体のappidを取得する。

    Steam category1=57 の検索結果は大半がゲーム本体のappidを返す（OST同梱ゲーム）が、
    タイトルに "Soundtrack" 等が含まれる場合は別途 appdetails で確認する。
    fullgame フィールドが存在する DLC 型 OST はここで正しく解決できる。
    ただし Steam API の fullgame は常に設定されるわけではないため、
    解決できなかった場合は元のappidをそのまま使う（既知の限界）。
    """
    if not _title_looks_like_standalone_ost(title):
        # タイトルがゲーム名そのもの → appdetails 不要、既に正しいappid
        return soundtrack_appid

    time.sleep(STEAM_WAIT)
    try:
        resp = http.get(
            STEAM_APP_DETAILS_URL,
            params={"appids": soundtrack_appid, "filters": "basic,fullgame"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get(str(soundtrack_appid), {})
        if not data.get("success"):
            return soundtrack_appid
        fullgame = data.get("data", {}).get("fullgame", {})
        parent_appid = fullgame.get("appid")
        if parent_appid:
            return int(parent_appid)
        # fullgame なし → 解決不可、元のappidを使う（既知の限界: Steam API が fullgame を
        # 常に設定するわけではないため、一部の standalone OST は game_app_id が OST appid のままになる）
        return soundtrack_appid
    except Exception:
        return soundtrack_appid


def steam_cover_url(game_appid: int) -> str:
    """ゲーム本体のappidから Steam CDN ヘッダー画像 URL を生成（API 不要）。
    サントラDLCではなくゲーム本体のカバー画像を使う。
    """
    return f"https://cdn.akamai.steamstatic.com/steam/apps/{game_appid}/header.jpg"


def _fetch_appdetails(game_appid: int, lang: str) -> dict:
    """指定言語で Steam appdetails を取得して data フィールドを返す。"""
    time.sleep(STEAM_WAIT)
    try:
        resp = http.get(
            STEAM_APP_DETAILS_URL,
            params={"appids": game_appid, "filters": "basic,release_date", "l": lang},
            timeout=10,
        )
        resp.raise_for_status()
        d = resp.json().get(str(game_appid), {})
        return d.get("data", {}) if d.get("success") else {}
    except Exception:
        return {}


_ALLOWED_APP_TYPES = {"game", ""}   # "game" または type 不明のものは通す

def fetch_game_metadata(game_appid: int) -> tuple[str | None, str | None, str | None, int | None, str | None]:
    """Steam appdetails から short_description (en/ja/zh)・release_year・type を取得。

    Returns:
        (description_en, description_ja, description_zh, release_year, app_type)
        app_type が "dlc" / "demo" / "advertising" 等の場合は登録をスキップすること。
    """
    en_data = _fetch_appdetails(game_appid, "english")

    app_type = en_data.get("type", "")
    if app_type not in _ALLOWED_APP_TYPES:
        # DLC・デモ等はここで早期リターン（ja/zh の API 呼び出しを省略）
        return None, None, None, None, app_type

    ja_data = _fetch_appdetails(game_appid, "japanese")
    zh_data = _fetch_appdetails(game_appid, "schinese")

    description_en = en_data.get("short_description") or None
    description_ja = ja_data.get("short_description") or None
    description_zh = zh_data.get("short_description") or None

    # 英語と同一テキストなら格納しない（翻訳なし扱い）
    if description_ja == description_en:
        description_ja = None
    if description_zh == description_en:
        description_zh = None

    release_year = None
    release_date = en_data.get("release_date", {})
    if not release_date.get("coming_soon") and release_date.get("date"):
        try:
            year = int(release_date["date"].strip()[-4:])
            if 1980 <= year <= 2030:
                release_year = year
        except (ValueError, IndexError):
            pass

    return description_en, description_ja, description_zh, release_year, app_type


# ── DB 操作 ───────────────────────────────────────────────────────────────────

def upsert_game(
    title: str,
    steam_app_id: int,
    cover_image_url: str,
    description: str | None = None,
    description_ja: str | None = None,
    description_zh: str | None = None,
    release_year: int | None = None,
) -> str | None:
    """ゲームを upsert して game_id を返す。"""
    payload: dict = {"title": title, "cover_image_url": cover_image_url}
    if description:
        payload["description"] = description
    if description_ja:
        payload["description_ja"] = description_ja
    if description_zh:
        payload["description_zh"] = description_zh
    if release_year:
        payload["release_year"] = release_year

    existing = db.table("games").select("id").eq("steam_app_id", steam_app_id).execute().data
    if existing:
        db.table("games").update(payload).eq("steam_app_id", steam_app_id).execute()
        return existing[0]["id"]

    result = db.table("games").insert({**payload, "steam_app_id": steam_app_id}).execute()
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



# ── メインループ ───────────────────────────────────────────────────────────────

def run(limit: int, min_score: int) -> None:
    label = SCORE_LABELS.get(min_score, f"score>={min_score}")
    print(f"Steam サウンドトラック（{label} 以上）を最大 {limit} 件取得します")
    print(f"最大 {limit * MAX_CANDIDATE_RATIO} 件を候補としてスキャンします\n")

    # 既登録の steam_app_id を取得（スキャン中のスキップ判定に使用）
    existing_app_ids: set[int] = {
        row["steam_app_id"]
        for row in (
            db.table("games")
            .select("steam_app_id")
            .not_.is_("steam_app_id", "null")
            .execute()
            .data or []
        )
    }
    print(f"既登録ゲーム: {len(existing_app_ids)} 件\n")

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

            # 非OST タイトルは appid = game_appid なので早期スキップ可能
            if not _title_looks_like_standalone_ost(item["title"]) and item["appid"] in existing_app_ids:
                print(f"  skip  {item['title'][:45]:<45}  既登録")
                continue

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

    for i, item in enumerate(targets, 1):
        soundtrack_appid = item["appid"]
        title = item["title"]
        print(f"[{i}/{len(targets)}] {title} (soundtrack_appid={soundtrack_appid}  {SCORE_LABELS.get(item['score'],'')} {item['pct']}%)")

        # ゲーム本体のappidを取得
        game_appid = fetch_parent_game_appid(soundtrack_appid, title)
        if game_appid != soundtrack_appid:
            print(f"  親ゲーム appid: {soundtrack_appid} → {game_appid} (fullgame 解決)")
        elif _title_looks_like_standalone_ost(title):
            print(f"  ⚠ 単独OST検出 / fullgame 未解決 → appid={game_appid} をそのまま使用")

        # OST タイトルは親解決後に既登録チェック
        if game_appid in existing_app_ids:
            print(f"  skip: 既登録 (appid={game_appid})")
            continue

        # ゲーム本体のメタデータ取得（説明文 en/ja/zh・リリース年・アプリ種別）
        description, description_ja, description_zh, release_year, app_type = fetch_game_metadata(game_appid)
        if app_type not in _ALLOWED_APP_TYPES:
            print(f"  skip: type={app_type!r} — ゲーム本体ではないため除外")
            continue
        if description:
            print(f"  説明文(en): {description[:60]}…")
        if description_ja:
            print(f"  説明文(ja): {description_ja[:60]}…")
        if description_zh:
            print(f"  説明文(zh): {description_zh[:60]}…")
        if release_year:
            print(f"  リリース年: {release_year}")

        # ゲーム登録
        game_id = upsert_game(title, game_appid, steam_cover_url(game_appid), description, description_ja, description_zh, release_year)
        if not game_id:
            print("  DB 登録失敗、スキップ")
            continue

        existing_app_ids.add(game_appid)
        imported += 1
        print()

    print(f"完了 — ゲーム: {imported} 件")


# ── バックフィルモード ─────────────────────────────────────────────────────────

def run_backfill(limit: int) -> None:
    """DBの既存ゲームで説明文（ja/zh）が欠損しているものを Steam API で補完する。
    Steam検索は行わず、保存済みの steam_app_id を使って直接 appdetails を取得する。
    """
    print(f"Steam 説明文バックフィル（最大 {limit} 件）\n")

    rows = (
        db.table("games")
        .select("id, title, steam_app_id, description, description_ja, description_zh")
        .not_.is_("steam_app_id", "null")
        .or_("description.is.null,description_ja.is.null,description_zh.is.null")
        .order("updated_at", desc=False)
        .limit(limit)
        .execute()
        .data or []
    )

    if not rows:
        print("補完対象のゲームはありません。")
        return

    print(f"{len(rows)} 件のゲームを補完します...\n")
    updated = 0

    for i, game in enumerate(rows, 1):
        title = game["title"]
        steam_app_id = game["steam_app_id"]
        print(f"[{i}/{len(rows)}] {title} (appid={steam_app_id})")

        desc_en, desc_ja, desc_zh, release_year, app_type = fetch_game_metadata(steam_app_id)
        if app_type not in _ALLOWED_APP_TYPES:
            print(f"  skip: type={app_type!r} — ゲーム本体ではないため除外")
            continue

        payload: dict = {}
        if game.get("description") is None and desc_en:
            payload["description"] = desc_en
        if game.get("description_ja") is None and desc_ja:
            payload["description_ja"] = desc_ja
        if game.get("description_zh") is None and desc_zh:
            payload["description_zh"] = desc_zh
        if game.get("release_year") is None and release_year:
            payload["release_year"] = release_year

        if payload:
            db.table("games").update(payload).eq("id", game["id"]).execute()
            filled = [k for k in ("description", "description_ja", "description_zh", "release_year") if k in payload]
            print(f"  → 更新: {', '.join(filled)}")
            updated += 1
        else:
            # 新規データなし: updated_at を更新してキューの末尾に回す（翌日以降は他ゲーム優先）
            db.table("games").update({"updated_at": "now()"}).eq("id", game["id"]).execute()
            print("  → 取得できる新規データなし（スキップ）")
        print()

    print(f"完了 — {updated}/{len(rows)} 件を更新")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Steam 高評価サウンドトラックを DB に登録する"
    )
    parser.add_argument("--limit", type=int, default=200,
                        help="登録するゲーム数 (デフォルト: 200)")
    parser.add_argument("--min-score", type=int, default=8,
                        help="Steam レビュースコアの最小値 1-9 (デフォルト: 8 = Very Positive 80%%以上)")
    parser.add_argument("--backfill", action="store_true",
                        help="DBの既存ゲームで欠損している説明文を補完する（Steam検索なし）")
    args = parser.parse_args()
    if args.backfill:
        run_backfill(args.limit)
    else:
        run(args.limit, args.min_score)
