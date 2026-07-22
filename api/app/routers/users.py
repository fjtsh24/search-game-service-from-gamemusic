import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import cache
from app.config import settings
from app.db import get_db
from app.services.similarity import composer_boost_for_games
from app.session import require_session

router = APIRouter()


class RatingRequest(BaseModel):
    rating: int  # 1-5


@router.get("/me")
async def get_me(session: dict = Depends(require_session)):
    db = get_db()
    rows = db.table("users").select("id, steam_id, display_name, avatar_url, created_at").eq(
        "id", session["user_id"]
    ).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    return rows[0]


@router.get("/me/library")
async def get_library(session: dict = Depends(require_session)):
    db = get_db()
    rows = (
        db.table("user_games")
        .select("*, games(id, title, title_ja, release_year, cover_image_url, steam_app_id, game_tags(mood_tags(id, name, name_ja)))")
        .eq("user_id", session["user_id"])
        .order("added_at", desc=True)
        .execute()
    )
    return rows.data or []


@router.post("/me/library/import")
async def import_library(session: dict = Depends(require_session)):
    """Steam GetOwnedGames でライブラリを取得して DB に登録。"""
    if not settings.steam_api_key:
        raise HTTPException(status_code=503, detail="STEAM_API_KEY が未設定です")

    steam_id = session["steam_id"]
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/",
            params={
                "key": settings.steam_api_key,
                "steamid": steam_id,
                "include_played_free_games": "true",
                "format": "json",
            },
            timeout=30,
        )
    resp.raise_for_status()

    owned = resp.json().get("response", {}).get("games", [])
    if not owned:
        return {"imported": 0, "matched": 0}

    owned_by_appid = {g["appid"]: g for g in owned}
    db = get_db()

    # DB 内のゲームと steam_app_id で突合（500 件ずつバッチ処理）
    matched_games: list[dict] = []
    batch_size = 500
    for i in range(0, len(owned), batch_size):
        batch_ids = [g["appid"] for g in owned[i : i + batch_size]]
        result = db.table("games").select("id, steam_app_id").in_("steam_app_id", batch_ids).execute()
        matched_games.extend(result.data or [])

    if not matched_games:
        return {"imported": len(owned), "matched": 0}

    user_id = session["user_id"]
    rows_to_upsert = [
        {
            "user_id": user_id,
            "game_id": game["id"],
            "is_played": True,
            "steam_playtime_minutes": owned_by_appid.get(game["steam_app_id"], {}).get(
                "playtime_forever", 0
            ),
        }
        for game in matched_games
    ]

    db.table("user_games").upsert(rows_to_upsert, on_conflict="user_id,game_id").execute()
    return {"imported": len(owned), "matched": len(matched_games)}


@router.post("/me/games/{game_id}/rating")
async def rate_game(
    game_id: str,
    body: RatingRequest,
    session: dict = Depends(require_session),
):
    if not (1 <= body.rating <= 5):
        raise HTTPException(status_code=422, detail="Rating must be between 1 and 5")
    db = get_db()
    db.table("user_games").upsert(
        {
            "user_id": session["user_id"],
            "game_id": game_id,
            "rating": body.rating,
            "is_played": True,
        },
        on_conflict="user_id,game_id",
    ).execute()
    await cache.delete(f"feed:{session['user_id']}")
    return {"ok": True}


@router.get("/me/feed")
async def get_feed(limit: int = Query(default=20, le=100), session: dict = Depends(require_session)):
    user_id = session["user_id"]
    cache_key = f"feed:{user_id}"
    cached = await cache.get(cache_key)
    if cached:
        return json.loads(cached)

    db = get_db()

    # 明示的な評価（星3以上）
    rated = (
        db.table("user_games")
        .select("game_id, rating")
        .eq("user_id", user_id)
        .gte("rating", 3)
        .execute()
    )
    # playtime > 0 かつ未評価 → 暗黙シグナル（重み 0.4 ≒ 星2相当）
    IMPLICIT_RATING = 2
    played_unrated = (
        db.table("user_games")
        .select("game_id, steam_playtime_minutes")
        .eq("user_id", user_id)
        .is_("rating", "null")
        .gt("steam_playtime_minutes", 0)
        .execute()
    )

    if not rated.data and not played_unrated.data:
        return []

    rating_map: dict[str, int] = {r["game_id"]: r["rating"] for r in (rated.data or [])}
    for r in (played_unrated.data or []):
        if r["game_id"] not in rating_map:
            rating_map[r["game_id"]] = IMPLICIT_RATING

    rated_ids = list(rating_map.keys())

    tags_result = (
        db.table("game_tags")
        .select("game_id, tag_id")
        .in_("game_id", rated_ids)
        .execute()
    )
    tag_weights: dict[str, float] = {}
    for row in (tags_result.data or []):
        w = rating_map.get(row["game_id"], IMPLICIT_RATING) / 5.0
        tag_weights[row["tag_id"]] = tag_weights.get(row["tag_id"], 0) + w

    scores: dict[str, float] = {}
    if tag_weights:
        top_tags = sorted(tag_weights, key=lambda t: -tag_weights[t])[:10]
        candidates = (
            db.table("game_tags")
            .select("game_id, tag_id")
            .in_("tag_id", top_tags)
            .not_.in_("game_id", rated_ids)
            .execute()
        )
        for row in (candidates.data or []):
            scores[row["game_id"]] = scores.get(row["game_id"], 0) + tag_weights.get(row["tag_id"], 0)

    # 作曲家類似度ブースト（composer_similarities にデータがあれば機能する）
    composer_boost = await composer_boost_for_games(db, rated_ids, rating_map)
    for gid, boost in composer_boost.items():
        scores[gid] = scores.get(gid, 0) + boost

    top_ids = sorted(scores, key=lambda g: -scores[g])[:limit]
    if not top_ids:
        return []

    games = (
        db.table("games")
        .select("id, title, title_ja, release_year, cover_image_url, game_tags(mood_tags(id, name, name_ja))")
        .in_("id", top_ids)
        .eq("is_discoverable", True)
        .execute()
    )
    order = {gid: i for i, gid in enumerate(top_ids)}
    result = sorted(games.data, key=lambda g: order.get(g["id"], 999))

    await cache.set(cache_key, result, ex=600)
    return result
