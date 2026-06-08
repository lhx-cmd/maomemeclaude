"""Model-driven cat motion selection for multi-character meme scenes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import config
from .doubao_client import client
from .utils import load_cat_motions


CAT_ROLE_MOTION_PROMPT = """你是猫meme短视频的角色动作选角导演。你的任务是为每个镜头里的每个猫角色，从可用猫动作素材目录中选择最贴合角色身份、台词和当前剧情的 motion_id。

原则：
- 只能从提供的 motion_catalog 中选择 motion_id，不能编造。
- 根据 speaker、line、scene_description、scene_caption 判断角色当下应该是什么状态。
- 多角色同屏时，如果角色关系、台词功能或情绪不同，必须选择不同动作素材，让画面有交流感。
- 如果找不到足够不同的动作素材，宁可减少多角色同屏，不要复制同一只猫。
- 如果某个角色确实适合沿用主猫动作，可以选择 current_motion_id，但同一镜头内其他角色不能再选择这个 motion_id。
- motion_tags/actions 或描述里含“双猫/两只猫/画面中有两只猫”的素材，代表素材本身已经包含多只猫，不要分配给单个 dialogue 角色。
- 同一镜头内不要给多个 dialogue 角色选择同一个 motion_id。
- 不要输出解释文本之外的内容，只返回 JSON。

返回 JSON：
{
  "scenes": [
    {
      "scene_id": 1,
      "cat_roles": [
        {"dialogue_index": 0, "motion_id": "1", "reason": "选择原因"}
      ]
    }
  ]
}
"""


def assign_cat_role_motions(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach model-selected cat motion files to scene dialogues."""
    target_scenes = [
        scene for scene in scenes
        if len(scene.get("dialogues", []) or []) > 1
    ]
    if not target_scenes:
        return scenes

    catalog = load_cat_motions()
    try:
        review = client.chat_json(
            system_prompt=CAT_ROLE_MOTION_PROMPT,
            user_message=json.dumps(_build_payload(target_scenes, catalog), ensure_ascii=False),
            temperature=0.1,
            max_tokens=4096,
            timeout=120,
        )
    except Exception as e:
        print(f"   ⚠️ 角色猫动作AI选择失败，沿用主猫动作: {e}")
        return _fallback_assignments(scenes, catalog)

    decisions = review.get("scenes", []) if isinstance(review, dict) else []
    return apply_cat_role_decisions(scenes, decisions, catalog)


def apply_cat_role_decisions(
    scenes: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    catalog: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Apply model role-motion decisions with duplicate and multi-cat safeguards."""
    if catalog is None:
        catalog = load_cat_motions()
    scenes_by_id = {scene.get("scene_id"): scene for scene in scenes}
    valid_motion_ids = {
        motion_id
        for motion_id in catalog.keys()
        if not _is_multi_cat_motion(motion_id, catalog)
    }
    for decision in decisions:
        scene = scenes_by_id.get(decision.get("scene_id"))
        if not scene:
            continue
        dialogues = scene.get("dialogues", []) or []
        used_motion_ids: set[str] = set()
        for role in decision.get("cat_roles", []):
            try:
                dialogue_index = int(role.get("dialogue_index", -1))
            except (TypeError, ValueError):
                continue
            if dialogue_index < 0 or dialogue_index >= len(dialogues):
                continue
            motion_id = str(role.get("motion_id", "")).strip()
            if motion_id not in valid_motion_ids:
                motion_id = _choose_replacement_motion(
                    scene=scene,
                    dialogue=dialogues[dialogue_index],
                    catalog=catalog,
                    used_motion_ids=used_motion_ids,
                )
            elif motion_id in used_motion_ids:
                motion_id = _choose_replacement_motion(
                    scene=scene,
                    dialogue=dialogues[dialogue_index],
                    catalog=catalog,
                    used_motion_ids=used_motion_ids,
                )
            if not motion_id:
                continue
            _attach_motion(dialogues[dialogue_index], motion_id, catalog, role.get("reason", ""))
            used_motion_ids.add(motion_id)

    return _fallback_assignments(scenes, catalog)


def _build_payload(scenes: list[dict[str, Any]], catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "motion_catalog": [
            {
                "motion_id": motion_id,
                "description": data.get("description", ""),
                "tags": data.get("motion_tags", {}),
            }
            for motion_id, data in sorted(catalog.items(), key=lambda item: int(item[0]))
        ],
        "scenes": [
            {
                "scene_id": scene.get("scene_id"),
                "scene_description": scene.get("description", ""),
                "scene_caption": scene.get("scene_caption", ""),
                "current_motion_id": scene.get("cat_motion_id"),
                "current_motion_desc": scene.get("cat_motion_desc", ""),
                "dialogues": [
                    {
                        "dialogue_index": index,
                        "speaker": dialogue.get("speaker", ""),
                        "line": dialogue.get("line", ""),
                    }
                    for index, dialogue in enumerate(scene.get("dialogues", []) or [])
                ],
            }
            for scene in scenes
        ],
    }


def _fallback_assignments(scenes: list[dict[str, Any]], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    for scene in scenes:
        dialogues = scene.get("dialogues", []) or []
        used_motion_ids = {
            str(dialogue.get("motion_id") or "")
            for dialogue in dialogues
            if _motion_is_available(str(dialogue.get("motion_id") or ""), catalog, set())
        }
        for dialogue in dialogues:
            if not dialogue.get("motion_id"):
                motion_id = _choose_replacement_motion(scene, dialogue, catalog, used_motion_ids)
                if not motion_id:
                    motion_id = str(scene.get("cat_motion_id") or "")
                if motion_id not in catalog:
                    continue
                reason = "兜底选择不同猫动作" if used_motion_ids else "沿用当前镜头主猫动作"
                _attach_motion(dialogue, motion_id, catalog, reason)
                used_motion_ids.add(motion_id)
    return scenes


def _choose_replacement_motion(
    scene: dict[str, Any],
    dialogue: dict[str, Any],
    catalog: dict[str, Any],
    used_motion_ids: set[str],
) -> str:
    preferred_ids = [
        str(scene.get("cat_motion_id") or ""),
        _motion_id_for_dialogue(dialogue, catalog),
        "1", "2", "18", "19", "4", "23", "12", "13", "25", "9",
    ]
    for motion_id in preferred_ids:
        if _motion_is_available(motion_id, catalog, used_motion_ids):
            return motion_id
    for motion_id in sorted(catalog.keys(), key=lambda item: int(item)):
        if _motion_is_available(motion_id, catalog, used_motion_ids):
            return motion_id
    return ""


def _motion_id_for_dialogue(dialogue: dict[str, Any], catalog: dict[str, Any]) -> str:
    text = f"{dialogue.get('speaker', '')} {dialogue.get('line', '')}"
    cue_order = [
        (("领导", "老板", "催", "讲话", "加把劲", "必须"), "4"),
        (("放空", "麻木", "累", "工作", "电脑"), "1"),
        (("无语", "嫌弃", "看穿"), "18"),
        (("震惊", "离谱", "不会吧"), "19"),
        (("咖啡", "奶茶", "撑住", "谢谢"), "23"),
        (("可爱", "轻松", "开心"), "2"),
    ]
    for cues, motion_id in cue_order:
        if any(cue in text for cue in cues) and motion_id in catalog:
            return motion_id
    return ""


def _motion_is_available(
    motion_id: str,
    catalog: dict[str, Any],
    used_motion_ids: set[str],
) -> bool:
    return (
        motion_id in catalog
        and motion_id not in used_motion_ids
        and not _is_multi_cat_motion(motion_id, catalog)
    )


def _is_multi_cat_motion(motion_id: str, catalog: dict[str, Any]) -> bool:
    data = catalog.get(str(motion_id), {})
    description = str(data.get("description", ""))
    tags = data.get("motion_tags", {})
    tag_text = " ".join(
        str(item)
        for values in tags.values()
        if isinstance(values, list)
        for item in values
    )
    text = f"{description} {tag_text}"
    return any(token in text for token in ("双猫", "两只猫", "画面中有两只猫", "多只猫"))


def _attach_motion(
    dialogue: dict[str, Any],
    motion_id: str,
    catalog: dict[str, Any],
    reason: Any,
) -> None:
    data = catalog.get(motion_id, {})
    dialogue["motion_id"] = motion_id
    dialogue["motion_file"] = str(config.cat_motions_dir / f"{motion_id}.mp4")
    dialogue["motion_desc"] = data.get("description", "")
    if reason:
        dialogue["motion_reason"] = str(reason)
