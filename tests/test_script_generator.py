import unittest
from unittest.mock import patch

from agent import script_generator


class ScriptGeneratorTest(unittest.TestCase):
    @patch("agent.script_generator.client.chat_json")
    @patch("agent.script_generator.build_material_context")
    def test_expand_script_detail_uses_lightweight_context(self, build_material_context, chat_json):
        build_material_context.return_value = "FULL_MATERIAL_CONTEXT_SHOULD_NOT_BE_USED"
        chat_json.return_value = {
            "title": "详细剧本",
            "version_name": "高点击版",
            "scenes": [{"scene_id": 1}],
        }

        result = script_generator.expand_script_detail(
            brief_script={
                "version": "high_click",
                "title": "简略",
                "hook": "开头",
                "narrative_arc": "铺垫→反转",
                "brief_summary": "一个周一故事",
            },
            theme="周一打工人",
            reference_structure={"video_name": "ref.mp4"},
        )

        user_message = chat_json.call_args.kwargs["user_message"]
        self.assertEqual(result["title"], "详细剧本")
        self.assertNotIn("FULL_MATERIAL_CONTEXT_SHOULD_NOT_BE_USED", user_message)
        self.assertLessEqual(chat_json.call_args.kwargs["max_tokens"], 3072)

    @patch("agent.script_generator.client.chat_json")
    @patch("agent.script_generator.build_material_context")
    def test_brief_prompt_puts_user_materials_before_local_materials(
        self,
        build_material_context,
        chat_json,
    ):
        build_material_context.return_value = "LOCAL_MATERIAL_CONTEXT"
        chat_json.return_value = {
            "version": "high_click",
            "title": "周一",
        }

        script_generator.generate_brief_scripts_streaming(
            theme="周一打工人",
            reference_structure={"video_name": "ref.mp4"},
            custom_materials=["/tmp/office_background.png"],
        )

        user_message = chat_json.call_args_list[0].kwargs["user_message"]
        self.assertIn("优先使用用户上传素材", user_message)
        self.assertIn("office_background.png", user_message)
        self.assertLess(
            user_message.index("## 用户上传素材"),
            user_message.index("## 本地素材库"),
        )
        self.assertLess(
            user_message.index("office_background.png"),
            user_message.index("LOCAL_MATERIAL_CONTEXT"),
        )

    @patch("agent.script_generator.client.chat_json")
    @patch("agent.script_generator.build_material_context")
    def test_brief_prompt_lists_uploaded_cat_motion_catalog_before_local_supplements(
        self,
        build_material_context,
        chat_json,
    ):
        build_material_context.return_value = "LOCAL_MATERIAL_CONTEXT"
        chat_json.return_value = {
            "version": "high_click",
            "title": "迟到",
        }

        script_generator.generate_brief_scripts_streaming(
            theme="迟到哄女友",
            reference_structure={"video_name": "ref.mp4"},
            custom_materials=["/tmp/anxious_road.mp4"],
            custom_material_index={
                "materials": [
                    {
                        "file": "/tmp/anxious_road.mp4",
                        "type": "video",
                        "asset_kind": "cat_motion",
                        "cat_motion_entry": {
                            "description": "用户上传焦虑赶路猫，左右张望，适合迟到堵车",
                            "motion_tags": {
                                "actions": ["赶路", "左右张望"],
                                "emotions": ["焦虑", "慌张"],
                                "contexts": ["迟到", "堵车"],
                                "avoid": ["温暖收束"],
                            },
                        },
                    }
                ]
            },
        )

        user_message = chat_json.call_args_list[0].kwargs["user_message"]
        self.assertIn("## 用户猫动作素材库（优先使用）", user_message)
        self.assertIn("**user:0**", user_message)
        self.assertIn("用户上传焦虑赶路猫", user_message)
        self.assertIn("本地补充素材库", user_message)
        self.assertLess(
            user_message.index("## 用户猫动作素材库（优先使用）"),
            user_message.index("## 本地补充素材库"),
        )


if __name__ == "__main__":
    unittest.main()
