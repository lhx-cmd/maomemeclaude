import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import generated_asset_library
from agent.seedream_client import SeedreamClient
from agent.utils import save_json


class GeneratedAssetLibraryTest(unittest.TestCase):
    def test_builds_background_index_for_fast_browsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_generated_dir = generated_asset_library.config.generated_dir
            generated_asset_library.config.generated_dir = Path(tmp)
            try:
                bg = Path(tmp) / "backgrounds" / "office.png"
                bg.parent.mkdir(parents=True)
                bg.touch()
                save_json(bg.with_suffix(".meta.json"), {
                    "asset_kind": "background",
                    "description": "办公室工位角落",
                    "prompt": "office workstation background",
                    "size": "2560x1440",
                    "style": "16:9 cartoon",
                    "generated_at": "2026-06-08T11:00:00",
                })

                index = generated_asset_library.rebuild_asset_index("background")

                index_path = Path(tmp) / "backgrounds" / "index.json"
                self.assertTrue(index_path.exists())
                self.assertEqual(index["asset_kind"], "background")
                self.assertEqual(index["assets"][0]["file"], str(bg))
                self.assertEqual(index["assets"][0]["description"], "办公室工位角落")
            finally:
                generated_asset_library.config.generated_dir = old_generated_dir

    def test_background_reuse_reads_summary_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_generated_dir = generated_asset_library.config.generated_dir
            generated_asset_library.config.generated_dir = Path(tmp)
            try:
                bg = Path(tmp) / "backgrounds" / "office.png"
                bg.parent.mkdir(parents=True)
                bg.touch()
                save_json(bg.parent / "index.json", {
                    "asset_kind": "background",
                    "assets": [
                        {
                            "file": str(bg),
                            "description": "办公室工位角落",
                            "prompt": "office workstation background",
                            "size": "2560x1440",
                            "style": "16:9 cartoon",
                        }
                    ],
                })

                match = generated_asset_library.find_reusable_asset(
                    "background",
                    "办公室工位角落",
                    expected_size="2560x1440",
                )

                self.assertEqual(match, bg)
            finally:
                generated_asset_library.config.generated_dir = old_generated_dir

    def test_background_can_reuse_existing_asset_by_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_generated_dir = generated_asset_library.config.generated_dir
            generated_asset_library.config.generated_dir = Path(tmp)
            try:
                bg = Path(tmp) / "backgrounds" / "office.png"
                bg.parent.mkdir(parents=True)
                bg.touch()
                save_json(bg.with_suffix(".meta.json"), {
                    "asset_kind": "background",
                    "description": "办公室工位角落",
                    "prompt": "office workstation background",
                    "size": "2560x1440",
                })

                match = generated_asset_library.find_reusable_asset(
                    "background",
                    "办公室工位角落",
                    expected_size="2560x1440",
                )

                self.assertEqual(match, bg)
            finally:
                generated_asset_library.config.generated_dir = old_generated_dir

    def test_seedream_background_reuses_asset_without_api_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_generated_dir = generated_asset_library.config.generated_dir
            generated_asset_library.config.generated_dir = Path(tmp)
            try:
                bg = Path(tmp) / "backgrounds" / "office.png"
                bg.parent.mkdir(parents=True)
                bg.touch()
                save_json(bg.with_suffix(".meta.json"), {
                    "asset_kind": "background",
                    "description": "办公室工位角落",
                    "prompt": "office workstation background",
                    "size": "2560x1440",
                })

                client = SeedreamClient()
                with patch.object(client, "generate_and_save") as generate_and_save:
                    result = client.generate_background("办公室工位角落", "scene_1_bg")

                self.assertEqual(result, bg)
                generate_and_save.assert_not_called()
            finally:
                generated_asset_library.config.generated_dir = old_generated_dir

    def test_seedream_prop_reuses_existing_asset_by_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_generated_dir = generated_asset_library.config.generated_dir
            generated_asset_library.config.generated_dir = Path(tmp)
            try:
                prop = Path(tmp) / "props" / "phone.png"
                prop.parent.mkdir(parents=True)
                prop.touch()
                save_json(prop.with_suffix(".meta.json"), {
                    "asset_kind": "prop",
                    "description": "手机贴近猫爪",
                    "prompt": "phone near cat paw",
                    "size": "1920x1920",
                })

                client = SeedreamClient()
                with patch.object(client, "generate_and_save") as generate_and_save:
                    result = client.generate_prop("手机贴近猫爪", "scene_2_prop")

                self.assertEqual(result, prop)
                generate_and_save.assert_not_called()
            finally:
                generated_asset_library.config.generated_dir = old_generated_dir

    def test_seedream_sticker_writes_description_meta_for_future_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_generated_dir = generated_asset_library.config.generated_dir
            generated_asset_library.config.generated_dir = Path(tmp)
            try:
                client = SeedreamClient()
                expected = Path(tmp) / "stickers" / "generated" / "phone_hand.png"
                with patch.object(client, "generate", return_value=[{"b64_json": _tiny_png_b64()}]):
                    result = client.generate_sticker("手机和猫爪", "phone_hand")

                meta = generated_asset_library.load_asset_meta(result.with_suffix(".meta.json"))
                self.assertEqual(result, expected)
                self.assertEqual(meta["asset_kind"], "sticker")
                self.assertEqual(meta["description"], "手机和猫爪")
                self.assertEqual(meta["size"], "1920x1920")
            finally:
                generated_asset_library.config.generated_dir = old_generated_dir


def _tiny_png_b64() -> str:
    return (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
    )


if __name__ == "__main__":
    unittest.main()
