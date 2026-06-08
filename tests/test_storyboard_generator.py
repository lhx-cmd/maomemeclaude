import json
import unittest
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from agent import script_generator, storyboard_generator


class StoryboardGeneratorTest(unittest.TestCase):
    def test_detailed_prompt_requests_background_and_prop_fields(self):
        prompt = script_generator.DETAILED_SCRIPT_PROMPT

        self.assertIn("suggested_background", prompt)
        self.assertIn("suggested_prop", prompt)
        self.assertIn("sticker_position", prompt)
        self.assertIn("scene_caption", prompt)
        self.assertIn("dialogues", prompt)
        self.assertIn("6-8", prompt)
        self.assertIn("3-4秒", prompt)
        self.assertNotIn("总镜头数控制在8-12个", prompt)
        self.assertNotIn("每2-3秒一个镜头切换", prompt)

    @patch("agent.storyboard_generator.assign_cat_role_motions", side_effect=lambda scenes: scenes)
    @patch("agent.storyboard_generator.match_stickers")
    @patch("agent.storyboard_generator.match_cat_motion")
    def test_storyboard_preserves_hyperframe_caption_fields(self, match_motion, match_stickers, assign_roles):
        match_motion.return_value = {
            "motion_id": "1",
            "file_path": "/tmp/1.mp4",
            "description": "cat",
            "score": 5,
        }
        match_stickers.return_value = []

        storyboard = storyboard_generator.generate_storyboard(
            selected_script={
                "title": "大学早八",
                "version_name": "v",
                "scenes": [
                    {
                        "scene_id": 1,
                        "description": "两只猫在宿舍讨论早八",
                        "duration_sec": 2,
                        "subtitle_text": "朋友",
                        "scene_caption": "早上起床",
                        "dialogues": [
                            {"speaker": "我", "line": "怎么又是早八啊！"},
                            {"speaker": "朋友", "line": "已经上三天早八了！"},
                        ],
                        "emotion": "崩溃",
                    }
                ],
            },
            theme="大学生活",
            auto_fill_gaps=False,
        )

        scene = storyboard["scenes"][0]
        self.assertEqual(scene["topic_caption"], "大学早八")
        self.assertEqual(scene["scene_caption"], "早上起床")
        self.assertEqual(len(scene["dialogues"]), 2)
        self.assertEqual(scene["dialogues"][1]["speaker"], "朋友")

    @patch("agent.storyboard_generator.match_stickers")
    @patch("agent.storyboard_generator.match_cat_motion")
    def test_storyboard_limits_scene_count_and_extends_short_durations(self, match_motion, match_stickers):
        match_motion.return_value = {
            "motion_id": "1",
            "file_path": "/tmp/1.mp4",
            "description": "cat",
            "score": 5,
        }
        match_stickers.return_value = []
        scenes = [
            {
                "scene_id": index,
                "description": f"第{index}镜：推进剧情",
                "duration_sec": 2,
                "subtitle_text": f"字幕{index}",
                "emotion": "焦虑",
            }
            for index in range(1, 10)
        ]
        scenes.append({
            "scene_id": 10,
            "description": "第10镜：结尾 CTA",
            "duration_sec": 2,
            "subtitle_text": "评论区集合",
            "emotion": "释然",
        })

        storyboard = storyboard_generator.generate_storyboard(
            selected_script={
                "title": "周一打工人",
                "version_name": "v",
                "scenes": scenes,
            },
            theme="打工人",
            auto_fill_gaps=False,
        )

        self.assertLessEqual(storyboard["scene_count"], 8)
        self.assertEqual(storyboard["scenes"][-1]["description"], "第10镜：结尾 CTA")
        self.assertTrue(all(3 <= scene["duration"] <= 5 for scene in storyboard["scenes"]))

    @patch("agent.storyboard_generator.load_cat_motions", create=True)
    @patch("agent.storyboard_generator.client.chat_json")
    def test_combined_ai_planning_reviews_dialogues_and_role_motions_in_one_call(
        self,
        chat_json,
        load_cat_motions,
    ):
        load_cat_motions.return_value = {
            "1": {"description": "主猫麻木敲电脑", "motion_tags": {}},
            "4": {"description": "老板猫碎碎念讲话", "motion_tags": {}},
        }
        chat_json.return_value = {
            "scenes": [
                {
                    "scene_id": 1,
                    "scene_caption": "开周会",
                    "dialogues": [
                        {"speaker": "老板", "line": "这个项目这周必须上线"},
                        {"speaker": "我", "line": "脑子已经飞到午饭了"},
                    ],
                    "stickers": [
                        {
                            "file": "/tmp/laptop.png",
                            "keep": True,
                            "position": "desk_right",
                            "scale": 160,
                            "reason": "电脑服务办公剧情",
                        }
                    ],
                    "prop": {"keep": False, "reason": "鼠标不是关键道具"},
                    "cat_roles": [
                        {"dialogue_index": 0, "motion_id": "4", "reason": "老板讲话"},
                        {"dialogue_index": 1, "motion_id": "1", "reason": "主猫放空"},
                    ],
                }
            ]
        }
        scenes = [
            {
                "scene_id": 1,
                "description": "老板催项目，我在会议室放空",
                "subtitle": "周一开会",
                "emotion": "焦虑",
                "scene_caption": "开会",
                "cat_motion_id": "1",
                "cat_motion_desc": "主猫麻木",
                "dialogues": [{"speaker": "我", "line": "好的老板"}],
                "stickers": [
                    {
                        "category": "digital-communication",
                        "file": "/tmp/mouse.png",
                        "position": "top_left",
                        "scale": 180,
                    },
                    {
                        "category": "digital-communication",
                        "file": "/tmp/laptop.png",
                        "position": "top_right",
                        "scale": 180,
                    },
                ],
                "suggested_prop": "鼠标",
            }
        ]

        planned, roles_assigned = storyboard_generator._review_enrich_and_assign_storyboard(
            scenes=scenes,
            theme="打工人周一",
            script_title="周一打工人",
        )

        chat_json.assert_called_once()
        self.assertTrue(roles_assigned)
        scene = planned[0]
        self.assertEqual(scene["scene_caption"], "开周会")
        self.assertEqual(scene["suggested_prop"], "")
        self.assertEqual([sticker["file"] for sticker in scene["stickers"]], ["/tmp/laptop.png"])
        self.assertEqual(scene["stickers"][0]["position"], "desk_right")
        self.assertEqual([dialogue["motion_id"] for dialogue in scene["dialogues"]], ["4", "1"])

    @patch("agent.storyboard_generator.match_stickers")
    @patch("agent.storyboard_generator.match_cat_motion")
    def test_storyboard_does_not_add_expression_sticker_from_emotion_only(self, match_motion, match_stickers):
        match_motion.return_value = {
            "motion_id": "1",
            "file_path": "/tmp/1.mp4",
            "description": "cat",
            "score": 5,
        }
        match_stickers.return_value = []

        storyboard = storyboard_generator.generate_storyboard(
            selected_script={
                "title": "t",
                "version_name": "v",
                "scenes": [
                    {
                        "scene_id": 1,
                        "description": "shock",
                        "duration_sec": 2,
                        "subtitle_text": "wow",
                        "emotion": "震惊",
                    }
                ],
            },
            theme="theme",
            auto_fill_gaps=False,
        )

        self.assertEqual(storyboard["scenes"][0]["stickers"], [])
        match_stickers.assert_not_called()

    @patch("agent.storyboard_generator.match_stickers")
    @patch("agent.storyboard_generator.match_cat_motion")
    def test_storyboard_does_not_add_random_stickers_without_relevant_cue(self, match_motion, match_stickers):
        match_motion.return_value = {
            "motion_id": "1",
            "file_path": "/tmp/1.mp4",
            "description": "cat",
            "score": 5,
        }
        match_stickers.return_value = [
            {
                "category": "emotion-effects",
                "file_path": "/tmp/random.png",
            }
        ]

        storyboard = storyboard_generator.generate_storyboard(
            selected_script={
                "title": "t",
                "version_name": "v",
                "scenes": [
                    {
                        "scene_id": 1,
                        "description": "猫看着镜头等待下一句字幕",
                        "duration_sec": 2,
                        "subtitle_text": "然后呢",
                        "emotion": "焦虑",
                    }
                ],
            },
            theme="theme",
            auto_fill_gaps=False,
        )

        self.assertEqual(storyboard["scenes"][0]["stickers"], [])
        match_stickers.assert_not_called()

    @patch("agent.storyboard_generator.match_stickers")
    @patch("agent.storyboard_generator.match_cat_motion")
    def test_storyboard_uses_explicit_sticker_suggestion_for_matching(self, match_motion, match_stickers):
        match_motion.return_value = {
            "motion_id": "1",
            "file_path": "/tmp/1.mp4",
            "description": "cat",
            "score": 5,
        }
        match_stickers.return_value = [
            {
                "category": "digital-communication",
                "file_path": "/tmp/phone.png",
            }
        ]

        storyboard = storyboard_generator.generate_storyboard(
            selected_script={
                "title": "t",
                "version_name": "v",
                "scenes": [
                    {
                        "scene_id": 1,
                        "description": "同事消息疯狂@我",
                        "duration_sec": 2,
                        "subtitle_text": "消息又来了",
                        "emotion": "崩溃",
                        "suggested_stickers": ["手机消息气泡"],
                    }
                ],
            },
            theme="打工人",
            auto_fill_gaps=False,
        )

        self.assertIn("手机消息气泡", match_stickers.call_args.kwargs["scene_description"])
        self.assertEqual(storyboard["scenes"][0]["stickers"][0]["category"], "digital-communication")

    @patch("agent.storyboard_generator.match_stickers")
    @patch("agent.storyboard_generator.match_cat_motion")
    def test_storyboard_drops_irrelevant_suggested_prop(self, match_motion, match_stickers):
        match_motion.return_value = {
            "motion_id": "1",
            "file_path": "/tmp/1.mp4",
            "description": "cat",
            "score": 5,
        }
        match_stickers.return_value = []

        storyboard = storyboard_generator.generate_storyboard(
            selected_script={
                "title": "t",
                "version_name": "v",
                "scenes": [
                    {
                        "scene_id": 1,
                        "description": "同事消息疯狂@我",
                        "duration_sec": 2,
                        "subtitle_text": "同事还一堆消息疯狂@我",
                        "emotion": "崩溃",
                        "suggested_prop": "金币",
                    }
                ],
            },
            theme="打工人",
            auto_fill_gaps=False,
        )

        self.assertEqual(storyboard["scenes"][0]["suggested_prop"], "")

    @patch("agent.storyboard_generator.enrich_hyperframe_dialogues", side_effect=lambda scenes, theme, script_title: scenes)
    @patch("agent.storyboard_generator.assign_cat_role_motions", side_effect=lambda scenes: scenes)
    @patch("agent.storyboard_generator.client.chat_json")
    @patch("agent.storyboard_generator.match_stickers")
    @patch("agent.storyboard_generator.match_cat_motion")
    def test_ai_material_review_removes_irrelevant_overlay(
        self,
        match_motion,
        match_stickers,
        chat_json,
        assign_roles,
        enrich_dialogues,
    ):
        match_motion.return_value = {
            "motion_id": "1",
            "file_path": "/tmp/1.mp4",
            "description": "cat",
            "score": 5,
        }
        match_stickers.return_value = [
            {
                "category": "digital-communication",
                "file_path": "/tmp/mouse.png",
            }
        ]
        chat_json.return_value = {
            "scenes": [
                {
                    "scene_id": 1,
                    "stickers": [],
                    "prop": {"keep": False, "reason": "鼠标和补考剧情无关"},
                }
            ]
        }

        storyboard = storyboard_generator.generate_storyboard(
            selected_script={
                "title": "t",
                "version_name": "v",
                "scenes": [
                    {
                        "scene_id": 1,
                        "description": "猫在教室里翻书，担心补考",
                        "duration_sec": 2,
                        "subtitle_text": "一翻书：这课我上过？",
                        "emotion": "疑问",
                        "suggested_stickers": ["鼠标"],
                        "suggested_prop": "鼠标",
                    }
                ],
            },
            theme="补考",
            auto_fill_gaps=False,
            review_materials=True,
        )

        scene = storyboard["scenes"][0]
        self.assertEqual(scene["stickers"], [])
        self.assertEqual(scene["suggested_prop"], "")

    @patch("agent.storyboard_generator.enrich_hyperframe_dialogues", side_effect=lambda scenes, theme, script_title: scenes)
    @patch("agent.storyboard_generator.assign_cat_role_motions", side_effect=lambda scenes: scenes)
    @patch("agent.storyboard_generator.client.chat_json")
    @patch("agent.storyboard_generator.match_stickers")
    @patch("agent.storyboard_generator.match_cat_motion")
    def test_ai_material_review_sets_safe_position_for_relevant_sticker(
        self,
        match_motion,
        match_stickers,
        chat_json,
        assign_roles,
        enrich_dialogues,
    ):
        match_motion.return_value = {
            "motion_id": "1",
            "file_path": "/tmp/1.mp4",
            "description": "cat",
            "score": 5,
        }
        match_stickers.return_value = [
            {
                "category": "campus-study",
                "file_path": "/tmp/exam.png",
            }
        ]
        chat_json.return_value = {
            "scenes": [
                {
                    "scene_id": 1,
                    "stickers": [
                        {
                            "file": "/tmp/exam.png",
                            "keep": True,
                            "position": "bottom_left",
                            "scale": 150,
                            "reason": "试卷贴纸呼应补考剧情",
                        }
                    ],
                    "prop": {"keep": False},
                }
            ]
        }

        storyboard = storyboard_generator.generate_storyboard(
            selected_script={
                "title": "t",
                "version_name": "v",
                "scenes": [
                    {
                        "scene_id": 1,
                        "description": "猫看到补考试卷",
                        "duration_sec": 2,
                        "subtitle_text": "补考来了",
                        "emotion": "崩溃",
                        "suggested_stickers": ["试卷"],
                    }
                ],
            },
            theme="补考",
            auto_fill_gaps=False,
            review_materials=True,
        )

        sticker = storyboard["scenes"][0]["stickers"][0]
        self.assertEqual(sticker["position"], "bottom_left")
        self.assertEqual(sticker["scale"], 150)
        self.assertIn("试卷贴纸", sticker["ai_reason"])

    def test_fallback_material_review_and_dialogue_enrichment_run_concurrently(self):
        active = 0
        max_active = 0
        lock = threading.Lock()

        def enter_parallel_section():
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1

        def fake_review(scenes, theme):
            enter_parallel_section()
            reviewed = [dict(scene) for scene in scenes]
            reviewed[0]["suggested_prop"] = ""
            return reviewed

        def fake_enrich(scenes, theme, script_title):
            enter_parallel_section()
            enriched = [dict(scene) for scene in scenes]
            enriched[0]["scene_caption"] = "并发对话"
            enriched[0]["dialogues"] = [{"speaker": "我", "line": "快点下班"}]
            return enriched

        with patch("agent.storyboard_generator._review_storyboard_materials", side_effect=fake_review), \
                patch("agent.storyboard_generator.enrich_hyperframe_dialogues", side_effect=fake_enrich):
            scenes = storyboard_generator._review_and_enrich_storyboard(
                scenes=[
                    {
                        "scene_id": 1,
                        "description": "打工人周一坐在电脑前",
                        "subtitle": "好累",
                        "emotion": "麻木",
                    }
                ],
                theme="打工人",
                script_title="周一",
            )

        self.assertEqual(max_active, 2)
        self.assertEqual(scenes[0]["suggested_prop"], "")
        self.assertEqual(scenes[0]["scene_caption"], "并发对话")

    def test_gap_fill_and_role_motion_assignment_run_concurrently(self):
        active = 0
        max_active = 0
        lock = threading.Lock()

        def enter_parallel_section():
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1

        def fake_fill_gaps(scenes, gaps):
            enter_parallel_section()
            filled = [dict(scene) for scene in scenes]
            filled[0]["generated_assets"] = [{"type": "背景缺失", "file": "/tmp/bg.png"}]
            return filled

        def fake_assign_roles(scenes):
            enter_parallel_section()
            assigned = [dict(scene) for scene in scenes]
            assigned[0]["dialogues"] = [dict(assigned[0]["dialogues"][0], motion_id="1", motion_file="/tmp/1.mp4")]
            return assigned

        with patch("agent.storyboard_generator._auto_fill_gaps", side_effect=fake_fill_gaps), \
                patch("agent.storyboard_generator.assign_cat_role_motions", side_effect=fake_assign_roles):
            scenes = storyboard_generator._fill_gaps_and_assign_roles(
                scenes=[
                    {
                        "scene_id": 1,
                        "description": "两只猫在办公室对话",
                        "cat_motion_id": "1",
                        "dialogues": [{"speaker": "我", "line": "今天又周一"}],
                    }
                ],
                gap_report={
                    "gaps": [
                        {
                            "scene_id": 1,
                            "gap_type": "背景缺失",
                            "fill_strategy": "AIGC生成",
                        }
                    ]
                },
                auto_fill_gaps=True,
                review_materials=True,
            )

        self.assertEqual(max_active, 2)
        self.assertEqual(scenes[0]["generated_assets"][0]["file"], "/tmp/bg.png")
        self.assertEqual(scenes[0]["dialogues"][0]["motion_file"], "/tmp/1.mp4")

    @patch("agent.storyboard_generator.load_cat_motions")
    @patch("agent.storyboard_generator.client.chat_json")
    def test_ai_planning_uses_compact_motion_payload_and_token_budget(self, chat_json, load_cat_motions):
        load_cat_motions.return_value = {
            str(index): {
                "description": f"motion {index}",
                "motion_tags": {
                    "actions": ["敲电脑"] if index == 1 else ["动作"],
                    "emotions": ["麻木"] if index == 1 else ["普通"],
                    "contexts": ["办公"] if index == 1 else ["日常"],
                },
            }
            for index in range(1, 31)
        }
        chat_json.return_value = {"scenes": []}

        storyboard_generator._review_enrich_and_assign_storyboard(
            scenes=[
                {
                    "scene_id": 1,
                    "description": "猫在办公室敲电脑，表情麻木",
                    "subtitle": "周一开工",
                    "emotion": "麻木",
                    "cat_motion_id": "1",
                    "cat_motion_desc": "蓝衣灰猫敲电脑",
                    "dialogues": [{"speaker": "我", "line": "又要上班了"}],
                }
            ],
            theme="周一打工人",
            script_title="周一",
        )

        payload = json.loads(chat_json.call_args.kwargs["user_message"])
        self.assertLess(len(payload["motion_catalog"]), 30)
        self.assertIn("1", {item["motion_id"] for item in payload["motion_catalog"]})
        self.assertLessEqual(chat_json.call_args.kwargs["max_tokens"], 4096)

    def test_role_assignment_waits_for_gap_fill_when_cat_motion_is_missing(self):
        scenes = [
            {
                "scene_id": 1,
                "cat_motion_id": None,
                "dialogues": [{"speaker": "我", "line": "好累"}],
            }
        ]
        gaps = {
            "gaps": [
                {
                    "scene_id": 1,
                    "gap_type": "猫动作缺失",
                    "fill_strategy": "现有素材复用",
                }
            ]
        }

        def fake_fill_gaps(input_scenes, gap_report):
            filled = [dict(scene) for scene in input_scenes]
            filled[0]["cat_motion_id"] = "2"
            return filled

        def fake_assign_roles(input_scenes):
            self.assertEqual(input_scenes[0]["cat_motion_id"], "2")
            assigned = [dict(scene) for scene in input_scenes]
            assigned[0]["dialogues"] = [dict(assigned[0]["dialogues"][0], motion_id="2")]
            return assigned

        with patch("agent.storyboard_generator._auto_fill_gaps", side_effect=fake_fill_gaps), \
                patch("agent.storyboard_generator.assign_cat_role_motions", side_effect=fake_assign_roles):
            result = storyboard_generator._fill_gaps_and_assign_roles(
                scenes=scenes,
                gap_report=gaps,
                auto_fill_gaps=True,
                review_materials=True,
            )

        self.assertEqual(result[0]["dialogues"][0]["motion_id"], "2")

    def test_fill_storyboard_gaps_for_video_runs_auto_fill_once(self):
        storyboard = {
            "scenes": [
                {
                    "scene_id": 1,
                    "description": "办公室工位",
                    "cat_motion_id": "1",
                    "_match_score": 5,
                    "suggested_background": "办公室工位背景",
                    "generated_assets": [],
                }
            ],
            "gaps": {
                "gaps": [
                    {
                        "scene_id": 1,
                        "gap_type": "背景缺失",
                        "fill_strategy": "AIGC生成",
                        "generation_prompt": "bg",
                    }
                ]
            },
        }

        def fake_fill(scenes, gaps):
            filled = [dict(scene) for scene in scenes]
            filled[0]["generated_assets"] = [{"type": "背景缺失", "file": "/tmp/bg.png"}]
            return filled

        with patch("agent.storyboard_generator._auto_fill_gaps", side_effect=fake_fill) as auto_fill:
            filled_storyboard = storyboard_generator.fill_storyboard_gaps_for_video(storyboard)
            filled_again = storyboard_generator.fill_storyboard_gaps_for_video(filled_storyboard)

        self.assertEqual(auto_fill.call_count, 1)
        self.assertEqual(filled_again["scenes"][0]["generated_assets"][0]["file"], "/tmp/bg.png")

    @patch("agent.storyboard_generator.match_stickers")
    @patch("agent.storyboard_generator.match_cat_motion")
    def test_storyboard_generates_background_even_when_script_omits_it(self, match_motion, match_stickers):
        match_motion.return_value = {
            "motion_id": "1",
            "file_path": "/tmp/1.mp4",
            "description": "cat",
            "score": 5,
        }
        match_stickers.return_value = []

        with tempfile.TemporaryDirectory() as tmp:
            old_generated_dir = storyboard_generator.config.generated_dir
            storyboard_generator.config.generated_dir = Path(tmp)
            try:
                with patch.object(
                    storyboard_generator.seedream,
                    "generate_background",
                    side_effect=RuntimeError("Seedream unavailable"),
                ):
                    storyboard = storyboard_generator.generate_storyboard(
                        selected_script={
                            "title": "t",
                            "version_name": "v",
                            "scenes": [
                                {
                                    "scene_id": 1,
                                    "description": "打工人周一坐在电脑前崩溃",
                                    "duration_sec": 2,
                                    "subtitle_text": "周一又来了",
                                    "emotion": "崩溃",
                                }
                            ],
                        },
                        theme="打工人周一综合症",
                        auto_fill_gaps=True,
                    )
                scene = storyboard["scenes"][0]
                self.assertTrue(scene["suggested_background"])
                bg_assets = [a for a in scene["generated_assets"] if a["type"] == "背景缺失"]
                self.assertEqual(len(bg_assets), 1)
                self.assertTrue(Path(bg_assets[0]["file"]).exists())
            finally:
                storyboard_generator.config.generated_dir = old_generated_dir


if __name__ == "__main__":
    unittest.main()
