import unittest

from agent.gap_detector import detect_gaps


class GapDetectorTest(unittest.TestCase):
    def test_emotion_alone_does_not_create_sticker_gap(self):
        gaps = detect_gaps([
            {
                "scene_id": 1,
                "description": "猫看着镜头崩溃",
                "subtitle": "周一怎么又来了",
                "emotion": "崩溃",
                "cat_motion_id": "1",
                "_match_score": 5,
                "stickers": [],
            }
        ])

        self.assertFalse(
            any(gap["gap_type"] == "贴纸不足" for gap in gaps["gaps"])
        )

    def test_reused_background_asset_does_not_create_background_gap(self):
        gaps = detect_gaps([
            {
                "scene_id": 1,
                "description": "办公室工位",
                "cat_motion_id": "1",
                "_match_score": 5,
                "suggested_background": "办公室工位",
                "generated_assets": [
                    {"type": "背景复用", "file": "/tmp/office.png"}
                ],
            }
        ])

        self.assertFalse(
            any(gap["gap_type"] == "背景缺失" for gap in gaps["gaps"])
        )

    def test_reused_prop_asset_does_not_create_prop_gap(self):
        gaps = detect_gaps([
            {
                "scene_id": 1,
                "description": "猫在工位敲电脑",
                "cat_motion_id": "1",
                "_match_score": 5,
                "suggested_prop": "键盘",
                "generated_assets": [
                    {"type": "道具复用", "file": "/tmp/keyboard.png"}
                ],
            }
        ])

        self.assertFalse(
            any(gap["gap_type"] == "道具缺失" for gap in gaps["gaps"])
        )

    def test_user_assets_do_not_create_background_or_prop_gaps(self):
        gaps = detect_gaps([
            {
                "scene_id": 1,
                "description": "办公室工位喝咖啡",
                "cat_motion_id": "1",
                "_match_score": 5,
                "suggested_background": "办公室工位",
                "suggested_prop": "咖啡杯",
                "generated_assets": [
                    {"type": "用户背景", "file": "/tmp/office_background.png", "source": "user"},
                    {"type": "用户道具", "file": "/tmp/coffee.png", "source": "user"},
                ],
            }
        ])

        gap_types = {gap["gap_type"] for gap in gaps["gaps"]}
        self.assertNotIn("背景缺失", gap_types)
        self.assertNotIn("道具缺失", gap_types)


if __name__ == "__main__":
    unittest.main()
