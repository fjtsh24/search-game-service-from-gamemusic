"""
Steam OpenID 2.0 認証。
check_authentication を必ず行い、なりすましを防ぐ。
"""

import uuid
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import settings
from app.db import get_db
from app.session import COOKIE_NAME, create_session, delete_session, require_session

router = APIRouter()

STEAM_OPENID_URL = "https://steamcommunity.com/openid/login"


@router.get("/steam")
async def steam_login():
    if not settings.steam_openid_return_url:
        raise HTTPException(status_code=503, detail="STEAM_OPENID_RETURN_URL が未設定です")
    params = {
        "openid.ns":         "http://specs.openid.net/auth/2.0",
        "openid.mode":       "checkid_setup",
        "openid.return_to":  settings.steam_openid_return_url,
        "openid.realm":      settings.steam_openid_return_url.split("/auth/")[0] + "/",
        "openid.identity":   "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }
    return RedirectResponse(f"{STEAM_OPENID_URL}?{urlencode(params)}")


@router.get("/steam/callback")
async def steam_callback(request: Request):
    params = dict(request.query_params)

    # check_authentication でなりすまし防止（省略厳禁）
    verify_params = {**params, "openid.mode": "check_authentication"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(STEAM_OPENID_URL, data=verify_params)
    if "is_valid:true" not in resp.text:
        raise HTTPException(status_code=401, detail="Steam authentication failed")

    # claimed_id から Steam ID を取り出す
    claimed_id = params.get("openid.claimed_id", "")
    if "steamcommunity.com/openid/id/" not in claimed_id:
        raise HTTPException(status_code=400, detail="Invalid Steam identity")
    steam_id = claimed_id.split("/")[-1]

    # Steam プロフィール情報を取得（API キーがある場合のみ）
    display_name: str | None = None
    avatar_url: str | None = None
    if settings.steam_api_key:
        try:
            async with httpx.AsyncClient() as client:
                profile = await client.get(
                    "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/",
                    params={"key": settings.steam_api_key, "steamids": steam_id},
                    timeout=10,
                )
            players = profile.json().get("response", {}).get("players", [])
            if players:
                display_name = players[0].get("personaname")
                avatar_url = players[0].get("avatarmedium")
        except Exception:
            pass

    # ユーザーを取得 or 作成
    db = get_db()
    rows = db.table("users").select("id").eq("steam_id", steam_id).execute().data or []
    if rows:
        user_id = rows[0]["id"]
        update: dict = {}
        if display_name:
            update["display_name"] = display_name
        if avatar_url:
            update["avatar_url"] = avatar_url
        if update:
            db.table("users").update(update).eq("id", user_id).execute()
    else:
        user_id = str(uuid.uuid4())
        db.table("users").insert({
            "id": user_id,
            "steam_id": steam_id,
            "display_name": display_name,
            "avatar_url": avatar_url,
        }).execute()

    session_id = await create_session(user_id, steam_id)

    response = RedirectResponse(url=f"{settings.frontend_url}/library", status_code=302)
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_id,
        max_age=30 * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=False,   # 本番環境では True に変更
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        await delete_session(session_id)
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME)
    return response


@router.delete("/account")
async def delete_account(request: Request, session: dict = Depends(require_session)):
    db = get_db()
    # user_games は CASCADE DELETE で自動削除される
    db.table("users").delete().eq("id", session["user_id"]).execute()

    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        await delete_session(session_id)

    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME)
    return response
