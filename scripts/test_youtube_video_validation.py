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

    def test_long_but_legitimate_full_ost_with_dlc_is_accepted(self):
        # The Witcher 3 の実例: DLC込みのフルサントラは3.6時間あるが、
        # タイトルに OST 語（"Soundtrack"）があるため長時間動画向けの上限（8時間）を適用し、
        # 3時間の上限で誤って弾かないことを確認する。
        valid, _ = is_valid_ost_video(
            game_title="The Witcher 3: Wild Hunt",
            video_title="The Witcher 3  Wild Hunt  FULL Soundtrack + DLC",
            channel_title="Some Channel",
            category_id=None,
            topic_categories=["Video_game_culture"],
            duration_seconds=int(3.6 * 3600),
        )
        self.assertTrue(valid)

    def test_long_legitimate_ost_examples_from_production_audit(self):
        # 2026-08-19 の本番DB全310件調査で見つかった、OST語ありで3時間を超える
        # 正規動画の実例（Portal 2 / Summer Pockets / Denshattack!）が全て通ることを確認する。
        cases = [
            ("Portal 2", "Portal 2 OST (Full 3 parts)", int(3.4 * 3600)),
            ("Summer Pockets", "Summer Pockets OST", int(3.1 * 3600)),
            ("Denshattack!", "Denshattack! Original Soundtrack", int(3.8 * 3600)),
        ]
        for game_title, video_title, duration in cases:
            with self.subTest(game=game_title):
                valid, reason = is_valid_ost_video(
                    game_title=game_title,
                    video_title=video_title,
                    channel_title="Some Channel",
                    category_id=None,
                    topic_categories=[],
                    duration_seconds=duration,
                )
                self.assertTrue(valid, f"{game_title} should be valid but got: {reason}")

    def test_extremely_long_video_rejected_even_with_ost_word(self):
        # OST 語があっても、24時間耐久配信のような極端な長さは弾く（8時間上限）
        valid, reason = is_valid_ost_video(
            game_title="Some Game",
            video_title="Some Game Full Soundtrack Marathon Stream",
            channel_title="Some Channel",
            category_id=None,
            topic_categories=[],
            duration_seconds=24 * 3600,
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
