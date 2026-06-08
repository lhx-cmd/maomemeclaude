import unittest
from unittest.mock import patch

from agent import cat_role_planner


class CatRolePlannerTest(unittest.TestCase):
    @patch("agent.cat_role_planner.client.chat_json")
    @patch("agent.cat_role_planner.load_cat_motions")
    def test_model_assigns_motion_per_dialogue_role(self, load_cat_motions, chat_json):
        load_cat_motions.return_value = {
            "1": {
                "description": "蓝衣灰猫坐在笔记本电脑前麻木敲键盘。",
                "motion_tags": {"actions": ["敲电脑"], "contexts": ["办公"]},
            },
            "16": {
                "description": "橘猫探头张嘴碎碎念，旁边灰白猫低头不动。",
                "motion_tags": {"actions": ["对话", "碎碎念"], "contexts": ["对话", "老板"]},
            },
        }
        chat_json.return_value = {
            "scenes": [
                {
                    "scene_id": 1,
                    "cat_roles": [
                        {"dialogue_index": 0, "motion_id": "1", "reason": "本人正在办公"},
                        {"dialogue_index": 1, "motion_id": "16", "reason": "对方像在持续讲话"},
                    ],
                }
            ]
        }
        scenes = [
            {
                "scene_id": 1,
                "description": "周一开会时领导突然派活",
                "cat_motion_id": "1",
                "dialogues": [
                    {"speaker": "我", "line": "脑子已经飞到午饭吃啥了"},
                    {"speaker": "领导", "line": "这个项目这周必须上线"},
                ],
            }
        ]

        planned = cat_role_planner.assign_cat_role_motions(scenes)
        dialogues = planned[0]["dialogues"]

        self.assertEqual(dialogues[0]["motion_id"], "1")
        self.assertTrue(dialogues[0]["motion_file"].endswith("/assets/cat-motions/1.mp4"))
        self.assertEqual(dialogues[1]["motion_id"], "16")
        self.assertTrue(dialogues[1]["motion_file"].endswith("/assets/cat-motions/16.mp4"))
        self.assertIn("持续讲话", dialogues[1]["motion_reason"])
        chat_json.assert_called_once()

    @patch("agent.cat_role_planner.client.chat_json", side_effect=RuntimeError("model down"))
    @patch("agent.cat_role_planner.load_cat_motions")
    def test_fallback_uses_distinct_motions_when_model_fails(self, load_cat_motions, chat_json):
        load_cat_motions.return_value = {
            "1": {"description": "办公猫", "motion_tags": {}},
            "2": {"description": "开心回应猫", "motion_tags": {}},
            "4": {"description": "讲话催促猫", "motion_tags": {}},
        }
        scenes = [
            {
                "scene_id": 1,
                "cat_motion_id": "1",
                "dialogues": [
                    {"speaker": "我", "line": "好累"},
                    {"speaker": "朋友", "line": "我也是"},
                ],
            }
        ]

        planned = cat_role_planner.assign_cat_role_motions(scenes)

        self.assertEqual(planned[0]["dialogues"][0]["motion_id"], "1")
        self.assertNotEqual(planned[0]["dialogues"][1]["motion_id"], "1")

    @patch("agent.cat_role_planner.client.chat_json")
    @patch("agent.cat_role_planner.load_cat_motions")
    def test_partial_model_decision_fills_missing_role_with_distinct_motion(
        self,
        load_cat_motions,
        chat_json,
    ):
        load_cat_motions.return_value = {
            "1": {"description": "本人赖床猫", "motion_tags": {}},
            "4": {"description": "闹钟碎碎念讲话猫", "motion_tags": {}},
            "18": {"description": "无语猫", "motion_tags": {}},
        }
        chat_json.return_value = {
            "scenes": [
                {
                    "scene_id": 1,
                    "cat_roles": [
                        {"dialogue_index": 0, "motion_id": "1", "reason": "本人赖床"}
                    ],
                }
            ]
        }
        scenes = [
            {
                "scene_id": 1,
                "description": "闹钟疯狂催我起床，我赖床",
                "cat_motion_id": "1",
                "dialogues": [
                    {"speaker": "我", "line": "再睡五分钟就起"},
                    {"speaker": "闹钟", "line": "你再不起就要扣全勤了"},
                ],
            }
        ]

        planned = cat_role_planner.assign_cat_role_motions(scenes)
        motion_ids = [dialogue["motion_id"] for dialogue in planned[0]["dialogues"]]

        self.assertEqual(len(set(motion_ids)), 2)

    @patch("agent.cat_role_planner.client.chat_json")
    @patch("agent.cat_role_planner.load_cat_motions")
    def test_multi_role_assignment_avoids_duplicate_and_multi_cat_source(
        self,
        load_cat_motions,
        chat_json,
    ):
        load_cat_motions.return_value = {
            "1": {
                "description": "蓝衣灰猫坐在电脑前麻木敲键盘。",
                "motion_tags": {"actions": ["敲电脑"], "contexts": ["办公"]},
            },
            "2": {
                "description": "灰猫直立站在画面中央，张开两只前爪小幅蹦跳。",
                "motion_tags": {"actions": ["蹦跳"], "contexts": ["轻松收束"]},
            },
            "16": {
                "description": "画面中有两只猫，橘猫探头碎碎念，旁边灰白猫低头不动。",
                "motion_tags": {"actions": ["双猫", "对话", "碎碎念"], "contexts": ["对话"]},
            },
        }
        chat_json.return_value = {
            "scenes": [
                {
                    "scene_id": 1,
                    "cat_roles": [
                        {"dialogue_index": 0, "motion_id": "16", "reason": "领导讲话"},
                        {"dialogue_index": 1, "motion_id": "16", "reason": "本人放空"},
                    ],
                }
            ]
        }
        scenes = [
            {
                "scene_id": 1,
                "description": "开周会时领导讲话，我脑内放空",
                "cat_motion_id": "1",
                "dialogues": [
                    {"speaker": "领导", "line": "这周大家加把劲"},
                    {"speaker": "我", "line": "脑内完全放空"},
                ],
            }
        ]

        planned = cat_role_planner.assign_cat_role_motions(scenes)
        motion_ids = [dialogue["motion_id"] for dialogue in planned[0]["dialogues"]]

        self.assertEqual(len(set(motion_ids)), 2)
        self.assertNotIn("16", motion_ids)


if __name__ == "__main__":
    unittest.main()
