import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import video_composer


class VideoComposerPlanTest(unittest.TestCase):
    def test_render_plan_keys_green_screen_over_background_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            motion = tmp_path / "motion.mp4"
            background = tmp_path / "background.png"
            sticker = tmp_path / "phone.png"
            motion.touch()
            background.touch()
            sticker.touch()

            scene = {
                "scene_id": 1,
                "generated_assets": [{"type": "背景缺失", "file": str(background)}],
                "stickers": [{"category": "emotion-effects", "file": str(sticker)}],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(motion),
                duration=2.0,
                font="/tmp/font.ttf",
                has_audio=False,
                scene_index=0,
            )

            self.assertIn(str(background), plan.input_paths)
            self.assertIn("colorkey=0x01d900", plan.filter_complex)
            self.assertNotIn("geq=", plan.filter_complex)
            self.assertIn("overlay=(W-w)/2:(H-h)/2", plan.filter_complex)
            self.assertIn("crop=1920:1080", plan.filter_complex)

    def test_render_plan_uses_explicit_sticker_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            motion = tmp_path / "motion.mp4"
            sticker = tmp_path / "sticker.png"
            motion.touch()
            sticker.touch()

            scene = {
                "scene_id": 1,
                "stickers": [
                    {
                        "category": "user_requested",
                        "file": str(sticker),
                        "position": "top_right",
                        "scale": 220,
                    }
                ],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(motion),
                duration=2.0,
                font="/tmp/font.ttf",
                has_audio=False,
                scene_index=0,
            )

            self.assertIn("scale=220:-1", plan.filter_complex)
            self.assertIn("overlay=W-w-80:160", plan.filter_complex)

    def test_render_plan_uses_user_prop_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            motion = tmp_path / "motion.mp4"
            prop = tmp_path / "coffee_cup.png"
            motion.touch()
            prop.touch()

            scene = {
                "scene_id": 1,
                "generated_assets": [
                    {
                        "type": "用户道具",
                        "kind": "prop",
                        "source": "user",
                        "file": str(prop),
                        "position": "desk_left",
                        "scale": 180,
                    }
                ],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(motion),
                duration=2.0,
                font="/tmp/font.ttf",
                has_audio=False,
                scene_index=0,
            )

            self.assertIn(str(prop), plan.input_paths)
            self.assertIn("overlay=260:H-h-320", plan.filter_complex)

    def test_render_plan_skips_decorative_expression_stickers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            motion = tmp_path / "motion.mp4"
            sticker = tmp_path / "021-eyes.png"
            motion.touch()
            sticker.touch()

            scene = {
                "scene_id": 1,
                "stickers": [
                    {
                        "category": "emotion-effects",
                        "file": str(sticker),
                        "position": "top_left",
                        "scale": 220,
                    }
                ],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(motion),
                duration=2.0,
                font="/tmp/font.ttf",
                has_audio=False,
                scene_index=0,
            )

            self.assertNotIn(str(sticker), plan.input_paths)
            self.assertNotIn("overlay=80:160", plan.filter_complex)

    def test_render_plan_places_story_phone_near_cat_paw(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            motion = tmp_path / "motion.mp4"
            sticker = tmp_path / "phone.png"
            motion.touch()
            sticker.touch()

            scene = {
                "scene_id": 1,
                "description": "猫趴在桌边玩手机",
                "subtitle": "同事消息疯狂@我",
                "stickers": [
                    {
                        "category": "digital-communication",
                        "file": str(sticker),
                    }
                ],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(motion),
                duration=2.0,
                font="/tmp/font.ttf",
                has_audio=False,
                scene_index=0,
            )

            self.assertIn("scale=180:-1", plan.filter_complex)
            self.assertIn("overlay=(W-w)/2-320:H-h-300", plan.filter_complex)

    def test_render_plan_draws_hyperframe_captions_and_multiple_cats(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            motion = tmp_path / "motion.mp4"
            motion.touch()

            scene = {
                "scene_id": 1,
                "description": "两只猫在宿舍讨论早八",
                "topic_caption": "大学期间和朋友的固定对话是：",
                "scene_caption": "早上起床",
                "subtitle": "朋友",
                "dialogues": [
                    {"speaker": "我", "line": "怎么又是早八啊！", "motion_file": str(motion)},
                    {"speaker": "朋友", "line": "已经上三天早八了！", "motion_file": str(motion)},
                ],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(motion),
                duration=2.0,
                font="/tmp/font.ttf",
                has_audio=False,
                scene_index=0,
            )

            self.assertIn("drawbox=x=88:y=24", plan.filter_complex)
            self.assertIn("大学期间和朋友的固定对话是", plan.filter_complex)
            self.assertIn("*早上起床", plan.filter_complex)
            self.assertIn("怎么又是早八啊", plan.filter_complex)
            self.assertNotIn("已经上三天早八了", plan.filter_complex)
            self.assertNotIn("[cat_keyed]split=2[cat_keyed_src0][cat_keyed_src1]", plan.filter_complex)
            self.assertIn("overlay=(W-w)/2:(H-h)/2", plan.filter_complex)

    def test_render_plan_does_not_split_duplicate_dialogue_motion(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            motion = tmp_path / "motion.mp4"
            motion.touch()

            scene = {
                "scene_id": 1,
                "description": "我和闹钟对话但模型给了同一个素材",
                "dialogues": [
                    {"speaker": "我", "line": "再睡五分钟", "motion_file": str(motion)},
                    {"speaker": "闹钟", "line": "你要迟到了", "motion_file": str(motion)},
                ],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(motion),
                duration=2.0,
                font="/tmp/font.ttf",
                has_audio=False,
                scene_index=0,
            )

            self.assertNotIn("split=2", plan.filter_complex)
            self.assertNotIn("你要迟到了", plan.filter_complex)
            self.assertIn("overlay=(W-w)/2:(H-h)/2", plan.filter_complex)

    def test_render_plan_does_not_split_when_role_motion_files_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            motion = tmp_path / "motion.mp4"
            missing_a = tmp_path / "missing-a.mp4"
            missing_b = tmp_path / "missing-b.mp4"
            motion.touch()

            scene = {
                "scene_id": 1,
                "description": "模型给了两个不存在的角色素材",
                "dialogues": [
                    {"speaker": "我", "line": "再睡五分钟", "motion_file": str(missing_a)},
                    {"speaker": "闹钟", "line": "你要迟到了", "motion_file": str(missing_b)},
                ],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(motion),
                duration=2.0,
                font="/tmp/font.ttf",
                has_audio=False,
                scene_index=0,
            )

            self.assertNotIn("split=2", plan.filter_complex)
            self.assertNotIn("你要迟到了", plan.filter_complex)
            self.assertIn("overlay=(W-w)/2:(H-h)/2", plan.filter_complex)

    def test_multi_cat_roles_use_large_compact_motion_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self_motion = tmp_path / "self.mp4"
            coworker_motion = tmp_path / "coworker.mp4"
            self_motion.touch()
            coworker_motion.touch()

            scene = {
                "scene_id": 1,
                "description": "同事递咖啡，两只猫互动",
                "dialogues": [
                    {"speaker": "同事", "line": "给你带了冰美式", "motion_file": str(coworker_motion)},
                    {"speaker": "我", "line": "你是我的神", "motion_file": str(self_motion)},
                ],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(self_motion),
                duration=2.0,
                font="/tmp/font.ttf",
                has_audio=False,
                scene_index=0,
            )

            self.assertIn("scale=900:-1", plan.filter_complex)
            self.assertIn("crop=iw*0.62:ih:iw*0.19:0,scale=900:-1", plan.filter_complex)
            self.assertIn("[cat_keyed_role0]", plan.filter_complex)

    def test_render_plan_honors_scene_audio_muted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            motion = tmp_path / "motion.mp4"
            motion.touch()

            scene = {
                "scene_id": 2,
                "audio_muted": True,
                "dialogues": [{"speaker": "我", "line": "这一镜不要原声", "motion_file": str(motion)}],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(motion),
                duration=2.0,
                font="/tmp/font.ttf",
                has_audio=True,
                scene_index=1,
            )

            self.assertIn("anullsrc=r=44100:cl=stereo:d=2.0[a0]", plan.filter_complex)
            self.assertNotIn("[0:a]atrim", plan.filter_complex)

    def test_render_plan_defaults_to_silence_even_when_motion_has_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            motion = tmp_path / "motion.mp4"
            motion.touch()

            scene = {
                "scene_id": 3,
                "dialogues": [{"speaker": "我", "line": "猫动作只当画面用", "motion_file": str(motion)}],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(motion),
                duration=2.0,
                font="/tmp/font.ttf",
                has_audio=True,
                scene_index=2,
            )

            self.assertIn("anullsrc=r=44100:cl=stereo:d=2.0[a0]", plan.filter_complex)
            self.assertNotIn("[0:a]atrim", plan.filter_complex)

    def test_render_plan_uses_motion_audio_only_when_explicitly_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            motion = tmp_path / "motion.mp4"
            motion.touch()

            scene = {
                "scene_id": 4,
                "use_motion_audio": True,
                "dialogues": [{"speaker": "我", "line": "这一镜显式保留原声", "motion_file": str(motion)}],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(motion),
                duration=2.0,
                font="/tmp/font.ttf",
                has_audio=True,
                scene_index=3,
            )

            self.assertIn("[0:a]atrim=0:2.0,asetpts=PTS-STARTPTS[a0]", plan.filter_complex)
            self.assertNotIn("anullsrc=r=44100:cl=stereo:d=2.0[a0]", plan.filter_complex)

    def test_render_plan_honors_left_cat_scale_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            left_motion = tmp_path / "left.mp4"
            right_motion = tmp_path / "right.mp4"
            left_motion.touch()
            right_motion.touch()

            scene = {
                "scene_id": 5,
                "cat_layout_overrides": {"left": {"scale_multiplier": 0.78}},
                "dialogues": [
                    {"speaker": "我", "line": "太大了", "motion_file": str(left_motion)},
                    {"speaker": "同事", "line": "缩小点", "motion_file": str(right_motion)},
                ],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(left_motion),
                duration=2.0,
                font="/tmp/font.ttf",
                has_audio=False,
                scene_index=4,
            )

            self.assertIn("crop=iw*0.62:ih:iw*0.19:0,scale=702:-1", plan.filter_complex)
            self.assertIn("crop=iw*0.62:ih:iw*0.19:0,scale=900:-1", plan.filter_complex)

    def test_render_plan_uses_distinct_motion_files_for_dialogue_cats(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self_motion = tmp_path / "self.mp4"
            boss_motion = tmp_path / "boss.mp4"
            self_motion.touch()
            boss_motion.touch()

            scene = {
                "scene_id": 1,
                "description": "领导突然派活",
                "topic_caption": "周一的我本人",
                "scene_caption": "领导突然@我",
                "dialogues": [
                    {"speaker": "我", "line": "不会又有活吧？", "motion_file": str(self_motion)},
                    {"speaker": "领导", "line": "这个项目这周必须上线", "motion_file": str(boss_motion)},
                ],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(self_motion),
                duration=2.0,
                font="/tmp/font.ttf",
                has_audio=False,
                scene_index=0,
            )

            self.assertIn(str(self_motion), plan.input_paths)
            self.assertIn(str(boss_motion), plan.input_paths)
            self.assertNotIn("split=2", plan.filter_complex)
            self.assertIn("[cat_keyed_role1]", plan.filter_complex)

    def test_render_plan_reuses_primary_motion_when_render_file_is_looped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            original_motion = tmp_path / "motion.mp4"
            looped_motion = tmp_path / "looped_6.mp4"
            original_motion.touch()
            looped_motion.touch()

            scene = {
                "scene_id": 7,
                "cat_motion_file": str(original_motion),
                "dialogues": [
                    {
                        "speaker": "我",
                        "line": "先喝杯奶茶缓一缓再说",
                        "motion_file": str(original_motion),
                    }
                ],
            }

            plan = video_composer._build_scene_plan(
                scene=scene,
                motion_file=str(looped_motion),
                duration=3.0,
                font="/tmp/font.ttf",
                has_audio=False,
                scene_index=6,
            )

            self.assertIn(str(looped_motion), plan.input_paths)
            self.assertNotIn(str(original_motion), plan.input_paths)
            self.assertNotIn("[cat_keyed_role0]", plan.filter_complex)
            self.assertIn("[bg][cat_keyed]overlay=(W-w)/2:(H-h)/2", plan.filter_complex)

    def test_ffmpeg_failure_log_includes_inputs_filter_and_stderr_tail(self):
        plan = video_composer.SceneRenderPlan(
            input_paths=["/tmp/bg.png", "/tmp/cat.mp4"],
            filter_complex="scale=1920:1080;" + ("x" * 2500) + "unconnected",
            video_label="[v_final]",
            audio_label="[a0]",
        )
        stderr = ("prefix " * 900) + "Filter colorkey output unconnected"

        message = video_composer._format_ffmpeg_failure_log(
            scene={"scene_id": 7},
            plan=plan,
            stderr=stderr,
        )

        self.assertIn("镜头7", message)
        self.assertIn("[0] /tmp/bg.png", message)
        self.assertIn("[1] /tmp/cat.mp4", message)
        self.assertIn("filter_complex_tail", message)
        self.assertIn("unconnected", message)

    @patch("agent.video_composer.subprocess.run")
    def test_concat_scenes_writes_faststart_mp4(self, run):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            scene_file = tmp_path / "scene_001.mp4"
            output_file = tmp_path / "final.mp4"
            scene_file.touch()

            video_composer._concat_scenes([scene_file], output_file)

        cmd = run.call_args.args[0]
        self.assertIn("-movflags", cmd)
        self.assertIn("+faststart", cmd)


if __name__ == "__main__":
    unittest.main()
