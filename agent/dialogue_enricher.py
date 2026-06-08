"""Model review for HyperFrames-style multi-cat dialogue planning."""

from __future__ import annotations

import json
from typing import Any

from .doubao_client import client


DIALOGUE_ENRICHMENT_PROMPT = """你是猫meme短视频的分镜对话导演。你的任务是审核一组分镜，决定哪些镜头应该是一只猫独白，哪些镜头应该出现2-3只不同猫形成互动。

目标：
- 让视频不只是单猫念字幕，而是出现角色关系、对话、打断、吐槽、回应，让剧情更丰富。
- 不要每镜都强塞多猫；强反应、崩溃、独白、转场可以保持单猫。
- 当分镜里出现他人介入、群消息、领导/同事/朋友/室友/老师/客户/家人、对话冲突、请求、催促、回应等关系时，优先改成多猫互动。
- 每个完整视频通常应至少有2个适合的多猫互动分镜；如果剧情确实完全没有他人关系，可以保留单猫。
- 如果一个镜头没有足够不同的猫动作素材承载不同角色，宁可保留单猫，不要复制同一只猫。
- dialogues 是猫头上的台词数组，1-3条；speaker 是角色名，line 是这只猫说的话。
- scene_caption 是画面中上方的当前分镜解释，只写4-8个字极短标签（如：赖床时刻/闹钟催命/开会走神），不要加星号，不要写完整剧情句。
- 不要输出解释文本之外的内容，只返回 JSON。

返回 JSON：
{
  "scenes": [
    {
      "scene_id": 1,
      "scene_caption": "4-8字短标签",
      "dialogues": [
        {"speaker": "我", "line": "台词"},
        {"speaker": "对方", "line": "回应"}
      ],
      "reason": "为什么这样安排"
    }
  ]
}
"""


def enrich_hyperframe_dialogues(
    scenes: list[dict[str, Any]],
    theme: str,
    script_title: str,
) -> list[dict[str, Any]]:
    """Ask the model to enrich selected scenes with multi-cat interactions."""
    if not scenes:
        return scenes

    try:
        review = client.chat_json(
            system_prompt=DIALOGUE_ENRICHMENT_PROMPT,
            user_message=json.dumps(_build_payload(scenes, theme, script_title), ensure_ascii=False),
            temperature=0.2,
            max_tokens=4096,
            timeout=120,
        )
    except Exception as e:
        print(f"   ⚠️ 多猫互动分镜规划失败，保留原对话: {e}")
        return scenes

    decisions = review.get("scenes", []) if isinstance(review, dict) else []
    scenes_by_id = {scene.get("scene_id"): scene for scene in scenes}
    for decision in decisions:
        scene = scenes_by_id.get(decision.get("scene_id"))
        if not scene:
            continue
        scene_caption = str(decision.get("scene_caption") or "").strip()
        if scene_caption:
            scene["scene_caption"] = scene_caption

        dialogues = _normalize_dialogues(decision.get("dialogues"))
        if dialogues:
            scene["dialogues"] = dialogues
        if decision.get("reason"):
            scene["dialogue_reason"] = str(decision["reason"])

    return scenes


def _build_payload(scenes: list[dict[str, Any]], theme: str, script_title: str) -> dict[str, Any]:
    return {
        "theme": theme,
        "script_title": script_title,
        "scenes": [
            {
                "scene_id": scene.get("scene_id"),
                "description": scene.get("description", ""),
                "subtitle": scene.get("subtitle", ""),
                "scene_caption": scene.get("scene_caption", ""),
                "emotion": scene.get("emotion", ""),
                "existing_dialogues": scene.get("dialogues", []),
                "notes": scene.get("notes", ""),
            }
            for scene in scenes
        ],
    }


def _normalize_dialogues(raw_dialogues: Any) -> list[dict[str, str]]:
    if isinstance(raw_dialogues, dict):
        raw_dialogues = [raw_dialogues]
    if not isinstance(raw_dialogues, list):
        return []

    dialogues = []
    for item in raw_dialogues:
        if isinstance(item, str):
            speaker, line = _split_dialogue_line(item)
        elif isinstance(item, dict):
            speaker = str(item.get("speaker") or item.get("name") or item.get("role") or "猫").strip()
            line = str(item.get("line") or item.get("text") or item.get("speech") or "").strip()
        else:
            continue
        if line:
            dialogues.append({"speaker": speaker or "猫", "line": line})
        if len(dialogues) >= 3:
            break
    return dialogues


def _split_dialogue_line(text: str) -> tuple[str, str]:
    cleaned = str(text or "").strip()
    for sep in ("：", ":"):
        if sep in cleaned:
            speaker, _, line = cleaned.partition(sep)
            if line.strip():
                return speaker.strip(), line.strip()
    return "", cleaned
