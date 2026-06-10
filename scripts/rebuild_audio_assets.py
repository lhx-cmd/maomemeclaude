#!/usr/bin/env python3
"""Rebuild extracted cat-motion audio assets and their index."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.audio_asset_library import rebuild_cat_motion_audio_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract audio tracks from assets/cat-motions and rebuild assets/audio/cat-motions/index.json"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract audio files even when they already exist.",
    )
    args = parser.parse_args()

    index = rebuild_cat_motion_audio_index(force=args.force)
    print(
        f"Audio asset index rebuilt: {index['count']} assets -> "
        f"{Path(index['folder']) / 'index.json'}"
    )
    if index.get("errors"):
        print(f"Skipped {len(index['errors'])} source videos with errors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
