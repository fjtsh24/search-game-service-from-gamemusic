"""
Steam の「良質サントラ」ユーザータグ（tag ID: 4667）で絞り込んだゲームを
新規取込み対象として追加するスクリプト。

import_steam_soundtracks.py（OST DLC 起点）を補完する別ルート。
「OST が Steam で別販売されていないが音楽が評価されているゲーム」を拾える。

タグ ID の確認方法:
  Steam のゲームページ（例: https://store.steampowered.com/app/550/Left4Dead2/）
  のソースで `良質サントラ` を検索 → `data-tagid="4667"` が確認できる。
  または: https://store.steampowered.com/tag/browse/#rgHeadingBrowse=4667

使い方:
  python3 scripts/import_steam_tag_search.py [--limit 20] [--min-score 8]

必要な環境変数 (.env ファイルまたはシェル環境で設定):
  SUPABASE_URL          : Supabase プロジェクト URL（例: https://xxxx.supabase.co）
  SUPABASE_SERVICE_ROLE_KEY : Supabase サービスロールキー

依存:
  pip install requests python-dotenv supabase
"""

import argparse
import html
import logging
import re
import time
import os
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

load_dotenv()

try:
    from supabase import create_client
except ImportError:
    print("pip install requests python-dotenv supabase")
    raise SystemExit(1)


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"エラー: 環境変数 {name} が設定されていません。.env ファイルを確認してください。")
        raise SystemExit(1)
    return val


SUPABASE_URL = _require_env("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = _require_env("SUPABASE_SERVICE_ROLE_KEY")
db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

STEAM_SEARCH_URL = "https://store.steampowered.com/search/results/"
STEAM_REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
STEAM_APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAM_WAIT = 1.2
PAGE_SIZE = 25
_RETRY_ATTEMPTS = 3
MIN_REVIEW_COUNT = 10
MAX_SCORE_CHECKS = 60
MAX_PAGES = 25

# Steam「良質サントラ」ユーザータグ ID
GREAT_SOUNDTRACK_TAG_ID = 4667

SCORE_LABELS = {
    9: "Overwhelmingly Positive",
    8: "Very Positive",
    7: "Mostly Positive",
    6: "Mixed",
    5: "Mostly Negative",
}

# 空文字列を除外: app_type が取得できないケース（API 失敗）はゲームと見なさない
_ALLOWED_APP_TYPES = {"game"}

http = requests.Session()
http.headers.update({"User-Agent": "GameMusicDiscovery/0.1.0 (hobby project)"})

_LOGO_APPID_RE = re.compile(r"/apps/(\d+)/")


# ── Steam API ─────────────────────────────────────────────────────────────────

def _http_get_with_retry(url: str, params: dict | None = None, timeout: int = 10) -> requests.Response:
    """指数バックオフで最大 _RETRY_ATTEMPTS 回リトライする HTTP GET。"""
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            resp = http.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt == _RETRY_ATTEMPTS - 1:
                raise
            wait = 2 ** attempt
            logging.warning("HTTP 失敗 (attempt %d/%d) %s: %s — %ds 待機", attempt + 1, _RETRY_ATTEMPTS, url, e, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def fetch_tag_search_page(tag_id: int, start: int) -> list[dict]:
    """Steam タグ検索結果をレビュー数降順で 25 件取得。"""
    time.sleep(STEAM_WAIT)
    try:
        resp = http.get(STEAM_SEARCH_URL, params={
            "tags": str(tag_id),
            "sort_by": "Reviews_DESC",
            "json": "1",
            "start": start,
            "count": PAGE_SIZE,
        }, timeout=15)
        resp.raise_for_status()

        results = []
        for item in resp.json().get("items", []):
            logo = item.get("logo", "")
            m = _LOGO_APPID_RE.search(logo)
            if not m:
                logging.warning("appid を logo URL から抽出できませんでした: logo=%r name=%r", logo, item.get("name"))
                continue
            results.append({
                "appid": int(m.group(1)),
                "title": html.unescape(item.get("name", "").strip()),
            })
        return results
    except requests.RequestException:
        logging.exception("fetch_tag_search_page HTTP 失敗 tag=%s start=%s", tag_id, start)
        return []
    except (ValueError, KeyError):
        logging.exception("fetch_tag_search_page JSON パース失敗 tag=%s start=%s", tag_id, start)
        return []


def fetch_review_score(appid: int) -> tuple[int, int, int]:
    """Steam appreviews API でゲームのレビュースコアを取得。"""
    time.sleep(STEAM_WAIT)
    try:
        resp = _http_get_with_retry(
            STEAM_REVIEWS_URL.format(appid=appid),
            params={"json": "1", "language": "all", "num_per_page": "0", "purchase_type": "all"},
        )
        qs = resp.json().get("query_summary", {})
        return (
            int(qs.get("review_score", 0)),
            int(qs.get("total_positive", 0)),
            int(qs.get("total_reviews", 0)),
        )
    except Exception:
        logging.exception("fetch_review_score 失敗 appid=%s", appid)
        return 0, 0, 0


def _fetch_appdetails(game_appid: int, lang: str) -> dict:
    time.sleep(STEAM_WAIT)
    try:
        resp = _http_get_with_retry(
            STEAM_APP_DETAILS_URL,
            params={"appids": game_appid, "filters": "basic,release_date", "l": lang},
        )
        d = resp.json().get(str(game_appid), {})
        return d.get("data", {}) if d.get("success") else {}
    except Exception:
        logging.exception("_fetch_appdetails 失敗 appid=%s lang=%s", game_appid, lang)
        return {}


def fetch_game_metadata(game_appid: int) -> tuple[str | None, str | None, str | None, str | None, int | None, str | None]:
    """Steam appdetails から short_description (en/ja/zh)・title_ja・release_year・type を取得。"""
    en_data = _fetch_appdetails(game_appid, "english")

    app_type = en_data.get("type", "")
    if app_type not in _ALLOWED_APP_TYPES:
        return None, None, None, None, None, app_type

    ja_data = _fetch_appdetails(game_appid, "japanese")
    zh_data = _fetch_appdetails(game_appid, "schinese")

    description_en = en_data.get("short_description") or None
    description_ja = ja_data.get("short_description") or None
    description_zh = zh_data.get("short_description") or None

    if description_ja == description_en:
        description_ja = None
    if description_zh == description_en:
        description_zh = None

    en_name = en_data.get("name") or ""
    ja_name = ja_data.get("name") or ""
    title_ja = ja_name if ja_name and ja_name != en_name else None

    release_year = None
    release_date = en_data.get("release_date", {})
    if not release_date.get("coming_soon") and release_date.get("date"):
        try:
            year = int(release_date["date"].strip()[-4:])
            if 1980 <= year <= 2030:
                release_year = year
        except (ValueError, IndexError):
            pass

    return description_en, description_ja, description_zh, title_ja, release_year, app_type


def steam_cover_url(game_appid: int) -> str:
    return f"https://cdn.akamai.steamstatic.com/steam/apps/{game_appid}/header.jpg"


# ── DB 操作 ───────────────────────────────────────────────────────────────────

def upsert_game(
    title: str,
    steam_app_id: int,
    cover_image_url: str,
    description: str | None = None,
    description_ja: str | None = None,
    description_zh: str | None = None,
    title_ja: str | None = None,
    release_year: int | None = None,
) -> str | None:
    payload: dict = {"title": title, "cover_image_url": cover_image_url}
    if description:
        payload["description"] = description
    if description_ja:
        payload["description_ja"] = description_ja
    if description_zh:
        payload["description_zh"] = description_zh
    if title_ja:
        payload["title_ja"] = title_ja
    if release_year:
        payload["release_year"] = release_year

    existing = db.table("games").select("id").eq("steam_app_id", steam_app_id).execute().data
    if existing:
        if len(existing) > 1:
            logging.warning("steam_app_id=%s の重複行が %d 件あります", steam_app_id, len(existing))
        game_id = existing[0]["id"]
        db.table("games").update(payload).eq("steam_app_id", steam_app_id).execute()
        return game_id

    result = db.table("games").insert({**payload, "steam_app_id": steam_app_id}).execute()
    return result.data[0]["id"] if result.data else None


# ── メインループ ───────────────────────────────────────────────────────────────

SCAN_OFFSET_KEY = "steam_tag_scan_offset"


def _load_scan_offset() -> int:
    """前回スキャン終了位置を DB から取得する。"""
    rows = db.table("system_settings").select("value").eq("key", SCAN_OFFSET_KEY).execute().data
    try:
        return int(rows[0]["value"]) if rows else 0
    except (IndexError, ValueError):
        return 0


def _save_scan_offset(offset: int) -> None:
    """次回スキャン開始位置を DB に保存する。"""
    db.table("system_settings").upsert(
        {
            "key": SCAN_OFFSET_KEY,
            "value": str(offset),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="key",
    ).execute()


def run(limit: int, min_score: int) -> None:
    label = SCORE_LABELS.get(min_score, f"score>={min_score}")
    print(f"Steam「良質サントラ」タグ検索（tag={GREAT_SOUNDTRACK_TAG_ID}、{label} 以上）を最大 {limit} 件取得します\n")

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

    scan_start = _load_scan_offset()
    print(f"スキャン開始位置: {scan_start} 件目\n")

    qualified: list[dict] = []
    start = scan_start
    score_checks = 0
    pages_fetched = 0
    reached_end = False

    while len(qualified) < limit and score_checks < MAX_SCORE_CHECKS and pages_fetched < MAX_PAGES:
        page = fetch_tag_search_page(GREAT_SOUNDTRACK_TAG_ID, start)
        if not page:
            print("Steam 検索結果の末尾に達しました。")
            reached_end = True
            break

        pages_fetched += 1
        for item in page:
            if len(qualified) >= limit or score_checks >= MAX_SCORE_CHECKS:
                break

            if item["appid"] in existing_app_ids:
                print(f"  skip  {item['title'][:50]:<50}  既登録")
                continue

            score_checks += 1
            score, pos, total = fetch_review_score(item["appid"])

            if total < MIN_REVIEW_COUNT:
                print(f"  skip  {item['title'][:50]:<50}  reviews={total} (少なすぎ)")
                continue

            pct = round(pos / total * 100) if total else 0
            tag = SCORE_LABELS.get(score, f"score={score}")
            status = "✓" if score >= min_score else "✗"
            print(f"  {status}  {item['title'][:50]:<50}  {tag} ({pct}% / {total}件)")

            if score >= min_score:
                qualified.append({**item, "score": score, "pct": pct})

        start += PAGE_SIZE
        print(f"  → {start} 件目まで / スコア確認 {score_checks} 件 / 合格 {len(qualified)} 件\n")

    next_offset = 0 if reached_end else start
    _save_scan_offset(next_offset)
    print(f"次回スキャン開始位置: {next_offset} 件目\n")

    qualified.sort(key=lambda x: (-x["score"], -x["pct"]))
    targets = qualified[:limit]
    print(f"\n合格 {len(qualified)} 件のうち上位 {len(targets)} 件を DB に登録します\n")

    imported = 0

    for i, item in enumerate(targets, 1):
        appid = item["appid"]
        title = item["title"]
        print(f"[{i}/{len(targets)}] {title} (appid={appid}  {SCORE_LABELS.get(item['score'],'')} {item['pct']}%)")

        description, description_ja, description_zh, title_ja, release_year, app_type = fetch_game_metadata(appid)
        if app_type not in _ALLOWED_APP_TYPES:
            reason = "API 取得失敗" if app_type == "" else f"type={app_type!r}"
            print(f"  skip: {reason} — 除外")
            continue

        if description:
            print(f"  説明文(en): {description[:60]}…")
        if title_ja:
            print(f"  タイトル(ja): {title_ja}")

        game_id = upsert_game(title, appid, steam_cover_url(appid), description, description_ja, description_zh, title_ja, release_year)
        if not game_id:
            print("  DB 登録失敗、スキップ")
            continue

        existing_app_ids.add(appid)
        imported += 1
        print()

    print(f"完了 — 新規ゲーム: {imported} 件")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Steam「良質サントラ」タグからゲームを取込む")
    parser.add_argument("--limit", type=int, default=5, help="最大取込み件数（デフォルト: 5）")
    parser.add_argument("--min-score", type=int, default=8, help="最低レビュースコア 0-9（デフォルト: 8 = Very Positive）")
    args = parser.parse_args()
    run(limit=args.limit, min_score=args.min_score)
