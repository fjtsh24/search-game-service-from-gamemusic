"""
類似度スコア計算のユニットテスト。

compute_similarity_score は純粋関数なので DB モック不要。
"""

import pytest

from app.services.similarity import _normalize_confidence, compute_similarity_score


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


class TestWeightedJaccard:
    """confidence を重みとした Jaccard の挙動（docs/planning/08_tagging_redesign.md §6-B）。"""

    def test_dict_with_all_confidence_one_matches_set_behavior(self):
        # 重みがすべて 1.0 なら従来の集合ベース Jaccard と一致する
        as_set = compute_similarity_score({"a", "b", "c"}, {"b", "c", "d"}, set(), set())
        as_dict = compute_similarity_score(
            {"a": 1.0, "b": 1.0, "c": 1.0},
            {"b": 1.0, "c": 1.0, "d": 1.0},
            set(), set(),
        )
        assert as_dict == pytest.approx(as_set)

    def test_low_confidence_shared_tag_scores_lower(self):
        # 同じ1タグを共有していても、確信度が低い側のペアはスコアが低くなる
        strong = compute_similarity_score({"a": 0.9}, {"a": 0.9}, set(), set())
        weak = compute_similarity_score({"a": 0.4}, {"a": 0.4}, set(), set())
        # 完全一致同士は比率が同じなので 1.0 になる
        assert strong == pytest.approx(1.0)
        assert weak == pytest.approx(1.0)

        # 片方だけ確信度が低い場合は min/max により減点される
        mixed = compute_similarity_score({"a": 0.9}, {"a": 0.4}, set(), set())
        assert mixed == pytest.approx(0.4 / 0.9)
        assert mixed < strong

    def test_low_confidence_extra_tag_dilutes_less_than_high_confidence(self):
        # 非共有タグの確信度が低いほど、分母への寄与が小さく減点が軽い
        weak_extra = compute_similarity_score(
            {"a": 0.9}, {"a": 0.9, "b": 0.4}, set(), set()
        )
        strong_extra = compute_similarity_score(
            {"a": 0.9}, {"a": 0.9, "b": 0.9}, set(), set()
        )
        assert weak_extra == pytest.approx(0.9 / 1.3)
        assert strong_extra == pytest.approx(0.5)
        assert weak_extra > strong_extra

    def test_tier1_pair_outranks_tier2_pair_with_same_tags(self):
        # 直接証拠どうしのペアが、推定タグどうしのペアより上に来る
        tier1 = compute_similarity_score(
            {"a": 0.9, "b": 0.9}, {"a": 0.9, "c": 0.9}, set(), set()
        )
        mixed = compute_similarity_score(
            {"a": 0.9, "b": 0.9}, {"a": 0.4, "c": 0.4}, set(), set()
        )
        assert mixed < tier1

    def test_empty_dicts_return_zero(self):
        assert compute_similarity_score({}, {}, set(), set()) == pytest.approx(0.0)

    def test_composer_bonus_still_applies_with_weights(self):
        score = compute_similarity_score({"a": 0.4}, {"b": 0.4}, {"c1"}, {"c1"})
        assert score == pytest.approx(0.2)


class TestNormalizeConfidence:
    """DB から読んだ confidence 値の正規化（PRレビュー指摘: 型不整合・範囲外への防御）。"""

    def test_none_defaults_to_one(self):
        assert _normalize_confidence(None) == pytest.approx(1.0)

    def test_valid_float_passes_through(self):
        assert _normalize_confidence(0.4) == pytest.approx(0.4)

    def test_string_number_is_converted(self):
        # PostgREST/ドライバの都合で数値が文字列で来るケースへの防御
        assert _normalize_confidence("0.7") == pytest.approx(0.7)

    def test_non_numeric_string_defaults_to_one(self):
        assert _normalize_confidence("not-a-number") == pytest.approx(1.0)

    def test_out_of_range_high_is_clamped(self):
        assert _normalize_confidence(1.5) == pytest.approx(1.0)

    def test_out_of_range_negative_is_clamped(self):
        assert _normalize_confidence(-0.3) == pytest.approx(0.0)

    def test_int_is_accepted(self):
        assert _normalize_confidence(1) == pytest.approx(1.0)


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
