"""
類似度スコア計算のユニットテスト。

compute_similarity_score は純粋関数なので DB モック不要。
"""

import pytest

from app.services.similarity import compute_similarity_score


class TestComputeSimilarityScore:
    def test_identical_tags_returns_one(self):
        tags = {"epic", "orchestral", "cinematic"}
        score = compute_similarity_score(tags, tags, set(), set())
        assert score == pytest.approx(1.0)

    def test_disjoint_tags_returns_zero(self):
        score = compute_similarity_score({"epic"}, {"chiptune"}, set(), set())
        assert score == pytest.approx(0.0)

    def test_partial_overlap_jaccard(self):
        # intersection={b,c} / union={a,b,c,d} = 2/4 = 0.5
        score = compute_similarity_score({"a", "b", "c"}, {"b", "c", "d"}, set(), set())
        assert score == pytest.approx(0.5)

    def test_shared_composer_adds_bonus(self):
        # Jaccard=0, 共有作曲家1人 → +0.2
        score = compute_similarity_score({"epic"}, {"chiptune"}, {"composer-A"}, {"composer-A"})
        assert score == pytest.approx(0.2)

    def test_composer_bonus_capped_at_max(self):
        # 共有作曲家3人 → 0.2 * 3 = 0.6 だが上限は 0.4
        score = compute_similarity_score(
            set(), set(),
            {"c1", "c2", "c3"},
            {"c1", "c2", "c3"},
        )
        assert score == pytest.approx(0.4)

    def test_both_empty_returns_zero(self):
        score = compute_similarity_score(set(), set(), set(), set())
        assert score == pytest.approx(0.0)

    def test_tag_and_composer_overlap_combine(self):
        # Jaccard = 1/1 = 1.0, composer bonus = 0.2 → 1.2
        score = compute_similarity_score({"epic"}, {"epic"}, {"c1"}, {"c1"})
        assert score == pytest.approx(1.2)

    def test_no_composer_overlap_no_bonus(self):
        score = compute_similarity_score({"epic"}, {"epic"}, {"c1"}, {"c2"})
        assert score == pytest.approx(1.0)


class TestSimilarGamesFor:
    """similar_games_for 関数の統合テスト（DB モック使用）。"""

    @pytest.mark.asyncio
    async def test_no_tags_returns_empty(self):
        from unittest.mock import MagicMock, patch

        from app.services.similarity import similar_games_for

        db = MagicMock()
        # game_tags → 空（タグなし）
        empty_result = MagicMock()
        empty_result.data = []
        # track_composers → 空（作曲家なし）
        db.table.return_value.select.return_value.eq.return_value.execute.return_value = empty_result
        db.table.return_value.select.return_value.neq.return_value.execute.return_value = empty_result
        db.table.return_value.select.return_value.in_.return_value.execute.return_value = empty_result

        with patch("app.services.similarity.get_db", return_value=db):
            result = await similar_games_for("game-with-no-tags")

        assert result == []

    @pytest.mark.asyncio
    async def test_with_no_candidates_returns_empty(self):
        from unittest.mock import MagicMock, patch

        from app.services.similarity import similar_games_for

        db = MagicMock()
        empty_result = MagicMock()
        empty_result.data = []

        # game_tags への最初の呼び出し（target tags）→ タグあり
        # game_tags への2回目の呼び出し（candidates）→ 空（他ゲームなし）
        call_count = {"n": 0}
        first_result = MagicMock()
        first_result.data = [{"tag_id": "tag-1"}]

        def table_side(name):
            m = MagicMock()
            m.select.return_value = m
            m.eq.return_value = m
            m.neq.return_value = m
            m.in_.return_value = m
            m.gte.return_value = m
            if name == "game_tags":
                call_count["n"] += 1
                m.execute.return_value = first_result if call_count["n"] == 1 else empty_result
            else:
                m.execute.return_value = empty_result
            return m

        db.table.side_effect = table_side

        with patch("app.services.similarity.get_db", return_value=db):
            result = await similar_games_for("game-1")

        assert result == []


class TestSearchEndpoints:
    def test_search_games_returns_list(self, client):
        from unittest.mock import patch

        from tests.conftest import make_db

        db = make_db({"games": [{"id": "g1", "title": "Celeste"}]})
        with patch("app.routers.search.get_db", return_value=db):
            resp = client.get("/search/games?q=celeste")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_search_games_requires_q_param(self, client):
        resp = client.get("/search/games")
        assert resp.status_code == 422  # q は必須パラメータ

    def test_search_composers_returns_list(self, client):
        from unittest.mock import patch

        from tests.conftest import make_db

        db = make_db()
        with patch("app.routers.search.get_db", return_value=db):
            resp = client.get("/search/composers?q=toby")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
