import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import generated_asset_library
from agent.seedream_client import SeedreamClient


class SeedreamClientTest(unittest.TestCase):
    def test_background_uses_seedream_5_minimum_16_9_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_generated_dir = generated_asset_library.config.generated_dir
            generated_asset_library.config.generated_dir = Path(tmp)
            try:
                client = SeedreamClient()
                with patch.object(client, "generate_and_save") as generate_and_save:
                    client.generate_background("办公室", "bg")
            finally:
                generated_asset_library.config.generated_dir = old_generated_dir

        self.assertEqual(generate_and_save.call_args.kwargs["size"], "2560x1440")

    def test_prop_uses_seedream_5_minimum_square_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_generated_dir = generated_asset_library.config.generated_dir
            generated_asset_library.config.generated_dir = Path(tmp)
            try:
                client = SeedreamClient()
                with patch.object(client, "generate_and_save") as generate_and_save:
                    client.generate_prop("闹钟", "prop")
            finally:
                generated_asset_library.config.generated_dir = old_generated_dir

        self.assertEqual(generate_and_save.call_args.kwargs["size"], "1920x1920")

    def test_sticker_uses_seedream_5_minimum_square_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_generated_dir = generated_asset_library.config.generated_dir
            generated_asset_library.config.generated_dir = Path(tmp)
            try:
                client = SeedreamClient()
                with patch.object(client, "generate_and_save") as generate_and_save:
                    client.generate_sticker("口罩", "mask")
            finally:
                generated_asset_library.config.generated_dir = old_generated_dir

        self.assertEqual(generate_and_save.call_args.kwargs["size"], "1920x1920")


if __name__ == "__main__":
    unittest.main()
