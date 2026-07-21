"""
VibeTag Jaccard係数によるゲーム類似度計算。

類似度スコア = |タグA ∩ タグB| / |タグA ∪ タグB|
同一作曲家ボーナス: 共有作曲家ごとに +0.2（上限 0.4）を Jaccard スコアに加算。

作曲家間類似度（composer_similarities）は get_feed のレコメンドブーストに使用する。
"""

from collections import defaultdict

from app.db import get_db

_COMPOSER_BONUS = 0.2
_MAX_COMPOSER_BONUS = 0.4


def compute_similarity_score(
    target_tags: set,
    candidate_tags: set,
    target_composers: set,
    candidate_composers: set,
) -> float:
    """Jaccard係数 + 同一作曲家ボーナスで類似度スコアを計算する（純粋関数）。"""
    union = target_tags | candidate_tags
    jaccard = len(target_tags & candidate_tags) / len(union) if union else 0.0
    shared_composers = target_composers & candidate_composers
    bonus = min(len(shared_composers) * _COMPOSER_BONUS, _MAX_COMPOSER_BONUS)
    return jaccard + bonus


def _get_composers_for_games(db, game_ids: list[str]) -> dict[str, set[str]]:
    """複数ゲームの作曲家IDセットをまとめて取得する。"""
    if not game_ids:
        return {}
    track_rows = (
        db.table("tracks").select("id, game_id").in_("game_id", game_ids).execute().data or []
    )
    if not track_rows:
        return {}
    track_to_game = {t["id"]: t["game_id"] for t in track_rows}
    tc_rows = (
        db.table("track_composers")
        .select("track_id, composer_id")
        .in_("track_id", list(track_to_game.keys()))
        .execute()
        .data or []
    )
    result: dict[str, set[str]] = {gid: set() for gid in game_ids}
    for tc in tc_rows:
        gid = track_to_game.get(tc["track_id"])
        if gid:
            result.setdefault(gid, set()).add(tc["composer_id"])
    return result


async def similar_games_for(game_id: str, limit: int = 8) -> list[dict]:
    db = get_db()

    # 対象ゲームのタグを取得
    tag_result = (
        db.table("game_tags")
        .select("tag_id")
        .eq("game_id", game_id)
        .execute()
    )
    target_tags = {row["tag_id"] for row in (tag_result.data or [])}

    # 同じタグを持つゲームをまとめて取得
    candidates_result = (
        db.table("game_tags")
        .select("game_id, tag_id")
        .in_("tag_id", list(target_tags))
        .neq("game_id", game_id)
        .execute()
    ) if target_tags else None

    game_shared: dict[str, set] = defaultdict(set)
    if candidates_result:
        for row in candidates_result.data:
            game_shared[row["game_id"]].add(row["tag_id"])

    # 同一作曲家ボーナス: タグがなくても同じ作曲家なら候補に入れる
    all_game_ids_to_check = list(game_shared.keys())
    composers_map = _get_composers_for_games(db, [game_id] + all_game_ids_to_check)
    target_composers = composers_map.get(game_id, set())

    # タグのない候補でも同一作曲家なら追加
    if target_composers:
        # 同一作曲家のゲームを取得（まだ候補にないもの）
        all_tc_rows = (
            db.table("track_composers")
            .select("track_id, composer_id")
            .in_("composer_id", list(target_composers))
            .execute()
            .data or []
        )
        if all_tc_rows:
            tc_track_ids = [r["track_id"] for r in all_tc_rows]
            tc_track_rows = (
                db.table("tracks")
                .select("id, game_id")
                .in_("id", tc_track_ids)
                .execute()
                .data or []
            )
            tc_track_to_game = {t["id"]: t["game_id"] for t in tc_track_rows}
            for tc in all_tc_rows:
                gid = tc_track_to_game.get(tc["track_id"])
                if gid and gid != game_id:
                    composers_map.setdefault(gid, set()).add(tc["composer_id"])
                    if gid not in game_shared:
                        game_shared[gid]  # ensure entry exists (defaultdict)

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
    for row in (all_tags_result.data or []):
        game_all_tags[row["game_id"]].add(row["tag_id"])

    scores: list[tuple[float, str]] = []
    for gid in game_shared:
        score = compute_similarity_score(
            target_tags=target_tags,
            candidate_tags=game_all_tags[gid],
            target_composers=target_composers,
            candidate_composers=composers_map.get(gid, set()),
        )
        scores.append((score, gid))

    scores.sort(reverse=True)
    top_ids = [gid for _, gid in scores[:limit]]

    if not top_ids:
        return []

    # ゲーム詳細を取得してスコア順に返す（タグも含めてカードに表示できるように）
    games_result = (
        db.table("games")
        .select("id, title, title_ja, release_year, cover_image_url, game_tags(mood_tags(id, name, name_ja))")
        .in_("id", top_ids)
        .execute()
    )
    order = {gid: i for i, gid in enumerate(top_ids)}
    return sorted(games_result.data, key=lambda g: order.get(g["id"], 999))


async def composer_boost_for_games(
    db,
    rated_ids: list[str],
    rating_map: dict[str, int],
    exclude_ids: list[str] | None = None,
) -> dict[str, float]:
    """評価済みゲームの作曲家類似度から候補ゲームのブーススコアを計算する。

    composer_similarities データが存在する場合にのみ効果を発揮する。
    データがない場合は空辞書を返し、フィードアルゴリズムに影響しない。

    Returns: {game_id: boost_score}
    """
    if not rated_ids:
        return {}

    # 評価済みゲームの作曲家を取得
    composers_map = _get_composers_for_games(db, rated_ids)
    composer_weights: dict[str, float] = {}
    for gid, composer_ids in composers_map.items():
        w = rating_map.get(gid, 2) / 5.0
        for cid in composer_ids:
            composer_weights[cid] = max(composer_weights.get(cid, 0), w)

    if not composer_weights:
        return {}

    liked_ids = list(composer_weights.keys())

    # composer_similarities から類似作曲家を取得（両方向）
    sims_a = (
        db.table("composer_similarities")
        .select("composer_id_a, composer_id_b, score")
        .in_("composer_id_a", liked_ids)
        .gte("score", 0.3)
        .execute()
        .data or []
    )
    sims_b = (
        db.table("composer_similarities")
        .select("composer_id_a, composer_id_b, score")
        .in_("composer_id_b", liked_ids)
        .gte("score", 0.3)
        .execute()
        .data or []
    )

    if not sims_a and not sims_b:
        return {}

    # 類似作曲家 → 重み付き類似スコア（評価済み作曲家とは別の作曲家のみ）
    similar_composers: dict[str, float] = {}
    for row in sims_a:
        b = row["composer_id_b"]
        if b not in composer_weights:
            wsim = row["score"] * composer_weights[row["composer_id_a"]]
            similar_composers[b] = max(similar_composers.get(b, 0), wsim)
    for row in sims_b:
        a = row["composer_id_a"]
        if a not in composer_weights:
            wsim = row["score"] * composer_weights[row["composer_id_b"]]
            similar_composers[a] = max(similar_composers.get(a, 0), wsim)

    if not similar_composers:
        return {}

    # 類似作曲家が担当するゲームを検索
    sim_tc_rows = (
        db.table("track_composers")
        .select("track_id, composer_id")
        .in_("composer_id", list(similar_composers.keys()))
        .execute()
        .data or []
    )
    if not sim_tc_rows:
        return {}

    sim_track_ids = list({r["track_id"] for r in sim_tc_rows})
    sim_track_rows = (
        db.table("tracks")
        .select("id, game_id")
        .in_("id", sim_track_ids)
        .execute()
        .data or []
    )
    sim_track_to_game = {t["id"]: t["game_id"] for t in sim_track_rows}

    exclude = set(exclude_ids or []) | set(rated_ids)
    BOOST_FACTOR = 0.5
    boosts: dict[str, float] = {}
    for tc in sim_tc_rows:
        game_id = sim_track_to_game.get(tc["track_id"])
        if game_id and game_id not in exclude:
            wsim = similar_composers.get(tc["composer_id"], 0)
            boosts[game_id] = boosts.get(game_id, 0) + wsim * BOOST_FACTOR

    return boosts
