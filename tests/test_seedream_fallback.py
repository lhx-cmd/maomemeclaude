import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from agent import storyboard_generator


class SeedreamFallbackTest(unittest.TestCase):
    def test_background_gap_gets_local_fallback_when_seedream_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_generated_dir = storyboard_generator.config.generated_dir
            storyboard_generator.config.generated_dir = Path(tmp)
            try:
                scenes = [
                    {
                        "scene_id": 1,
                        "suggested_background": "办公室",
                        "generated_assets": [],
                    }
                ]
                gaps = {
                    "gaps": [
                        {
                            "scene_id": 1,
                            "gap_type": "背景缺失",
                            "fill_strategy": "AIGC生成",
                            "generation_prompt": "office background",
                        }
                    ]
                }

                with patch.object(
                    storyboard_generator.seedream,
                    "generate_background",
                    side_effect=RuntimeError("Seedream unavailable"),
                ):
                    result = storyboard_generator._auto_fill_gaps(scenes, gaps)

                asset = result[0]["generated_assets"][0]
                self.assertEqual(asset["type"], "背景缺失")
                self.assertTrue(asset["fallback"])
                self.assertTrue(Path(asset["file"]).exists())
                with Image.open(asset["file"]) as image:
                    self.assertEqual(image.size, (1920, 1080))
                self.assertNotIn("error", asset)
            finally:
                storyboard_generator.config.generated_dir = old_generated_dir

    def test_prop_gap_gets_local_fallback_when_seedream_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_generated_dir = storyboard_generator.config.generated_dir
            storyboard_generator.config.generated_dir = Path(tmp)
            try:
                scenes = [
                    {
                        "scene_id": 2,
                        "suggested_prop": "闹钟",
                        "generated_assets": [],
                    }
                ]
                gaps = {
                    "gaps": [
                        {
                            "scene_id": 2,
                            "gap_type": "道具缺失",
                            "fill_strategy": "AIGC生成",
                            "generation_prompt": "alarm prop",
                        }
                    ]
                }

                with patch.object(
                    storyboard_generator.seedream,
                    "generate_prop",
                    side_effect=RuntimeError("Seedream unavailable"),
                ):
                    result = storyboard_generator._auto_fill_gaps(scenes, gaps)

                asset = result[0]["generated_assets"][0]
                self.assertEqual(asset["type"], "道具缺失")
                self.assertTrue(asset["fallback"])
                self.assertTrue(Path(asset["file"]).exists())
                self.assertNotIn("error", asset)
            finally:
                storyboard_generator.config.generated_dir = old_generated_dir

    def test_duplicate_background_descriptions_reuse_one_seedream_asset(self):
        scenes = [
            {"scene_id": 1, "suggested_background": "办公室", "generated_assets": []},
            {"scene_id": 2, "suggested_background": "办公室", "generated_assets": []},
        ]
        gaps = {
            "gaps": [
                {
                    "scene_id": 1,
                    "gap_type": "背景缺失",
                    "fill_strategy": "AIGC生成",
                    "generation_prompt": "office background",
                },
                {
                    "scene_id": 2,
                    "gap_type": "背景缺失",
                    "fill_strategy": "AIGC生成",
                    "generation_prompt": "office background",
                },
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            asset_path = Path(tmp) / "office.png"
            asset_path.touch()
            with patch.object(
                storyboard_generator.seedream,
                "generate_background",
                return_value=asset_path,
            ) as generate_background:
                result = storyboard_generator._auto_fill_gaps(scenes, gaps)

        self.assertEqual(generate_background.call_count, 1)
        self.assertEqual(result[0]["generated_assets"][0]["file"], str(asset_path))
        self.assertEqual(result[1]["generated_assets"][0]["file"], str(asset_path))

    def test_aigc_gap_generation_uses_bounded_concurrency(self):
        old_workers = storyboard_generator.config.seedream_max_workers
        storyboard_generator.config.seedream_max_workers = 5
        active = 0
        max_active = 0
        lock = threading.Lock()

        def fake_generate_background(description, name):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            path = Path(tempfile.gettempdir()) / f"{name}.png"
            path.touch()
            return path

        scenes = [
            {"scene_id": i, "suggested_background": f"背景{i}", "generated_assets": []}
            for i in range(1, 5)
        ]
        gaps = {
            "gaps": [
                {
                    "scene_id": i,
                    "gap_type": "背景缺失",
                    "fill_strategy": "AIGC生成",
                    "generation_prompt": f"background {i}",
                }
                for i in range(1, 5)
            ]
        }

        try:
            with patch.object(
                storyboard_generator.seedream,
                "generate_background",
                side_effect=fake_generate_background,
            ):
                storyboard_generator._auto_fill_gaps(scenes, gaps)
        finally:
            storyboard_generator.config.seedream_max_workers = old_workers

        self.assertGreaterEqual(max_active, 4)
        self.assertLessEqual(max_active, 5)


if __name__ == "__main__":
    unittest.main()
