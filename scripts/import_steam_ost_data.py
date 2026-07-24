"""
Steam Music アプリ（type=music）からトラックリストと作曲家クレジットを取得して DB に保存する。

2フェーズで実行:
  Phase discover（APIベース）:
    steam_ost_appid が未設定のゲームを対象に、Steam Search + appdetails API で
    対応する Music アプリを発見して games.steam_ost_appid に保存する。

  Phase scrape（HTMLスクレイピング）:
    steam_ost_appid があって steam_ost_scraped_at が未設定のゲームを対象に、
    Steam ストアページをスクレイピングしてトラックリストと作曲家クレジットを取得する。
    サーバー負荷への配慮として、リクエスト間隔を 600 秒（10分）に設定している。

使い方:
  python3 scripts/import_steam_ost_data.py [--phase discover|scrape|all] [--limit N]

  --phase discover : OSTアプリIDの発見のみ（デフォルト上限: 50件）
  --phase scrape   : スクレイピングのみ（デフォルト上限: 3件）
  --phase all      : 両方を順番に実行（デフォルト）
  --limit N        : 処理件数上限

依存:
  pip install requests python-dotenv supabase beautifulsoup4
"""

import argparse
import os
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

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
        m = re.search(r"/apps/(\d+)/", item.get("logo", ""))
        if not m:
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


def run_discover(limit: int) -> None:
    games = (
        db.table("games")
        .select("id, title, steam_app_id")
        .is_("steam_ost_appid", "null")
        .not_.is_("steam_app_id", "null")
        .limit(limit)
        .execute()
        .data or []
    )

    if not games:
        print("[discover] 対象ゲームなし。")
        return

    print(f"[discover] {len(games)} 件を処理します...")
    found = 0
    for i, game in enumerate(games, 1):
        title = game["title"]
        appid = game["steam_app_id"]
        print(f"[{i}/{len(games)}] {title}")
        ost_appid = _find_ost_appid(title, appid)
        if ost_appid:
            db.table("games").update({"steam_ost_appid": ost_appid}).eq("id", game["id"]).execute()
            print(f"  → steam_ost_appid={ost_appid}")
            found += 1
        else:
            print("  → 見つからず")

    print(f"[discover] 完了 — {found}/{len(games)} 件で OST アプリ発見")


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
    game_id = game["id"]

    # 既存トラックから youtube_video_id を回収（再挿入時に引き継ぐ）
    existing = (
        db.table("tracks")
        .select("id, youtube_video_id")
        .eq("game_id", game_id)
        .execute()
        .data or []
    )
    preserved_yt = next(
        (ex["youtube_video_id"] for ex in existing if ex.get("youtube_video_id")),
        None,
    )

    if not scraped_tracks:
        return

    # 既存トラックをすべて削除してからスクレイプ結果を再挿入
    # （unique constraint (game_id, track_number) の競合を確実に回避）
    if existing:
        db.table("tracks").delete().eq("game_id", game_id).execute()

    saved_track_ids: list[str] = []
    for i, t in enumerate(scraped_tracks):
        payload: dict = {
            "game_id": game_id,
            "title": t["title"],
            "track_number": t["number"],
            "duration_seconds": t["duration_seconds"],
        }
        if i == 0 and preserved_yt:
            payload["youtube_video_id"] = preserved_yt
        result = db.table("tracks").insert(payload).execute()
        if result.data:
            saved_track_ids.append(result.data[0]["id"])

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
    rows = [
        {"track_id": tid, "composer_id": cid, "is_primary": True}
        for tid in saved_track_ids
        for cid in name_to_id.values()
    ]
    if rows:
        db.table("track_composers").upsert(rows, on_conflict="track_id,composer_id").execute()


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


# ── メイン ────────────────────────────────────────────────────────────────────

def run(phase: str, limit: int | None) -> None:
    if phase in ("discover", "all"):
        run_discover(limit if limit is not None else 50)
        print()
    if phase in ("scrape", "all"):
        run_scrape(limit if limit is not None else 3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Steam OST ページからトラックリストと作曲家クレジットを取得して DB に保存する"
    )
    parser.add_argument(
        "--phase",
        choices=["discover", "scrape", "all"],
        default="all",
        help="実行フェーズ: discover=OSTアプリID発見, scrape=ページ取得, all=両方 (デフォルト: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="処理件数上限 (discover デフォルト: 50, scrape デフォルト: 3)",
    )
    args = parser.parse_args()
    run(args.phase, args.limit)
