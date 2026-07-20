import json
from fastapi import APIRouter, HTTPException
from app.db import get_db
from app import cache

router = APIRouter()


@router.get("")
async def list_tags():
    cached = await cache.get("tags:all")
    if cached:
        return json.loads(cached)

    db = get_db()
    result = db.table("mood_tags").select("id, name, name_ja").order("name_ja").execute()
    await cache.set("tags:all", result.data, ex=3600)
    return result.data


@router.get("/{tag_id}")
async def get_tag(tag_id: str):
    cache_key = f"tags:{tag_id}"
    cached = await cache.get(cache_key)
    if cached:
        return json.loads(cached)

    db = get_db()
    result = db.table("mood_tags").select("id, name, name_ja").eq("id", tag_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Tag not found")

    await cache.set(cache_key, result.data, ex=3600)
    return result.data
