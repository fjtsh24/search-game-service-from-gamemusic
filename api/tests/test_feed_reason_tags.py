"""
_attach_reason_tags のユニットテスト。

reason_tags 付与ロジック（ソート・上限・エッジケース）を検証する。
"""

from app.routers.users import _attach_reason_tags


def _make_game(game_id: str, tag_ids: list[str]) -> dict:
    return {
        "id": game_id,
        "title": "Test",
        "game_tags": [
            {"mood_tags": {"id": tid, "name": tid, "name_ja": None}}
            for tid in tag_ids
        ],
    }


class TestAttachReasonTags:
    def test_top2_by_weight(self):
        """weight 降順で上位2件が選ばれる。"""
        game = _make_game("g1", ["t1", "t2", "t3"])
        tag_weights = {"t1": 0.5, "t2": 2.0, "t3": 1.0}
        reason_ids = {"t1", "t2", "t3"}

        _attach_reason_tags(game, reason_ids, tag_weights)

        assert [t["id"] for t in game["reason_tags"]] == ["t2", "t3"]

    def test_tie_breaker_by_id(self):
        """同 weight のタグは id 昇順で並ぶ（表示が安定する）。"""
        game = _make_game("g1", ["tz", "ta", "tb"])
        tag_weights = {"tz": 1.0, "ta": 1.0, "tb": 1.0}
        reason_ids = {"tz", "ta", "tb"}

        _attach_reason_tags(game, reason_ids, tag_weights)

        assert [t["id"] for t in game["reason_tags"]] == ["ta", "tb"]

    def test_only_matching_ids_included(self):
        """reason_tag_ids に含まれないタグは除外される。"""
        game = _make_game("g1", ["t1", "t2", "t3"])
        tag_weights = {"t1": 1.0, "t2": 0.5, "t3": 0.1}
        reason_ids = {"t2"}

        _attach_reason_tags(game, reason_ids, tag_weights)

        assert [t["id"] for t in game["reason_tags"]] == ["t2"]

    def test_empty_reason_ids(self):
        """reason_tag_ids が空なら reason_tags も空。"""
        game = _make_game("g1", ["t1", "t2"])
        _attach_reason_tags(game, set(), {"t1": 1.0})

        assert game["reason_tags"] == []

    def test_no_game_tags(self):
        """game_tags が存在しなくても例外を投げない。"""
        game = {"id": "g1", "title": "Test"}
        _attach_reason_tags(game, {"t1"}, {"t1": 1.0})

        assert game["reason_tags"] == []

    def test_game_tags_empty_list(self):
        """game_tags が空リストでも例外を投げない。"""
        game = {"id": "g1", "title": "Test", "game_tags": []}
        _attach_reason_tags(game, {"t1"}, {"t1": 1.0})

        assert game["reason_tags"] == []

    def test_exactly_two_returned_when_more_match(self):
        """マッチが3件以上あっても最大2件に絞られる。"""
        game = _make_game("g1", ["t1", "t2", "t3", "t4"])
        tag_weights = {"t1": 4.0, "t2": 3.0, "t3": 2.0, "t4": 1.0}
        reason_ids = {"t1", "t2", "t3", "t4"}

        _attach_reason_tags(game, reason_ids, tag_weights)

        assert len(game["reason_tags"]) == 2
        assert game["reason_tags"][0]["id"] == "t1"
        assert game["reason_tags"][1]["id"] == "t2"
