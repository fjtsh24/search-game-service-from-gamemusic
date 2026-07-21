"""
テスト共通フィクスチャ。

- mock_cache: Redis キャッシュを全テストでオフにする (autouse)
- make_db: Supabase クライアントの代替モックを生成するヘルパー
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def mock_cache(monkeypatch):
    """全テストでキャッシュをバイパスする。"""
    monkeypatch.setattr("app.cache.get", AsyncMock(return_value=None))
    monkeypatch.setattr("app.cache.set", AsyncMock(return_value=None))
    monkeypatch.setattr("app.cache.delete", AsyncMock(return_value=None))


@pytest.fixture
def client():
    return TestClient(app)


def make_db(tables: dict | None = None) -> MagicMock:
    """Supabase クライアントの簡易モックを返す。

    tables: {"テーブル名": [行データのリスト]} を渡すと、
            そのテーブルの SELECT 結果として使われる。
    """
    tables = tables or {}

    def _table(name: str) -> MagicMock:
        rows = tables.get(name, [])
        t = MagicMock()

        # チェーン可能なメソッドはすべて self を返す
        for method in ("select", "eq", "neq", "is_", "not_", "in_",
                       "ilike", "limit", "order", "gte", "update", "insert", "delete"):
            getattr(t, method).return_value = t

        # .single() は data が先頭要素 or None のレスポンスを返す
        single_result = MagicMock()
        single_result.data = rows[0] if rows else None
        t.single.return_value = MagicMock(execute=MagicMock(return_value=single_result))

        # 通常の .execute() は data がリストのレスポンスを返す
        list_result = MagicMock()
        list_result.data = rows
        t.execute.return_value = list_result

        return t

    db = MagicMock()
    db.table.side_effect = _table
    return db
