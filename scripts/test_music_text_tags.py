"""
music_text_tags.extract_tags のユニットテスト（標準ライブラリの unittest のみ使用）。

scripts/ 配下には pytest 等の依存を追加しておらず、CI にも scripts 用のテスト
ジョブが無いため、追加の依存やインフラ無しで実行できる形にしている。

実行方法:
  python3 scripts/test_music_text_tags.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from music_text_tags import extract_tags  # noqa: E402


class TestMusicContextTrue(unittest.TestCase):
    """music_context=True（OST 説明文向け）の挙動。

    docs/planning/08_tagging_redesign.md §4-A の調査で実際に Steam OST の
    appdetails から取得したテキストをそのまま使う（回帰防止）。
    """

    def test_chicory_ost_description(self):
        text = (
            "an eclectic range of music from intimate piano, "
            "to chamber grooves and electronic bombast"
        )
        tags = extract_tags(text, music_context=True)
        self.assertIn("acoustic", tags)
        self.assertIn("electronic", tags)
        self.assertIn("epic", tags)

    def test_our_life_ost_description(self):
        text = (
            "The relaxing tunes from Our Life: Beginnings & Always. "
            "This OST includes the instrumental background songs from the game."
        )
        tags = extract_tags(text, music_context=True)
        self.assertIn("relaxing", tags)
        self.assertIn("instrumental", tags)

    def test_dead_cells_ost_description(self):
        text = (
            "Music For Your Headless Self. There are songs with guitar, "
            "and songs without. This full length soundtrack will enhance "
            "your ears with subtle epic music."
        )
        tags = extract_tags(text, music_context=True)
        self.assertIn("epic", tags)

    def test_no_text_returns_empty(self):
        self.assertEqual(extract_tags("", music_context=True), [])
        self.assertEqual(extract_tags(None, music_context=True), [])


class TestMusicContextFalsePositiveGuards(unittest.TestCase):
    """music_context=True を音楽と無関係な紹介文に適用しても誤爆しないことを確認する。

    OST 説明文が空/取得失敗の場合でも呼び出し側が誤って通常の description を
    渡すことがあり得るため、無関係語で汎用パターンが過剰マッチしないことは
    継続的に守るべき性質。
    """

    def test_spiderman_gameplay_blurb_no_false_positive(self):
        text = (
            "the worlds of Peter Parker and Spider-Man collide in an "
            "original action-packed story. Web-swing through vibrant "
            "neighborhoods and defeat villains with epic takedowns."
        )
        tags = extract_tags(text, music_context=True)
        # "Web-swing" は \bswing\b とは無関係の語であり jazz に誤爆してはいけない
        self.assertNotIn("jazz", tags)

    def test_dead_cells_gameplay_blurb_no_false_positive(self):
        text = (
            "Dead Cells is a roguelite, metroidvania inspired, "
            "action-platformer. Kill, die, learn, repeat."
        )
        self.assertEqual(extract_tags(text, music_context=True), [])


class TestMusicContextFalse(unittest.TestCase):
    """music_context=False（旧 import_description_tags.py の挙動）を維持する回帰テスト。"""

    def test_explicit_phrase_matches_without_anchor(self):
        text = "The game features an orchestral score composed by a live orchestra."
        tags = extract_tags(text, music_context=False)
        self.assertIn("orchestral", tags)

    def test_bare_style_word_without_anchor_does_not_match(self):
        # music_context=False では contextual パターンにアンカー語の近接が必須
        text = "The melancholic knight walked home alone."
        tags = extract_tags(text, music_context=False)
        self.assertNotIn("melancholic", tags)

    def test_bare_style_word_with_anchor_matches(self):
        # "soundtrack" がアンカー語として近傍にあるため contextual パターンが有効になる
        text = "The soundtrack has some melancholic moments in the final act."
        tags = extract_tags(text, music_context=False)
        self.assertIn("melancholic", tags)


if __name__ == "__main__":
    unittest.main()
