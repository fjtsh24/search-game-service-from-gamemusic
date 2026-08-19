"""tag_attempts のユニットテスト（標準ライブラリの unittest のみ使用）。

Supabase に接続せず、クエリビルダの必要最小限を模したフェイクで検証する。
狙いは「タグが 1 件も付かなかったゲームを日次バッチが毎日拾い直す」退行の防止。

実行方法:
  python3 scripts/test_tag_attempts.py
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tag_attempts  # noqa: E402
from tag_attempts import (  # noqa: E402
    RESULT_ERROR,
    RESULT_INVALID,
    RESULT_NO_MATCH,
    RESULT_TAGGED,
    load_skip_ids,
    paged,
    record,
)


class _FakeQuery:
    """rows を保持し、eq でフィルタ・range でページングするだけのクエリビルダ。"""

    def __init__(self, table):
        self._table = table
        self._rows = list(table.rows)
        self._range = None

    def select(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self._rows = [r for r in self._rows if r.get(column) == value]
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def upsert(self, row, on_conflict=None):
        key = tuple(row[c] for c in on_conflict.split(","))
        self._table.rows = [
            r for r in self._table.rows if tuple(r[c] for c in on_conflict.split(",")) != key
        ]
        self._table.rows.append(row)
        return self

    def execute(self):
        rows = self._rows
        if self._range:
            start, end = self._range
            rows = rows[start:end + 1]
        return type("Result", (), {"data": rows})()


class _FakeDB:
    def __init__(self, tables):
        self.tables = {
            name: type("T", (), {"rows": rows})() for name, rows in tables.items()
        }

    def table(self, name):
        if name not in self.tables:
            self.tables[name] = type("T", (), {"rows": []})()
        return _FakeQuery(self.tables[name])


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class TestLoadSkipIds(unittest.TestCase):
    def test_terminal_results_are_skipped(self):
        """tagged / no_match / invalid はすべて恒久スキップ。

        no_match を対象に残していたことが「毎日同じゲームを外部 API に
        問い合わせ続ける」原因だった。
        """
        db = _FakeDB({
            "game_tag_attempts": [
                {"game_id": "g1", "source": "s", "result": RESULT_TAGGED, "attempted_at": _iso(30)},
                {"game_id": "g2", "source": "s", "result": RESULT_NO_MATCH, "attempted_at": _iso(30)},
                {"game_id": "g3", "source": "s", "result": RESULT_INVALID, "attempted_at": _iso(30)},
            ],
            "game_tags": [],
        })
        self.assertEqual(load_skip_ids(db, "s"), {"g1", "g2", "g3"})

    def test_error_is_retried_only_after_the_wait_period(self):
        db = _FakeDB({
            "game_tag_attempts": [
                {"game_id": "fresh", "source": "s", "result": RESULT_ERROR,
                 "attempted_at": _iso(tag_attempts.RETRY_ERROR_AFTER_DAYS - 1)},
                {"game_id": "stale", "source": "s", "result": RESULT_ERROR,
                 "attempted_at": _iso(tag_attempts.RETRY_ERROR_AFTER_DAYS + 1)},
            ],
            "game_tags": [],
        })
        skip = load_skip_ids(db, "s")
        self.assertIn("fresh", skip)
        self.assertNotIn("stale", skip)

    def test_other_sources_do_not_leak(self):
        db = _FakeDB({
            "game_tag_attempts": [
                {"game_id": "g1", "source": "other", "result": RESULT_NO_MATCH, "attempted_at": _iso(1)},
            ],
            "game_tags": [{"game_id": "g2", "added_by": "other"}],
        })
        self.assertEqual(load_skip_ids(db, "s"), set())

    def test_legacy_game_tags_count_as_done(self):
        """試行記録の導入前に付与済みのゲームを叩き直さない（移行用フォールバック）。"""
        db = _FakeDB({
            "game_tag_attempts": [],
            "game_tags": [{"game_id": "g1", "added_by": "s"}, {"game_id": "g2", "added_by": "x"}],
        })
        self.assertEqual(load_skip_ids(db, "s"), {"g1"})


class TestRecord(unittest.TestCase):
    def test_record_upserts_by_game_and_source(self):
        db = _FakeDB({"game_tag_attempts": [], "game_tags": []})
        record(db, "g1", "s", RESULT_ERROR, "http_503")
        record(db, "g1", "s", RESULT_TAGGED, "tags=2")
        record(db, "g1", "other", RESULT_NO_MATCH)

        rows = db.tables["game_tag_attempts"].rows
        self.assertEqual(len(rows), 2)
        same_source = [r for r in rows if r["source"] == "s"]
        self.assertEqual(len(same_source), 1)
        self.assertEqual(same_source[0]["result"], RESULT_TAGGED)

    def test_recorded_result_is_then_skipped(self):
        db = _FakeDB({"game_tag_attempts": [], "game_tags": []})
        record(db, "g1", "s", RESULT_NO_MATCH, "chars=120")
        self.assertEqual(load_skip_ids(db, "s"), {"g1"})


class TestPaged(unittest.TestCase):
    def test_reads_past_the_single_request_row_cap(self):
        """PostgREST の 1 リクエスト上限（既定 1000 行）を超えても全件返す。"""
        rows = [{"game_id": f"g{i}", "source": "s", "result": RESULT_NO_MATCH,
                 "attempted_at": _iso(1)} for i in range(2500)]
        db = _FakeDB({"game_tag_attempts": rows, "game_tags": []})
        self.assertEqual(len(paged(lambda: db.table("game_tag_attempts").select("*"))), 2500)
        self.assertEqual(len(load_skip_ids(db, "s")), 2500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
