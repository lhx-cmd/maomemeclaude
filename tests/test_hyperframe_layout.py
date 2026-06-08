import unittest

from agent.hyperframe_layout import build_hyperframe_layout


class HyperframeLayoutTest(unittest.TestCase):
    def test_builds_topic_scene_caption_and_dialogue_cats(self):
        layout = build_hyperframe_layout(
            {
                "scene_id": 1,
                "description": "两只猫在宿舍讨论早八",
                "subtitle": "朋友：怎么又是早八啊！",
                "topic_caption": "大学期间和朋友的固定对话是：",
                "scene_caption": "早上起床",
                "dialogues": [
                    {"speaker": "我", "line": "怎么又是早八啊！", "motion_file": "/tmp/me.mp4"},
                    {"speaker": "朋友", "line": "已经上三天早八了！", "motion_file": "/tmp/friend.mp4"},
                ],
            },
            storyboard_title="大学早八",
            theme="大学生活",
        )

        self.assertEqual(layout["topic_caption"], "大学期间和朋友的固定对话是：")
        self.assertEqual(layout["scene_caption"], "*早上起床")
        self.assertEqual(len(layout["cat_instances"]), 2)
        self.assertEqual(layout["cat_instances"][0]["speaker"], "我")
        self.assertEqual(layout["cat_instances"][0]["speech"], "怎么又是早八啊！")
        self.assertEqual(layout["cat_instances"][0]["slot"], "left")
        self.assertEqual(layout["cat_instances"][1]["slot"], "right")

    def test_falls_back_to_single_cat_from_subtitle(self):
        layout = build_hyperframe_layout(
            {
                "scene_id": 2,
                "description": "猫看到试卷崩溃",
                "subtitle": "这题我真没见过",
            },
            storyboard_title="补考",
            theme="补考",
        )

        self.assertEqual(layout["topic_caption"], "补考")
        self.assertEqual(layout["scene_caption"], "*猫看到试卷崩溃")
        self.assertEqual(len(layout["cat_instances"]), 1)
        self.assertEqual(layout["cat_instances"][0]["speech"], "这题我真没见过")
        self.assertEqual(layout["cat_instances"][0]["slot"], "center")

    def test_limits_to_three_dialogue_cats(self):
        layout = build_hyperframe_layout(
            {
                "description": "三只猫开会",
                "dialogues": [
                    {"speaker": "A", "line": "一号发言", "motion_file": "/tmp/a.mp4"},
                    {"speaker": "B", "line": "二号发言", "motion_file": "/tmp/b.mp4"},
                    {"speaker": "C", "line": "三号发言", "motion_file": "/tmp/c.mp4"},
                    {"speaker": "D", "line": "四号发言", "motion_file": "/tmp/d.mp4"},
                ],
            },
            storyboard_title="开会",
            theme="打工人",
        )

        self.assertEqual([cat["slot"] for cat in layout["cat_instances"]], ["left", "center", "right"])
        self.assertEqual([cat["speaker"] for cat in layout["cat_instances"]], ["A", "B", "C"])

    def test_collapses_duplicate_motion_dialogues_to_single_cat(self):
        layout = build_hyperframe_layout(
            {
                "description": "闹钟催我起床",
                "dialogues": [
                    {"speaker": "我", "line": "再睡五分钟就起", "motion_file": "/tmp/same.mp4"},
                    {"speaker": "闹钟", "line": "你再不起就迟到了", "motion_file": "/tmp/same.mp4"},
                ],
            },
            storyboard_title="周一谁懂",
            theme="周一",
        )

        self.assertEqual(len(layout["cat_instances"]), 1)
        self.assertEqual(layout["cat_instances"][0]["slot"], "center")

    def test_scene_caption_is_shortened_for_star_text(self):
        layout = build_hyperframe_layout(
            {
                "description": "周一早上闹钟响了N次，你埋在枕头里死活不想起，疯狂拖延赖床",
                "scene_caption": "周一早上闹钟响了N次，你埋在枕头里死活不想起，疯狂拖延赖床",
                "subtitle": "五分钟过去了我还在床上",
            },
            storyboard_title="周一谁懂",
            theme="周一",
        )

        self.assertEqual(layout["scene_caption"], "*周一早上闹钟响了N次")
        self.assertLessEqual(len(layout["scene_caption"]), 13)


if __name__ == "__main__":
    unittest.main()
