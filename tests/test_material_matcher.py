import unittest
from pathlib import Path
from unittest.mock import patch

from agent import material_matcher


class MaterialMatcherTest(unittest.TestCase):
    @patch("agent.material_matcher.load_sticker_catalog")
    @patch("agent.material_matcher.find_sticker_files")
    def test_playing_phone_prefers_phone_in_hand(self, find_sticker_files, load_sticker_catalog):
        load_sticker_catalog.return_value = [{"folder": "digital-communication"}]
        find_sticker_files.return_value = [
            Path("/tmp/030-computer.png"),
            Path("/tmp/003-mouse.png"),
            Path("/tmp/020-phone-in-hand.png"),
            Path("/tmp/005-phone.png"),
        ]

        results = material_matcher.match_stickers(
            scene_description="猫在玩手机刷视频，像是在用爪子操作屏幕",
            emotion="开心",
            max_results=2,
        )

        self.assertEqual(results[0]["file_path"].name, "020-phone-in-hand.png")
        self.assertEqual(results[1]["file_path"].name, "005-phone.png")

    @patch("agent.material_matcher.load_sticker_catalog")
    @patch("agent.material_matcher.find_sticker_files")
    def test_makeup_exam_prefers_exam_objects_over_mouse(self, find_sticker_files, load_sticker_catalog):
        load_sticker_catalog.return_value = [{"folder": "campus-study"}]
        find_sticker_files.return_value = [
            Path("/tmp/003-mouse.png"),
            Path("/tmp/011-book.png"),
            Path("/tmp/018-exam-paper.png"),
            Path("/tmp/020-pen.png"),
        ]

        results = material_matcher.match_stickers(
            scene_description="猫在教室补考，一翻书发现这课没听过",
            emotion="崩溃",
            max_results=2,
        )

        self.assertEqual(results[0]["file_path"].name, "018-exam-paper.png")
        self.assertEqual(results[1]["file_path"].name, "011-book.png")


if __name__ == "__main__":
    unittest.main()
