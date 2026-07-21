import json
import random as _random

from fastapi import APIRouter, Depends, HTTPException, Query

from app import cache
from app.db import get_db
from app.services.similarity import similar_games_for
from app.session import require_session

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
    if random:
        # 全件数を取得してランダムoffsetで limit 件だけ取得
        if tag_id:
            count_result = (
                db.table("game_tags")
                .select("game_id", count="exact")
                .eq("tag_id", tag_id)
                .execute()
            )
            total = count_result.count or 0
            offset = _random.randint(0, max(0, total - limit))
            result = (
                db.table("game_tags")
                .select("game_id, games(id, title, title_ja, release_year, cover_image_url, game_tags(mood_tags(id, name, name_ja)))")
                .eq("tag_id", tag_id)
                .range(offset, offset + limit - 1)
                .execute()
            )
            data = [row["games"] for row in result.data]
        else:
            count_result = db.table("games").select("id", count="exact").execute()
            total = count_result.count or 0
            offset = _random.randint(0, max(0, total - limit))
            result = (
                db.table("games")
                .select("id, title, title_ja, release_year, cover_image_url, game_tags(mood_tags(id, name, name_ja))")
                .range(offset, offset + limit - 1)
                .execute()
            )
            data = result.data
        _random.shuffle(data)
    else:
        if tag_id:
            result = (
                db.table("game_tags")
                .select("game_id, games(id, title, title_ja, release_year, cover_image_url, game_tags(mood_tags(id, name, name_ja)))")
                .eq("tag_id", tag_id)
                .limit(limit)
                .execute()
            )
            data = [row["games"] for row in result.data]
        else:
            result = (
                db.table("games")
                .select("id, title, title_ja, release_year, cover_image_url, game_tags(mood_tags(id, name, name_ja))")
                .limit(limit)
                .execute()
            )
            data = result.data
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


@router.post("/{game_id}/flag-video")
async def flag_video(game_id: str, session: dict = Depends(require_session)):
    """再生中の YouTube 動画が違うとユーザーが報告する。
    VideoID は即座には削除せず、tracks.youtube_flagged = TRUE をセットして管理者確認待ちにする。
    """
    db = get_db()
    result = db.table("tracks").select("id").eq("game_id", game_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Track not found")

    track_ids = [r["id"] for r in result.data]
    for tid in track_ids:
        db.table("tracks").update({"youtube_flagged": True}).eq("id", tid).execute()

    await cache.delete(f"games:detail:{game_id}")
    return {"flagged": True}


@router.get("/{game_id}/similar")
async def get_similar_games(game_id: str, limit: int = Query(default=8, le=50)):
    cache_key = f"games:similar:{game_id}:{limit}"
    cached = await cache.get(cache_key)
    if cached:
        return json.loads(cached)

    data = await similar_games_for(game_id, limit=limit)
    await cache.set(cache_key, data, ex=3600)
    return data
