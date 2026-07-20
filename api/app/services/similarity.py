"""
VibeTag Jaccard係数によるゲーム類似度計算。

類似度スコア = |タグA ∩ タグB| / |タグA ∪ タグB|

タグセットには composer_similarities のスコアを重みとして加算することで
音楽的なつながりも加味する（将来拡張）。
"""

from collections import defaultdict
from app.db import get_db


async def similar_games_for(game_id: str, limit: int = 8) -> list[dict]:
    db = get_db()

    # 対象ゲームのタグを取得
    tag_result = (
        db.table("game_tags")
        .select("tag_id")
        .eq("game_id", game_id)
        .execute()
    )
    if not tag_result.data:
        return []

    target_tags = {row["tag_id"] for row in tag_result.data}

    # 同じタグを持つゲームとそのタグをまとめて取得
    candidates_result = (
        db.table("game_tags")
        .select("game_id, tag_id")
        .in_("tag_id", list(target_tags))
        .neq("game_id", game_id)
        .execute()
    )

    # ゲームごとの共通タグを集計
    game_shared: dict[str, set] = defaultdict(set)
    for row in candidates_result.data:
        game_shared[row["game_id"]].add(row["tag_id"])

    if not game_shared:
        return []

    # 各候補ゲームの全タグを取得して Jaccard を計算
    candidate_ids = list(game_shared.keys())
    all_tags_result = (
        db.table("game_tags")
        .select("game_id, tag_id")
        .in_("game_id", candidate_ids)
        .execute()
    )
    game_all_tags: dict[str, set] = defaultdict(set)
    for row in all_tags_result.data:
        game_all_tags[row["game_id"]].add(row["tag_id"])

    scores: list[tuple[float, str]] = []
    for gid, shared in game_shared.items():
        union = target_tags | game_all_tags[gid]
        jaccard = len(shared) / len(union) if union else 0
        scores.append((jaccard, gid))

    scores.sort(reverse=True)
    top_ids = [gid for _, gid in scores[:limit]]

    # ゲーム詳細を取得
    games_result = (
        db.table("games")
        .select("id, title, title_ja, release_year, cover_image_url")
        .in_("id", top_ids)
        .execute()
    )
    # スコア順に並び替えて返す
    order = {gid: i for i, gid in enumerate(top_ids)}
    return sorted(games_result.data, key=lambda g: order.get(g["id"], 999))
