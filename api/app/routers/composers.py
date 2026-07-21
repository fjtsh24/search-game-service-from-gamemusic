from fastapi import APIRouter, HTTPException

from app.db import get_db

router = APIRouter()


@router.get("/{composer_id}")
async def get_composer(composer_id: str):
    db = get_db()
    composer = (
        db.table("composers")
        .select("id, name, bio, image_url")
        .eq("id", composer_id)
        .single()
        .execute()
    )
    if not composer.data:
        raise HTTPException(status_code=404, detail="Composer not found")

    # 担当ゲーム一覧（tracks 経由で取得）
    tracks = (
        db.table("track_composers")
        .select("tracks(game_id, games(id, title, title_ja, release_year, cover_image_url))")
        .eq("composer_id", composer_id)
        .eq("is_primary", True)
        .execute()
    )
    seen = set()
    games = []
    for row in tracks.data:
        game = row["tracks"]["games"]
        if game["id"] not in seen:
            seen.add(game["id"])
            games.append(game)

    return {**composer.data, "games": games}
