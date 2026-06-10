"""自然语言编辑 — 根据用户指令调整分镜脚本"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .config import config
from .doubao_client import client
from .material_matcher import match_cat_motion, match_stickers
from .gap_detector import detect_gaps
from .hyperframe_layout import build_hyperframe_layout
from .scene_tuner import choose_dialogue_motion_replacement
from .storyboard_generator import _build_sticker_item


# 自然语言编辑的系统提示词
EDIT_PROMPT = """你是一位视频分镜编辑助手。用户会给出自然语言指令来调整分镜脚本。

你需要理解用户的意图并返回具体的修改方案。支持的修改类型包括：

1. **改Hook**: 修改开头的吸引力方式
2. **调顺序**: 重新排列镜头顺序
3. **改字幕**: 修改字幕内容或密度
4. **改节奏**: 调整镜头时长和切换速度
5. **改情绪**: 调整某个镜头的情绪表达
6. **改贴纸**: 添加/删除/替换贴纸
7. **改猫动作**: 替换某个镜头的猫动作素材，或替换某个 dialogue 角色/左侧/右侧/中间猫的动作素材
8. **改结尾**: 调整CTA或收束方式
9. **改猫头台词**: 修改 dialogues 中某只猫的 line，或交换同一镜头内两只猫的 line
10. **改渲染控制**: 删除/静音某镜头音频；调整左/右/中间某只猫的画面大小

请分析用户的指令，返回JSON格式的修改方案：
```json
{
  "intent": "change_hook | reorder | adjust_subtitle | adjust_rhythm | change_emotion | change_sticker | change_motion | change_ending | mixed",
  "explanation": "对用户意图的理解",
  "modifications": [
    {
      "scene_id": 1,
      "action": "modify | insert | delete | swap",
      "field": "subtitle | description | duration | dialogues | swap_dialogue_lines | replace_dialogue_motion | audio_muted | cat_layout_overrides | ...",
      "old_value": "...",
      "new_value": "...",
      "reason": "..."
    }
  ]
}
```
"""


def parse_edit_intent(
    user_instruction: str,
    current_storyboard: dict,
) -> dict:
    """解析用户的自然语言编辑指令。

    Args:
        user_instruction: 用户的自然语言指令
        current_storyboard: 当前分镜脚本

    Returns:
        修改方案 JSON
    """
    deterministic_plan = _parse_deterministic_edit(user_instruction, current_storyboard)
    if deterministic_plan:
        return deterministic_plan

    # 构建当前分镜的文本表示
    scenes_summary = []
    for s in current_storyboard.get("scenes", []):
        dialogue_text = _format_dialogues_for_summary(s.get("dialogues", []))
        scenes_summary.append(
            f"镜{s['scene_id']}[{s.get('duration', 0)}s]: "
            f"{s.get('description', '')} | "
            f"情绪: {s.get('emotion', '')} | "
            f"字幕: {s.get('subtitle', '')} | "
            f"猫头台词: {dialogue_text or '无'} | "
            f"猫动作: motion#{s.get('cat_motion_id', '?')} | "
            f"音频: {'静音' if s.get('audio_muted') else '保留'} | "
            f"猫布局: {_format_cat_layout_overrides(s.get('cat_layout_overrides')) or '默认'} | "
            f"贴纸: {len(s.get('stickers', []))}个"
        )

    scenes_text = "\n".join(scenes_summary)

    user_message = f"""用户指令：{user_instruction}

当前分镜脚本：
{scenes_text}

请分析用户的修改意图并返回具体的修改方案。"""

    try:
        result = client.chat_json(
            system_prompt=EDIT_PROMPT,
            user_message=user_message,
            temperature=0.3,
            max_tokens=4096,
        )
        return result
    except Exception:
        # 回退：返回一个基本的修改方案
        return {
            "intent": "mixed",
            "explanation": f"理解用户意图: {user_instruction}",
            "modifications": [],
            "_fallback": True,
        }


def apply_edits(
    storyboard: dict,
    edit_plan: dict,
) -> dict:
    """将编辑方案应用到分镜脚本。

    Args:
        storyboard: 当前分镜脚本
        edit_plan: parse_edit_intent 返回的修改方案

    Returns:
        修改后的分镜脚本
    """
    scenes = storyboard.get("scenes", [])
    modifications = edit_plan.get("modifications", [])

    for mod in modifications:
        scene_id = mod.get("scene_id")
        action = mod.get("action", "modify")
        field = mod.get("field", "")
        new_value = mod.get("new_value", "")

        if action == "modify":
            scene = _find_scene(scenes, scene_id)
            if scene:
                _apply_field_change(scene, field, new_value)

        elif action == "insert":
            new_scene = {
                "scene_id": scene_id,
                "duration": mod.get("duration", 3),
                "description": new_value,
                "subtitle": mod.get("subtitle", ""),
                "emotion": mod.get("emotion", ""),
                "transition": "硬切",
                "cat_motion_id": None,
                "stickers": [],
                "generated_assets": [],
                "_inserted": True,
            }
            # 在指定位置插入
            insert_idx = next(
                (i for i, s in enumerate(scenes) if s["scene_id"] >= scene_id),
                len(scenes),
            )
            scenes.insert(insert_idx, new_scene)

        elif action == "delete":
            scenes = [s for s in scenes if s["scene_id"] != scene_id]

        elif action == "swap":
            target_id = mod.get("target_scene_id")
            if target_id:
                idx1 = next((i for i, s in enumerate(scenes) if s["scene_id"] == scene_id), None)
                idx2 = next((i for i, s in enumerate(scenes) if s["scene_id"] == target_id), None)
                if idx1 is not None and idx2 is not None:
                    scenes[idx1], scenes[idx2] = scenes[idx2], scenes[idx1]

    # 重新编号
    for i, s in enumerate(scenes, 1):
        s["scene_id"] = i

    # 重新匹配素材
    for scene in scenes:
        if scene.get("_inserted") or scene.get("_modified"):
            best_motion = match_cat_motion(
                scene_description=scene.get("description", ""),
                required_emotion=scene.get("emotion", ""),
            )
            if best_motion:
                scene["cat_motion_id"] = best_motion["motion_id"]
                scene["cat_motion_file"] = str(best_motion["file_path"])
                scene["cat_motion_desc"] = best_motion["description"]

            matched_stickers = match_stickers(
                scene_description=scene.get("description", ""),
                emotion=scene.get("emotion", ""),
                max_results=2,
            )
            scene["stickers"] = [
                _build_sticker_item(s, i, scene.get("sticker_position", ""))
                for i, s in enumerate(matched_stickers)
            ]

    # 更新元数据
    storyboard["scenes"] = scenes
    storyboard["scene_count"] = len(scenes)
    storyboard["total_duration"] = sum(s.get("duration", 0) for s in scenes)
    storyboard["gaps"] = detect_gaps(scenes)
    storyboard["_last_edit"] = {
        "instruction": edit_plan.get("explanation", ""),
        "modifications_count": len(modifications),
    }

    return storyboard


def _find_scene(scenes: list[dict], scene_id: int) -> Optional[dict]:
    """在分镜列表中查找指定ID的场景。"""
    for s in scenes:
        if s["scene_id"] == scene_id:
            return s
    return None


def _apply_field_change(scene: dict, field: str, new_value: str):
    """应用单个字段的修改。"""
    rematch_materials = True
    if field == "subtitle" or field == "subtitle_text":
        scene["subtitle"] = new_value
    elif field == "dialogues":
        if isinstance(new_value, list):
            scene["dialogues"] = new_value
        rematch_materials = False
    elif field == "swap_dialogue_lines":
        _swap_dialogue_lines(scene, new_value)
        rematch_materials = False
    elif field in ("audio_muted", "mute_audio", "remove_audio", "delete_audio"):
        scene["audio_muted"] = _coerce_bool(new_value, default=True)
        rematch_materials = False
    elif field in ("cat_layout_overrides", "cat_scale", "cat_instance_scale"):
        _merge_cat_layout_overrides(scene, new_value)
        rematch_materials = False
    elif field in ("replace_dialogue_motion", "dialogue_motion", "cat_role_motion"):
        _replace_dialogue_motion(scene, new_value)
        rematch_materials = False
    elif field == "emotion":
        scene["emotion"] = new_value
    elif field == "duration":
        try:
            scene["duration"] = int(new_value)
        except (ValueError, TypeError):
            pass
    elif field == "description":
        scene["description"] = new_value
    elif field == "cat_motion_id":
        scene["cat_motion_id"] = str(new_value)
        scene["cat_motion_file"] = str(config.cat_motions_dir / f"{new_value}.mp4")
    elif field == "transition":
        scene["transition"] = new_value
    elif field == "subtitle_style":
        scene["subtitle_style"] = new_value
    elif field == "add_sticker":
        scene.setdefault("stickers", []).append({
            "category": "user_requested",
            "file": new_value,
            "position": "top_right",
            "scale": 180,
        })
    elif field == "clear_stickers":
        scene["stickers"] = []

    if rematch_materials:
        scene["_modified"] = True


def _parse_deterministic_edit(user_instruction: str, storyboard: dict) -> dict | None:
    """Handle precise low-risk edits without asking the model."""
    instruction = str(user_instruction or "").strip()
    if not instruction:
        return None

    modifications = []
    explanations = []

    render_modifications = _parse_render_control_modifications(instruction, storyboard)
    if render_modifications:
        modifications.extend(render_modifications)
        explanations.append("调整音频/猫画面布局")

    dialogue_swap = _parse_dialogue_swap_modification(instruction, storyboard)
    if dialogue_swap:
        modifications.append(dialogue_swap)
        explanations.append(f"交换镜{dialogue_swap.get('scene_id')}两只猫的台词")

    motion_replacement = _parse_dialogue_motion_replacement_modification(instruction, storyboard)
    if motion_replacement:
        modifications.append(motion_replacement)
        explanations.append(f"更换镜{motion_replacement.get('scene_id')}{_slot_label(motion_replacement.get('new_value', {}).get('slot', ''))}猫动作")

    if not modifications:
        return None

    intent = "mixed" if len(modifications) > 1 else _intent_for_field(modifications[0].get("field"))
    return {
        "intent": intent,
        "explanation": "；".join(explanations) or "应用精确编辑",
        "modifications": modifications,
        "_deterministic": True,
    }


def _parse_dialogue_swap_modification(instruction: str, storyboard: dict) -> dict | None:
    if not _looks_like_dialogue_swap(instruction):
        return None
    scene = _resolve_dialogue_swap_scene(instruction, storyboard.get("scenes", []))
    if not scene:
        return None
    dialogues = [
        dialogue
        for dialogue in scene.get("dialogues", []) or []
        if isinstance(dialogue, dict) and str(dialogue.get("line") or "").strip()
    ]
    if len(dialogues) != 2:
        return None

    return {
        "scene_id": scene.get("scene_id"),
        "action": "modify",
        "field": "swap_dialogue_lines",
        "new_value": [0, 1],
        "reason": "用户要求互换两只猫的台词",
    }


def _parse_dialogue_motion_replacement_modification(instruction: str, storyboard: dict) -> dict | None:
    scenes = storyboard.get("scenes", []) or []
    scene_ids = {scene.get("scene_id") for scene in scenes if isinstance(scene, dict)}
    active_scene_id = None
    for clause in _split_instruction_clauses(instruction):
        scene_id = _extract_scene_id(clause)
        if scene_id is not None:
            active_scene_id = scene_id
        elif active_scene_id is not None:
            scene_id = active_scene_id
        if scene_id is None or (scene_ids and scene_id not in scene_ids):
            continue
        if not _looks_like_dialogue_motion_replacement(clause):
            continue
        slot = _extract_cat_slot(clause)
        if not slot:
            continue
        scene = _find_scene(scenes, scene_id)
        target = _dialogue_target_for_slot(scene, slot) if scene else None
        if not target:
            continue
        dialogue = target["dialogue"]
        return {
            "scene_id": scene_id,
            "action": "modify",
            "field": "replace_dialogue_motion",
            "new_value": {
                "slot": slot,
                "dialogue_index": target["dialogue_index"],
                "avoid_motion_id": str(dialogue.get("motion_id") or scene.get("cat_motion_id") or ""),
            },
            "reason": f"用户要求更换{_slot_label(slot)}那只猫的动作素材",
        }
    return None


def _looks_like_dialogue_motion_replacement(text: str) -> bool:
    if any(token in text for token in ("贴纸", "背景", "道具", "字幕", "标题", "台词", "对白")):
        return False
    has_replace = any(token in text for token in ("更换", "换掉", "换一个", "替换", "重新选", "重选", "不合适", "不适合", "选择不合适"))
    has_target = any(token in text for token in ("猫", "锚", "motion", "动作", "角色", "选择"))
    return has_replace and has_target


def _dialogue_target_for_slot(scene: dict, slot: str) -> dict | None:
    layout = build_hyperframe_layout(scene)
    for cat in layout.get("cat_instances", []) or []:
        if cat.get("slot") != slot:
            continue
        try:
            dialogue_index = int(cat.get("dialogue_index", -1))
        except (TypeError, ValueError):
            return None
        dialogues = scene.get("dialogues", []) or []
        if 0 <= dialogue_index < len(dialogues) and isinstance(dialogues[dialogue_index], dict):
            return {
                "dialogue_index": dialogue_index,
                "dialogue": dialogues[dialogue_index],
            }
    return None


def _looks_like_dialogue_swap(instruction: str) -> bool:
    text = instruction.lower()
    has_dialogue = any(token in text for token in ("台词", "对白", "话", "dialogue", "line"))
    has_swap = any(token in text for token in ("反了", "弄反", "说反", "换过来", "互换", "交换", "调换", "对调", "swap"))
    has_cat_pair = any(token in text for token in ("两只猫", "两个猫", "双猫", "两猫"))
    return has_dialogue and has_swap and has_cat_pair


def _resolve_dialogue_swap_scene(instruction: str, scenes: list[dict]) -> dict | None:
    explicit_scene_id = _extract_scene_id(instruction)
    if explicit_scene_id is not None:
        return _find_scene(scenes, explicit_scene_id)

    candidates = []
    for scene in scenes:
        dialogues = [
            dialogue
            for dialogue in scene.get("dialogues", []) or []
            if isinstance(dialogue, dict) and str(dialogue.get("line") or "").strip()
        ]
        if len(dialogues) == 2:
            candidates.append(scene)
    if len(candidates) == 1:
        return candidates[0]
    return None


def _extract_scene_id(text: str) -> int | None:
    patterns = (
        r"第\s*(\d+)\s*(?:镜|个分镜|段)",
        r"分镜\s*(\d+)",
        r"镜\s*(\d+)",
        r"scene\s*(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                return None
    return None


def _parse_render_control_modifications(instruction: str, storyboard: dict) -> list[dict]:
    scenes = storyboard.get("scenes", []) or []
    scene_ids = {scene.get("scene_id") for scene in scenes if isinstance(scene, dict)}
    modifications = []
    seen = set()

    active_scene_id = None
    for clause in _split_instruction_clauses(instruction):
        scene_id = _extract_scene_id(clause)
        if scene_id is not None:
            active_scene_id = scene_id
        elif active_scene_id is not None:
            scene_id = active_scene_id
        if scene_id is None or (scene_ids and scene_id not in scene_ids):
            continue

        if _looks_like_audio_mute(clause):
            key = (scene_id, "audio_muted")
            if key not in seen:
                modifications.append({
                    "scene_id": scene_id,
                    "action": "modify",
                    "field": "audio_muted",
                    "new_value": True,
                    "reason": "用户要求删除该分镜音频",
                })
                seen.add(key)

        slot = _extract_cat_slot(clause)
        scale_multiplier = _extract_cat_scale_multiplier(clause)
        if slot and scale_multiplier is not None:
            key = (scene_id, "cat_layout_overrides", slot)
            if key not in seen:
                modifications.append({
                    "scene_id": scene_id,
                    "action": "modify",
                    "field": "cat_layout_overrides",
                    "new_value": {slot: {"scale_multiplier": scale_multiplier}},
                    "reason": f"用户要求{_scale_action_label(scale_multiplier)}{_slot_label(slot)}那只猫",
                })
                seen.add(key)

    return modifications


def _split_instruction_clauses(instruction: str) -> list[str]:
    return [
        clause.strip()
        for clause in re.split(r"[，,。；;！!？?\n]+", instruction)
        if clause.strip()
    ]


def _looks_like_audio_mute(text: str) -> bool:
    has_audio = any(token in text for token in ("音频", "声音", "原声", "声轨"))
    has_mute = any(token in text for token in ("删除", "去掉", "去除", "不要", "静音", "关掉", "移除", "无声", "没声音"))
    return has_audio and has_mute


def _extract_cat_slot(text: str) -> str | None:
    if any(token in text for token in ("左边", "左侧", "左面", "左猫", "left")):
        return "left"
    if any(token in text for token in ("右边", "右侧", "右面", "右猫", "right")):
        return "right"
    if any(token in text for token in ("中间", "中间那只", "中间猫", "center", "middle")):
        return "center"
    return None


def _extract_cat_scale_multiplier(text: str) -> float | None:
    lower = text.lower()
    if any(token in lower for token in ("缩小", "小一点", "变小", "调小", "太大", "too big", "smaller")):
        return 0.78
    if any(token in lower for token in ("放大", "大一点", "变大", "调大", "太小", "too small", "larger")):
        return 1.18
    return None


def _slot_label(slot: str) -> str:
    return {
        "left": "左边",
        "right": "右边",
        "center": "中间",
    }.get(slot, slot)


def _scale_action_label(scale_multiplier: float) -> str:
    return "缩小" if scale_multiplier < 1 else "放大"


def _intent_for_field(field: str) -> str:
    if field == "audio_muted":
        return "adjust_audio"
    if field == "cat_layout_overrides":
        return "adjust_cat_layout"
    if field == "swap_dialogue_lines":
        return "swap_dialogue_lines"
    if field == "replace_dialogue_motion":
        return "replace_dialogue_motion"
    return "mixed"


def _coerce_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on", "静音", "删除", "去掉", "mute"}:
        return True
    if text in {"false", "0", "no", "n", "off", "保留", "恢复"}:
        return False
    return default


def _merge_cat_layout_overrides(scene: dict, value) -> None:
    override = _normalize_cat_layout_override(value)
    if not override:
        return
    current = scene.get("cat_layout_overrides")
    if not isinstance(current, dict):
        current = {}
    for slot, slot_override in override.items():
        existing = current.get(slot) if isinstance(current.get(slot), dict) else {}
        merged = dict(existing)
        merged.update(slot_override)
        current[slot] = merged
    scene["cat_layout_overrides"] = current


def _normalize_cat_layout_override(value) -> dict:
    if not isinstance(value, dict):
        return {}

    if value.get("slot"):
        slot = str(value.get("slot")).strip()
        normalized = _normalize_slot_override(value)
        return {slot: normalized} if slot and normalized else {}

    normalized = {}
    for slot in ("left", "right", "center"):
        slot_value = value.get(slot)
        if isinstance(slot_value, dict):
            slot_override = _normalize_slot_override(slot_value)
            if slot_override:
                normalized[slot] = slot_override
    return normalized


def _normalize_slot_override(value: dict) -> dict:
    result = {}
    if "scale_multiplier" in value:
        try:
            result["scale_multiplier"] = round(float(value["scale_multiplier"]), 2)
        except (TypeError, ValueError):
            pass
    elif "scale" in value:
        try:
            result["scale"] = int(value["scale"])
        except (TypeError, ValueError):
            pass
    return result


def _replace_dialogue_motion(scene: dict, value) -> None:
    if not isinstance(value, dict):
        return
    dialogues = scene.get("dialogues", []) or []
    try:
        dialogue_index = int(value.get("dialogue_index", -1))
    except (TypeError, ValueError):
        dialogue_index = -1
    if dialogue_index < 0 or dialogue_index >= len(dialogues):
        return
    dialogue = dialogues[dialogue_index]
    if not isinstance(dialogue, dict):
        return

    avoid_ids = set()
    if value.get("avoid_motion_id"):
        avoid_ids.add(str(value.get("avoid_motion_id")))
    for motion_id in value.get("avoid_motion_ids", []) if isinstance(value.get("avoid_motion_ids"), list) else []:
        if motion_id:
            avoid_ids.add(str(motion_id))

    if value.get("motion_id"):
        replacement = {
            "motion_id": str(value.get("motion_id")),
            "motion_file": str(value.get("motion_file") or config.cat_motions_dir / f"{value.get('motion_id')}.mp4"),
            "motion_desc": str(value.get("motion_desc") or ""),
            "reason": str(value.get("reason") or "用户指定替换猫动作"),
        }
    else:
        replacement = choose_dialogue_motion_replacement(
            scene=scene,
            target_dialogue=dialogue,
            target_slot=str(value.get("slot") or ""),
            avoid_motion_ids=avoid_ids,
        )
    if not replacement:
        return

    old_motion_id = str(dialogue.get("motion_id") or "")
    dialogue["motion_id"] = str(replacement.get("motion_id") or "")
    dialogue["motion_file"] = str(replacement.get("motion_file") or config.cat_motions_dir / f"{dialogue['motion_id']}.mp4")
    dialogue["motion_desc"] = str(replacement.get("motion_desc") or "")
    if replacement.get("reason"):
        dialogue["motion_reason"] = str(replacement.get("reason"))
    if scene.get("cat_motion_id") == old_motion_id and dialogue_index == 0:
        scene["cat_motion_id"] = dialogue["motion_id"]
        scene["cat_motion_file"] = dialogue["motion_file"]
        scene["cat_motion_desc"] = dialogue["motion_desc"]
    scene["_dialogue_modified"] = True


def _swap_dialogue_lines(scene: dict, value) -> None:
    dialogues = scene.get("dialogues", []) or []
    if len(dialogues) < 2:
        return
    try:
        left_index, right_index = list(value)[:2]
        left_index = int(left_index)
        right_index = int(right_index)
    except (TypeError, ValueError):
        left_index, right_index = 0, 1
    if left_index < 0 or right_index < 0:
        return
    if left_index >= len(dialogues) or right_index >= len(dialogues):
        return
    if not isinstance(dialogues[left_index], dict) or not isinstance(dialogues[right_index], dict):
        return
    left_line = dialogues[left_index].get("line", "")
    right_line = dialogues[right_index].get("line", "")
    dialogues[left_index]["line"] = right_line
    dialogues[right_index]["line"] = left_line
    scene["_dialogue_modified"] = True


def _format_dialogues_for_summary(dialogues) -> str:
    if not isinstance(dialogues, list):
        return ""
    parts = []
    for index, dialogue in enumerate(dialogues[:3], 1):
        if not isinstance(dialogue, dict):
            continue
        speaker = str(dialogue.get("speaker") or "猫").strip()
        line = str(dialogue.get("line") or "").strip()
        motion_id = str(dialogue.get("motion_id") or "").strip()
        if line:
            motion = f"/motion#{motion_id}" if motion_id else ""
            parts.append(f"{index}.{speaker}{motion}: {line}")
    return "；".join(parts)


def _format_cat_layout_overrides(overrides) -> str:
    if not isinstance(overrides, dict):
        return ""
    parts = []
    for slot in ("left", "center", "right"):
        value = overrides.get(slot)
        if not isinstance(value, dict):
            continue
        if "scale_multiplier" in value:
            parts.append(f"{_slot_label(slot)}x{value.get('scale_multiplier')}")
        elif "scale" in value:
            parts.append(f"{_slot_label(slot)}={value.get('scale')}")
    return "；".join(parts)


def format_edit_summary(edit_plan: dict, storyboard: dict) -> str:
    """格式化为可读的编辑摘要。"""
    explanation = edit_plan.get("explanation", "已应用修改")
    mods = edit_plan.get("modifications", [])
    scenes = storyboard.get("scenes", [])
    gaps = storyboard.get("gaps", {})

    lines = [f"✅ **已调整分镜**: {explanation}"]
    lines.append("")

    if mods:
        lines.append("**具体修改**:")
        for m in mods:
            action = m.get("action", "modify")
            scene_id = m.get("scene_id", "?")
            field = m.get("field", "")
            new_val = m.get("new_value", "")
            if action == "modify":
                lines.append(f"  - 镜{scene_id} {field}: → {new_val}")
            elif action == "insert":
                lines.append(f"  - 新增镜{scene_id}: {new_val}")
            elif action == "delete":
                lines.append(f"  - 删除镜{scene_id}")
            elif action == "swap":
                lines.append(f"  - 交换镜{scene_id}和镜{m.get('target_scene_id', '?')}")

    lines.append("")
    lines.append(f"**更新后**: {storyboard.get('scene_count', 0)}镜, "
                 f"{storyboard.get('total_duration', 0)}秒")

    if gaps.get("total_gaps", 0) > 0:
        lines.append(f"⚠️ 修改后产生{gaps['total_gaps']}个新素材缺口")

    return "\n".join(lines)
