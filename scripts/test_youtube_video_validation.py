"""
youtube_video_validation.is_valid_ost_video のユニットテスト（標準ライブラリの unittest のみ使用）。

実行方法:
  python3 scripts/test_youtube_video_validation.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from youtube_video_validation import (  # noqa: E402
    is_valid_ost_video,
    parse_iso8601_duration,
    title_matches_game,
)


class TestParseDuration(unittest.TestCase):
    def test_hours_minutes_seconds(self):
        self.assertEqual(parse_iso8601_duration("PT1H2M3S"), 3723)

    def test_minutes_only(self):
        self.assertEqual(parse_iso8601_duration("PT20M"), 1200)

    def test_seconds_only(self):
        self.assertEqual(parse_iso8601_duration("PT45S"), 45)

    def test_none_or_invalid(self):
        self.assertEqual(parse_iso8601_duration(None), 0)
        self.assertEqual(parse_iso8601_duration(""), 0)


class TestIsValidOstVideo(unittest.TestCase):
    """issue #105 の実データ（2026-08-19 本番DB調査）で検証したケースの回帰テスト。"""

    def test_legitimate_ost_video_passes(self):
        valid, _ = is_valid_ost_video(
            game_title="Path of Achra",
            video_title="Path of Achra SOUNDTRACK + some lore",
            channel_title="Ulfsire",
            category_id=None,
            topic_categories=["Video_game_culture"],
            duration_seconds=672,
        )
        self.assertTrue(valid)

    def test_walkthrough_video_rejected(self):
        valid, reason = is_valid_ost_video(
            game_title="The Mr. Rabbit Magic Show",
            video_title="The Mr. Rabbit Magic Show: Full Game Walkthrough Guide + All Achievements",
            channel_title="App Unwrapper",
            category_id=None,
            topic_categories=["Video_game_culture"],
            duration_seconds=1200,
        )
        self.assertFalse(valid)
        self.assertIn("実況", reason)

    def test_trailer_video_rejected(self):
        valid, reason = is_valid_ost_video(
            game_title="CATO: Buttered Cat",
            video_title="CATO: Buttered Cat – Launch Trailer – Nintendo Switch",
            channel_title="Nintendo of America",
            category_id=None,
            topic_categories=["Video_game_culture"],
            duration_seconds=90,
        )
        self.assertFalse(valid)
        self.assertIn("トレーラー", reason)

    def test_too_short_clip_rejected(self):
        valid, reason = is_valid_ost_video(
            game_title="Travellin Cats in Bali",
            video_title="#bali #music #song #cats #cat #backpacking",
            channel_title="Holly Paterson",
            category_id="10",
            topic_categories=["Music"],
            duration_seconds=16,
        )
        self.assertFalse(valid)
        self.assertIn("短すぎる", reason)

    def test_unrelated_long_bgm_mix_rejected_by_duration_cap(self):
        # AQUARIUM の実例: 無関係な12時間の作業用BGMミックスがゲーム名と部分一致してしまうケース。
        # タイトル一致だけでは弾けないため、上限尺（3時間）で弾く。
        valid, reason = is_valid_ost_video(
            game_title="AQUARIUM",
            video_title=(
                "12 Hours of Stunning Aquarium Relax Music, "
                "Beautiful Aquarium Coral Reef Fish, Relaxing Ocean"
            ),
            channel_title="Enlightenment Meditation Music",
            category_id="10",
            topic_categories=["Music"],
            duration_seconds=43045,
        )
        self.assertFalse(valid)
        self.assertIn("長すぎる", reason)

    def test_no_music_evidence_rejected(self):
        valid, reason = is_valid_ost_video(
            game_title="Mount & Blade: Warband",
            video_title="4K HD - Mount & Blade Music and Ambience: Swadian Hall",
            channel_title="Eye Of All",
            category_id=None,
            topic_categories=["Lifestyle_(sociology)"],
            duration_seconds=600,
        )
        self.assertFalse(valid)
        self.assertIn("根拠がない", reason)

    def test_topic_channel_counts_as_music_evidence(self):
        valid, _ = is_valid_ost_video(
            game_title="Our Life: Beginnings & Always",
            video_title="Our Life",
            channel_title="Fat Bard - Topic",
            category_id=None,
            topic_categories=["Independent_music"],
            duration_seconds=180,
        )
        self.assertTrue(valid)

    def test_ost_keyword_overrides_bad_word_guard(self):
        # トレーラー語を含んでいても OST 語があれば除外しない
        valid, _ = is_valid_ost_video(
            game_title="Some Game",
            video_title="Some Game Official Soundtrack Trailer Preview",
            channel_title="Some Channel",
            category_id="10",
            topic_categories=["Music"],
            duration_seconds=200,
        )
        self.assertTrue(valid)


class TestTitleMatchesGame(unittest.TestCase):
    def test_ascii_title_match(self):
        self.assertTrue(title_matches_game("Dead Cells", "Dead Cells Full OST"))

    def test_ascii_title_no_match(self):
        self.assertFalse(title_matches_game("Dead Cells", "Random Lofi Beats Mix"))

    def test_cjk_title_match(self):
        self.assertTrue(title_matches_game("坦率的小红帽和爱说谎的狼", "坦率的小红帽和爱说谎的狼 OST"))

    def test_short_ascii_title_without_tokens_does_not_default_true(self):
        # 旧 import_youtube_video_ids.py は非ASCII/短いタイトルを無条件 True にしていたが、
        # それが誤検出の一因だった（issue #105）。ここでは検証をスキップしないことを確認する。
        self.assertFalse(title_matches_game("Ib", "Random Unrelated Video Title"))


if __name__ == "__main__":
    unittest.main()
