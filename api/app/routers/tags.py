import json
from fastapi import APIRouter
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
