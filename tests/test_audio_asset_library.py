import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.utils import save_json


class AudioAssetLibraryTest(unittest.TestCase):
    def test_builds_cat_motion_audio_index_with_descriptions(self):
        from agent import audio_asset_library

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            old_assets_root = audio_asset_library.config.assets_root
            old_cat_motions_dir = audio_asset_library.config.cat_motions_dir
            audio_asset_library.config.assets_root = tmp_path / "assets"
            audio_asset_library.config.cat_motions_dir = tmp_path / "cat-motions"
            audio_asset_library.config.cat_motions_dir.mkdir(parents=True)
            motion_file = audio_asset_library.config.cat_motions_dir / "1.mp4"
            motion_file.touch()
            save_json(audio_asset_library.config.cat_motions_dir / "descriptions.json", {
                "1": {
                    "description": "蓝衣灰猫坐在笔记本电脑前反复敲键盘，表情木然。",
                    "motion_tags": {
                        "actions": ["敲电脑", "打字"],
                        "emotions": ["疲惫", "麻木"],
                        "contexts": ["办公", "职场"],
                        "avoid": ["温暖收束"],
                    },
                }
            })

            try:
                with patch.object(audio_asset_library, "_probe_audio_stream", return_value={
                    "duration_seconds": 2.5,
                    "codec_name": "aac",
                    "sample_rate": 44100,
                    "channels": 2,
                }), patch.object(audio_asset_library, "_extract_audio_track") as extract_audio:
                    extract_audio.side_effect = lambda source, target: target.touch()

                    index = audio_asset_library.rebuild_cat_motion_audio_index()

                index_path = tmp_path / "assets" / "audio" / "cat-motions" / "index.json"
                audio_file = tmp_path / "assets" / "audio" / "cat-motions" / "cat_motion_1.m4a"
                self.assertTrue(index_path.exists())
                self.assertTrue(audio_file.exists())
                self.assertEqual(index["asset_kind"], "cat_motion_audio")
                self.assertEqual(index["count"], 1)
                self.assertEqual(index["assets"][0]["source_motion_id"], "1")
                self.assertEqual(index["assets"][0]["file"], str(audio_file))
                self.assertEqual(index["assets"][0]["source_video"], str(motion_file))
                self.assertEqual(
                    index["assets"][0]["description"],
                    "蓝衣灰猫坐在笔记本电脑前反复敲键盘，表情木然。",
                )
                self.assertIn("敲电脑", index["assets"][0]["tags"])
                self.assertIn("职场", index["assets"][0]["use_cases"])
                extract_audio.assert_called_once_with(motion_file, audio_file)
            finally:
                audio_asset_library.config.assets_root = old_assets_root
                audio_asset_library.config.cat_motions_dir = old_cat_motions_dir

    def test_audio_index_context_is_model_readable(self):
        from agent import audio_asset_library

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            old_assets_root = audio_asset_library.config.assets_root
            audio_asset_library.config.assets_root = tmp_path / "assets"
            index_dir = tmp_path / "assets" / "audio" / "cat-motions"
            index_dir.mkdir(parents=True)
            audio_file = index_dir / "cat_motion_1.m4a"
            audio_file.touch()
            save_json(index_dir / "index.json", {
                "asset_kind": "cat_motion_audio",
                "assets": [
                    {
                        "file": str(audio_file),
                        "source_motion_id": "1",
                        "description": "蓝衣灰猫敲电脑，表情疲惫。",
                        "tags": ["敲电脑", "疲惫"],
                        "use_cases": ["办公", "职场"],
                        "duration_seconds": 2.5,
                    }
                ],
            })

            try:
                context = audio_asset_library.audio_asset_index_context()

                self.assertIn("猫 meme 原声音频素材库", context)
                self.assertIn("motion#1", context)
                self.assertIn("蓝衣灰猫敲电脑", context)
                self.assertIn(str(audio_file), context)
            finally:
                audio_asset_library.config.assets_root = old_assets_root


if __name__ == "__main__":
    unittest.main()
