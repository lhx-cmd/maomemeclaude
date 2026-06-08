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


if __name__ == "__main__":
    unittest.main()
