"""分镜脚本生成器 — 从选定剧本生成逐镜头分镜"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from .config import config
from .doubao_client import client
from .material_matcher import match_cat_motion, match_stickers, match_user_materials
from .gap_detector import detect_gaps, format_gaps_for_display
from .seedream_client import seedream
from .generated_asset_library import find_reusable_asset, write_asset_meta
from .cat_role_planner import assign_cat_role_motions, apply_cat_role_decisions
from .dialogue_enricher import enrich_hyperframe_dialogues
from .user_material_library import build_user_motion_catalog
from .audio_asset_library import default_audio_for_motion
from .utils import load_cat_motions


MAX_STORYBOARD_SCENES = 8
MIN_SCENE_DURATION = 3
DEFAULT_SCENE_DURATION = 4
MAX_SCENE_DURATION = 5
CAT_APPEARANCE_PATTERN = re.compile(
    r"(?:[\u4e00-\u9fff]{0,4}(?:衣|帽|衫|袍|装|西装|校服|工牌|围裙|睡衣|蓝衣|红衣|黄衣|绿衣|黑衣|白衣)?"
    r"[\u4e00-\u9fff]{0,3}(?:灰|白|黑|橘|黄|棕|狸花|三花|奶牛|蓝|红|绿|胖|瘦|大|小)猫)"
)
STICKER_SCENE_KEYWORDS = (
    "消息", "@", "聊天", "通知", "手机", "电脑", "弹窗", "群", "微信", "ddl", "考试", "作业",
    "补考", "试卷", "翻书", "书", "笔", "奶茶", "外卖", "迟到", "闹钟", "会议", "老板",
    "同事", "工资", "加班", "游戏", "刷视频", "拍照", "直播",
)
CONCRETE_STICKER_CATEGORIES = {
    "digital-communication",
    "campus-study",
    "food-drinks",
    "home-daily",
    "career-identity",
    "plot-conflict",
}
DECORATIVE_STICKER_CATEGORIES = {"emotion-effects", "atmosphere-decor"}
PROP_RELEVANCE_KEYWORDS = {
    "手机": ("消息", "@", "聊天", "通知", "群", "微信", "电话", "刷视频"),
    "电脑": ("电脑", "工位", "办公", "加班", "代码", "文档", "会议", "同事"),
    "键盘": ("电脑", "工位", "办公", "打字", "代码"),
    "闹钟": ("迟到", "早八", "时间", "起床", "ddl", "截止"),
    "奶茶": ("奶茶", "饮料", "下午茶", "续命"),
    "外卖": ("外卖", "吃饭", "午饭", "晚饭"),
    "试卷": ("考试", "试卷", "作业", "期末", "复习"),
    "书": ("考试", "学习", "作业", "复习", "课堂"),
    "日历": ("日期", "周一", "deadline", "ddl", "截止"),
}
VALID_MATERIAL_POSITIONS = {
    "top_left",
    "top_right",
    "center_left",
    "center_right",
    "bottom_left",
    "bottom_right",
    "center",
    "near_cat_paw_left",
    "near_cat_paw_right",
    "desk_left",
    "desk_right",
    "upper_context_left",
    "upper_context_right",
}
MATERIAL_REVIEW_PROMPT = """你是猫meme短视频的分镜美术审核。你的任务是判断每个镜头是否真的需要贴纸或道具，以及素材应该放在哪里。

审核原则：
- 贴纸/道具必须直接服务剧情、字幕或情绪反转；只是装饰、随机好看、和剧情弱相关时一律删除。
- 鼠标、键盘、电脑、手机等物件只有在字幕/剧情明确出现办公、消息、电脑、聊天、游戏、上网等语义时才保留。
- 考试/补考/上课场景优先考虑试卷、书本、笔、闹钟等素材；和课堂无关的数码物件应删除。
- 如果剧情是“猫玩手机/刷视频/聊天”，应保留手机类素材并放在猫爪附近，位置用 near_cat_paw_left/near_cat_paw_right；如果素材库里有手/爪/phone-in-hand，优先选择这类能让动作成立的素材。
- 考试、补考、翻书、办公桌面类物件用 desk_left/desk_right，像真实放在桌面上一样；不要漂浮在 top_left/top_right。
- 只有消息气泡、倒计时、通知牌这类“界面提示”才可以用 upper_context_left/upper_context_right。
- 位置必须避开猫脸、猫主体中央和底部字幕；不要把贴纸贴到画面边缘或随机角落。
- 表情脸、眼睛、meme-face、纯装饰元素默认删除，除非字幕明确要求展示一个表情包。
- 如果不确定，宁可不加素材。

只返回 JSON：
{
  "scenes": [
    {
      "scene_id": 1,
      "stickers": [
        {"file": "候选贴纸file原值", "keep": true, "position": "top_left", "scale": 150, "reason": "保留原因"}
      ],
      "prop": {"keep": false, "description": "", "position": "", "scale": 0, "reason": "删除或保留原因"}
    }
  ]
}
"""
STORYBOARD_AI_PLANNING_PROMPT = """你是猫meme短视频的分镜 AI 编排导演。你的任务是在一次审核里同时完成三件事：
1. 判断每个镜头是否真的需要贴纸/道具，并给出安全位置。
2. 用 HyperFrames 风格优化 scene_caption 和猫头台词 dialogues。
3. 为每个猫角色从 motion_catalog 中选择合适 motion_id。

编排原则：
- 贴纸/道具必须直接服务剧情、字幕或角色动作；只是装饰、随机好看、和剧情弱相关时删除。
- 手机、电脑、试卷、奶茶等物件只有在剧情明确需要时保留；应贴近真实交互位置，如手机放猫爪附近，桌面物件放 desk_left/desk_right。
- 表情脸、眼睛、meme-face、纯装饰元素默认删除，除非字幕明确要求展示表情包。
- scene_caption 只写4-8个字极短标签，如“赖床时刻”“闹钟催命”“开会走神”；不要写完整剧情句，不要超过12个字。
- 当剧情出现朋友、同事、领导、老师、室友、客户、群消息、请求、催促、回应、争辩等关系时，优先安排 2-3 只不同猫形成互动。
- 不要每镜都强塞多猫；独白、强反应、转场、情绪落点可以保持一只猫。
- 多猫同屏时，不是复制同一只猫；不同 speaker 要根据身份、台词、情绪选择不同 motion_id。
- 如果 motion_catalog 中存在 motion_id 以 user: 开头或 source=user 的用户上传猫动作素材，必须优先从这些用户素材中为角色选动作；只有用户素材不适合当前剧情时，才选择本地素材补充。
- motion_catalog 中描述或 tags 含“双猫/两只猫/画面中有两只猫/多只猫”的素材代表素材本身已有多只猫，不要分配给单个 dialogue 角色。
- 同一镜头内不要给多个 dialogue 角色选择同一个 motion_id；如果找不到不同动作素材，就减少 dialogue 数量，不要复制同一只猫。
- 只能从 motion_catalog 中选择 motion_id，不能编造。
- 位置必须避开猫脸、猫主体中央和底部字幕；如果不确定，宁可不加素材。

只返回 JSON：
{
  "scenes": [
    {
      "scene_id": 1,
      "scene_caption": "4-8字短标签，不要加星号",
      "dialogues": [
        {"speaker": "我", "line": "猫头上的台词"},
        {"speaker": "同事", "line": "另一只猫的回应"}
      ],
      "stickers": [
        {"file": "候选贴纸file原值", "keep": true, "position": "desk_right", "scale": 160, "reason": "保留原因"}
      ],
      "prop": {"keep": false, "description": "", "position": "", "scale": 0, "reason": "删除或保留原因"},
      "cat_roles": [
        {"dialogue_index": 0, "motion_id": "1", "reason": "选择原因"}
      ],
      "reason": "整体编排原因"
    }
  ]
}
"""


def generate_storyboard(
    selected_script: dict,
    theme: str,
    auto_fill_gaps: bool = True,
    review_materials: bool = False,
    custom_materials: Optional[list[str]] = None,
    custom_material_index: Optional[dict] = None,
) -> dict:
    """从选定的剧本生成详细分镜脚本。

    对每个镜头：
    1. 匹配猫动作素材
    2. 匹配贴纸
    3. 检测素材缺口
    4. （可选）自动补全缺口

    Args:
        selected_script: 用户选定的剧本文本
        theme: 主题描述
        auto_fill_gaps: 是否自动补全素材缺口
        review_materials: 是否用模型审核贴纸/道具的必要性和位置

    Returns:
        {
            "theme": "...",
            "script_title": "...",
            "script_version": "...",
            "total_duration": 25,
            "scenes": [
                {
                    "scene_id": 1,
                    "duration": 3,
                    "description": "...",
                    "cat_motion_id": "15",
                    "cat_motion_file": "/path/to/15.mp4",
                    "cat_motion_desc": "...",
                    "stickers": [{"category": "...", "file": "..."}],
                    "subtitle": "...",
                    "subtitle_style": "...",
                    "transition": "...",
                    "emotion": "...",
                    "generated_assets": [],  # Seedream生成的资产
                    "_match_score": 5,
                }
            ],
            "gaps": {...},
        }
    """
    scenes_data = _pace_script_scenes(selected_script.get("scenes", []))

    storyboard_scenes = []
    for scene in scenes_data:
        scene_id = scene.get("scene_id", len(storyboard_scenes) + 1)
        desc = scene.get("description", "")
        desc = _neutralize_fixed_cat_appearance(desc)
        emotion = scene.get("emotion", "")
        suggested_motion = scene.get("suggested_cat_motion", "")
        suggested_stickers = scene.get("suggested_stickers", [])
        subtitle = scene.get("subtitle_text", "")
        scene_text = f"{desc} {subtitle}"
        suggested_prop = _validate_suggested_prop(
            scene.get("suggested_prop", ""),
            scene_text=scene_text,
            theme=theme,
        )

        # 匹配猫动作
        best_motion = match_cat_motion(
            scene_description=desc,
            required_emotion=emotion,
            required_action=suggested_motion,
        )

        # 匹配贴纸：只在剧本明确建议或场景有高置信关键词时添加，避免无关装饰乱入。
        matched_stickers = _match_relevant_stickers(
            scene_description=scene_text,
            emotion=emotion,
            suggested_stickers=suggested_stickers,
        )

        # 组装分镜
        storyboard_scene = {
            "scene_id": scene_id,
            "duration": _normalize_scene_duration(scene.get("duration_sec", DEFAULT_SCENE_DURATION)),
            "description": desc,
            "subtitle": scene.get("subtitle_text", ""),
            "subtitle_style": scene.get("subtitle_style", "底部居中/白字黑描边"),
            "topic_caption": scene.get("topic_caption") or selected_script.get("title", "") or theme,
            "scene_caption": scene.get("scene_caption") or _derive_scene_caption(desc),
            "dialogues": _normalize_dialogues_for_scene(scene.get("dialogues"), scene.get("subtitle_text", "")),
            "transition": scene.get("transition", "硬切"),
            "emotion": emotion,
            "notes": scene.get("notes", ""),
            "suggested_background": scene.get("suggested_background", "") or _derive_background_description(
                theme=theme,
                description=desc,
                emotion=emotion,
            ),
            "suggested_prop": suggested_prop,
            "generated_assets": [],
        }

        if best_motion:
            storyboard_scene["cat_motion_id"] = best_motion["motion_id"]
            storyboard_scene["cat_motion_file"] = str(best_motion["file_path"])
            storyboard_scene["cat_motion_desc"] = best_motion["description"]
            storyboard_scene["_match_score"] = best_motion["score"]
        else:
            storyboard_scene["cat_motion_id"] = None
            storyboard_scene["cat_motion_file"] = None
            storyboard_scene["cat_motion_desc"] = "未匹配（需手动选择）"
            storyboard_scene["_match_score"] = 0
            # 兜底：建议用常见动作
            storyboard_scene["suggested_fallback_motions"] = ["1", "2", "15"]

        sticker_position = scene.get("sticker_position", "")
        storyboard_scene["stickers"] = [
            _build_sticker_item(s, i, sticker_position)
            for i, s in enumerate(matched_stickers)
        ]

        _apply_user_material_matches(storyboard_scene, custom_materials, custom_material_index)

        storyboard_scenes.append(storyboard_scene)

    roles_already_assigned = False
    if review_materials:
        storyboard_scenes, roles_already_assigned = _review_enrich_and_assign_storyboard(
            scenes=storyboard_scenes,
            theme=theme,
            script_title=selected_script.get("title", ""),
            user_motion_catalog=build_user_motion_catalog(custom_material_index),
        )

    _sync_storyboard_cat_motion_fields(storyboard_scenes)
    user_motion_bindings = _collect_user_motion_bindings(storyboard_scenes)

    _attach_reusable_generated_assets(storyboard_scenes)

    # 检测素材缺口
    gap_report = detect_gaps(storyboard_scenes)
    needs_role_assignment = review_materials and (
        not roles_already_assigned
        or _has_cat_motion_gap(gap_report)
        or _has_dialogue_without_motion(storyboard_scenes)
    )

    storyboard_scenes = _fill_gaps_and_assign_roles(
        scenes=storyboard_scenes,
        gap_report=gap_report,
        auto_fill_gaps=auto_fill_gaps,
        review_materials=needs_role_assignment,
        user_motion_catalog=build_user_motion_catalog(custom_material_index),
    )

    _restore_user_motion_bindings(storyboard_scenes, user_motion_bindings)
    _sync_storyboard_cat_motion_fields(storyboard_scenes)
    _assign_audio_to_scenes(storyboard_scenes)

    return {
        "theme": theme,
        "script_title": selected_script.get("title", ""),
        "script_version": selected_script.get("version_name", ""),
        "total_duration": sum(s.get("duration", 0) for s in storyboard_scenes),
        "scene_count": len(storyboard_scenes),
        "scenes": storyboard_scenes,
        "gaps": gap_report,
    }


def fill_storyboard_gaps_for_video(storyboard: dict) -> dict:
    """Fill deferred material gaps just before video composition.

    The storyboard preview path intentionally skips AIGC generation for speed.
    This function performs the expensive fills once they are actually needed.
    """
    scenes = _copy_scenes(storyboard.get("scenes", []))
    gap_report = storyboard.get("gaps") or detect_gaps(scenes)
    pending_gap_report = dict(gap_report)
    pending_gap_report["gaps"] = _pending_video_fill_gaps(scenes, gap_report)
    if pending_gap_report["gaps"]:
        needs_role_assignment = (
            _has_cat_motion_gap(pending_gap_report)
            or _has_dialogue_without_motion(scenes)
        )
        scenes = _fill_gaps_and_assign_roles(
            scenes=scenes,
            gap_report=pending_gap_report,
            auto_fill_gaps=True,
            review_materials=needs_role_assignment,
        )

    _sync_storyboard_cat_motion_fields(scenes)
    _assign_audio_to_scenes(scenes)

    updated = dict(storyboard)
    updated["scenes"] = scenes
    updated["total_duration"] = sum(scene.get("duration", 0) for scene in scenes)
    updated["scene_count"] = len(scenes)
    updated["gaps"] = _remaining_gap_report(gap_report, scenes)
    updated["_video_gaps_filled"] = True
    return updated


def _pace_script_scenes(scenes_data: Any) -> list[dict]:
    """Keep a complete story shape while avoiding overly dense shot lists."""
    if not isinstance(scenes_data, list):
        return []
    scenes = [scene for scene in scenes_data if isinstance(scene, dict)]
    if len(scenes) <= MAX_STORYBOARD_SCENES:
        return scenes

    indices = _evenly_spaced_indices(len(scenes), MAX_STORYBOARD_SCENES)
    return [scenes[index] for index in indices]


def _evenly_spaced_indices(total: int, desired: int) -> list[int]:
    if total <= desired:
        return list(range(total))
    if desired <= 1:
        return [total - 1]

    raw_indices = [round(index * (total - 1) / (desired - 1)) for index in range(desired)]
    indices = []
    for index in raw_indices:
        if index not in indices:
            indices.append(index)
    candidate = 0
    while len(indices) < desired and candidate < total:
        if candidate not in indices:
            indices.append(candidate)
        candidate += 1
    return sorted(indices[:desired])


def _normalize_scene_duration(value: Any) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_SCENE_DURATION
    if parsed < MIN_SCENE_DURATION:
        return MIN_SCENE_DURATION
    if parsed > MAX_SCENE_DURATION:
        return MAX_SCENE_DURATION
    return int(round(parsed))


def _review_and_enrich_storyboard(
    scenes: list[dict],
    theme: str,
    script_title: str,
) -> list[dict]:
    """Run independent text review passes concurrently and merge their fields."""
    user_motion_bindings = _collect_user_motion_bindings(scenes)
    with ThreadPoolExecutor(max_workers=2) as executor:
        review_future = executor.submit(_review_storyboard_materials, _copy_scenes(scenes), theme)
        dialogue_future = executor.submit(
            enrich_hyperframe_dialogues,
            _copy_scenes(scenes),
            theme,
            script_title,
        )
        reviewed_scenes = review_future.result()
        dialogue_scenes = dialogue_future.result()

    merged = _merge_dialogue_fields(
        base_scenes=reviewed_scenes,
        dialogue_scenes=dialogue_scenes,
    )
    _restore_user_motion_bindings(merged, user_motion_bindings)
    return merged


def _review_enrich_and_assign_storyboard(
    scenes: list[dict],
    theme: str,
    script_title: str,
    user_motion_catalog: Optional[dict[str, Any]] = None,
) -> tuple[list[dict], bool]:
    """Use one model pass for material review, dialogue planning, and role motions."""
    if not scenes:
        return scenes, True
    user_motion_bindings = _collect_user_motion_bindings(scenes)
    catalog = _combined_planning_catalog(user_motion_catalog)
    try:
        review = client.chat_json(
            system_prompt=STORYBOARD_AI_PLANNING_PROMPT,
            user_message=json.dumps(
                _build_storyboard_ai_planning_payload(scenes, theme, script_title, catalog),
                ensure_ascii=False,
            ),
            temperature=0.15,
            max_tokens=4096,
            timeout=150,
        )
    except Exception as e:
        print(f"   ⚠️ 分镜AI合并编排失败，回退旧流程: {e}")
        return _review_and_enrich_storyboard(scenes, theme, script_title), False

    decisions = review.get("scenes", []) if isinstance(review, dict) else []
    if not isinstance(decisions, list):
        return scenes, False
    _apply_material_decisions(scenes, decisions)
    _apply_dialogue_decisions(scenes, decisions)
    _restore_user_motion_bindings(scenes, user_motion_bindings)
    apply_cat_role_decisions(scenes, decisions, catalog)
    _restore_user_motion_bindings(scenes, user_motion_bindings)
    return scenes, True


def _build_storyboard_ai_planning_payload(
    scenes: list[dict],
    theme: str,
    script_title: str,
    catalog: dict[str, Any],
) -> dict:
    return {
        "theme": theme,
        "script_title": script_title,
        "allowed_positions": sorted(VALID_MATERIAL_POSITIONS),
        "motion_catalog": _compact_motion_catalog_for_planning(scenes, theme, script_title, catalog),
        "scenes": [
            {
                "scene_id": scene.get("scene_id"),
                "description": scene.get("description", ""),
                "subtitle": scene.get("subtitle", ""),
                "emotion": scene.get("emotion", ""),
                "scene_caption": scene.get("scene_caption", ""),
                "existing_dialogues": scene.get("dialogues", []),
                "suggested_background": scene.get("suggested_background", ""),
                "suggested_prop": scene.get("suggested_prop", ""),
                "current_motion_id": scene.get("cat_motion_id"),
                "current_motion_desc": scene.get("cat_motion_desc", ""),
                "candidate_stickers": [
                    {
                        "category": sticker.get("category", ""),
                        "file": sticker.get("file", ""),
                        "position": sticker.get("position", ""),
                        "scale": sticker.get("scale", 180),
                    }
                    for sticker in scene.get("stickers", [])
                ],
            }
            for scene in scenes
        ],
    }


def _combined_planning_catalog(user_motion_catalog: Optional[dict[str, Any]]) -> dict[str, Any]:
    catalog: dict[str, Any] = {}
    if user_motion_catalog:
        catalog.update(user_motion_catalog)
    catalog.update(load_cat_motions())
    return catalog


def _compact_motion_catalog_for_planning(
    scenes: list[dict],
    theme: str,
    script_title: str,
    catalog: dict[str, Any],
    max_items: int = 12,
) -> list[dict[str, Any]]:
    """Return a small, relevant motion list for AI planning prompts."""
    if not catalog:
        return []

    pinned_ids = _pinned_motion_ids_for_scenes(scenes)
    selected: list[tuple[str, dict]] = []
    seen = set()
    user_items = [
        (motion_id, data)
        for motion_id, data in catalog.items()
        if _is_user_motion_catalog_entry(motion_id, data)
    ]
    user_items.sort(key=lambda item: _motion_catalog_sort_key(item[0]))
    for motion_id, data in user_items:
        if motion_id in seen:
            continue
        selected.append((motion_id, data))
        seen.add(motion_id)
        if len(selected) >= max_items:
            break
    if len(selected) >= max_items:
        return _serialize_compact_motion_catalog(selected)

    scored: list[tuple[int, int, str, dict]] = []
    search_text = _planning_search_text(scenes, theme, script_title)
    for motion_id, data in catalog.items():
        if motion_id in seen:
            continue
        score = _planning_motion_score(motion_id, data, search_text, pinned_ids)
        try:
            numeric_id = int(motion_id)
        except (TypeError, ValueError):
            numeric_id = 10_000
        scored.append((score, -numeric_id, str(motion_id), data))

    scored.sort(reverse=True)
    for _, _, motion_id, data in scored:
        if motion_id in seen:
            continue
        selected.append((motion_id, data))
        seen.add(motion_id)
        if len(selected) >= max_items:
            break

    return _serialize_compact_motion_catalog(selected)


def _serialize_compact_motion_catalog(selected: list[tuple[str, dict]]) -> list[dict[str, Any]]:
    return [
        {
            "motion_id": motion_id,
            "description": str(data.get("description", ""))[:90],
            "tags": _compact_motion_tags(data.get("motion_tags", {})),
        }
        for motion_id, data in selected
    ]


def _is_user_motion_catalog_entry(motion_id: Any, data: Any) -> bool:
    if str(motion_id).startswith("user:"):
        return True
    return isinstance(data, dict) and data.get("source") == "user"


def _motion_catalog_sort_key(motion_id: Any) -> tuple[int, int, str]:
    text = str(motion_id)
    if text.startswith("user:"):
        try:
            return (0, int(text.split(":", 1)[1]), text)
        except (TypeError, ValueError):
            return (0, 999, text)
    try:
        return (1, int(text), text)
    except (TypeError, ValueError):
        return (2, 0, text)


def _pinned_motion_ids_for_scenes(scenes: list[dict]) -> set[str]:
    pinned = set()
    for scene in scenes:
        if scene.get("cat_motion_id"):
            pinned.add(str(scene.get("cat_motion_id")))
        for dialogue in scene.get("dialogues", []) or []:
            if isinstance(dialogue, dict) and dialogue.get("motion_id"):
                pinned.add(str(dialogue.get("motion_id")))
    return pinned


def _planning_search_text(scenes: list[dict], theme: str, script_title: str) -> str:
    parts = [theme, script_title]
    for scene in scenes:
        parts.extend([
            scene.get("description", ""),
            scene.get("subtitle", ""),
            scene.get("emotion", ""),
            scene.get("scene_caption", ""),
            scene.get("cat_motion_desc", ""),
            scene.get("suggested_background", ""),
            scene.get("suggested_prop", ""),
        ])
        for dialogue in scene.get("dialogues", []) or []:
            if isinstance(dialogue, dict):
                parts.extend([dialogue.get("speaker", ""), dialogue.get("line", "")])
    return " ".join(str(part).lower() for part in parts if part)


def _planning_motion_score(
    motion_id: str,
    data: dict,
    search_text: str,
    pinned_ids: set[str],
) -> int:
    score = 100 if str(motion_id) in pinned_ids else 0
    description = str(data.get("description", "")).lower()
    tags = data.get("motion_tags", {}) if isinstance(data.get("motion_tags", {}), dict) else {}

    for key, weight in (("actions", 7), ("emotions", 8), ("contexts", 6)):
        for tag in tags.get(key, []) or []:
            tag_text = str(tag).lower()
            if tag_text and tag_text in search_text:
                score += weight

    for keyword in ("电脑", "办公", "会议", "老板", "同事", "周一", "考试", "补考", "教室",
                    "宿舍", "手机", "奶茶", "通勤", "崩溃", "哭", "震惊", "无语", "吐槽"):
        if keyword in search_text and keyword in description:
            score += 4

    for avoid in tags.get("avoid", []) or []:
        avoid_text = str(avoid).lower()
        if avoid_text and avoid_text in search_text and "默认避用" not in avoid_text:
            score -= 10

    if "主体不是猫" in description or "非猫素材" in " ".join(str(v) for v in tags.get("avoid", [])):
        score -= 20
    return score


def _compact_motion_tags(tags: Any) -> dict[str, list[str]]:
    if not isinstance(tags, dict):
        return {}
    compact = {}
    for key in ("actions", "emotions", "contexts"):
        values = tags.get(key, [])
        if isinstance(values, list):
            compact[key] = [str(value) for value in values[:4]]
    return compact


def _fill_gaps_and_assign_roles(
    scenes: list[dict],
    gap_report: dict,
    auto_fill_gaps: bool,
    review_materials: bool,
    user_motion_catalog: Optional[dict[str, Any]] = None,
) -> list[dict]:
    """Run AIGC gap filling and role motion selection concurrently when possible."""
    if not auto_fill_gaps and not review_materials:
        return scenes
    if auto_fill_gaps and not review_materials:
        return _auto_fill_gaps(scenes, gap_report)
    if review_materials and not auto_fill_gaps:
        return _assign_cat_role_motions(scenes, user_motion_catalog)
    if _has_cat_motion_gap(gap_report):
        filled_scenes = _auto_fill_gaps(scenes, gap_report)
        return _assign_cat_role_motions(filled_scenes, user_motion_catalog)

    with ThreadPoolExecutor(max_workers=2) as executor:
        fill_future = executor.submit(_auto_fill_gaps, _copy_scenes(scenes), gap_report)
        if user_motion_catalog:
            roles_future = executor.submit(
                assign_cat_role_motions,
                _copy_scenes(scenes),
                user_motion_catalog=user_motion_catalog,
            )
        else:
            roles_future = executor.submit(assign_cat_role_motions, _copy_scenes(scenes))
        filled_scenes = fill_future.result()
        role_scenes = roles_future.result()

    return _merge_role_fields(
        base_scenes=filled_scenes,
        role_scenes=role_scenes,
    )


def _assign_cat_role_motions(
    scenes: list[dict],
    user_motion_catalog: Optional[dict[str, Any]] = None,
) -> list[dict]:
    if user_motion_catalog:
        return assign_cat_role_motions(scenes, user_motion_catalog=user_motion_catalog)
    return assign_cat_role_motions(scenes)


def _has_cat_motion_gap(gap_report: dict) -> bool:
    return any(
        gap.get("gap_type") == "猫动作缺失"
        for gap in gap_report.get("gaps", [])
    )


def _has_dialogue_without_motion(scenes: list[dict]) -> bool:
    return any(
        bool(dialogue.get("line")) and not dialogue.get("motion_id")
        for scene in scenes
        for dialogue in scene.get("dialogues", []) or []
        if isinstance(dialogue, dict)
    )


def _pending_video_fill_gaps(scenes: list[dict], gap_report: dict) -> list[dict]:
    scenes_by_id = {scene.get("scene_id"): scene for scene in scenes}
    pending = []
    for gap in gap_report.get("gaps", []):
        scene = scenes_by_id.get(gap.get("scene_id"))
        if not scene or _gap_already_filled(scene, gap):
            continue
        if gap.get("fill_strategy") in {"AIGC生成", "现有素材复用", "包装补全"}:
            pending.append(gap)
    return pending


def _remaining_gap_report(gap_report: dict, scenes: list[dict]) -> dict:
    scenes_by_id = {scene.get("scene_id"): scene for scene in scenes}
    remaining_gaps = [
        gap for gap in gap_report.get("gaps", [])
        if not _gap_already_filled(scenes_by_id.get(gap.get("scene_id"), {}), gap)
    ]
    updated = dict(gap_report)
    updated["gaps"] = remaining_gaps
    updated["total_gaps"] = len(remaining_gaps)
    updated["high_priority"] = sum(1 for gap in remaining_gaps if gap.get("severity") == "high")
    updated["medium_priority"] = sum(1 for gap in remaining_gaps if gap.get("severity") == "medium")
    updated["low_priority"] = sum(1 for gap in remaining_gaps if gap.get("severity") == "low")
    if not remaining_gaps:
        updated["fill_summary"] = "✅ 所有镜头素材充足"
    return updated


def _gap_already_filled(scene: dict, gap: dict) -> bool:
    gap_type = str(gap.get("gap_type", ""))
    if gap_type == "背景缺失":
        if scene.get("background_file") or scene.get("background"):
            return True
        return any(_asset_fills_gap(asset, "background") for asset in scene.get("generated_assets", []))
    if gap_type == "道具缺失":
        return any(_asset_fills_gap(asset, "prop") for asset in scene.get("generated_assets", []))
    if gap_type == "猫动作缺失":
        return bool(scene.get("cat_motion_id"))
    if gap_type == "贴纸不足":
        return bool(scene.get("stickers"))
    return False


def _asset_fills_gap(asset: dict, kind: str) -> bool:
    if not isinstance(asset, dict) or not asset.get("file"):
        return False
    asset_type = str(asset.get("type", ""))
    if kind == "background":
        return "背景" in asset_type or asset.get("kind") == "background"
    if kind == "prop":
        return "道具" in asset_type or asset.get("kind") == "prop"
    return False


def _copy_scenes(scenes: list[dict]) -> list[dict]:
    return json.loads(json.dumps(scenes, ensure_ascii=False))


def _collect_user_motion_bindings(scenes: list[dict]) -> dict[Any, dict[str, str]]:
    """Remember uploaded cat motion bindings before model rewrites scene text."""
    bindings: dict[Any, dict[str, str]] = {}
    for index, scene in enumerate(scenes):
        binding = _user_motion_binding_for_scene(scene)
        if binding:
            bindings[_scene_binding_key(scene, index)] = binding
    return bindings


def _scene_binding_key(scene: dict, index: int) -> Any:
    scene_id = scene.get("scene_id")
    if scene_id is None or scene_id == "":
        return f"idx:{index}"
    return scene_id


def _user_motion_binding_for_scene(scene: dict) -> Optional[dict[str, str]]:
    user_dialogues = [
        (index, dialogue)
        for index, dialogue in enumerate(scene.get("dialogues", []) or [])
        if isinstance(dialogue, dict)
        and str(dialogue.get("line") or "").strip()
        and dialogue.get("motion_binding") != "auto_user_match"
        and (
            dialogue.get("motion_source") == "user"
            or str(dialogue.get("motion_id") or "").strip() == "user"
        )
        and str(dialogue.get("motion_file") or scene.get("cat_motion_file") or "").strip()
    ]
    if user_dialogues:
        dialogue_index, dialogue = user_dialogues[0]
        file_path = str(dialogue.get("motion_file") or scene.get("cat_motion_file") or "").strip()
        return {
            "motion_id": str(dialogue.get("motion_id") or scene.get("cat_motion_id") or "user"),
            "file": file_path,
            "desc": str(dialogue.get("motion_desc") or scene.get("cat_motion_desc") or Path(file_path).name).strip(),
            "speaker": str(dialogue.get("speaker") or "").strip(),
            "dialogue_index": str(dialogue_index),
        }

    if (
        scene.get("cat_motion_source") == "user"
        and scene.get("cat_motion_binding") != "auto_user_match"
        and str(scene.get("cat_motion_file") or "").strip()
    ):
        file_path = str(scene.get("cat_motion_file") or "").strip()
        return {
            "motion_id": str(scene.get("cat_motion_id") or "user"),
            "file": file_path,
            "desc": str(scene.get("cat_motion_desc") or Path(file_path).name).strip(),
            "speaker": "",
            "dialogue_index": "0",
        }
    return None


def _restore_user_motion_bindings(
    scenes: list[dict],
    bindings: dict[Any, dict[str, str]],
) -> None:
    if not bindings:
        return
    for index, scene in enumerate(scenes):
        binding = bindings.get(_scene_binding_key(scene, index))
        if binding:
            _apply_user_motion_binding(scene, binding)


def _apply_user_motion_binding(scene: dict, binding: dict[str, str]) -> None:
    file_path = str(binding.get("file") or "").strip()
    if not file_path:
        return

    motion_desc = str(binding.get("desc") or Path(file_path).name).strip()
    motion_id = str(binding.get("motion_id") or "user")
    scene["cat_motion_id"] = motion_id
    scene["cat_motion_file"] = file_path
    scene["cat_motion_desc"] = motion_desc
    scene["cat_motion_source"] = "user"
    scene["_match_score"] = max(int(scene.get("_match_score", 0) or 0), 8)

    dialogues = scene.get("dialogues", []) or []
    visible_dialogues = [
        (index, dialogue)
        for index, dialogue in enumerate(dialogues)
        if isinstance(dialogue, dict) and str(dialogue.get("line") or "").strip()
    ]
    if not visible_dialogues:
        return

    target_dialogue = None
    speaker = str(binding.get("speaker") or "").strip()
    if speaker:
        for _, dialogue in visible_dialogues:
            if str(dialogue.get("speaker") or "").strip() == speaker:
                target_dialogue = dialogue
                break
    if target_dialogue is None:
        try:
            original_index = int(binding.get("dialogue_index", "0"))
        except (TypeError, ValueError):
            original_index = 0
        original_index = max(0, min(original_index, len(visible_dialogues) - 1))
        target_dialogue = visible_dialogues[original_index][1]

    target_dialogue["motion_id"] = motion_id
    target_dialogue["motion_file"] = file_path
    target_dialogue["motion_desc"] = motion_desc
    target_dialogue["motion_source"] = "user"
    target_dialogue["motion_reason"] = "用户上传猫动作素材优先"


def _neutralize_fixed_cat_appearance(description: Any) -> str:
    """Remove fixed visual identity from scene descriptions.

    Motion matching can choose different cat assets later; keeping visual terms
    like "蓝衣灰猫" in description makes the storyboard text contradict the
    rendered meme. Action and emotion cues are preserved.
    """
    text = str(description or "").strip()
    if not text:
        return ""
    text = CAT_APPEARANCE_PATTERN.sub("猫", text)
    text = re.sub(r"猫+", "猫", text)
    return text.strip()


def _sync_storyboard_cat_motion_fields(scenes: list[dict]) -> list[dict]:
    """Keep primary scene motion aligned with single-cat rendered dialogue.

    HyperFrames renders dialogue motions. For a one-dialogue scene, that means
    the dialogue motion is the actual visible cat, so the scene-level motion
    displayed in the storyboard must point to the same asset.
    """
    for scene in scenes:
        dialogues = [
            dialogue
            for dialogue in scene.get("dialogues", []) or []
            if isinstance(dialogue, dict) and str(dialogue.get("line") or "").strip()
        ]
        if len(dialogues) != 1:
            continue
        dialogue = dialogues[0]
        motion_id = str(dialogue.get("motion_id") or "").strip()
        motion_file = str(dialogue.get("motion_file") or "").strip()
        if not motion_id and not motion_file:
            continue
        if motion_id:
            scene["cat_motion_id"] = motion_id
        if motion_file:
            scene["cat_motion_file"] = motion_file
        motion_desc = str(dialogue.get("motion_desc") or "").strip()
        if motion_desc:
            scene["cat_motion_desc"] = motion_desc
        motion_source = str(dialogue.get("motion_source") or "").strip()
        if motion_source:
            scene["cat_motion_source"] = motion_source
        elif motion_id == "user":
            scene["cat_motion_source"] = "user"
        else:
            scene.pop("cat_motion_source", None)
    return scenes


def _attach_reusable_generated_assets(scenes: list[dict]) -> None:
    """Attach indexed generated assets before gap detection."""
    for scene in scenes:
        background_description = str(scene.get("suggested_background", "")).strip()
        if background_description and not _gap_already_filled(scene, {"gap_type": "背景缺失"}):
            reusable_bg = find_reusable_asset(
                "background",
                background_description,
                expected_size="2560x1440",
            ) or find_reusable_asset("background", background_description)
            if reusable_bg:
                scene.setdefault("generated_assets", []).append({
                    "type": "背景复用",
                    "file": str(reusable_bg),
                    "description": background_description,
                    "reused": True,
                })

        prop_description = str(scene.get("suggested_prop", "")).strip()
        if prop_description and not _gap_already_filled(scene, {"gap_type": "道具缺失"}):
            reusable_prop = find_reusable_asset(
                "prop",
                prop_description,
                expected_size="1920x1920",
            ) or find_reusable_asset("prop", prop_description)
            if reusable_prop:
                scene.setdefault("generated_assets", []).append({
                    "type": "道具复用",
                    "file": str(reusable_prop),
                    "description": prop_description,
                    "position": scene.get("suggested_prop_position", "bottom_right"),
                    "scale": scene.get("suggested_prop_scale", 180),
                    "reused": True,
                })


def _apply_user_material_matches(
    scene: dict,
    custom_materials: Optional[list[str]],
    custom_material_index: Optional[dict] = None,
) -> None:
    """Attach user-uploaded materials to the scene before local/generated assets."""
    for match in match_user_materials(scene, custom_materials, custom_material_index):
        kind = match.get("kind")
        file_path = match.get("file", "")
        if kind == "background" and not _gap_already_filled(scene, {"gap_type": "背景缺失"}):
            scene.setdefault("generated_assets", []).append({
                "type": "用户背景",
                "file": file_path,
                "description": scene.get("suggested_background", ""),
                "source": "user",
                "reason": match.get("reason", ""),
            })
        elif kind == "prop" and not _gap_already_filled(scene, {"gap_type": "道具缺失"}):
            scene.setdefault("generated_assets", []).append({
                "type": "用户道具",
                "file": file_path,
                "description": scene.get("suggested_prop", ""),
                "position": scene.get("suggested_prop_position", "bottom_right"),
                "scale": scene.get("suggested_prop_scale", 180),
                "source": "user",
                "reason": match.get("reason", ""),
            })
        elif kind == "sticker":
            scene.setdefault("stickers", []).append({
                "category": "user_uploaded",
                "file": file_path,
                "position": scene.get("sticker_position", "upper_context_right") or "upper_context_right",
                "scale": 180,
                "source": "user",
                "reason": match.get("reason", ""),
            })
        elif kind == "cat_motion":
            motion_id = str(match.get("motion_id") or "user")
            scene["cat_motion_id"] = motion_id
            scene["cat_motion_file"] = file_path
            scene["cat_motion_desc"] = str(match.get("description") or Path(file_path).name)
            scene["_match_score"] = max(int(scene.get("_match_score", 0) or 0), 8)
            scene["cat_motion_source"] = "user"
            scene["cat_motion_binding"] = "auto_user_match"
            _bind_user_motion_to_visible_dialogues(scene, file_path, scene["cat_motion_desc"], motion_id)


def _assign_audio_to_scenes(scenes: list[dict]) -> None:
    audio_cursors: dict[str, float] = {}
    for scene in scenes:
        _assign_scene_audio(scene)
        _assign_scene_audio_start(scene, audio_cursors)


def _assign_scene_audio(scene: dict) -> None:
    if scene.get("audio_muted"):
        scene["audio_source"] = "silent"
        scene["use_motion_audio"] = False
        scene.pop("audio_file", None)
        scene.pop("audio_motion_id", None)
        return

    motion_file = str(scene.get("cat_motion_file") or "").strip()
    motion_id = str(scene.get("cat_motion_id") or "").strip()
    if not motion_file:
        scene["audio_source"] = "silent"
        scene["use_motion_audio"] = False
        return

    if scene.get("cat_motion_source") == "user" or motion_id.startswith("user"):
        _set_scene_motion_original_audio(
            scene=scene,
            motion_file=motion_file,
            motion_id=motion_id or "user",
            reason="用户上传猫动作素材原声优先",
        )
        return

    audio_match = default_audio_for_motion(motion_id)
    if audio_match:
        scene["audio_source"] = str(audio_match.get("source") or "cat_motion_audio")
        scene["audio_file"] = str(audio_match.get("file") or "")
        scene["audio_motion_id"] = str(audio_match.get("source_motion_id") or motion_id)
        scene["audio_desc"] = str(audio_match.get("description") or "")
        scene["audio_reason"] = str(audio_match.get("reason") or "按剧情和猫动作匹配音频")
        duration = _float_or_none(audio_match.get("duration_seconds"))
        if duration is not None:
            scene["audio_duration"] = duration
        scene["use_motion_audio"] = True
        return

    _set_scene_motion_original_audio(
        scene=scene,
        motion_file=motion_file,
        motion_id=motion_id,
        reason="音频库无匹配时使用当前猫动作原声兜底",
    )


def _set_scene_motion_original_audio(
    scene: dict,
    motion_file: str,
    motion_id: str,
    reason: str,
) -> None:
    scene["audio_source"] = "motion_original"
    scene["audio_file"] = motion_file
    scene["audio_motion_id"] = motion_id
    scene["audio_desc"] = scene.get("cat_motion_desc", "")
    scene["audio_reason"] = reason
    scene["use_motion_audio"] = True


def _assign_scene_audio_start(scene: dict, audio_cursors: dict[str, float]) -> None:
    if not scene.get("use_motion_audio"):
        scene.pop("audio_start_offset", None)
        return
    audio_file = str(scene.get("audio_file") or "").strip()
    if not audio_file:
        scene.pop("audio_start_offset", None)
        return

    cursor_key = _audio_cursor_key(audio_file)
    start_offset = audio_cursors.get(cursor_key, 0.0)
    audio_duration = _float_or_none(scene.get("audio_duration"))
    if audio_duration is not None and start_offset >= max(audio_duration - 0.02, 0):
        scene["audio_source"] = "silent"
        scene["use_motion_audio"] = False
        scene["audio_start_offset"] = round(start_offset, 3)
        scene["audio_reason"] = "默认音频已播放完，避免从头循环，使用静音补足"
        return

    scene["audio_start_offset"] = round(start_offset, 3)
    audio_cursors[cursor_key] = start_offset + float(scene.get("duration", DEFAULT_SCENE_DURATION) or DEFAULT_SCENE_DURATION)


def _audio_cursor_key(audio_file: str) -> str:
    try:
        return str(Path(audio_file).resolve())
    except Exception:
        return str(audio_file)


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bind_user_motion_to_visible_dialogues(
    scene: dict,
    file_path: str,
    motion_desc: str | None = None,
    motion_id: str = "user",
) -> None:
    dialogues = scene.get("dialogues", []) or []
    for dialogue in dialogues:
        if not isinstance(dialogue, dict):
            continue
        if not str(dialogue.get("line") or "").strip():
            continue
        if dialogue.get("motion_source") == "user":
            continue
        if dialogue.get("motion_file") and dialogue.get("motion_source") != "user":
            continue
        dialogue["motion_id"] = motion_id
        dialogue["motion_file"] = file_path
        dialogue["motion_desc"] = motion_desc or Path(file_path).name
        dialogue["motion_source"] = "user"
        dialogue["motion_binding"] = "auto_user_match"
        dialogue["motion_reason"] = "用户上传猫动作素材优先"
        break


def _merge_dialogue_fields(base_scenes: list[dict], dialogue_scenes: list[dict]) -> list[dict]:
    dialogue_by_id = {scene.get("scene_id"): scene for scene in dialogue_scenes}
    for scene in base_scenes:
        enriched = dialogue_by_id.get(scene.get("scene_id"))
        if not enriched:
            continue
        for key in ("scene_caption", "dialogues", "dialogue_reason"):
            if key in enriched:
                scene[key] = enriched[key]
    return base_scenes


def _merge_role_fields(base_scenes: list[dict], role_scenes: list[dict]) -> list[dict]:
    roles_by_id = {scene.get("scene_id"): scene for scene in role_scenes}
    for scene in base_scenes:
        role_scene = roles_by_id.get(scene.get("scene_id"))
        if not role_scene:
            continue
        role_dialogues = role_scene.get("dialogues", []) or []
        dialogues = scene.get("dialogues", []) or []
        for index, role_dialogue in enumerate(role_dialogues):
            if index >= len(dialogues):
                break
            if (
                dialogues[index].get("motion_source") == "user"
                and dialogues[index].get("motion_binding") != "auto_user_match"
            ):
                continue
            for key in ("motion_id", "motion_file", "motion_desc", "motion_reason", "motion_source"):
                if key in role_dialogue:
                    dialogues[index][key] = role_dialogue[key]
            if "motion_source" not in role_dialogue:
                dialogues[index].pop("motion_source", None)
            dialogues[index].pop("motion_binding", None)
    return base_scenes


def _auto_fill_gaps(
    scenes: list[dict],
    gap_report: dict,
) -> list[dict]:
    """自动补全素材缺口。

    策略优先级：
    1. 现有素材复用
    2. 贴纸/包装补全
    3. Seedream AIGC 生成
    """
    aigc_groups: dict[tuple[str, str], dict] = {}

    for gap in gap_report.get("gaps", []):
        scene_id = gap["scene_id"]
        gap_type = gap["gap_type"]
        strategy = gap["fill_strategy"]

        # 找到对应场景
        scene = next((s for s in scenes if s["scene_id"] == scene_id), None)
        if scene is None:
            continue

        if strategy == "现有素材复用" and gap_type == "猫动作缺失":
            # 用常见动作兜底
            fallback_ids = ["2", "15", "1"]
            for fid in fallback_ids:
                if fid not in str(scene.get("cat_motion_id", "")):
                    scene["cat_motion_id"] = fid
                    scene["cat_motion_file"] = str(config.cat_motions_dir / f"{fid}.mp4")
                    scene["cat_motion_desc"] = f"兜底素材 #{fid}"
                    scene["_fallback"] = True
                    break

        elif strategy == "包装补全" and gap_type == "贴纸不足":
            # 添加默认贴纸
            emotion_effects_dir = config.stickers_dir / "emotion-effects"
            if emotion_effects_dir.exists():
                default_stickers = sorted(emotion_effects_dir.glob("*.png"))[:1]
                scene["stickers"] = [
                    _build_sticker_item(
                        {"category": "emotion-effects", "file_path": s},
                        i,
                        scene.get("sticker_position", ""),
                    )
                    for i, s in enumerate(default_stickers)
                ]

        elif strategy == "AIGC生成":
            gen_prompt = gap.get("generation_prompt", "")
            if gen_prompt and gap_type in ("背景缺失", "道具缺失"):
                key = _aigc_gap_key(gap_type, scene)
                group = aigc_groups.setdefault(
                    key,
                    {
                        "gap_type": gap_type,
                        "scene_id": scene_id,
                        "scene": scene,
                        "prompt": gen_prompt,
                        "targets": [],
                    },
                )
                group["targets"].append(scene)

    _fill_aigc_groups(aigc_groups)

    return scenes


def _fill_aigc_groups(aigc_groups: dict[tuple[str, str], dict]) -> None:
    """Generate unique AIGC assets with bounded concurrency, then attach them."""
    if not aigc_groups:
        return

    max_workers = max(1, min(config.seedream_max_workers, len(aigc_groups)))
    print(f"   🎨 Seedream 并发生成 {len(aigc_groups)} 个唯一素材 (max_workers={max_workers})...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_group = {
            executor.submit(
                _generate_aigc_asset,
                group["gap_type"],
                group["scene_id"],
                group["scene"],
                group["prompt"],
            ): group
            for group in aigc_groups.values()
        }

        for future in as_completed(future_to_group):
            group = future_to_group[future]
            asset = future.result()
            for target_scene in group["targets"]:
                target_scene.setdefault("generated_assets", []).append(dict(asset))


def _aigc_gap_key(gap_type: str, scene: dict) -> tuple[str, str]:
    """Return a stable key so identical generated assets can be reused."""
    if gap_type == "背景缺失":
        description = scene.get("suggested_background", "generic scene")
    else:
        description = scene.get("suggested_prop", "generic prop")
    return gap_type, str(description).strip()


def _generate_aigc_asset(
    gap_type: str,
    scene_id: int,
    scene: dict,
    prompt: str,
) -> dict:
    """Generate one AIGC asset or a local fallback when the API fails."""
    try:
        print(f"   🎨 Seedream 生成中: {gap_type} for 镜{scene_id}...")
        if gap_type == "背景缺失":
            filepath = seedream.generate_background(
                description=scene.get("suggested_background", "generic scene"),
                name=f"scene_{scene_id}_bg",
            )
        else:
            filepath = seedream.generate_prop(
                description=scene.get("suggested_prop", "generic prop"),
                name=f"scene_{scene_id}_prop",
            )
        print(f"   ✅ 已生成: {filepath.name}")
        return {
            "type": gap_type,
            "file": str(filepath),
            "prompt": prompt,
            "position": scene.get("suggested_prop_position", "bottom_right"),
            "scale": scene.get("suggested_prop_scale", 180),
        }
    except Exception as e:
        print(f"   ⚠️ Seedream 生成失败: {e}")
        return _create_fallback_asset(
            gap_type=gap_type,
            scene_id=scene_id,
            scene=scene,
            prompt=prompt,
            source_error=str(e),
        )


def _create_fallback_asset(
    gap_type: str,
    scene_id: int,
    scene: dict,
    prompt: str,
    source_error: str,
) -> dict:
    """Create a local visible asset when the image API is unavailable."""
    if gap_type == "背景缺失":
        description = scene.get("suggested_background", "通用背景")
        filepath = _create_fallback_background(description, f"scene_{scene_id}_bg")
    else:
        description = scene.get("suggested_prop", "通用道具")
        filepath = _create_fallback_prop(description, f"scene_{scene_id}_prop")

    return {
        "type": gap_type,
        "file": str(filepath),
        "prompt": prompt,
        "position": scene.get("suggested_prop_position", "bottom_right"),
        "scale": scene.get("suggested_prop_scale", 180),
        "fallback": True,
        "source_error": source_error,
    }


def _review_storyboard_materials(scenes: list[dict], theme: str) -> list[dict]:
    """Use the text model to remove irrelevant overlays and set safe positions."""
    payload = {
        "theme": theme,
        "allowed_positions": sorted(VALID_MATERIAL_POSITIONS),
        "scenes": [
            {
                "scene_id": scene.get("scene_id"),
                "description": scene.get("description", ""),
                "subtitle": scene.get("subtitle", ""),
                "emotion": scene.get("emotion", ""),
                "suggested_background": scene.get("suggested_background", ""),
                "suggested_prop": scene.get("suggested_prop", ""),
                "candidate_stickers": [
                    {
                        "category": sticker.get("category", ""),
                        "file": sticker.get("file", ""),
                        "position": sticker.get("position", ""),
                        "scale": sticker.get("scale", 180),
                    }
                    for sticker in scene.get("stickers", [])
                ],
            }
            for scene in scenes
        ],
    }

    try:
        review = client.chat_json(
            system_prompt=MATERIAL_REVIEW_PROMPT,
            user_message=json.dumps(payload, ensure_ascii=False),
            temperature=0.1,
            max_tokens=4096,
            timeout=120,
        )
    except Exception as e:
        print(f"   ⚠️ 素材AI审核失败，使用规则结果: {e}")
        return scenes

    decisions = review.get("scenes", []) if isinstance(review, dict) else []
    return _apply_material_decisions(scenes, decisions)


def _apply_material_decisions(scenes: list[dict], decisions: list[dict]) -> list[dict]:
    scenes_by_id = {scene.get("scene_id"): scene for scene in scenes}
    for decision in decisions:
        scene = scenes_by_id.get(decision.get("scene_id"))
        if not scene:
            continue

        original_stickers = {sticker.get("file", ""): sticker for sticker in scene.get("stickers", [])}
        reviewed_stickers = []
        for item in decision.get("stickers", []):
            if item.get("keep") is False:
                continue
            sticker_file = str(item.get("file", ""))
            base_sticker = original_stickers.get(sticker_file)
            if not base_sticker:
                continue

            sticker = dict(base_sticker)
            position = item.get("position", sticker.get("position", "top_right"))
            if position in VALID_MATERIAL_POSITIONS:
                sticker["position"] = position
            sticker["scale"] = _clamp_int(item.get("scale", sticker.get("scale", 180)), 120, 220)
            if item.get("reason"):
                sticker["ai_reason"] = str(item["reason"])
            reviewed_stickers.append(sticker)
        scene["stickers"] = reviewed_stickers[:1]

        prop_decision = decision.get("prop")
        if isinstance(prop_decision, dict):
            if prop_decision.get("keep") is False:
                scene["suggested_prop"] = ""
                scene.pop("suggested_prop_position", None)
                scene.pop("suggested_prop_scale", None)
            elif prop_decision.get("keep") is True:
                description = str(prop_decision.get("description") or scene.get("suggested_prop", "")).strip()
                scene["suggested_prop"] = description
                position = prop_decision.get("position", "bottom_right")
                if position in VALID_MATERIAL_POSITIONS:
                    scene["suggested_prop_position"] = position
                scene["suggested_prop_scale"] = _clamp_int(prop_decision.get("scale", 180), 120, 240)
                if prop_decision.get("reason"):
                    scene["suggested_prop_reason"] = str(prop_decision["reason"])

    return scenes


def _apply_dialogue_decisions(scenes: list[dict], decisions: list[dict]) -> list[dict]:
    scenes_by_id = {scene.get("scene_id"): scene for scene in scenes}
    for decision in decisions:
        scene = scenes_by_id.get(decision.get("scene_id"))
        if not scene:
            continue
        scene_caption = str(decision.get("scene_caption") or "").strip()
        if scene_caption:
            scene["scene_caption"] = scene_caption

        dialogues = _normalize_dialogues_for_scene(decision.get("dialogues"), "")
        if dialogues:
            scene["dialogues"] = dialogues
        if decision.get("reason"):
            scene["dialogue_reason"] = str(decision["reason"])
    return scenes


def _clamp_int(value, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = min_value
    return max(min_value, min(max_value, parsed))


def _normalize_suggested_stickers(suggested_stickers) -> list[str]:
    if isinstance(suggested_stickers, str):
        return [suggested_stickers.strip()] if suggested_stickers.strip() else []
    if not isinstance(suggested_stickers, list):
        return []

    normalized = []
    for item in suggested_stickers:
        if isinstance(item, str) and item.strip():
            normalized.append(item.strip())
        elif isinstance(item, dict):
            value = item.get("type") or item.get("name") or item.get("description")
            if value:
                normalized.append(str(value).strip())
    return [item for item in normalized if item]


def _match_relevant_stickers(
    scene_description: str,
    emotion: str,
    suggested_stickers,
) -> list[dict]:
    """Match stickers only when the script or scene gives a concrete reason."""
    suggestions = _normalize_suggested_stickers(suggested_stickers)
    if suggestions:
        return _filter_concrete_stickers(match_stickers(
            scene_description=f"{scene_description} {' '.join(suggestions)}",
            emotion=emotion,
            max_results=1,
        ))

    has_scene_cue = any(keyword in scene_description for keyword in STICKER_SCENE_KEYWORDS)
    if not has_scene_cue:
        return []

    return _filter_concrete_stickers(match_stickers(
        scene_description=scene_description,
        emotion=emotion,
        max_results=1,
    ))


def _filter_concrete_stickers(stickers: list[dict]) -> list[dict]:
    """Keep object-like stickers and drop pure decorative expression overlays."""
    filtered = []
    for sticker in stickers:
        category = sticker.get("category") or sticker.get("folder", "")
        file_name = Path(str(sticker.get("file_path", sticker.get("file", "")))).stem.lower()
        if category in DECORATIVE_STICKER_CATEGORIES:
            continue
        if category in CONCRETE_STICKER_CATEGORIES or any(
            keyword in file_name
            for keyword in (
                "phone", "hand", "book", "exam", "paper", "pen", "computer", "keyboard",
                "clock", "milk-tea", "cup", "message", "tablet",
            )
        ):
            filtered.append(sticker)
    return filtered[:1]


def _validate_suggested_prop(suggested_prop: str, scene_text: str, theme: str) -> str:
    """Drop decorative or unrelated props before they become generated overlays."""
    prop = str(suggested_prop or "").strip()
    if not prop:
        return ""

    context = f"{scene_text} {theme}".lower()
    prop_lower = prop.lower()
    if prop_lower in context or prop in scene_text or prop in theme:
        return prop

    for prop_keyword, context_keywords in PROP_RELEVANCE_KEYWORDS.items():
        if prop_keyword in prop and any(keyword.lower() in context for keyword in context_keywords):
            return prop

    return ""


def _fallback_colors(seed_text: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    seed = sum(ord(ch) for ch in seed_text)
    base = (
        70 + seed % 90,
        80 + (seed // 3) % 90,
        110 + (seed // 7) % 90,
    )
    accent = (
        180 + seed % 50,
        150 + (seed // 5) % 70,
        90 + (seed // 11) % 90,
    )
    return base, accent


def _create_fallback_background(description: str, name: str) -> Path:
    from PIL import Image, ImageDraw

    output_path = config.generated_dir / "backgrounds" / f"{name}_fallback.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base, accent = _fallback_colors(description)
    image = Image.new("RGB", (1920, 1080), base)
    draw = ImageDraw.Draw(image)

    # Simple landscape composition that reads as a deliberate background layer.
    draw.rectangle((0, 0, 1920, 280), fill=tuple(max(c - 30, 0) for c in base))
    draw.rectangle((0, 760, 1920, 1080), fill=tuple(max(c - 45, 0) for c in base))
    for i in range(7):
        x0 = 150 + i * 250
        draw.rounded_rectangle((x0, 360, x0 + 130, 560), radius=18, fill=accent)
    draw.rounded_rectangle((360, 640, 1560, 760), radius=32, fill=tuple(min(c + 35, 255) for c in base))
    image.save(output_path)
    write_asset_meta(
        output_path=output_path,
        asset_kind="background",
        description=description,
        prompt=f"fallback background: {description}",
        size="1920x1080",
        style="local fallback landscape cartoon background",
        revised_prompt=f"fallback background: {description}",
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    return output_path


def _create_fallback_prop(description: str, name: str) -> Path:
    from PIL import Image, ImageDraw

    output_path = config.generated_dir / "props" / f"{name}_fallback.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base, accent = _fallback_colors(description)
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((70, 70, 442, 442), fill=(*accent, 230), outline=(255, 255, 255, 255), width=12)
    draw.rounded_rectangle((135, 225, 377, 310), radius=30, fill=(*base, 255))
    draw.rectangle((246, 120, 266, 392), fill=(255, 255, 255, 220))
    draw.rectangle((120, 246, 392, 266), fill=(255, 255, 255, 220))
    image.save(output_path)
    write_asset_meta(
        output_path=output_path,
        asset_kind="prop",
        description=description,
        prompt=f"fallback prop: {description}",
        size="512x512",
        style="local fallback transparent prop",
        revised_prompt=f"fallback prop: {description}",
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    return output_path


def _build_sticker_item(sticker: dict, index: int, preferred_position: str = "") -> dict:
    """Create a sticker record with stable layout data for rendering."""
    category = sticker.get("category", "")
    default_positions = [
        "top_left",
        "top_right",
        "center_left",
        "center_right",
        "bottom_left",
        "bottom_right",
    ]
    if index == 0 and preferred_position:
        position = preferred_position
    else:
        position = default_positions[index % len(default_positions)]
    scale_by_category = {
        "emotion-effects": 180,
        "food-drinks": 190,
        "digital-communication": 180,
        "campus-study": 180,
        "home-daily": 190,
        "career-identity": 170,
        "plot-conflict": 180,
        "atmosphere-decor": 200,
    }
    return {
        "category": category,
        "file": str(sticker.get("file_path", sticker.get("file", ""))),
        "position": position,
        "scale": scale_by_category.get(category, 180),
    }


def _normalize_dialogues_for_scene(raw_dialogues, fallback_subtitle: str) -> list[dict]:
    """Normalize model dialogue output for HyperFrames-style cat speech captions."""
    if isinstance(raw_dialogues, dict):
        raw_dialogues = [raw_dialogues]
    if not isinstance(raw_dialogues, list):
        raw_dialogues = []

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

    if not dialogues and fallback_subtitle:
        speaker, line = _split_dialogue_line(fallback_subtitle)
        if line:
            dialogues.append({"speaker": speaker or "猫", "line": line})
    return dialogues


def _split_dialogue_line(text: str) -> tuple[str, str]:
    cleaned = str(text or "").strip()
    for sep in ("：", ":"):
        if sep in cleaned:
            speaker, _, line = cleaned.partition(sep)
            if line.strip():
                return speaker.strip(), line.strip()
    return "", cleaned


def _derive_scene_caption(description: str) -> str:
    """Fallback short scene explanation for the center-top caption."""
    text = str(description or "").strip()
    if len(text) <= 14:
        return text
    for sep in ("，", "。", "；", ",", ";"):
        if sep in text:
            first = text.split(sep, 1)[0].strip()
            if first:
                return first[:14]
    return text[:14]


def _derive_background_description(theme: str, description: str, emotion: str = "") -> str:
    """Derive a usable background prompt when the LLM omits one."""
    text = f"{theme} {description}"
    if any(kw in text for kw in ("办公室", "打工", "上班", "工位", "电脑", "键盘")):
        scene = "办公室工位"
    elif any(kw in text for kw in ("教室", "考试", "复习", "作业", "校园")):
        scene = "教室课桌"
    elif any(kw in text for kw in ("宿舍", "床", "熬夜")):
        scene = "宿舍房间"
    elif any(kw in text for kw in ("厨房", "吃", "饭", "奶茶", "外卖")):
        scene = "生活厨房餐桌"
    else:
        scene = "简洁室内场景"
    mood = f"，氛围{emotion}" if emotion else ""
    return f"{scene}{mood}，适合猫meme短视频的卡通背景，无人物无动物"


def format_storyboard_for_display(storyboard: dict) -> str:
    """将分镜脚本格式化为可读文本。"""
    lines = []
    lines.append(f"# 📋 分镜脚本")
    lines.append(f"**主题**: {storyboard.get('theme', '')}")
    lines.append(f"**剧本**: {storyboard.get('script_title', '')}")
    lines.append(f"**版本**: {storyboard.get('script_version', '')}")
    lines.append(f"**总时长**: {storyboard.get('total_duration', 0)}秒 | "
                 f"**镜头数**: {storyboard.get('scene_count', 0)}")
    lines.append("")

    for scene in storyboard.get("scenes", []):
        sid = scene["scene_id"]
        dur = scene["duration"]
        desc = scene.get("description", "")
        motion_id = scene.get("cat_motion_id", "?")
        motion_desc = scene.get("cat_motion_desc", "")
        subtitle = scene.get("subtitle", "")
        emotion = scene.get("emotion", "")
        stickers = scene.get("stickers", [])
        gen_assets = scene.get("generated_assets", [])
        fallback = scene.get("_fallback", False)

        # 镜号
        lines.append(f"### 🎞️ 镜{sid} [{dur}秒] {'🔧兜底素材' if fallback else ''}")
        lines.append(f"**描述**: {desc}")
        lines.append(f"**猫动作**: motion#{motion_id} — {motion_desc[:80]}")

        if emotion:
            lines.append(f"**情绪**: {emotion}")

        if subtitle:
            lines.append(f'**字幕**: "{subtitle}"')

        if scene.get("scene_caption"):
            lines.append(f"**分镜解释**: {scene.get('scene_caption', '')}")

        if scene.get("dialogues"):
            dialogue_text = " / ".join(
                f"{d.get('speaker', '猫')}: {d.get('line', '')}"
                for d in scene.get("dialogues", [])[:3]
                if isinstance(d, dict)
            )
            if dialogue_text:
                lines.append(f"**猫咪台词**: {dialogue_text}")

        if stickers:
            sticker_names = [Path(s["file"]).stem for s in stickers
                           if isinstance(s, dict) and "file" in s]
            lines.append(f"**贴纸**: {', '.join(sticker_names[:3])}")

        if gen_assets:
            for ga in gen_assets:
                if "error" in ga:
                    lines.append(f"**生成素材**: ⚠️ 失败 — {ga['error']}")
                else:
                    lines.append(f"**生成素材**: ✅ {Path(ga['file']).name}")

        lines.append("")

    # 缺口报告
    gaps = storyboard.get("gaps", {})
    if gaps:
        lines.append("---")
        lines.append(format_gaps_for_display(gaps))

    lines.append("")
    lines.append("💬 **你可以用自然语言调整分镜**，例如：")
    lines.append('  - "开头更抓人一些" → 调整Hook镜头')
    lines.append('  - "减少字幕，增强节奏感" → 调整字幕密度和镜头时长')
    lines.append('  - "把崩溃镜头提前" → 重排镜头顺序')
    lines.append('  - "加个奶茶贴纸" → 添加特定贴纸')

    return "\n".join(lines)
