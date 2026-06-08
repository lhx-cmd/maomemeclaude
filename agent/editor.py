"""自然语言编辑 — 根据用户指令调整分镜脚本"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .config import config
from .doubao_client import client
from .material_matcher import match_cat_motion, match_stickers
from .gap_detector import detect_gaps
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
7. **改猫动作**: 替换某个镜头的猫动作素材
8. **改结尾**: 调整CTA或收束方式

请分析用户的指令，返回JSON格式的修改方案：
```json
{
  "intent": "change_hook | reorder | adjust_subtitle | adjust_rhythm | change_emotion | change_sticker | change_motion | change_ending | mixed",
  "explanation": "对用户意图的理解",
  "modifications": [
    {
      "scene_id": 1,
      "action": "modify | insert | delete | swap",
      "field": "...",
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
    # 构建当前分镜的文本表示
    scenes_summary = []
    for s in current_storyboard.get("scenes", []):
        scenes_summary.append(
            f"镜{s['scene_id']}[{s.get('duration', 0)}s]: "
            f"{s.get('description', '')} | "
            f"情绪: {s.get('emotion', '')} | "
            f"字幕: {s.get('subtitle', '')} | "
            f"猫动作: motion#{s.get('cat_motion_id', '?')} | "
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
    if field == "subtitle" or field == "subtitle_text":
        scene["subtitle"] = new_value
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

    scene["_modified"] = True


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
