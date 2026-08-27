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
    見つからなかったトラックは tracks.youtube_locked = TRUE にして以後スキップする。

  --mode tags
    games.youtube_video_id が設定済みのゲームを対象に、動画のタイトル・説明文から
    mood タグを抽出して game_tags に保存する（added_by='youtube_desc'）。
    videos.list（50件/リクエスト=1 unit）でメタ取得し、youtube_video_validation.py の
    判定（ゲーム名一致・尺90秒〜3時間・実況/トレーラー除外）を通った動画のみを対象にする。
    tags_locked / steam_ost_appid の有無は問わない（このモードは動画メタデータのみ参照）。
    処理済み判定は game_tag_attempts で行い、検証NG・マッチなしのゲームも記録する
    （タグの有無で判定すると同じゲームを毎日取り直すことになるため）。
    詳細: docs/planning/08_tagging_redesign.md §11

YouTube Data API は 1 クエリ = 100 units / 1 日の無料枠 = 10,000 units。
videos.list は 50 件/リクエスト = 1 unit と非常に安い。
週次バッチ（.github/workflows/daily-import.yml）での実行頻度・件数:
  - games モード: 週次 10 件 = 1,000 units
  - tracks モード: 週次 5 件 = 500 units
  - tags モード: 週次 25 件 ≈ 1 unit（videos.list のみ、search は使わない）
  合計 1,500 units/回 で余裕を保つ。

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

from music_text_tags import extract_tags
from tag_attempts import (
    RESULT_ERROR,
    RESULT_INVALID,
    RESULT_NO_MATCH,
    RESULT_TAGGED,
    load_skip_ids,
    paged,
    record,
)
from youtube_video_validation import is_valid_ost_video, parse_iso8601_duration

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
    """tracks.youtube_video_id が未設定かつ youtube_locked でないトラックを取得する。

    youtube_locked を見ないと、検索が当たらなかったトラックが created_at 昇順の
    キュー先頭に恒久的に居座り、毎日同じ検索を繰り返すことになる
    （1件 100 units なので日次 10 件で 1,000 units を空費していた）。
    """
    rows = (
        db.table("tracks")
        .select("id, title, games(id, title)")
        .is_("youtube_video_id", "null")
        .eq("youtube_locked", False)
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
    locked = 0

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
            # games モードと同じく、見つからなかったトラックはロックして以後スキップする
            db.table("tracks").update({"youtube_locked": True}).eq("id", track["id"]).execute()
            print(f"  NG (locked): [{game_title}] {track_title}")
            locked += 1

        time.sleep(WAIT)

    print(f"\n完了 — {done}/{len(tracks)} 件に VideoID を設定")
    print(f"消費クォータ: 約 {len(tracks) * 100} units")
    if locked:
        print(f"locked 追加: {locked} 件（再試行するには tracks.youtube_locked = FALSE に更新）")


YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

TAGS_SOURCE = "youtube_desc"
TAGS_CONFIDENCE = 0.75  # Steam OST 説明文（0.9）より低め。動画の誤登録を完全には排除できないため


def get_games_for_tag_extraction(limit: int) -> tuple[list[dict], int, int]:
    """youtube_video_id が設定済みで、まだ youtube_desc タグを試みていないゲームを取得する。

    処理済み判定は game_tag_attempts で行う。「試したがタグが付かなかった」ゲームにも
    記録が残るので、同じゲームを毎日 videos.list に投げ続けることはない。
    候補は全件取得してから除外する（先に limit*N 件で打ち切ると、未処理のまま滞留した
    ゲームが枠を占有して以降のゲームに永久に到達できなくなるため）。

    Returns: (処理対象, 候補総数, 試行済み件数)
    """
    skip_ids = load_skip_ids(db, TAGS_SOURCE)
    rows = paged(
        lambda: db.table("games")
        .select("id, title, youtube_video_id")
        .not_.is_("youtube_video_id", "null")
        .order("created_at", desc=False)
    )
    candidates = [r for r in rows if r["id"] not in skip_ids]
    return candidates[:limit], len(rows), len(skip_ids)


def _fetch_videos_meta(video_ids: list[str]) -> tuple[dict[str, dict], set[str]]:
    """videos.list で複数動画のメタデータをまとめて取得する（50件/リクエスト = 1 unit）。

    Returns: (videoId → メタデータ, リクエスト自体が失敗した videoId の集合)

    videos.list は削除済み・非公開の動画を 200 応答から黙って落とすため、
    「リクエスト成功かつ結果に無い＝動画が存在しない（恒久）」と
    「リクエスト自体が失敗（一時的）」を呼び出し側で区別できるよう分けて返す。
    """
    meta: dict[str, dict] = {}
    request_failed: set[str] = set()
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        try:
            resp = http.get(YOUTUBE_VIDEOS_URL, params={
                "part": "snippet,topicDetails,contentDetails",
                "id": ",".join(chunk),
                "key": YOUTUBE_API_KEY,
            }, timeout=15)
        except requests.RequestException as e:
            print(f"  videos.list 通信エラー: {e}")
            request_failed.update(chunk)
            continue
        if resp.status_code != 200:
            print(f"  videos.list エラー: {resp.status_code} {resp.text[:100]}")
            request_failed.update(chunk)
            continue
        for item in resp.json().get("items", []):
            meta[item["id"]] = item
    return meta, request_failed


def run_tags(limit: int) -> None:
    """games.youtube_video_id の動画タイトル・説明文から mood タグを抽出する。

    youtube_video_validation.is_valid_ost_video() で妥当そうと判定された動画のみを
    対象にする（issue #105 で実測した「実況・トレーラー・尺異常」を除外するルール）。
    誤登録の動画（例: 無関係な作業用BGMミックス）からタグを抽出すると
    ノイズになるため、検証をスキップしない。

    検証で弾かれた動画・ムード語が出なかった動画も game_tag_attempts に記録する。
    記録しないと「タグが付いていない＝未処理」と見なされ、同じゲームを毎日
    videos.list に投げ直し、以降のゲームに永久に到達できなくなる。
    """
    print(f"YouTube 動画メタからムードタグ抽出 (上限: {limit} 件)")

    games, total_candidates, skipped = get_games_for_tag_extraction(limit)
    if not games:
        print(f"対象ゲームはありません（候補 {total_candidates} 件はすべて試行済み）。")
        return

    meta, request_failed = _fetch_videos_meta([g["youtube_video_id"] for g in games])
    print(
        f"{len(games)} 件を処理します（候補 {total_candidates} 件 / 試行済み {skipped} 件、"
        f"videos.list {(len(games) + 49) // 50} 回 = 同units消費）...\n"
    )

    tag_rows = db.table("mood_tags").select("id, name").execute().data or []
    tag_id_map = {r["name"]: r["id"] for r in tag_rows}

    tagged = 0
    invalid = 0
    no_match = 0
    unavailable = 0

    for game in games:
        title = game["title"]
        video_id = game["youtube_video_id"]
        item = meta.get(video_id)
        if not item:
            if video_id in request_failed:
                # videos.list 自体が失敗した分。動画の状態は不明なので error として
                # 記録し、一定期間後に再試行する。
                print(f"  [{title}] videos.list 失敗（後日再試行）")
                record(db, game["id"], TAGS_SOURCE, RESULT_ERROR, "videos_list_failed")
            else:
                # 200 応答に含まれなかった = 削除済み・非公開。再試行しても結果は同じ。
                print(f"  [{title}] 動画が取得できず（削除・非公開）")
                record(db, game["id"], TAGS_SOURCE, RESULT_INVALID, "video_unavailable")
            unavailable += 1
            continue

        snippet = item.get("snippet", {})
        video_title = snippet.get("title", "")
        channel_title = snippet.get("channelTitle", "")
        category_id = snippet.get("categoryId")
        topics = [
            t.split("/")[-1]
            for t in item.get("topicDetails", {}).get("topicCategories", [])
        ]
        duration = parse_iso8601_duration(item.get("contentDetails", {}).get("duration"))

        valid, reason = is_valid_ost_video(
            title, video_title, channel_title, category_id, topics, duration,
        )
        if not valid:
            print(f"  [{title}] SKIP（{reason}）")
            invalid += 1
            record(db, game["id"], TAGS_SOURCE, RESULT_INVALID, reason)
            continue

        text = f"{video_title}. {snippet.get('description') or ''}"
        names = extract_tags(text, music_context=True)

        rows = []
        for name in names:
            tid = tag_id_map.get(name)
            if not tid:
                continue
            rows.append({
                "game_id": game["id"],
                "tag_id": tid,
                "confidence": TAGS_CONFIDENCE,
                "added_by": TAGS_SOURCE,
            })
        if not rows:
            print(f"  [{title}] マッチなし")
            no_match += 1
            record(db, game["id"], TAGS_SOURCE, RESULT_NO_MATCH, f"chars={len(text)}")
            continue

        db.table("game_tags").upsert(rows, on_conflict="game_id,tag_id").execute()
        record(db, game["id"], TAGS_SOURCE, RESULT_TAGGED, f"tags={len(rows)}")
        print(f"  [{title}] → タグ付与: {', '.join(names)}")
        tagged += 1

    print(
        f"\n完了 — タグ付与 {tagged} 件 / 動画不正で除外 {invalid} 件 / "
        f"マッチなし {no_match} 件 / メタ取得不可 {unavailable} 件（対象 {len(games)} 件）"
    )


def run(limit: int, mode: str) -> None:
    if mode == "tracks":
        run_tracks(limit)
    elif mode == "tags":
        run_tags(limit)
    else:
        run_games(limit)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="YouTube VideoID をゲーム OST またはトラック単位で付与する（毎日バッチ向け）"
    )
    parser.add_argument("--limit", type=int, default=100,
                        help="YouTube API 呼び出し上限 (デフォルト: 100 = 10,000 units)")
    parser.add_argument("--mode", choices=["games", "tracks", "tags"], default="games",
                        help="games: ゲーム OST 動画（デフォルト）/ tracks: トラック別動画 / tags: 動画メタからムードタグ抽出")
    args = parser.parse_args()
    run(args.limit, args.mode)
