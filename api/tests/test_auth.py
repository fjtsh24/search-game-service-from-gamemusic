"""
認証・セッション管理のテスト。

- 認証必須エンドポイントへの未認証アクセスが 401 を返すことを確認
- セッション作成・取得・削除の動作を確認
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

# ── 認証ゲートのテスト ────────────────────────────────────────────────────────

class TestRequireSession:
    """Cookie なしでの認証必須エンドポイントは 401 を返す。"""

    def test_get_me_unauthenticated(self, client):
        resp = client.get("/users/me")
        assert resp.status_code == 401

    def test_get_library_unauthenticated(self, client):
        resp = client.get("/users/me/library")
        assert resp.status_code == 401

    def test_get_feed_unauthenticated(self, client):
        resp = client.get("/users/me/feed")
        assert resp.status_code == 401

    def test_post_import_library_unauthenticated(self, client):
        resp = client.post("/users/me/library/import")
        assert resp.status_code == 401

    def test_delete_account_unauthenticated(self, client):
        resp = client.delete("/auth/account")
        assert resp.status_code == 401

    def test_rate_game_unauthenticated(self, client):
        resp = client.post("/users/me/games/some-id/rating", json={"rating": 5})
        assert resp.status_code == 401


class TestLogout:
    def test_logout_without_session_returns_ok(self, client):
        resp = client.post("/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_logout_clears_cookie(self, client):
        resp = client.post("/auth/logout")
        assert resp.status_code == 200
        # Cookie 削除指示が Set-Cookie に含まれる (max-age=0 or expires past)
        set_cookie = resp.headers.get("set-cookie", "")
        assert "gsession" in set_cookie


class TestSteamLoginRedirect:
    def test_steam_login_redirects_when_return_url_set(self, client):
        with patch("app.routers.auth.settings") as mock_settings:
            mock_settings.steam_openid_return_url = "http://localhost:8000/auth/steam/callback"
            resp = client.get("/auth/steam", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "steamcommunity.com" in resp.headers.get("location", "")

    def test_steam_login_503_when_return_url_not_set(self, client):
        with patch("app.routers.auth.settings") as mock_settings:
            mock_settings.steam_openid_return_url = None
            resp = client.get("/auth/steam")
        assert resp.status_code == 503


# ── セッション管理のユニットテスト ───────────────────────────────────────────

class TestSessionUnit:
    @pytest.mark.asyncio
    async def test_create_and_get_session(self):
        import app.cache as cache_module
        from app.session import create_session, get_session

        stored: dict = {}

        async def fake_set(key, value, ex=300):
            stored[key] = json.dumps(value) if isinstance(value, dict) else value

        async def fake_get(key):
            return stored.get(key)

        with (
            patch.object(cache_module, "set", side_effect=fake_set),
            patch.object(cache_module, "get", side_effect=fake_get),
        ):
            session_id = await create_session("user-1", "steam-123")
            assert len(session_id) == 64  # secrets.token_hex(32)

            session = await get_session(session_id)
            assert session is not None
            assert session["user_id"] == "user-1"
            assert session["steam_id"] == "steam-123"

    @pytest.mark.asyncio
    async def test_get_nonexistent_session_returns_none(self):
        import app.cache as cache_module
        from app.session import get_session

        with patch.object(cache_module, "get", new_callable=AsyncMock, return_value=None):
            result = await get_session("no-such-session")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_session(self):
        import app.cache as cache_module
        from app.session import delete_session

        deleted_keys = []

        async def fake_delete(key):
            deleted_keys.append(key)

        with patch.object(cache_module, "delete", side_effect=fake_delete):
            await delete_session("some-session-id")

        assert deleted_keys == ["sess:some-session-id"]
