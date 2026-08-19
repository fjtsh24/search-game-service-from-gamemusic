"""composer_matching のユニットテスト（標準ライブラリの unittest のみ使用）。

実行方法:
  python3 scripts/test_composer_matching.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from composer_matching import build_similarity_pairs, match_key  # noqa: E402

# ID はソート順が判定に効くので、意図が読めるよう固定値を使う
A, B, C = "aaaa", "bbbb", "cccc"
COMPOSERS = [
    {"id": A, "name": "Toby Fox", "lastfm_name": None},
    {"id": B, "name": "Lena Raine", "lastfm_name": None},
    {"id": C, "name": "内山修作", "lastfm_name": "Shusaku Uchiyama"},
]


class TestMatchKey(unittest.TestCase):
    def test_lastfm_name_takes_precedence(self):
        self.assertEqual(match_key(COMPOSERS[2]), "shusaku uchiyama")

    def test_falls_back_to_name(self):
        self.assertEqual(match_key(COMPOSERS[0]), "toby fox")


class TestBuildSimilarityPairs(unittest.TestCase):
    def test_matches_are_case_insensitive_and_trimmed(self):
        cached = [{"composer_id": A, "similar_name": "  lena RAINE ", "score": 0.8}]
        rows = build_similarity_pairs(cached, COMPOSERS)
        self.assertEqual(rows, [
            {"composer_id_a": A, "composer_id_b": B, "score": 0.8, "source": "lastfm"}
        ])

    def test_lastfm_name_is_used_for_matching(self):
        cached = [{"composer_id": A, "similar_name": "Shusaku Uchiyama", "score": 0.5}]
        rows = build_similarity_pairs(cached, COMPOSERS)
        self.assertEqual([r["composer_id_b"] for r in rows], [C])

    def test_unknown_artists_are_dropped(self):
        """自前 composers に居ないアーティストはペアにならない（キャッシュには残る）。"""
        cached = [{"composer_id": A, "similar_name": "Some Unrelated Band", "score": 0.9}]
        self.assertEqual(build_similarity_pairs(cached, COMPOSERS), [])

    def test_self_reference_is_dropped(self):
        cached = [{"composer_id": A, "similar_name": "Toby Fox", "score": 1.0}]
        self.assertEqual(build_similarity_pairs(cached, COMPOSERS), [])

    def test_both_directions_collapse_to_one_row_with_the_higher_score(self):
        """PK が (a, b) なので A→B と B→A を1行にまとめる必要がある。"""
        cached = [
            {"composer_id": A, "similar_name": "Lena Raine", "score": 0.4},
            {"composer_id": B, "similar_name": "Toby Fox", "score": 0.9},
        ]
        rows = build_similarity_pairs(cached, COMPOSERS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], 0.9)
        self.assertEqual((rows[0]["composer_id_a"], rows[0]["composer_id_b"]), (A, B))

    def test_newly_added_composer_matches_previously_cached_response(self):
        """後から作曲家が増えたとき、Last.fm を叩き直さずに突合できること。

        キャッシュを挟む目的そのものなので、退行したら気付けるようにしておく。
        """
        cached = [{"composer_id": A, "similar_name": "Darren Korb", "score": 0.7}]
        self.assertEqual(build_similarity_pairs(cached, COMPOSERS), [])

        grown = COMPOSERS + [{"id": "dddd", "name": "Darren Korb", "lastfm_name": None}]
        rows = build_similarity_pairs(cached, grown)
        self.assertEqual([r["composer_id_b"] for r in rows], ["dddd"])

    def test_empty_and_missing_names_are_ignored(self):
        cached = [
            {"composer_id": A, "similar_name": "", "score": 0.5},
            {"composer_id": A, "similar_name": None, "score": 0.5},
        ]
        self.assertEqual(build_similarity_pairs(cached, COMPOSERS), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
