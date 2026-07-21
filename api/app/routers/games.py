import json

from fastapi import APIRouter, HTTPException, Query

from app import cache
from app.db import get_db
from app.services.similarity import similar_games_for

router = APIRouter()


@router.get("")
async def list_games(
    tag_id: str | None = Query(default=None),
    limit: int = Query(default=20, le=100),
    random: bool = Query(default=False),
):
    # random=True のときはキャッシュをスキップ
    cache_key = f"games:list:{tag_id or 'all'}:{limit}"
    if not random:
        cached = await cache.get(cache_key)
        if cached:
            return json.loads(cached)

    db = get_db()
    if tag_id:
        q = (
            db.table("game_tags")
            .select("game_id, games(id, title, title_ja, release_year, cover_image_url, game_tags(mood_tags(id, name, name_ja)))")
            .eq("tag_id", tag_id)
            .limit(limit)
        )
        if random:
            q = q.order("random()")
        result = q.execute()
        data = [row["games"] for row in result.data]
    else:
        q = (
            db.table("games")
            .select("id, title, title_ja, release_year, cover_image_url, game_tags(mood_tags(id, name, name_ja))")
            .limit(limit)
        )
        if random:
            q = q.order("random()")
        result = q.execute()
        data = result.data

    if not random:
        await cache.set(cache_key, data, ex=600)
    return data


@router.get("/{game_id}")
async def get_game(game_id: str):
    cache_key = f"games:detail:{game_id}"
    cached = await cache.get(cache_key)
    if cached:
        return json.loads(cached)

    db = get_db()
    result = (
        db.table("games")
        .select(
            "id, title, title_ja, description, description_ja, description_zh, release_year, cover_image_url, steam_app_id,"
            "game_tags(tag_id, mood_tags(id, name, name_ja)),"
            "tracks(id, title, track_number, youtube_video_id,"
            "  track_composers(is_primary, composers(id, name)))"
        )
        .eq("id", game_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Game not found")

    await cache.set(cache_key, result.data, ex=3600)
    return result.data


@router.get("/{game_id}/similar")
async def get_similar_games(game_id: str, limit: int = Query(default=8, le=50)):
    cache_key = f"games:similar:{game_id}:{limit}"
    cached = await cache.get(cache_key)
    if cached:
        return json.loads(cached)

    data = await similar_games_for(game_id, limit=limit)
    await cache.set(cache_key, data, ex=3600)
    return data
