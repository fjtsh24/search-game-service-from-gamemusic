import json

from fastapi import APIRouter, Query

from app import cache
from app.db import get_db

router = APIRouter()


@router.get("/composers")
async def search_composers(q: str = Query(min_length=1)):
    cache_key = f"search:composers:{q.lower()}"
    cached = await cache.get(cache_key)
    if cached:
        return json.loads(cached)

    db = get_db()
    result = (
        db.table("composers")
        .select("id, name, image_url")
        .ilike("name", f"%{q}%")
        .limit(20)
        .execute()
    )
    await cache.set(cache_key, result.data, ex=300)
    return result.data


@router.get("/games")
async def search_games(q: str = Query(min_length=1)):
    cache_key = f"search:games:{q.lower()}"
    cached = await cache.get(cache_key)
    if cached:
        return json.loads(cached)

    db = get_db()
    result = (
        db.table("games")
        .select("id, title, title_ja, release_year, cover_image_url, game_tags(mood_tags(id, name, name_ja))")
        .ilike("title", f"%{q}%")
        .limit(20)
        .execute()
    )
    await cache.set(cache_key, result.data, ex=300)
    return result.data
