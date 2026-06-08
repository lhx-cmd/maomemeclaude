import unittest
from unittest.mock import patch

from agent import dialogue_enricher


class DialogueEnricherTest(unittest.TestCase):
    @patch("agent.dialogue_enricher.client.chat_json")
    def test_model_can_upgrade_scene_to_multi_cat_interaction(self, chat_json):
        chat_json.return_value = {
            "scenes": [
                {
                    "scene_id": 2,
                    "scene_caption": "领导突然@我",
                    "dialogues": [
                        {"speaker": "我", "line": "不会又有活吧？"},
                        {"speaker": "领导", "line": "小X来我办公室一下"},
                    ],
                    "reason": "这一镜有明确他人介入，适合双猫对话",
                }
            ]
        }
        scenes = [
            {
                "scene_id": 1,
                "description": "猫独自发呆",
                "subtitle": "脑子已经飞走了",
                "topic_caption": "周一的我本人",
                "scene_caption": "开会走神",
                "dialogues": [{"speaker": "我", "line": "脑子已经飞走了"}],
            },
            {
                "scene_id": 2,
                "description": "领导突然在群里@我",
                "subtitle": "预感大事不妙",
                "topic_caption": "周一的我本人",
                "scene_caption": "领导突然@我",
                "dialogues": [{"speaker": "我", "line": "预感大事不妙"}],
            },
        ]

        enriched = dialogue_enricher.enrich_hyperframe_dialogues(
            scenes=scenes,
            theme="打工人周一",
            script_title="周一的我本人",
        )

        self.assertEqual(len(enriched[0]["dialogues"]), 1)
        self.assertEqual(len(enriched[1]["dialogues"]), 2)
        self.assertEqual(enriched[1]["dialogues"][1]["speaker"], "领导")
        self.assertEqual(enriched[1]["dialogue_reason"], "这一镜有明确他人介入，适合双猫对话")
        chat_json.assert_called_once()

    @patch("agent.dialogue_enricher.client.chat_json", side_effect=RuntimeError("model down"))
    def test_keeps_existing_dialogues_when_model_fails(self, chat_json):
        scenes = [
            {
                "scene_id": 1,
                "description": "猫独自发呆",
                "dialogues": [{"speaker": "我", "line": "累了"}],
            }
        ]

        enriched = dialogue_enricher.enrich_hyperframe_dialogues(
            scenes=scenes,
            theme="打工人",
            script_title="周一",
        )

        self.assertEqual(enriched, scenes)


if __name__ == "__main__":
    unittest.main()
