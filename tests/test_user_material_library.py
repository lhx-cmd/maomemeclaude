import unittest
from pathlib import Path
from unittest.mock import patch

from agent.user_material_library import (
    build_user_material_index,
    build_user_motion_catalog,
    describe_user_materials,
)


class UserMaterialLibraryTest(unittest.TestCase):
    def test_describes_images_and_videos_with_intended_uses(self):
        context = describe_user_materials([
            "/tmp/office_background.png",
            "/tmp/coffee_cup.jpg",
            "/tmp/talking_cat.mp4",
        ])

        self.assertIn("office_background.png", context)
        self.assertIn("类型: image", context)
        self.assertIn("背景", context)
        self.assertIn("coffee_cup.jpg", context)
        self.assertIn("道具", context)
        self.assertIn("talking_cat.mp4", context)
        self.assertIn("类型: video", context)
        self.assertIn("猫动作", context)

    def test_describes_suffixless_uploaded_mp4_as_video_cat_motion(self):
        context = describe_user_materials(["/tmp/session_mat_mp4"])

        self.assertIn("session_mat_mp4", context)
        self.assertIn("类型: video", context)
        self.assertIn("猫动作", context)

    def test_empty_materials_have_stable_message(self):
        self.assertIn("无用户上传素材", describe_user_materials([]))

    @patch("agent.user_material_library.get_video_info")
    @patch("agent.user_material_library.extract_video_frames")
    @patch("agent.user_material_library.client.chat_vision_json")
    def test_builds_visual_index_for_uploaded_cat_videos(
        self,
        chat_vision_json,
        extract_frames,
        get_video_info,
    ):
        extract_frames.return_value = [Path("/tmp/frame1.jpg"), Path("/tmp/frame2.jpg")]
        get_video_info.return_value = {"duration_seconds": 2.5, "file_size_mb": 1.2}
        chat_vision_json.return_value = {
            "asset_kind": "cat_motion",
            "description": "小白猫焦虑地左右摇晃，适合迟到赶路和慌张求饶",
            "intended_uses": ["猫动作"],
            "motion_tags": {
                "actions": ["左右摇晃", "赶路"],
                "emotions": ["焦虑", "慌张"],
                "contexts": ["迟到"],
                "roles": ["我"],
                "avoid": [],
            },
            "search_keywords": ["焦虑", "迟到", "赶路"],
        }

        index = build_user_material_index(["/tmp/session_mat_a.mp4"])

        self.assertEqual(index["version"], 1)
        self.assertEqual(index["materials"][0]["file"], "/tmp/session_mat_a.mp4")
        self.assertEqual(index["materials"][0]["type"], "video")
        self.assertEqual(index["materials"][0]["analysis_mode"], "vision")
        self.assertIn("焦虑", index["materials"][0]["description"])
        self.assertEqual(index["materials"][0]["motion_tags"]["actions"], ["左右摇晃", "赶路"])
        chat_vision_json.assert_called_once()

    @patch("agent.user_material_library.get_video_info")
    @patch("agent.user_material_library.extract_video_frames")
    @patch("agent.user_material_library.client.chat_vision_json")
    def test_uploaded_cat_video_index_contains_local_cat_motion_shaped_entry(
        self,
        chat_vision_json,
        extract_frames,
        get_video_info,
    ):
        extract_frames.return_value = [Path("/tmp/frame1.jpg")]
        get_video_info.return_value = {"duration_seconds": 3.0, "file_size_mb": 1.0}
        chat_vision_json.return_value = {
            "description": "小猫趴地翻滚，动作幅度大，适合崩溃和压力爆表剧情",
            "motion_tags": {
                "actions": ["翻滚", "倒地"],
                "emotions": ["崩溃", "失控"],
                "contexts": ["压力爆表"],
                "avoid": ["安静对话"],
            },
        }

        index = build_user_material_index(["/tmp/user_roll.mp4"])

        entry = index["materials"][0]["cat_motion_entry"]
        self.assertEqual(set(entry.keys()), {"description", "motion_tags"})
        self.assertEqual(
            entry,
            {
                "description": "小猫趴地翻滚，动作幅度大，适合崩溃和压力爆表剧情",
                "motion_tags": {
                    "actions": ["翻滚", "倒地"],
                    "emotions": ["崩溃", "失控"],
                    "contexts": ["压力爆表"],
                    "avoid": ["安静对话"],
                },
            },
        )

        catalog = build_user_motion_catalog(index)
        self.assertEqual(catalog["user:0"]["description"], entry["description"])
        self.assertEqual(catalog["user:0"]["motion_tags"], entry["motion_tags"])

    def test_describes_user_materials_with_visual_index(self):
        context = describe_user_materials(
            ["/tmp/session_mat_a.mp4"],
            {
                "materials": [
                    {
                        "file": "/tmp/session_mat_a.mp4",
                        "type": "video",
                        "asset_kind": "cat_motion",
                        "description": "小白猫焦虑地左右摇晃",
                        "intended_uses": ["猫动作"],
                        "motion_tags": {"actions": ["左右摇晃"], "emotions": ["焦虑"]},
                    }
                ]
            },
        )

        self.assertIn("视觉描述: 小白猫焦虑地左右摇晃", context)
        self.assertIn("动作: 左右摇晃", context)
        self.assertIn("情绪: 焦虑", context)


if __name__ == "__main__":
    unittest.main()
