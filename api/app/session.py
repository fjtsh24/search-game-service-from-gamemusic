"""
Upstash Redis を使ったサーバーサイドセッション管理。
セッション ID は HttpOnly Cookie に保存し、JS からは読み取れない。
"""

import json
import secrets
from fastapi import HTTPException, Request
from app import cache

SESSION_TTL = 30 * 24 * 3600  # 30 日
COOKIE_NAME = "gsession"


async def create_session(user_id: str, steam_id: str) -> str:
    session_id = secrets.token_hex(32)
    await cache.set(
        f"sess:{session_id}",
        {"user_id": user_id, "steam_id": steam_id},
        ex=SESSION_TTL,
    )
    return session_id


async def get_session(session_id: str) -> dict | None:
    raw = await cache.get(f"sess:{session_id}")
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


async def delete_session(session_id: str) -> None:
    await cache.delete(f"sess:{session_id}")


async def require_session(request: Request) -> dict:
    """認証済みセッションを要求する FastAPI Dependency。"""
    session_id = request.cookies.get(COOKIE_NAME)
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired")
    return session
