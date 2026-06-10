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
                        "source": "user",
                    }
                ],
            }
        ]

        serialized = server._serialize_scenes(scenes)

        self.assertEqual(serialized[0]["stickers"][0]["position"], "top_right")
        self.assertEqual(serialized[0]["stickers"][0]["scale"], 220)
        self.assertEqual(serialized[0]["stickers"][0]["source"], "user")
        self.assertEqual(serialized[0]["topic_caption"], "大学期间和朋友的固定对话是：")
        self.assertEqual(serialized[0]["scene_caption"], "早上起床")
        self.assertEqual(serialized[0]["dialogues"][0]["speaker"], "朋友")

    def test_serialize_scenes_exposes_actual_rendered_cat_roles(self):
        scenes = [
            {
                "scene_id": 1,
                "cat_motion_id": "1",
                "cat_motion_file": "/tmp/main.mp4",
                "cat_motion_desc": "主猫敲电脑",
                "dialogues": [
                    {
                        "speaker": "我",
                        "line": "魂还在周末",
                        "motion_id": "1",
                        "motion_file": "/tmp/main.mp4",
                        "motion_desc": "主猫敲电脑",
                    },
                    {
                        "speaker": "领导",
                        "line": "这个项目今天上线",
                        "motion_id": "4",
                        "motion_file": "/tmp/boss.mp4",
                        "motion_desc": "讲话猫",
                    },
                ],
            }
        ]

        serialized = server._serialize_scenes(scenes)

        self.assertEqual(serialized[0]["cat_motion_file"], "/tmp/main.mp4")
        self.assertEqual(
            serialized[0]["rendered_cats"],
            [
                {
                    "speaker": "我",
                    "line": "魂还在周末",
                    "motion_id": "1",
                    "motion_file": "/tmp/main.mp4",
                    "motion_desc": "主猫敲电脑",
                    "motion_source": "",
                },
                {
                    "speaker": "领导",
                    "line": "这个项目今天上线",
                    "motion_id": "4",
                    "motion_file": "/tmp/boss.mp4",
                    "motion_desc": "讲话猫",
                    "motion_source": "",
                },
            ],
        )

    def test_serialize_scenes_exposes_user_motion_source(self):
        scenes = [
            {
                "scene_id": 1,
                "cat_motion_id": "user",
                "cat_motion_file": "/tmp/uploaded_cat.mp4",
                "cat_motion_desc": "uploaded_cat.mp4",
                "cat_motion_source": "user",
                "dialogues": [
                    {
                        "speaker": "我",
                        "line": "用户猫素材",
                        "motion_id": "user",
                        "motion_file": "/tmp/uploaded_cat.mp4",
                        "motion_desc": "uploaded_cat.mp4",
                        "motion_source": "user",
                    }
                ],
            }
        ]

        serialized = server._serialize_scenes(scenes)

        self.assertEqual(serialized[0]["cat_motion_source"], "user")
        self.assertEqual(serialized[0]["rendered_cats"][0]["motion_source"], "user")

    def test_rendered_cat_source_does_not_fallback_to_scene_user_source_for_local_motion(self):
        scenes = [
            {
                "scene_id": 1,
                "cat_motion_id": "28",
                "cat_motion_file": "/tmp/assets/cat-motions/28.mp4",
                "cat_motion_desc": "小香蕉猫跑步",
                "cat_motion_source": "user",
                "dialogues": [
                    {
                        "speaker": "我",
                        "line": "完了完了要迟到了！",
                        "motion_id": "28",
                        "motion_file": "/tmp/assets/cat-motions/28.mp4",
                        "motion_desc": "小香蕉猫跑步",
                    }
                ],
            }
        ]

        serialized = server._serialize_scenes(scenes)

        self.assertEqual(serialized[0]["rendered_cats"][0]["motion_source"], "")

    @patch("server.run_edit_storyboard")
    def test_edit_response_preserves_storyboard_metadata(self, run_edit_storyboard):
        server.sessions.clear()
        session_id = "edit_meta"
        storyboard = {
            "theme": "周一",
            "script_title": "周一的我本人",
            "script_version": "高共鸣版",
            "total_duration": 4,
            "scene_count": 1,
            "scenes": [{"scene_id": 1, "duration": 4}],
            "gaps": {},
        }
        server.sessions[session_id] = {
            "state": "STORYBOARD",
            "theme": "周一",
            "video_path": None,
            "materials": [],
            "scripts": None,
            "selected_script": None,
            "storyboard": storyboard,
            "edit_history": [],
        }
        run_edit_storyboard.return_value = {
            "state": "STORYBOARD",
            "storyboard": storyboard,
            "edit_plan": {"intent": "modify", "explanation": "ok", "modifications": []},
            "validation": {"ok": True, "issues": []},
        }

        response = server.app.test_client().post(
            "/api/edit",
            json={"session_id": session_id, "instruction": "节奏慢一点"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["theme"], "周一")
        self.assertEqual(payload["script_title"], "周一的我本人")
        self.assertEqual(payload["script_version"], "高共鸣版")
        run_edit_storyboard.assert_called_once_with({
            "session_id": session_id,
            "instruction": "节奏慢一点",
            "storyboard": storyboard,
        })

    @patch("agent.editor.client.chat_json")
    def test_edit_api_swaps_two_cat_dialogue_lines_deterministically(self, chat_json):
        server.sessions.clear()
        session_id = "edit_swap_dialogues"
        server.sessions[session_id] = {
            "state": "STORYBOARD",
            "theme": "周一",
            "video_path": None,
            "materials": [],
            "scripts": None,
            "selected_script": None,
            "storyboard": {
                "theme": "周一",
                "script_title": "周一的我本人",
                "script_version": "高点击版",
                "total_duration": 4,
                "scene_count": 1,
                "scenes": [
                    {
                        "scene_id": 1,
                        "duration": 4,
                        "dialogues": [
                            {"speaker": "我", "line": "老板台词", "motion_id": "1"},
                            {"speaker": "老板", "line": "我的台词", "motion_id": "4"},
                        ],
                        "stickers": [],
                    }
                ],
                "gaps": {},
            },
            "edit_history": [],
        }

        response = server.app.test_client().post(
            "/api/edit",
            json={"session_id": session_id, "instruction": "两只猫的台词弄反了，换过来"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        dialogues = payload["scenes"][0]["dialogues"]
        self.assertEqual(dialogues[0]["speaker"], "我")
        self.assertEqual(dialogues[0]["line"], "我的台词")
        self.assertEqual(dialogues[1]["speaker"], "老板")
        self.assertEqual(dialogues[1]["line"], "老板台词")
        self.assertEqual(payload["edit_result"]["intent"], "swap_dialogue_lines")
        self.assertEqual(len(payload["edit_history"]), 1)
        chat_json.assert_not_called()

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

    @patch("agent.editor.client.chat_json")
    def test_parse_edit_intent_detects_two_cat_line_swap_without_model(self, chat_json):
        storyboard = {
            "scenes": [
                {"scene_id": 1, "dialogues": [{"speaker": "我", "line": "累了"}]},
                {
                    "scene_id": 2,
                    "dialogues": [
                        {"speaker": "我", "line": "不会又有活吧？", "motion_id": "1"},
                        {"speaker": "领导", "line": "这个项目今天上线", "motion_id": "4"},
                    ],
                },
            ]
        }

        plan = editor.parse_edit_intent("第2镜两只猫的台词弄反了，换过来", storyboard)

        chat_json.assert_not_called()
        self.assertEqual(plan["intent"], "swap_dialogue_lines")
        self.assertEqual(plan["modifications"], [
            {
                "scene_id": 2,
                "action": "modify",
                "field": "swap_dialogue_lines",
                "new_value": [0, 1],
                "reason": "用户要求互换两只猫的台词",
            }
        ])

    @patch("agent.editor.client.chat_json")
    def test_parse_edit_intent_handles_audio_mute_and_left_cat_resize_without_model(self, chat_json):
        storyboard = {
            "scenes": [
                {"scene_id": index, "dialogues": []}
                for index in range(1, 6)
            ]
        }

        plan = editor.parse_edit_intent(
            "删除分镜 2 的音频，分镜 5 的左边那只猫太大了，缩小它",
            storyboard,
        )

        chat_json.assert_not_called()
        self.assertEqual(plan["intent"], "mixed")
        self.assertEqual(plan["modifications"], [
            {
                "scene_id": 2,
                "action": "modify",
                "field": "audio_muted",
                "new_value": True,
                "reason": "用户要求删除该分镜音频",
            },
            {
                "scene_id": 5,
                "action": "modify",
                "field": "cat_layout_overrides",
                "new_value": {"left": {"scale_multiplier": 0.78}},
                "reason": "用户要求缩小左边那只猫",
            },
        ])

    @patch("agent.editor.client.chat_json")
    def test_parse_edit_intent_detects_right_cat_motion_replacement_without_model(self, chat_json):
        storyboard = {
            "scenes": [
                {"scene_id": 1, "dialogues": []},
                {"scene_id": 4, "dialogues": [
                    {"speaker": "领导", "line": "开会=带薪发呆", "motion_id": "4"},
                    {"speaker": "我", "line": "左耳进右耳出", "motion_id": "14"},
                ]},
            ]
        }

        plan = editor.parse_edit_intent("分镜 4 的右侧锚选择不合适，要求更换", storyboard)

        chat_json.assert_not_called()
        self.assertEqual(plan["intent"], "replace_dialogue_motion")
        self.assertEqual(plan["modifications"], [
            {
                "scene_id": 4,
                "action": "modify",
                "field": "replace_dialogue_motion",
                "new_value": {
                    "slot": "right",
                    "dialogue_index": 1,
                    "avoid_motion_id": "14",
                },
                "reason": "用户要求更换右边那只猫的动作素材",
            }
        ])

    def test_apply_edits_persists_render_controls_without_rematching_materials(self):
        storyboard = {
            "scenes": [
                {
                    "scene_id": 2,
                    "duration": 4,
                    "cat_motion_id": "1",
                    "cat_motion_file": "/tmp/original.mp4",
                    "dialogues": [],
                },
                {
                    "scene_id": 5,
                    "duration": 4,
                    "cat_motion_id": "2",
                    "cat_motion_file": "/tmp/left.mp4",
                    "dialogues": [
                        {"speaker": "我", "line": "撑住", "motion_file": "/tmp/left.mp4"},
                        {"speaker": "同事", "line": "加油", "motion_file": "/tmp/right.mp4"},
                    ],
                },
            ]
        }
        edit_plan = {
            "explanation": "删音频并缩小左猫",
            "modifications": [
                {"scene_id": 2, "action": "modify", "field": "audio_muted", "new_value": True},
                {
                    "scene_id": 5,
                    "action": "modify",
                    "field": "cat_layout_overrides",
                    "new_value": {"left": {"scale_multiplier": 0.78}},
                },
            ],
        }

        result = editor.apply_edits(storyboard, edit_plan)

        self.assertTrue(result["scenes"][0]["audio_muted"])
        self.assertEqual(result["scenes"][1]["cat_layout_overrides"], {"left": {"scale_multiplier": 0.78}})
        self.assertNotIn("_modified", result["scenes"][0])
        self.assertNotIn("_modified", result["scenes"][1])

    @patch("agent.editor.choose_dialogue_motion_replacement")
    def test_apply_edits_replaces_right_dialogue_motion(self, choose_replacement):
        choose_replacement.return_value = {
            "motion_id": "23",
            "motion_file": "/tmp/23.mp4",
            "motion_desc": "放松治愈的小白猫抱饮料",
            "reason": "右侧神游角色更适合放松动作",
        }
        storyboard = {
            "scenes": [
                {
                    "scene_id": 4,
                    "cat_motion_id": "4",
                    "cat_motion_file": "/tmp/4.mp4",
                    "cat_motion_desc": "领导讲话猫",
                    "dialogues": [
                        {"speaker": "领导", "line": "开会=带薪发呆", "motion_id": "4", "motion_file": "/tmp/4.mp4"},
                        {"speaker": "我", "line": "左耳进右耳出", "motion_id": "14", "motion_file": "/tmp/14.mp4"},
                    ],
                }
            ]
        }
        edit_plan = {
            "intent": "replace_dialogue_motion",
            "modifications": [
                {
                    "scene_id": 4,
                    "action": "modify",
                    "field": "replace_dialogue_motion",
                    "new_value": {"slot": "right", "dialogue_index": 1, "avoid_motion_id": "14"},
                }
            ],
        }

        result = editor.apply_edits(storyboard, edit_plan)

        dialogues = result["scenes"][0]["dialogues"]
        self.assertEqual(dialogues[0]["motion_id"], "4")
        self.assertEqual(dialogues[1]["motion_id"], "23")
        self.assertEqual(dialogues[1]["motion_file"], "/tmp/23.mp4")
        self.assertEqual(dialogues[1]["motion_desc"], "放松治愈的小白猫抱饮料")
        self.assertEqual(dialogues[1]["motion_reason"], "右侧神游角色更适合放松动作")
        choose_replacement.assert_called_once()

    @patch("agent.editor.choose_dialogue_motion_replacement")
    @patch("agent.editor.client.chat_json")
    def test_edit_api_replaces_right_rendered_cat_motion(self, chat_json, choose_replacement):
        choose_replacement.return_value = {
            "motion_id": "23",
            "motion_file": "/tmp/23.mp4",
            "motion_desc": "放松治愈的小白猫抱饮料",
            "reason": "右侧神游角色更适合放松动作",
        }
        server.sessions.clear()
        session_id = "edit_right_cat_motion"
        server.sessions[session_id] = {
            "state": "DONE",
            "theme": "周一",
            "video_path": "/tmp/old.mp4",
            "materials": [],
            "scripts": None,
            "selected_script": None,
            "storyboard": {
                "theme": "周一",
                "script_title": "周一",
                "script_version": "高共鸣版",
                "total_duration": 16,
                "scene_count": 4,
                "scenes": [
                    {"scene_id": 1, "duration": 4, "dialogues": [{"speaker": "我", "line": "魂还在周末", "motion_id": "1"}]},
                    {"scene_id": 2, "duration": 4, "dialogues": [{"speaker": "我", "line": "人还没醒", "motion_id": "2"}]},
                    {"scene_id": 3, "duration": 4, "dialogues": [{"speaker": "我", "line": "咖啡续命", "motion_id": "3"}]},
                    {
                        "scene_id": 4,
                        "duration": 4,
                        "cat_motion_id": "4",
                        "cat_motion_file": "/tmp/4.mp4",
                        "cat_motion_desc": "领导讲话猫",
                        "dialogues": [
                            {"speaker": "领导", "line": "开会=带薪发呆", "motion_id": "4", "motion_file": "/tmp/4.mp4"},
                            {"speaker": "我", "line": "左耳进右耳出", "motion_id": "14", "motion_file": "/tmp/14.mp4"},
                        ],
                    }
                ],
                "gaps": {},
            },
            "edit_history": [],
        }

        response = server.app.test_client().post(
            "/api/edit",
            json={"session_id": session_id, "instruction": "分镜 4 的右侧锚选择不合适，要求更换"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        rendered = payload["scenes"][3]["rendered_cats"]
        self.assertEqual(rendered[0]["motion_id"], "4")
        self.assertEqual(rendered[1]["motion_id"], "23")
        self.assertIsNone(payload["video_url"])
        self.assertIsNone(server.sessions[session_id]["video_path"])
        chat_json.assert_not_called()

    @patch("server.run_edit_storyboard")
    def test_edit_response_serializes_render_controls(self, run_edit_storyboard):
        server.sessions.clear()
        session_id = "edit_render_controls"
        storyboard = {
            "theme": "周一",
            "script_title": "周一",
            "script_version": "高共鸣版",
            "total_duration": 8,
            "scene_count": 2,
            "scenes": [
                {"scene_id": 2, "duration": 4, "audio_muted": True},
                {
                    "scene_id": 5,
                    "duration": 4,
                    "cat_layout_overrides": {"left": {"scale_multiplier": 0.78}},
                },
            ],
            "gaps": {},
        }
        server.sessions[session_id] = {
            "state": "STORYBOARD",
            "theme": "周一",
            "video_path": None,
            "materials": [],
            "scripts": None,
            "selected_script": None,
            "storyboard": storyboard,
            "edit_history": [],
        }
        run_edit_storyboard.return_value = {
            "state": "STORYBOARD",
            "storyboard": storyboard,
            "edit_plan": {"intent": "mixed", "explanation": "ok", "modifications": [{"scene_id": 2}]},
            "validation": {"ok": True, "issues": []},
        }

        response = server.app.test_client().post(
            "/api/edit",
            json={"session_id": session_id, "instruction": "删除分镜2音频，缩小分镜5左猫"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["scenes"][0]["audio_muted"])
        self.assertEqual(
            payload["scenes"][1]["cat_layout_overrides"],
            {"left": {"scale_multiplier": 0.78}},
        )

    @patch("server.run_edit_storyboard")
    def test_edit_invalidates_existing_generated_video(self, run_edit_storyboard):
        server.sessions.clear()
        session_id = "edit_invalidates_video"
        storyboard = {
            "theme": "周一",
            "script_title": "周一",
            "script_version": "高共鸣版",
            "total_duration": 4,
            "scene_count": 1,
            "scenes": [{"scene_id": 1, "duration": 4}],
            "gaps": {},
        }
        server.sessions[session_id] = {
            "state": "DONE",
            "theme": "周一",
            "video_path": "/tmp/old_final_video.mp4",
            "materials": [],
            "scripts": None,
            "selected_script": None,
            "storyboard": storyboard,
            "edit_history": [],
        }
        run_edit_storyboard.return_value = {
            "state": "STORYBOARD",
            "storyboard": storyboard,
            "edit_plan": {"intent": "modify", "explanation": "ok", "modifications": []},
            "validation": {"ok": True, "issues": []},
        }

        response = server.app.test_client().post(
            "/api/edit",
            json={"session_id": session_id, "instruction": "缩小左边猫"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsNone(server.sessions[session_id]["video_path"])
        self.assertIsNone(payload["video_url"])
        self.assertEqual(payload["state"], "STORYBOARD")

    @patch("agent.editor.client.chat_json")
    def test_parse_edit_intent_includes_dialogues_in_model_context(self, chat_json):
        chat_json.return_value = {"intent": "adjust_subtitle", "explanation": "ok", "modifications": []}
        storyboard = {
            "scenes": [
                {
                    "scene_id": 1,
                    "duration": 4,
                    "dialogues": [
                        {"speaker": "我", "line": "不会又有活吧？", "motion_id": "1"},
                        {"speaker": "领导", "line": "这个项目今天上线", "motion_id": "4"},
                    ],
                }
            ]
        }

        editor.parse_edit_intent("把领导那句改短一点", storyboard)

        user_message = chat_json.call_args.kwargs["user_message"]
        self.assertIn("猫头台词", user_message)
        self.assertIn("领导/motion#4: 这个项目今天上线", user_message)

    @patch("agent.editor.match_stickers")
    @patch("agent.editor.match_cat_motion")
    def test_apply_edits_swaps_dialogue_lines_without_swapping_roles_or_rematching(
        self,
        match_motion,
        match_stickers,
    ):
        storyboard = {
            "scenes": [
                {
                    "scene_id": 1,
                    "duration": 4,
                    "dialogues": [
                        {"speaker": "我", "line": "老板台词", "motion_id": "1"},
                        {"speaker": "老板", "line": "我的台词", "motion_id": "4"},
                    ],
                    "stickers": [],
                }
            ]
        }
        edit_plan = {
            "intent": "swap_dialogue_lines",
            "explanation": "交换两只猫台词",
            "modifications": [
                {
                    "scene_id": 1,
                    "action": "modify",
                    "field": "swap_dialogue_lines",
                    "new_value": [0, 1],
                }
            ],
        }

        result = editor.apply_edits(storyboard, edit_plan)

        dialogues = result["scenes"][0]["dialogues"]
        self.assertEqual(dialogues[0]["speaker"], "我")
        self.assertEqual(dialogues[0]["motion_id"], "1")
        self.assertEqual(dialogues[0]["line"], "我的台词")
        self.assertEqual(dialogues[1]["speaker"], "老板")
        self.assertEqual(dialogues[1]["motion_id"], "4")
        self.assertEqual(dialogues[1]["line"], "老板台词")
        match_motion.assert_not_called()
        match_stickers.assert_not_called()


if __name__ == "__main__":
    unittest.main()
