import unittest
from unittest.mock import patch

import server
from agent import editor


class SerializationAndEditorTest(unittest.TestCase):
    def test_serialize_scenes_preserves_sticker_layout(self):
        scenes = [
            {
                "scene_id": 1,
                "topic_caption": "大学期间和朋友的固定对话是：",
                "scene_caption": "早上起床",
                "dialogues": [{"speaker": "朋友", "line": "已经上三天早八了！"}],
                "stickers": [
                    {
                        "category": "emotion-effects",
                        "file": "/tmp/sticker.png",
                        "position": "top_right",
                        "scale": 220,
                    }
                ],
            }
        ]

        serialized = server._serialize_scenes(scenes)

        self.assertEqual(serialized[0]["stickers"][0]["position"], "top_right")
        self.assertEqual(serialized[0]["stickers"][0]["scale"], 220)
        self.assertEqual(serialized[0]["topic_caption"], "大学期间和朋友的固定对话是：")
        self.assertEqual(serialized[0]["scene_caption"], "早上起床")
        self.assertEqual(serialized[0]["dialogues"][0]["speaker"], "朋友")

    @patch("agent.editor.match_stickers")
    @patch("agent.editor.match_cat_motion")
    def test_editor_rematch_assigns_sticker_layout(self, match_motion, match_stickers):
        match_motion.return_value = None
        match_stickers.return_value = [
            {
                "category": "emotion-effects",
                "file_path": "/tmp/sticker.png",
            }
        ]
        storyboard = {
            "scenes": [
                {
                    "scene_id": 1,
                    "duration": 2,
                    "description": "old",
                    "emotion": "震惊",
                    "stickers": [],
                }
            ]
        }
        edit_plan = {
            "explanation": "change",
            "modifications": [
                {
                    "scene_id": 1,
                    "action": "modify",
                    "field": "description",
                    "new_value": "new shock",
                }
            ],
        }

        result = editor.apply_edits(storyboard, edit_plan)

        sticker = result["scenes"][0]["stickers"][0]
        self.assertEqual(sticker["position"], "top_left")
        self.assertEqual(sticker["scale"], 180)


if __name__ == "__main__":
    unittest.main()
