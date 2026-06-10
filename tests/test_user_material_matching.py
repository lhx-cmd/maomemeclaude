import unittest

from agent.material_matcher import match_user_materials


class UserMaterialMatchingTest(unittest.TestCase):
    def test_matches_office_background_and_coffee_prop(self):
        matches = match_user_materials(
            {
                "description": "猫坐在办公室工位，同事递来咖啡",
                "suggested_background": "办公室工位",
                "suggested_prop": "咖啡杯",
            },
            ["/tmp/office_background.png", "/tmp/coffee_cup.png"],
        )

        self.assertIn({
            "kind": "background",
            "file": "/tmp/office_background.png",
            "source": "user",
            "reason": "文件名与背景/场景语义匹配",
        }, matches)
        self.assertIn({
            "kind": "prop",
            "file": "/tmp/coffee_cup.png",
            "source": "user",
            "reason": "文件名与道具语义匹配",
        }, matches)

    def test_treats_uploaded_video_as_cat_motion_even_without_semantic_filename(self):
        matches = match_user_materials(
            {
                "description": "猫站在办公室里吐槽迟到",
                "subtitle": "今天又迟到了",
            },
            ["/tmp/session_mat_mp4"],
        )

        self.assertIn({
            "kind": "cat_motion",
            "file": "/tmp/session_mat_mp4",
            "source": "user",
            "reason": "用户上传视频优先作为猫动作素材",
        }, matches)

    def test_uses_visual_index_to_choose_best_uploaded_cat_motion(self):
        matches = match_user_materials(
            {
                "description": "男主猫骑着摩托在路上堵车，满脸焦急",
                "subtitle": "完了完了要迟到了",
                "emotion": "焦虑慌乱",
            },
            ["/tmp/cute_talk.mp4", "/tmp/anxious_road.mp4"],
            {
                "materials": [
                    {
                        "file": "/tmp/cute_talk.mp4",
                        "type": "video",
                        "asset_kind": "cat_motion",
                        "description": "猫撒娇卖萌，适合恋爱聊天",
                        "motion_tags": {
                            "actions": ["撒娇", "聊天"],
                            "emotions": ["可爱", "放松"],
                            "contexts": ["恋爱"],
                        },
                    },
                    {
                        "file": "/tmp/anxious_road.mp4",
                        "type": "video",
                        "asset_kind": "cat_motion",
                        "description": "猫慌张赶路，左右张望，适合迟到、堵车、骑车赶路剧情",
                        "motion_tags": {
                            "actions": ["赶路", "左右张望"],
                            "emotions": ["焦虑", "慌张"],
                            "contexts": ["迟到", "堵车", "骑车"],
                        },
                    },
                ]
            },
        )

        cat_matches = [match for match in matches if match["kind"] == "cat_motion"]
        self.assertEqual(cat_matches[0]["file"], "/tmp/anxious_road.mp4")
        self.assertIn("视觉描述匹配", cat_matches[0]["reason"])


if __name__ == "__main__":
    unittest.main()
