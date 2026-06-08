import unittest

from agent.composition_planner import apply_hyperframe_plan, plan_scene_composition


class CompositionPlannerTest(unittest.TestCase):
    def test_phone_scene_places_phone_near_cat_paw(self):
        scene = {
            "scene_id": 1,
            "description": "猫趴在桌上玩手机刷视频",
            "subtitle": "同事消息疯狂@我",
            "stickers": [
                {
                    "category": "digital-communication",
                    "file": "/tmp/020-phone-in-hand.png",
                }
            ],
        }

        planned = apply_hyperframe_plan(scene)

        self.assertEqual(len(planned["stickers"]), 1)
        sticker = planned["stickers"][0]
        self.assertEqual(sticker["position"], "near_cat_paw_left")
        self.assertEqual(sticker["composition_role"], "phone_hand")
        self.assertIn("猫爪", sticker["composition_reason"])
        self.assertEqual(planned["composition_plan"]["engine"], "hyperframes-lite")

    def test_exam_scene_places_study_object_on_desk(self):
        scene = {
            "scene_id": 2,
            "description": "猫在教室里翻书，突然发现还要补考",
            "subtitle": "一翻书：这课我上过？",
            "stickers": [
                {
                    "category": "campus-study",
                    "file": "/tmp/final-exam-paper.png",
                    "position": "top_left",
                    "scale": 220,
                }
            ],
        }

        planned = apply_hyperframe_plan(scene)

        sticker = planned["stickers"][0]
        self.assertEqual(sticker["position"], "desk_left")
        self.assertLessEqual(sticker["scale"], 190)
        self.assertNotEqual(sticker["position"], "top_left")

    def test_decorative_expression_sticker_is_removed(self):
        scene = {
            "scene_id": 3,
            "description": "猫盯着镜头无语",
            "subtitle": "算了算了",
            "emotion": "无语",
            "stickers": [
                {
                    "category": "emotion-effects",
                    "file": "/tmp/021-eyes.png",
                    "position": "top_left",
                }
            ],
        }

        planned = apply_hyperframe_plan(scene)
        decision = planned["composition_plan"]["overlays"][0]

        self.assertEqual(planned["stickers"], [])
        self.assertFalse(decision["keep"])
        self.assertEqual(decision["reason"], "纯表情/装饰贴纸不直接服务剧情")

    def test_irrelevant_mouse_is_removed_from_study_scene(self):
        scene = {
            "scene_id": 4,
            "description": "猫看到补考试卷后开始翻书",
            "subtitle": "救命，这题我没见过",
            "stickers": [
                {
                    "category": "digital-communication",
                    "file": "/tmp/gaming-mouse.png",
                }
            ],
        }

        planned = apply_hyperframe_plan(scene)

        self.assertEqual(planned["stickers"], [])
        self.assertFalse(planned["composition_plan"]["overlays"][0]["keep"])

    def test_generated_prop_is_positioned_by_description(self):
        scene = {
            "scene_id": 5,
            "description": "猫在桌边假装刷手机",
            "subtitle": "我只是看一眼消息",
            "suggested_prop": "手机和手",
            "generated_assets": [
                {
                    "type": "道具缺失",
                    "file": "/tmp/generated_prop.png",
                    "description": "一只手拿着手机",
                    "prompt": "cartoon hand holding a phone",
                }
            ],
        }

        planned = apply_hyperframe_plan(scene)
        prop = planned["generated_assets"][0]

        self.assertEqual(prop["position"], "near_cat_paw_left")
        self.assertEqual(prop["composition_role"], "phone_hand")

    def test_plan_reports_safe_zones(self):
        plan = plan_scene_composition({"scene_id": 6, "description": "猫坐在桌前"})

        self.assertIn("subtitle_band", plan["safe_zones"])
        self.assertIn("cat_face", plan["safe_zones"])


if __name__ == "__main__":
    unittest.main()
