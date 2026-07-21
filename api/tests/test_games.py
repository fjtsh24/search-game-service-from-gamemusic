"""
/games エンドポイントのテスト。

DB と類似度サービスをモックし、エンドポイントの振る舞いを検証する。
"""

from unittest.mock import AsyncMock, patch

from tests.conftest import make_db

GAME_ROW = {
    "id": "game-1",
    "title": "Test Game",
    "title_ja": None,
    "description": "A test game.",
    "description_ja": None,
    "description_zh": None,
    "release_year": 2023,
    "cover_image_url": "https://example.com/cover.jpg",
    "steam_app_id": 12345,
    "game_tags": [],
    "tracks": [],
}


class TestListGames:
    def test_returns_empty_list_when_no_games(self, client):
        db = make_db()
        with patch("app.routers.games.get_db", return_value=db):
            resp = client.get("/games")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_games_list(self, client):
        db = make_db({"games": [GAME_ROW]})
        with patch("app.routers.games.get_db", return_value=db):
            resp = client.get("/games")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["id"] == "game-1"

    def test_limit_parameter_accepted(self, client):
        db = make_db()
        with patch("app.routers.games.get_db", return_value=db):
            resp = client.get("/games?limit=5")
        assert resp.status_code == 200

    def test_tag_id_filter_accepted(self, client):
        db = make_db({"game_tags": [{"games": GAME_ROW}]})
        with patch("app.routers.games.get_db", return_value=db):
            resp = client.get("/games?tag_id=some-tag")
        assert resp.status_code == 200


class TestGetGame:
    def test_returns_404_when_not_found(self, client):
        db = make_db()  # テーブルが空 → single() は data=None
        with patch("app.routers.games.get_db", return_value=db):
            resp = client.get("/games/nonexistent-id")
        assert resp.status_code == 404

    def test_returns_game_when_found(self, client):
        db = make_db({"games": [GAME_ROW]})
        with patch("app.routers.games.get_db", return_value=db):
            resp = client.get("/games/game-1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "game-1"
        assert resp.json()["title"] == "Test Game"

    def test_game_includes_multilang_descriptions(self, client):
        row = {**GAME_ROW, "description_ja": "テストゲーム", "description_zh": "测试游戏"}
        db = make_db({"games": [row]})
        with patch("app.routers.games.get_db", return_value=db):
            resp = client.get("/games/game-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["description_ja"] == "テストゲーム"
        assert data["description_zh"] == "测试游戏"


class TestSimilarGames:
    def test_returns_empty_when_no_tags(self, client):
        with patch(
            "app.routers.games.similar_games_for",
            new_callable=lambda: lambda *a, **kw: AsyncMock(return_value=[])(),
        ):
            # similar_games_for を直接モック
            pass

        async def mock_similar(game_id, limit=8):
            return []

        with patch("app.routers.games.similar_games_for", side_effect=mock_similar):
            resp = client.get("/games/game-1/similar")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_similar_games(self, client):
        async def mock_similar(game_id, limit=8):
            return [GAME_ROW]

        with patch("app.routers.games.similar_games_for", side_effect=mock_similar):
            resp = client.get("/games/game-1/similar")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
