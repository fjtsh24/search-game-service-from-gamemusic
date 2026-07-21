"""
/tags・/composers エンドポイントのテスト。
"""

import json
from unittest.mock import patch

from tests.conftest import make_db

TAG_ROW = {"id": "tag-1", "name": "epic", "name_ja": "壮大"}
COMPOSER_ROW = {
    "id": "comp-1",
    "name": "Toby Fox",
    "bio": None,
    "image_url": None,
    "games": [],
}


class TestTags:
    def test_list_tags_returns_list(self, client):
        db = make_db({"mood_tags": [TAG_ROW]})
        with patch("app.routers.tags.get_db", return_value=db):
            resp = client.get("/tags")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_tags_empty(self, client):
        db = make_db()
        with patch("app.routers.tags.get_db", return_value=db):
            resp = client.get("/tags")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_tag_found(self, client):
        db = make_db({"mood_tags": [TAG_ROW]})
        with patch("app.routers.tags.get_db", return_value=db):
            resp = client.get("/tags/tag-1")
        assert resp.status_code == 200

    def test_get_tag_not_found(self, client):
        db = make_db()
        with patch("app.routers.tags.get_db", return_value=db):
            resp = client.get("/tags/nonexistent")
        assert resp.status_code == 404

    def test_get_tag_returns_correct_fields(self, client):
        db = make_db({"mood_tags": [TAG_ROW]})
        with patch("app.routers.tags.get_db", return_value=db):
            resp = client.get("/tags/tag-1")
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data
        assert "name_ja" in data


class TestComposers:
    def test_get_composer_found(self, client):
        from unittest.mock import MagicMock

        # composers テーブルは single() で返し、track_composers はリスト
        db = MagicMock()
        composer_result = MagicMock()
        composer_result.data = COMPOSER_ROW
        db.table("composers").select.return_value.eq.return_value.single.return_value.execute.return_value = composer_result

        tracks_result = MagicMock()
        tracks_result.data = []  # 担当ゲームなし
        db.table("track_composers").select.return_value.eq.return_value.eq.return_value.execute.return_value = tracks_result

        with patch("app.routers.composers.get_db", return_value=db):
            resp = client.get("/composers/comp-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Toby Fox"
        assert data["games"] == []

    def test_get_composer_not_found(self, client):
        from unittest.mock import MagicMock

        db = MagicMock()
        result = MagicMock()
        result.data = None
        db.table("composers").select.return_value.eq.return_value.single.return_value.execute.return_value = result

        with patch("app.routers.composers.get_db", return_value=db):
            resp = client.get("/composers/nonexistent")
        assert resp.status_code == 404


class TestAuthenticatedUser:
    """セッション Cookie を持つユーザーへのレスポンスをテスト。"""

    SESSION_ID = "test-session-abc123"
    USER_ID = "user-uuid-1"
    SESSION_DATA = {"user_id": USER_ID, "steam_id": "76561198000000001"}
    USER_ROW = {
        "id": USER_ID,
        "steam_id": "76561198000000001",
        "display_name": "TestUser",
        "avatar_url": None,
        "created_at": "2026-01-01T00:00:00Z",
    }

    def _auth_client(self, client, monkeypatch):
        """セッション付きクライアントを返すヘルパー。"""
        session_json = json.dumps(self.SESSION_DATA)

        async def smart_get(key):
            if key == f"sess:{self.SESSION_ID}":
                return session_json
            return None

        monkeypatch.setattr("app.cache.get", smart_get)
        client.cookies.set("gsession", self.SESSION_ID)
        return client

    def test_get_me_authenticated(self, client, monkeypatch):
        authed = self._auth_client(client, monkeypatch)
        db = make_db({"users": [self.USER_ROW]})
        with patch("app.routers.users.get_db", return_value=db):
            resp = authed.get("/users/me")
        assert resp.status_code == 200
        assert resp.json()["steam_id"] == "76561198000000001"

    def test_get_me_user_not_in_db_returns_404(self, client, monkeypatch):
        authed = self._auth_client(client, monkeypatch)
        db = make_db()  # users テーブルが空
        with patch("app.routers.users.get_db", return_value=db):
            resp = authed.get("/users/me")
        assert resp.status_code == 404

    def test_get_library_authenticated(self, client, monkeypatch):
        authed = self._auth_client(client, monkeypatch)
        db = make_db({"user_games": []})
        with patch("app.routers.users.get_db", return_value=db):
            resp = authed.get("/users/me/library")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_rate_game_invalid_rating(self, client, monkeypatch):
        authed = self._auth_client(client, monkeypatch)
        resp = authed.post("/users/me/games/g1/rating", json={"rating": 99})
        # バリデーションエラー（rating は 1-5 の範囲外）は 422 または 400
        assert resp.status_code in (400, 422)
