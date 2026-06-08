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


if __name__ == "__main__":
    unittest.main()
