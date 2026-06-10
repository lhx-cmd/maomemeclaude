"""Audio asset library for cat meme source clips."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .config import config
from .utils import load_json, save_json


AUDIO_ASSET_KIND = "cat_motion_audio"
AUDIO_SUBDIR = Path("audio") / "cat-motions"


def rebuild_cat_motion_audio_index(force: bool = False) -> dict[str, Any]:
    """Extract audio tracks from cat motion videos and rebuild the index."""
    audio_dir = _audio_dir()
    audio_dir.mkdir(parents=True, exist_ok=True)

    descriptions = _load_motion_descriptions()
    assets: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for motion_id, meta in _sorted_motion_items(descriptions):
        source_video = config.cat_motions_dir / f"{motion_id}.mp4"
        if not source_video.exists():
            errors.append({
                "source_motion_id": motion_id,
                "source_video": str(source_video),
                "error": "source video not found",
            })
            continue

        try:
            stream_info = _probe_audio_stream(source_video)
        except Exception as exc:
            errors.append({
                "source_motion_id": motion_id,
                "source_video": str(source_video),
                "error": f"ffprobe failed: {exc}",
            })
            continue

        if not stream_info:
            errors.append({
                "source_motion_id": motion_id,
                "source_video": str(source_video),
                "error": "no audio stream",
            })
            continue

        audio_file = audio_dir / f"cat_motion_{motion_id}.m4a"
        if force or not audio_file.exists():
            try:
                _extract_audio_track(source_video, audio_file)
            except Exception as exc:
                errors.append({
                    "source_motion_id": motion_id,
                    "source_video": str(source_video),
                    "error": f"ffmpeg extract failed: {exc}",
                })
                continue

        motion_tags = _motion_tags(meta)
        assets.append({
            "file": str(audio_file),
            "source_video": str(source_video),
            "source_motion_id": motion_id,
            "description": str(meta.get("description", "")).strip(),
            "duration_seconds": stream_info.get("duration_seconds"),
            "codec_name": stream_info.get("codec_name", ""),
            "sample_rate": stream_info.get("sample_rate"),
            "channels": stream_info.get("channels"),
            "tags": _unique_list(
                motion_tags.get("actions", [])
                + motion_tags.get("emotions", [])
                + motion_tags.get("contexts", [])
            ),
            "actions": _unique_list(motion_tags.get("actions", [])),
            "emotions": _unique_list(motion_tags.get("emotions", [])),
            "use_cases": _unique_list(motion_tags.get("contexts", [])),
            "avoid": _unique_list(motion_tags.get("avoid", [])),
        })

    assets.sort(key=lambda item: int(str(item["source_motion_id"])))
    index = {
        "asset_kind": AUDIO_ASSET_KIND,
        "folder": str(audio_dir),
        "source_folder": str(config.cat_motions_dir),
        "count": len(assets),
        "assets": assets,
    }
    if errors:
        index["errors"] = errors
    save_json(_index_path(), index)
    return index


def audio_asset_index_context(limit: int = 30) -> str:
    """Return a compact audio asset summary suitable for model prompts."""
    assets = _load_index_assets()
    if not assets:
        try:
            assets = rebuild_cat_motion_audio_index().get("assets", [])
        except Exception:
            assets = []
    if not assets:
        return ""

    lines = ["## 猫 meme 原声音频素材库（可复用，按剧情、情绪和场景选择）"]
    for item in assets[:limit]:
        tags = "、".join(str(tag) for tag in item.get("tags", [])[:6])
        use_cases = "、".join(str(tag) for tag in item.get("use_cases", [])[:5])
        duration = item.get("duration_seconds")
        duration_text = f"{duration:.2f}s" if isinstance(duration, (int, float)) else ""
        lines.append(
            f"- motion#{item.get('source_motion_id')} {duration_text}: "
            f"{item.get('description', '')} "
            f"[标签: {tags}] [适用: {use_cases}] 文件: {item.get('file', '')}"
        )
    return "\n".join(lines)


def _audio_dir() -> Path:
    return config.assets_root / AUDIO_SUBDIR


def _index_path() -> Path:
    return _audio_dir() / "index.json"


def _load_index_assets() -> list[dict[str, Any]]:
    try:
        index = load_json(_index_path())
    except Exception:
        return []
    if not isinstance(index, dict):
        return []
    if index.get("asset_kind") != AUDIO_ASSET_KIND:
        return []
    assets = index.get("assets", [])
    return assets if isinstance(assets, list) else []


def _load_motion_descriptions() -> dict[str, Any]:
    try:
        descriptions = load_json(config.cat_motions_dir / "descriptions.json")
    except Exception:
        return {}
    return descriptions if isinstance(descriptions, dict) else {}


def _sorted_motion_items(descriptions: dict[str, Any]):
    def sort_key(item):
        key = str(item[0])
        return int(key) if key.isdigit() else key

    for motion_id, meta in sorted(descriptions.items(), key=sort_key):
        yield str(motion_id), meta if isinstance(meta, dict) else {}


def _motion_tags(meta: dict[str, Any]) -> dict[str, list[str]]:
    tags = meta.get("motion_tags", {})
    if not isinstance(tags, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for key, value in tags.items():
        if isinstance(value, list):
            normalized[key] = [str(item) for item in value if str(item).strip()]
    return normalized


def _unique_list(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _probe_audio_stream(video_path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate,channels,duration",
        "-of", "json",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    if not streams:
        return {}
    stream = streams[0]
    duration = _float_or_none(stream.get("duration"))
    return {
        "codec_name": str(stream.get("codec_name", "")),
        "sample_rate": _int_or_none(stream.get("sample_rate")),
        "channels": _int_or_none(stream.get("channels")),
        "duration_seconds": duration,
    }


def _extract_audio_track(source_video: Path, target_audio: Path) -> None:
    target_audio.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(source_video),
        "-vn",
        "-map", "0:a:0",
        "-c:a", "aac",
        "-b:a", "128k",
        str(target_audio),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def _float_or_none(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _int_or_none(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
