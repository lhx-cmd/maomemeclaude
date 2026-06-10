"""Local HyperFrames-style tools for precise one-scene tuning."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import config
from .utils import load_cat_motions


def choose_dialogue_motion_replacement(
    scene: dict[str, Any],
    target_dialogue: dict[str, Any],
    target_slot: str = "",
    avoid_motion_ids: Any = None,
    instruction: str = "",
) -> dict[str, str]:
    """Choose a replacement cat motion for one dialogue role.

    This is intentionally scoped to one rendered role, not the whole scene.
    """
    catalog = load_cat_motions()
    avoid = _normalize_avoid_ids(avoid_motion_ids)
    current_motion_id = str(target_dialogue.get("motion_id") or scene.get("cat_motion_id") or "").strip()
    if current_motion_id:
        avoid.add(current_motion_id)
    for dialogue in scene.get("dialogues", []) or []:
        if dialogue is target_dialogue:
            continue
        motion_id = str(dialogue.get("motion_id") or "").strip()
        if motion_id:
            avoid.add(motion_id)

    scored = []
    query = _role_query(scene, target_dialogue, target_slot, instruction)
    for motion_id, data in catalog.items():
        motion_id = str(motion_id)
        if motion_id in avoid or _is_unsuitable_motion(data):
            continue
        scored.append((_motion_score(query, data), motion_id, data))

    if not scored:
        return {}

    scored.sort(key=lambda item: (-item[0], _safe_int(item[1])))
    _, motion_id, data = scored[0]
    return {
        "motion_id": motion_id,
        "motion_file": str(config.cat_motions_dir / f"{motion_id}.mp4"),
        "motion_desc": str(data.get("description", "")),
        "reason": f"局部微调{_slot_label(target_slot)}角色动作",
    }


def _normalize_avoid_ids(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (str, int)):
        return {str(value)}
    if isinstance(value, dict):
        return {str(item) for item in value.values() if item}
    try:
        return {str(item) for item in value if item}
    except TypeError:
        return set()


def _role_query(
    scene: dict[str, Any],
    dialogue: dict[str, Any],
    target_slot: str,
    instruction: str,
) -> str:
    return " ".join(
        str(item or "")
        for item in (
            instruction,
            target_slot,
            scene.get("description"),
            scene.get("scene_caption"),
            scene.get("emotion"),
            dialogue.get("speaker"),
            dialogue.get("line"),
        )
    )


def _motion_score(query: str, data: dict[str, Any]) -> int:
    text = _motion_text(data)
    score = 0
    for token in _query_tokens(query):
        if token and token in text:
            score += 3
    cue_bonus = [
        (("领导", "老板", "开会", "任务", "kpi", "KPI"), ("叫嚷", "吐槽", "反驳", "晃头")),
        (("神游", "发呆", "左耳", "右耳", "摆烂", "没听"), ("冷漠", "松弛", "无语", "低电量", "装镇定")),
        (("崩溃", "破防", "哭", "压力"), ("崩溃", "大哭", "破防", "压力")),
        (("咖啡", "奶茶", "饮料", "治愈"), ("饮料", "奶茶", "咖啡", "放松", "治愈")),
    ]
    for query_cues, motion_cues in cue_bonus:
        if any(cue in query for cue in query_cues) and any(cue in text for cue in motion_cues):
            score += 12
    return score


def _motion_text(data: dict[str, Any]) -> str:
    tags = data.get("motion_tags", {})
    tag_text = " ".join(
        str(item)
        for values in tags.values()
        if isinstance(values, list)
        for item in values
    )
    return f"{data.get('description', '')} {tag_text}"


def _query_tokens(query: str) -> list[str]:
    tokens = []
    for token in ("领导", "老板", "开会", "任务", "KPI", "kpi", "神游", "发呆", "左耳", "右耳", "没听", "摆烂", "崩溃", "破防", "咖啡", "奶茶", "饮料"):
        if token in query:
            tokens.append(token)
    return tokens


def _is_unsuitable_motion(data: dict[str, Any]) -> bool:
    text = _motion_text(data)
    return any(token in text for token in ("非猫素材", "山羊", "小狗", "双猫", "两只猫", "画面中有两只猫", "多只猫"))


def _slot_label(slot: str) -> str:
    return {
        "left": "左侧",
        "right": "右侧",
        "center": "中间",
    }.get(slot, "")


def _safe_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 999999
