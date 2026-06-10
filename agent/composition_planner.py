"""Semantic overlay planner for cat meme video composition.

The planner is intentionally deterministic. It acts as the final visual
director before FFmpeg composition, so prompt drift cannot place decorative or
irrelevant stickers into the rendered frame.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


ENGINE = "hyperframes-lite"
VERSION = "2026-06-07"

DECORATIVE_CATEGORIES = {"emotion-effects", "atmosphere-decor"}

PHONE_CUES = (
    "手机", "刷视频", "聊天", "消息", "通知", "微信", "@", "群", "电话", "直播",
    "拍照", "私信", "弹窗",
)
STUDY_CUES = (
    "补考", "考试", "试卷", "作业", "翻书", "上课", "课堂", "教室", "复习",
    "学习", "书", "笔", "题",
)
WORK_CUES = (
    "电脑", "键盘", "鼠标", "办公", "工位", "加班", "代码", "文档", "会议",
    "老板", "打工",
)
FOOD_CUES = ("奶茶", "饮料", "咖啡", "外卖", "吃饭", "午饭", "晚饭", "零食")
TIME_CUES = ("迟到", "闹钟", "时间", "早八", "ddl", "deadline", "截止", "倒计时")

PHONE_ASSET_WORDS = (
    "phone", "mobile", "cell", "iphone", "wechat", "message", "chat", "notification",
    "手机", "消息", "通知", "微信",
)
HAND_ASSET_WORDS = ("phone-in-hand", "hand", "holding", "ok-hand", "手", "爪", "拿")
MESSAGE_ASSET_WORDS = ("message", "chat", "bubble", "notification", "wechat", "消息", "弹窗")
STUDY_ASSET_WORDS = (
    "exam", "paper", "book", "pen", "notebook", "homework", "test", "试卷", "书", "笔",
)
COMPUTER_ASSET_WORDS = ("computer", "keyboard", "laptop", "monitor", "电脑", "键盘")
MOUSE_ASSET_WORDS = ("mouse", "鼠标")
FOOD_ASSET_WORDS = ("tea", "coffee", "drink", "cup", "food", "milk", "奶茶", "饮料")
TIME_ASSET_WORDS = ("clock", "timer", "calendar", "alarm", "闹钟", "日历", "倒计时")
DECORATIVE_FILE_WORDS = (
    "meme-face", "eyes", "eye", "poop", "face", "tear", "cry", "kawaii", "表情",
)


def apply_hyperframe_plan(scene: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``scene`` with planned overlays applied."""
    planned_scene = deepcopy(scene)
    plan = plan_scene_composition(planned_scene)
    decisions = {
        (decision["kind"], decision["source_index"]): decision
        for decision in plan["overlays"]
    }

    planned_stickers: list[dict[str, Any]] = []
    for index, sticker in enumerate(planned_scene.get("stickers", [])):
        decision = decisions.get(("sticker", index))
        if not decision or not decision.get("keep"):
            continue
        planned_stickers.append(_apply_decision(sticker, decision))
    planned_scene["stickers"] = planned_stickers

    planned_assets: list[dict[str, Any]] = []
    for index, asset in enumerate(planned_scene.get("generated_assets", [])):
        if not _is_generated_prop(asset):
            planned_assets.append(asset)
            continue
        decision = decisions.get(("generated_prop", index))
        if not decision or not decision.get("keep"):
            continue
        planned_assets.append(_apply_decision(asset, decision))
    planned_scene["generated_assets"] = planned_assets

    planned_scene["composition_plan"] = plan
    return planned_scene


def plan_scene_composition(scene: dict[str, Any]) -> dict[str, Any]:
    """Plan all sticker-like overlays for one scene."""
    scene_text = _scene_text(scene)
    decisions = [
        _decide_overlay(candidate, scene_text)
        for candidate in _overlay_candidates(scene)
    ]
    _keep_best_overlay(decisions)

    return {
        "engine": ENGINE,
        "version": VERSION,
        "coordinate_space": {"width": 1920, "height": 1080},
        "safe_zones": _safe_zones(),
        "overlays": decisions,
    }


def _overlay_candidates(scene: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, sticker in enumerate(scene.get("stickers", [])):
        candidates.append({
            "kind": "sticker",
            "source_index": index,
            "item": sticker,
            "scene": scene,
        })
    for index, asset in enumerate(scene.get("generated_assets", [])):
        if _is_generated_prop(asset):
            candidates.append({
                "kind": "generated_prop",
                "source_index": index,
                "item": asset,
                "scene": scene,
            })
    return candidates


def _decide_overlay(candidate: dict[str, Any], scene_text: str) -> dict[str, Any]:
    item = candidate["item"]
    role = _classify_role(item, scene_text, candidate["kind"])
    file_path = str(item.get("file", "") or item.get("file_path", ""))
    decision = {
        "kind": candidate["kind"],
        "source_index": candidate["source_index"],
        "file": file_path,
        "keep": False,
        "role": role or "",
        "position": "",
        "scale": int(item.get("scale", 180) or 180),
        "reason": "",
        "priority": 0,
    }

    if _is_manual_overlay(item):
        position = str(item.get("position") or "top_right")
        decision.update({
            "keep": True,
            "role": role or "manual",
            "position": position,
            "scale": _clamp_int(item.get("scale", 180), 120, 260),
            "reason": "用户手动指定素材，保留原有位置",
            "priority": 45,
        })
        return decision

    if _is_decorative_overlay(item):
        decision["reason"] = "纯表情/装饰贴纸不直接服务剧情"
        return decision

    if not role:
        decision["reason"] = "素材与当前字幕/剧情没有明确关系"
        return decision

    layout = _layout_for_role(role)
    decision.update({
        "keep": True,
        "position": layout["position"],
        "scale": _clamp_int(item.get("scale", layout["scale"]), 120, layout["max_scale"]),
        "reason": layout["reason"],
        "priority": layout["priority"],
    })
    return decision


def _classify_role(item: dict[str, Any], scene_text: str, kind: str) -> str:
    category = str(item.get("category", "") or item.get("folder", ""))
    item_text = _item_text(item)

    if _has_any(scene_text, PHONE_CUES):
        if _has_any(item_text, HAND_ASSET_WORDS) and (
            _has_any(item_text, PHONE_ASSET_WORDS) or kind == "generated_prop" or category == "emotion-effects"
        ):
            return "phone_hand"
        if _has_any(item_text, MESSAGE_ASSET_WORDS):
            return "message_bubble"
        if _has_any(item_text, PHONE_ASSET_WORDS) or category == "digital-communication":
            if _has_any(item_text, MOUSE_ASSET_WORDS):
                return ""
            return "phone"

    if _has_any(scene_text, STUDY_CUES):
        if _has_any(item_text, STUDY_ASSET_WORDS) or category == "campus-study":
            return "study_prop"
        return ""

    if _has_any(scene_text, WORK_CUES):
        if _has_any(item_text, MOUSE_ASSET_WORDS):
            return "work_prop" if _has_any(scene_text, ("鼠标", "电脑", "游戏")) else ""
        if _has_any(item_text, COMPUTER_ASSET_WORDS) or category == "career-identity":
            return "work_prop"

    if _has_any(scene_text, FOOD_CUES) and (
        _has_any(item_text, FOOD_ASSET_WORDS) or category == "food-drinks"
    ):
        return "food_prop"

    if _has_any(scene_text, TIME_CUES) and _has_any(item_text, TIME_ASSET_WORDS):
        return "time_prop"

    if kind == "generated_prop":
        return _classify_generated_prop_without_asset_name(item_text, scene_text)

    return ""


def _classify_generated_prop_without_asset_name(item_text: str, scene_text: str) -> str:
    if _has_any(scene_text, PHONE_CUES) and _has_any(item_text, PHONE_CUES + PHONE_ASSET_WORDS + HAND_ASSET_WORDS):
        return "phone_hand" if _has_any(item_text, HAND_ASSET_WORDS) else "phone"
    if _has_any(scene_text, STUDY_CUES) and _has_any(item_text, STUDY_CUES + STUDY_ASSET_WORDS):
        return "study_prop"
    if _has_any(scene_text, WORK_CUES) and _has_any(item_text, WORK_CUES + COMPUTER_ASSET_WORDS + MOUSE_ASSET_WORDS):
        return "work_prop"
    if _has_any(scene_text, FOOD_CUES) and _has_any(item_text, FOOD_CUES + FOOD_ASSET_WORDS):
        return "food_prop"
    if _has_any(scene_text, TIME_CUES) and _has_any(item_text, TIME_CUES + TIME_ASSET_WORDS):
        return "time_prop"
    return ""


def _layout_for_role(role: str) -> dict[str, Any]:
    layouts = {
        "phone_hand": {
            "position": "near_cat_paw_left",
            "scale": 210,
            "max_scale": 230,
            "priority": 100,
            "reason": "手机/手部道具需要贴近猫爪，让动作成立",
        },
        "phone": {
            "position": "near_cat_paw_left",
            "scale": 180,
            "max_scale": 210,
            "priority": 90,
            "reason": "手机道具需要贴近猫爪，而不是漂浮在角落",
        },
        "message_bubble": {
            "position": "upper_context_right",
            "scale": 150,
            "max_scale": 180,
            "priority": 70,
            "reason": "消息气泡属于情境提示，放在上方边区避开猫脸和字幕",
        },
        "study_prop": {
            "position": "desk_left",
            "scale": 180,
            "max_scale": 190,
            "priority": 85,
            "reason": "学习/考试道具应落在桌面区域，呼应补考剧情",
        },
        "work_prop": {
            "position": "desk_right",
            "scale": 180,
            "max_scale": 200,
            "priority": 65,
            "reason": "办公道具应落在桌面区域，避免遮挡主体",
        },
        "food_prop": {
            "position": "desk_left",
            "scale": 180,
            "max_scale": 200,
            "priority": 60,
            "reason": "饮食道具应贴近桌面，作为剧情物件出现",
        },
        "time_prop": {
            "position": "upper_context_right",
            "scale": 160,
            "max_scale": 190,
            "priority": 65,
            "reason": "时间提示适合放在上方边区，避开猫脸和字幕",
        },
    }
    return layouts[role]


def _keep_best_overlay(decisions: list[dict[str, Any]]) -> None:
    kept = [decision for decision in decisions if decision.get("keep")]
    kept.sort(key=lambda decision: decision.get("priority", 0), reverse=True)
    for index, decision in enumerate(kept):
        if index == 0:
            continue
        decision["keep"] = False
        decision["reason"] = "已有更贴合剧情的主道具，避免画面堆叠"


def _apply_decision(item: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    planned_item = dict(item)
    planned_item["position"] = decision["position"]
    planned_item["scale"] = decision["scale"]
    planned_item["composition_role"] = decision["role"]
    planned_item["composition_reason"] = decision["reason"]
    return planned_item


def _is_generated_prop(asset: dict[str, Any]) -> bool:
    return "道具" in str(asset.get("type", ""))


def _is_manual_overlay(item: dict[str, Any]) -> bool:
    return (
        str(item.get("category", "")) == "user_requested"
        or item.get("source") in {"manual", "user"}
    )


def _is_decorative_overlay(item: dict[str, Any]) -> bool:
    category = str(item.get("category", "") or item.get("folder", ""))
    file_name = Path(str(item.get("file", "") or item.get("file_path", ""))).stem.lower()
    item_text = _item_text(item)

    if category in DECORATIVE_CATEGORIES:
        if _has_any(item_text, HAND_ASSET_WORDS) and not _has_any(item_text, DECORATIVE_FILE_WORDS):
            return False
        return True
    return _has_any(file_name, DECORATIVE_FILE_WORDS)


def _scene_text(scene: dict[str, Any]) -> str:
    parts = [
        scene.get("description", ""),
        scene.get("subtitle", ""),
        scene.get("emotion", ""),
        scene.get("notes", ""),
        scene.get("suggested_prop", ""),
        scene.get("suggested_background", ""),
    ]
    return " ".join(str(part) for part in parts if part).lower()


def _item_text(item: dict[str, Any]) -> str:
    file_path = str(item.get("file", "") or item.get("file_path", ""))
    parts = [
        Path(file_path).stem,
        item.get("category", ""),
        item.get("folder", ""),
        item.get("description", ""),
        item.get("prompt", ""),
        item.get("revised_prompt", ""),
        item.get("name", ""),
    ]
    return " ".join(str(part) for part in parts if part).lower()


def _safe_zones() -> dict[str, dict[str, Any]]:
    return {
        "subtitle_band": {"x": 0, "y": 810, "width": 1920, "height": 270, "avoid": True},
        "cat_face": {"x": 620, "y": 90, "width": 700, "height": 470, "avoid": True},
        "cat_body": {"x": 520, "y": 320, "width": 880, "height": 560, "avoid": "soft"},
        "desk_prop_band": {"x": 80, "y": 560, "width": 1760, "height": 250, "avoid": False},
    }


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle.lower() in text for needle in needles)


def _clamp_int(value: Any, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = min_value
    return max(min_value, min(max_value, parsed))
