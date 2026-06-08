"""HyperFrames-style scene layout helpers.

The layout is a small semantic layer: it turns storyboard fields into a stable
set of visual captions and cat instances that the FFmpeg compositor can render.
"""

from __future__ import annotations

from typing import Any


MAX_CAT_INSTANCES = 3
MAX_SCENE_CAPTION_CHARS = 12


def build_hyperframe_layout(
    scene: dict[str, Any],
    storyboard_title: str = "",
    theme: str = "",
) -> dict[str, Any]:
    """Build rich caption and multi-cat layout data for a scene."""
    topic_caption = _clean_text(
        scene.get("topic_caption")
        or scene.get("video_topic")
        or scene.get("script_title")
        or storyboard_title
        or theme
    )
    scene_caption = _normalize_scene_caption(
        scene.get("scene_caption") or scene.get("frame_caption") or scene.get("description", "")
    )
    dialogues = _normalize_dialogues(scene)
    cat_instances = _build_cat_instances(dialogues)

    return {
        "topic_caption": topic_caption,
        "scene_caption": scene_caption,
        "cat_instances": cat_instances,
    }


def _normalize_dialogues(scene: dict[str, Any]) -> list[dict[str, str]]:
    raw_dialogues = scene.get("dialogues") or scene.get("dialogue") or []
    if isinstance(raw_dialogues, dict):
        raw_dialogues = [raw_dialogues]
    if not isinstance(raw_dialogues, list):
        raw_dialogues = []

    dialogues: list[dict[str, str]] = []
    for item in raw_dialogues:
        motion_id = ""
        motion_file = ""
        motion_desc = ""
        if isinstance(item, str):
            speaker, line = _split_speaker_line(item)
        elif isinstance(item, dict):
            speaker = _clean_text(item.get("speaker") or item.get("name") or item.get("role") or "猫")
            line = _clean_text(item.get("line") or item.get("text") or item.get("speech") or "")
            motion_id = _clean_text(item.get("motion_id"))
            motion_file = _clean_text(item.get("motion_file"))
            motion_desc = _clean_text(item.get("motion_desc"))
        else:
            continue
        if line:
            dialogue = {"speaker": speaker or "猫", "line": line}
            if motion_id:
                dialogue["motion_id"] = motion_id
            if motion_file:
                dialogue["motion_file"] = motion_file
            if motion_desc:
                dialogue["motion_desc"] = motion_desc
            dialogues.append(dialogue)
        if len(dialogues) >= MAX_CAT_INSTANCES:
            break

    if not dialogues:
        subtitle = _clean_text(scene.get("subtitle") or scene.get("subtitle_text") or "")
        if subtitle:
            speaker, line = _split_speaker_line(subtitle)
            dialogues.append({"speaker": speaker or "猫", "line": line})

    if not dialogues:
        dialogues.append({"speaker": "猫", "line": ""})
    return _collapse_duplicate_motion_dialogues(dialogues[:MAX_CAT_INSTANCES])


def _build_cat_instances(dialogues: list[dict[str, str]]) -> list[dict[str, str]]:
    slots_by_count = {
        1: ["center"],
        2: ["left", "right"],
        3: ["left", "center", "right"],
    }
    slots = slots_by_count.get(len(dialogues), ["center"])
    instances = []
    for index, dialogue in enumerate(dialogues):
        instances.append({
            "speaker": dialogue.get("speaker", "猫"),
            "speech": dialogue.get("line", ""),
            "slot": slots[index],
            "motion_id": dialogue.get("motion_id", ""),
            "motion_file": dialogue.get("motion_file", ""),
            "motion_desc": dialogue.get("motion_desc", ""),
        })
    return instances


def _normalize_scene_caption(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    text = text[1:].strip() if text.startswith("*") else text
    text = _shorten_scene_caption(text)
    return f"*{text}" if text else ""


def _collapse_duplicate_motion_dialogues(dialogues: list[dict[str, str]]) -> list[dict[str, str]]:
    """Avoid rendering multiple identical cats when role motions are missing or duplicated."""
    if len(dialogues) <= 1:
        return dialogues

    motion_keys = [_dialogue_motion_key(dialogue) for dialogue in dialogues]
    if any(not key for key in motion_keys):
        return [dialogues[0]]
    if len(set(motion_keys)) < len(motion_keys):
        return [dialogues[0]]
    return dialogues


def _dialogue_motion_key(dialogue: dict[str, str]) -> str:
    motion_file = _clean_text(dialogue.get("motion_file"))
    if motion_file:
        return f"file:{motion_file}"
    return ""


def _shorten_scene_caption(text: str) -> str:
    text = _clean_text(text)
    for sep in ("，", "。", "；", ",", ";", "！", "!", "？", "?"):
        if sep in text:
            candidate = text.split(sep, 1)[0].strip()
            if candidate:
                text = candidate
                break
    return text[:MAX_SCENE_CAPTION_CHARS].strip()


def _split_speaker_line(text: str) -> tuple[str, str]:
    text = _clean_text(text)
    for sep in ("：", ":"):
        if sep in text:
            speaker, _, line = text.partition(sep)
            if line.strip():
                return _clean_text(speaker), _clean_text(line)
    return "", text


def _clean_text(value: Any) -> str:
    return str(value or "").strip()
