"""タグ抽出バッチの試行記録（game_tag_attempts）を読み書きする共通ヘルパ。

## なぜ必要か

タグ抽出バッチは当初「game_tags に自分のソース名（added_by）の行があるか」だけで
処理済みを判定していた。しかしタグが 1 件も付かなかったゲームは行が増えないため
永久に「未処理」のままキュー先頭に残り、日次バッチが毎日同じゲームの説明文を
外部 API から取り直しては同じ結果を出す、という空回りが発生していた。
（実測: OST 説明文ソースで 117 件中 58 件が滞留し、--limit 50 の枠を食い潰していた）

そこで「タグが付いたか」とは独立に「試したか」を game_tag_attempts に残す。
result が tagged / no_match / invalid なら恒久スキップ、error（通信・API 失敗）だけ
RETRY_ERROR_AFTER_DAYS 後に再試行する。
"""

from datetime import datetime, timedelta, timezone

# 恒久スキップ扱いにする結果。error だけは一時的な失敗なので再試行対象に残す。
RESULT_TAGGED = "tagged"
RESULT_NO_MATCH = "no_match"
RESULT_INVALID = "invalid"
RESULT_ERROR = "error"

TERMINAL_RESULTS = (RESULT_TAGGED, RESULT_NO_MATCH, RESULT_INVALID)

# 通信・API 失敗を再試行するまでの待ち日数。
# 短すぎると障害中の相手を毎日叩き、長すぎると復旧後の取りこぼしが伸びる。
RETRY_ERROR_AFTER_DAYS = 7

_PAGE = 1000


def paged(query_factory) -> list[dict]:
    """PostgREST の 1 リクエスト上限（既定 1000 行）を超えても全行を取得する。"""
    rows: list[dict] = []
    offset = 0
    while True:
        page = query_factory().range(offset, offset + _PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < _PAGE:
            return rows
        offset += _PAGE


def load_skip_ids(db, source: str) -> set[str]:
    """このソースで再処理する必要がないゲーム ID の集合を返す。

    - game_tag_attempts が恒久結果（tagged/no_match/invalid）を持つ
    - game_tag_attempts が error だが再試行待ち期間内
    - game_tag_attempts 導入前に付与済みの game_tags 行がある（移行用フォールバック。
      過去に成功したゲームを試行記録がないという理由だけで叩き直さないため）
    """
    attempts = paged(
        lambda: db.table("game_tag_attempts")
        .select("game_id, result, attempted_at")
        .eq("source", source)
    )

    retry_before = datetime.now(timezone.utc) - timedelta(days=RETRY_ERROR_AFTER_DAYS)
    skip: set[str] = set()
    for row in attempts:
        if row["result"] in TERMINAL_RESULTS:
            skip.add(row["game_id"])
            continue
        attempted_at = datetime.fromisoformat(row["attempted_at"])
        if attempted_at.tzinfo is None:
            attempted_at = attempted_at.replace(tzinfo=timezone.utc)
        if attempted_at > retry_before:
            skip.add(row["game_id"])

    legacy = paged(
        lambda: db.table("game_tags").select("game_id").eq("added_by", source)
    )
    skip.update(r["game_id"] for r in legacy)
    return skip


def record(db, game_id: str, source: str, result: str, detail: str | None = None) -> None:
    """1 ゲーム分の試行結果を UPSERT する（再試行時は上書き）。"""
    db.table("game_tag_attempts").upsert(
        {
            "game_id": game_id,
            "source": source,
            "result": result,
            "detail": detail,
            "attempted_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="game_id,source",
    ).execute()
