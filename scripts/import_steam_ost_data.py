"""
Steam Music アプリ（type=music）からトラックリストと作曲家クレジットを取得して DB に保存する。

2フェーズで実行:
  Phase discover（APIベース）:
    steam_ost_appid が未設定かつ steam_ost_locked=FALSE のゲームを対象に、
    Steam Search + appdetails API で対応する Music アプリを発見して
    games.steam_ost_appid に保存する。
    見つからなかったゲームには steam_ost_locked=TRUE をセットして以後スキップ。

  Phase tags（APIベース）:
    steam_ost_appid があるゲームの OST 説明文を appdetails API から取得し、
    ムードタグを抽出して game_tags に保存する（added_by='steam_ost_desc'）。
    games.description と違い OST 説明文は音楽そのものの記述なのでタグ抽出に有効。

  Phase scrape（HTMLスクレイピング）:
    steam_ost_appid があって steam_ost_scraped_at が未設定のゲームを対象に、
    Steam ストアページをスクレイピングしてトラックリストと作曲家クレジットを取得する。
    サーバー負荷への配慮として、リクエスト間隔を 600 秒（10分）に設定している。

使い方:
  python3 scripts/import_steam_ost_data.py [--phase discover|tags|scrape|all] [--limit N] [--overwrite]

  --phase discover : OSTアプリIDの発見のみ（デフォルト上限: 50件）
  --phase tags     : OST説明文からムードタグ抽出（デフォルト上限: 50件）
  --phase scrape   : スクレイピングのみ（デフォルト上限: 3件）
  --phase all      : 両方を順番に実行（デフォルト）
  --limit N        : 処理件数上限
  --overwrite      : steam_ost_locked=TRUE のゲームも再試行する

依存:
  pip install requests python-dotenv supabase beautifulsoup4
"""

import argparse
import os
import re
import time
from html import unescape
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from music_text_tags import extract_tags

load_dotenv(dotenv_path=".env")

try:
    from supabase import create_client
except ImportError:
    print("pip install requests python-dotenv supabase beautifulsoup4")
    raise SystemExit(1)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

db = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

STEAM_SEARCH_URL = "https://store.steampowered.com/search/results/"
STEAM_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAM_STORE_URL = "https://store.steampowered.com/app/{appid}/"

DISCOVER_WAIT = 1.0
SCRAPE_WAIT = 120
TAGS_WAIT = 1.3

# OST 説明文由来タグの識別子と確信度（Tier 1: 音楽そのものの記述に基づく直接証拠）
OST_TAG_SOURCE = "steam_ost_desc"
OST_TAG_CONFIDENCE = 0.9

UPSTASH_REDIS_URL = os.environ.get("UPSTASH_REDIS_URL", "")
UPSTASH_REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_TOKEN", "")

_OST_KEYWORDS = ("soundtrack", "ost", "music")

http = requests.Session()
http.headers.update({
    "User-Agent": "GameMusicDiscovery/0.1.0 (hobby project; contact: rob.rom.room@gmail.com)",
    "Referer": "https://store.steampowered.com/",
})


# ── ユーティリティ ────────────────────────────────────────────────────────────

def _parse_duration(text: str) -> int | None:
    """'3:39' → 219 秒。パースできなければ None。"""
    text = text.strip()
    m = re.match(r"^(\d+):(\d{2})$", text)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


# ── Phase discover ────────────────────────────────────────────────────────────

def _find_ost_appid(game_title: str, game_appid: int) -> int | None:
    """Steam Search + appdetails で Music アプリを探す。見つからなければ None。"""
    time.sleep(DISCOVER_WAIT)
    try:
        resp = http.get(STEAM_SEARCH_URL, params={
            "term": f"{game_title} soundtrack",
            "json": "1",
            "count": "5",
        }, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Steam Search エラー: {e}")
        return None

    for item in resp.json().get("items", []):
        name = item.get("name", "")
        if not any(kw in name.lower() for kw in _OST_KEYWORDS):
            continue

        # appid の取得: 直接フィールド → logo URL → icon URL の順で試みる
        if item.get("appid"):
            candidate_appid = int(item["appid"])
        else:
            logo_or_icon = item.get("logo", "") or item.get("icon", "") or ""
            m = re.search(r"/apps/(\d+)/", logo_or_icon)
            if not m:
                print(f"  SKIP（appid 解析不可）: item={list(item.keys())}")
                continue
            candidate_appid = int(m.group(1))

        time.sleep(DISCOVER_WAIT)
        try:
            detail_resp = http.get(STEAM_APPDETAILS_URL, params={
                "appids": candidate_appid,
                "filters": "basic,fullgame",
            }, timeout=10)
            detail_resp.raise_for_status()
        except Exception as e:
            print(f"  appdetails エラー (appid={candidate_appid}): {e}")
            continue

        entry = detail_resp.json().get(str(candidate_appid)) or {}
        if not entry.get("success"):
            continue
        data = entry["data"]
        if data.get("type") != "music":
            continue
        fg = data.get("fullgame") or {}
        if str(fg.get("appid")) == str(game_appid):
            return candidate_appid

    return None


def _lock_ost(game_id: str) -> None:
    """steam_ost_locked = TRUE をセット。以後の日次バッチでスキップされる。"""
    db.table("games").update({"steam_ost_locked": True}).eq("id", game_id).execute()


def run_discover(limit: int, overwrite: bool = False) -> None:
    query = (
        db.table("games")
        .select("id, title, steam_app_id")
        .is_("steam_ost_appid", "null")
        .not_.is_("steam_app_id", "null")
        .order("created_at", desc=False)
        .limit(limit)
    )
    if not overwrite:
        query = query.eq("steam_ost_locked", False)
    games = query.execute().data or []

    if not games:
        print("[discover] 対象ゲームなし。")
        return

    print(f"[discover] {len(games)} 件を処理します...")
    found = 0
    locked_titles: list[str] = []
    for i, game in enumerate(games, 1):
        title = game["title"]
        appid = game["steam_app_id"]
        print(f"[{i}/{len(games)}] {title}")
        ost_appid = _find_ost_appid(title, appid)
        if ost_appid:
            db.table("games").update({"steam_ost_appid": ost_appid, "steam_ost_locked": False}).eq("id", game["id"]).execute()
            print(f"  → steam_ost_appid={ost_appid}")
            found += 1
        else:
            _lock_ost(game["id"])
            locked_titles.append(title)
            print("  → 見つからず（steam_ost_locked=TRUE）")

    print(f"[discover] 完了 — {found}/{len(games)} 件で OST アプリ発見")
    if locked_titles:
        print(f"locked 追加: {len(locked_titles)} 件（再試行するには steam_ost_locked=FALSE に更新）")
        for t in locked_titles:
            print(f"  - {t}")


# ── Phase scrape ──────────────────────────────────────────────────────────────

def _scrape_ost_page(ost_appid: int) -> tuple[list[dict], dict]:
    """
    Steam OST ページをスクレイピングしてトラックリストとクレジットを返す。
    Returns: (tracks, credits)
      tracks: [{"number": int, "title": str, "duration_seconds": int|None}, ...]
      credits: {"artist": str|None, "composer": str|None, "label": str|None}
    """
    url = STEAM_STORE_URL.format(appid=ost_appid)
    try:
        resp = http.get(url, cookies={
            "birthtime": "0",
            "lastagecheckage": "1-0-1990",
            "mature_content": "1",
        }, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  HTTP エラー: {e}")
        return [], {}

    soup = BeautifulSoup(resp.text, "html.parser")

    # トラックリスト
    tracks = []
    for ctn in soup.select("div.music_album_track_ctn"):
        name_el = ctn.select_one(".music_album_track_name")
        dur_el = ctn.select_one(".music_album_track_duration")
        if not name_el:
            continue
        number = len(tracks) + 1  # 全体での連番（複数アルバムで番号が重複するため）
        title = name_el.get_text(strip=True)
        duration = _parse_duration(dur_el.get_text()) if dur_el else None
        tracks.append({"number": number, "title": title, "duration_seconds": duration})

    # クレジット
    credits: dict[str, str | None] = {"artist": None, "composer": None, "label": None}
    for row in soup.select("tr.album_metadata_row"):
        key_el = row.select_one("td.album_metadata_chunk_name")
        val_el = row.select_one("td.album_metadata_chunk_contents")
        if not key_el or not val_el:
            continue
        key = key_el.get_text(strip=True).lower().rstrip(":")
        val = val_el.get_text(strip=True)
        if key == "artist":
            credits["artist"] = val
        elif key == "composer":
            credits["composer"] = val
        elif key == "label":
            credits["label"] = val

    return tracks, credits


def _split_composer_names(raw: str) -> list[str]:
    """", " や " & " で区切られた複合作曲家名を個別名に分割して返す。"""
    return [name.strip() for name in re.split(r",\s+|\s+&\s+", raw) if name.strip()]


def _upsert_composers(names: list[str]) -> dict[str, str]:
    """composer 名リストを composers テーブルに UPSERT して {name: id} を返す。"""
    name_to_id: dict[str, str] = {}
    for name in names:
        if not name:
            continue
        existing = (
            db.table("composers")
            .select("id")
            .eq("name", name)
            .limit(1)
            .execute()
            .data or []
        )
        if existing:
            name_to_id[name] = existing[0]["id"]
        else:
            result = db.table("composers").insert({"name": name}).execute()
            if result.data:
                name_to_id[name] = result.data[0]["id"]
    return name_to_id


def _save_tracks_and_composers(
    game: dict,
    scraped_tracks: list[dict],
    credits: dict,
) -> None:
    """トラックと作曲家をDBに保存する。
    既存トラックは track_number をキーに更新（id を保持）し、
    スクレイプに存在しなくなったトラックのみ削除する。
    削除→再挿入を避けることで外部参照（track_composers 等）の整合性を保つ。
    """
    game_id = game["id"]

    if not scraped_tracks:
        return

    # 既存トラックを track_number でインデックス化
    existing = (
        db.table("tracks")
        .select("id, track_number")
        .eq("game_id", game_id)
        .execute()
        .data or []
    )
    existing_by_number: dict[int, str] = {ex["track_number"]: ex["id"] for ex in existing}
    scraped_numbers = {t["number"] for t in scraped_tracks}

    saved_track_ids: list[str] = []
    for t in scraped_tracks:
        track_payload = {
            "title": t["title"],
            "duration_seconds": t["duration_seconds"],
        }
        existing_id = existing_by_number.get(t["number"])
        if existing_id:
            # 既存トラックを更新（id・youtube_video_id を保持）
            db.table("tracks").update(track_payload).eq("id", existing_id).execute()
            saved_track_ids.append(existing_id)
        else:
            # 新規トラックを挿入
            result = db.table("tracks").insert({
                "game_id": game_id,
                "track_number": t["number"],
                **track_payload,
            }).execute()
            if result.data:
                saved_track_ids.append(result.data[0]["id"])

    # スクレイプ結果に存在しない古いトラックを削除
    obsolete_ids = [eid for num, eid in existing_by_number.items() if num not in scraped_numbers]
    for eid in obsolete_ids:
        db.table("tracks").delete().eq("id", eid).execute()

    # 作曲家クレジット（", " や " & " で区切られた複数名を個別に分割）
    composer_names = list({
        name
        for raw in [credits.get("composer"), credits.get("artist")]
        if raw
        for name in _split_composer_names(raw)
    })
    if not composer_names or not saved_track_ids:
        return

    name_to_id = _upsert_composers(composer_names)

    # track_composers は全置換（作曲家クレジットが変わる可能性があるため）
    db.table("track_composers").delete().in_("track_id", saved_track_ids).execute()
    rows = [
        {"track_id": tid, "composer_id": cid, "is_primary": True}
        for tid in saved_track_ids
        for cid in name_to_id.values()
    ]
    if rows:
        db.table("track_composers").insert(rows).execute()


def run_scrape(limit: int) -> None:
    games = (
        db.table("games")
        .select("id, title, steam_ost_appid")
        .not_.is_("steam_ost_appid", "null")
        .is_("steam_ost_scraped_at", "null")
        .limit(limit)
        .execute()
        .data or []
    )

    if not games:
        print("[scrape] 対象ゲームなし。")
        return

    print(f"[scrape] {len(games)} 件を処理します（2分間隔）...")

    for i, game in enumerate(games, 1):
        title = game["title"]
        ost_appid = game["steam_ost_appid"]
        print(f"[{i}/{len(games)}] {title} (OST appid={ost_appid})")

        tracks, credits = _scrape_ost_page(ost_appid)

        if not tracks and not any(credits.values()):
            # HTTP エラー等で取得失敗 → steam_ost_scraped_at をセットしない（次回再試行対象に残す）
            print("  → トラックリスト・クレジットともに取得できず（スキップ、次回再試行）")
        else:
            print(f"  → トラック {len(tracks)} 件 / credits={credits}")
            _save_tracks_and_composers(game, tracks, credits)
            now = datetime.now(timezone.utc).isoformat()
            db.table("games").update({"steam_ost_scraped_at": now}).eq("id", game["id"]).execute()
            print(f"  → steam_ost_scraped_at 更新")

        if i < len(games):
            print(f"  → {SCRAPE_WAIT // 60} 分待機...")
            time.sleep(SCRAPE_WAIT)

    print(f"[scrape] 完了 — {len(games)} 件処理")



# ── Phase tags ────────────────────────────────────────────────────────────────

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _plain_text(html_text: str) -> str:
    """Steam の説明文 HTML からプレーンテキストを取り出す。"""
    if not html_text:
        return ""
    return " ".join(unescape(_HTML_TAG_RE.sub(" ", html_text)).split())


def _fetch_ost_description(ost_appid: int) -> str:
    """appdetails API から OST の説明文（detailed + short）を取得する。

    ストアページの HTML スクレイピングではなく appdetails API を使う。
    """
    time.sleep(TAGS_WAIT)
    try:
        resp = http.get(STEAM_APPDETAILS_URL, params={
            "appids": ost_appid,
            "l": "english",
        }, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  appdetails エラー (appid={ost_appid}): {e}")
        return ""

    entry = resp.json().get(str(ost_appid)) or {}
    if not entry.get("success"):
        return ""
    data = entry["data"]
    return _plain_text(
        f"{data.get('detailed_description') or ''} {data.get('short_description') or ''}"
    )


def _clear_tag_cache(game_ids: list[str], tag_ids: list[str]) -> None:
    """タグ更新後に関連する Redis キャッシュを削除する。"""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return
    keys: list[str] = []
    for gid in game_ids:
        keys.append(f"games:detail:{gid}")
        keys.append(f"games:similar:{gid}:8")
    for tid in tag_ids:
        for limit in (20, 50, 100):
            keys.append(f"games:list:{tid}:{limit}")
    for limit in (20, 50, 100):
        keys.append(f"games:list:all:{limit}")
    if not keys:
        return
    try:
        resp = http.post(
            f"{UPSTASH_REDIS_URL}/",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            json=["del"] + keys,
            timeout=5,
        )
        print(f"キャッシュクリア: {resp.json().get('result', '?')} 件削除")
    except Exception as e:
        print(f"キャッシュクリア失敗（無視）: {e}")


def run_tags(limit: int, dry_run: bool = False) -> None:
    """OST ストアページの説明文から mood タグを抽出して game_tags に保存する。

    games.description（Steam の short_description）はゲームプレイの宣伝文であり
    音楽への言及をほとんど含まないが、OST（type=music）の説明文は音楽そのものの
    記述であるため、mood タグの抽出元として有効。
    詳細: docs/planning/08_tagging_redesign.md §4-A
    """
    tag_rows = db.table("mood_tags").select("id, name").execute().data or []
    tag_id_map: dict[str, str] = {r["name"]: r["id"] for r in tag_rows}

    # すでにこのソースでタグ付け済みのゲームは対象外
    done_rows = (
        db.table("game_tags")
        .select("game_id")
        .eq("added_by", OST_TAG_SOURCE)
        .execute()
        .data or []
    )
    already_done = {r["game_id"] for r in done_rows}

    candidates = (
        db.table("games")
        .select("id, title, steam_ost_appid")
        .not_.is_("steam_ost_appid", "null")
        .order("created_at", desc=False)
        .execute()
        .data or []
    )
    games = [g for g in candidates if g["id"] not in already_done][:limit]

    if not games:
        print("[tags] 対象ゲームなし。")
        return

    print(f"[tags] {len(games)} 件を処理します...")
    tagged_game_ids: list[str] = []
    tagged_tag_ids: set[str] = set()
    total_tags = 0
    no_match = 0

    for i, game in enumerate(games, 1):
        title = game["title"]
        print(f"[{i}/{len(games)}] {title}")

        text = _fetch_ost_description(game["steam_ost_appid"])
        if not text:
            print("  → 説明文を取得できず（次回再試行）")
            continue

        names = extract_tags(text, music_context=True)
        if not names:
            print(f"  → ムードタグにマッチせず（{len(text)} 字）")
            no_match += 1
            continue

        rows = []
        for name in names:
            tid = tag_id_map.get(name)
            if not tid:
                print(f"  タグ ID 不明: {name}")
                continue
            rows.append({
                "game_id": game["id"],
                "tag_id": tid,
                "confidence": OST_TAG_CONFIDENCE,
                "added_by": OST_TAG_SOURCE,
            })
            tagged_tag_ids.add(tid)

        if not rows:
            continue

        print(f"  → タグ付与: {', '.join(names)}")
        if not dry_run:
            db.table("game_tags").upsert(rows, on_conflict="game_id,tag_id").execute()
        tagged_game_ids.append(game["id"])
        total_tags += len(rows)

    print(
        f"[tags] 完了 — {len(tagged_game_ids)} ゲームに計 {total_tags} タグ付与"
        f"（マッチなし {no_match} 件）"
    )
    if dry_run:
        print("[tags] dry-run のため DB 書き込みはスキップしました")
    elif tagged_game_ids:
        _clear_tag_cache(tagged_game_ids, list(tagged_tag_ids))


# ── メイン ────────────────────────────────────────────────────────────────────

def run(phase: str, limit: int | None, overwrite: bool = False, dry_run: bool = False) -> None:
    if phase in ("discover", "all"):
        run_discover(limit if limit is not None else 50, overwrite=overwrite)
        print()
    if phase in ("tags", "all"):
        run_tags(limit if limit is not None else 50, dry_run=dry_run)
        print()
    if phase in ("scrape", "all"):
        run_scrape(limit if limit is not None else 3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Steam OST ページからトラックリストと作曲家クレジットを取得して DB に保存する"
    )
    parser.add_argument(
        "--phase",
        choices=["discover", "tags", "scrape", "all"],
        default="all",
        help=(
            "実行フェーズ: discover=OSTアプリID発見, tags=OST説明文からムードタグ抽出, "
            "scrape=ページ取得, all=すべて (デフォルト: all)"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="処理件数上限 (discover/tags デフォルト: 50, scrape デフォルト: 3)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="steam_ost_locked=TRUE のゲームも再試行する",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="tags フェーズで DB 書き込みを行わず抽出結果のみ表示する",
    )
    args = parser.parse_args()
    run(args.phase, args.limit, overwrite=args.overwrite, dry_run=args.dry_run)
