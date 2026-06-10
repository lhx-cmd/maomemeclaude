"""Lightweight descriptions for user-uploaded materials."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .config import config
from .doubao_client import client
from .utils import extract_video_frames, get_video_info


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv"}

BACKGROUND_WORDS = ("background", "bg", "office", "room", "classroom", "dorm", "meeting", "背景", "办公室", "会议室", "教室", "宿舍")
PROP_WORDS = ("coffee", "cup", "phone", "book", "laptop", "computer", "keyboard", "奶茶", "咖啡", "手机", "书", "电脑", "键盘")
STICKER_WORDS = ("sticker", "emoji", "bubble", "贴纸", "表情", "气泡")
CAT_MOTION_WORDS = ("cat", "motion", "meme", "猫", "动作")
SOUND_WORDS = ("audio", "sound", "music", "voice", "音频", "声音", "音乐")

USER_MATERIAL_ANALYSIS_PROMPT = """你是猫meme短视频素材分析 agent。请观察用户上传猫 meme 视频的关键帧，把它分析成和 assets/cat-motions/descriptions.json 中单个 motion 条目一致的结构。

重点判断：
- 这是不是猫meme动作素材。
- 猫的动作、情绪、适用剧情场景。
- 如果素材不适合某些剧情，也写入 motion_tags.avoid。
- description 要像本地 cat-motions/descriptions.json 一样客观描述画面、动作幅度、表情和循环状态。

只返回 JSON：
{
  "asset_kind": "cat_motion",
  "description": "一句中文动作描述",
  "intended_uses": ["猫动作"],
  "motion_tags": {
    "actions": ["动作"],
    "emotions": ["情绪"],
    "contexts": ["场景"],
    "avoid": ["不适合的用途"]
  },
  "search_keywords": ["关键词"]
}
"""


def build_user_material_index(material_paths: list[str] | None) -> dict[str, Any]:
    """Analyze uploaded materials into a structured per-session index."""
    paths = material_paths or []
    return {
        "version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "materials": [_describe_material(Path(str(path))) for path in paths],
    }


def build_user_motion_catalog(material_index: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Convert indexed uploaded cat videos into selectable motion catalog entries."""
    if not isinstance(material_index, dict):
        return {}
    catalog: dict[str, dict[str, Any]] = {}
    motion_index = 0
    for item in material_index.get("materials", []) or []:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file") or "").strip()
        if not file_path:
            continue
        material_type = str(item.get("type") or _material_type(Path(file_path)))
        asset_kind = str(item.get("asset_kind") or "")
        if material_type != "video" and asset_kind != "cat_motion":
            continue
        if asset_kind and asset_kind != "cat_motion":
            continue
        entry = _cat_motion_entry_for_item(item, Path(file_path))
        tags = dict(entry.get("motion_tags", {}))
        item_tags = item.get("motion_tags", {})
        if isinstance(item_tags, dict) and isinstance(item_tags.get("roles"), list):
            roles = [str(role) for role in item_tags.get("roles", []) if str(role).strip()]
            if roles:
                tags["roles"] = roles
        motion_id = f"user:{motion_index}"
        catalog[motion_id] = {
            "motion_id": motion_id,
            "description": entry["description"],
            "motion_tags": tags,
            "file_path": file_path,
            "source": "user",
            "name": item.get("name") or Path(file_path).name,
            "search_keywords": item.get("search_keywords", []),
        }
        motion_index += 1
    return catalog


def describe_user_materials(
    material_paths: list[str] | None,
    material_index: dict[str, Any] | None = None,
) -> str:
    """Return a compact, model-readable description of uploaded materials."""
    if not material_paths:
        return "## 用户上传素材\n无用户上传素材"

    indexed_by_file = _index_by_file(material_index)
    lines = []
    motion_catalog = build_user_motion_catalog(material_index)
    if motion_catalog:
        lines.extend([
            "## 用户猫动作素材库（优先使用）",
            "这些条目与本地 assets/cat-motions/descriptions.json 的单个 motion 描述同构。剧本和分镜应优先围绕这些 user:* 动作素材设计；只有用户动作无法表达时，才用本地素材补充。",
        ])
        for motion_id, item in motion_catalog.items():
            tags = item.get("motion_tags", {}) if isinstance(item.get("motion_tags"), dict) else {}
            actions = "、".join(tags.get("actions", [])[:4])
            emotions = "、".join(tags.get("emotions", [])[:4])
            contexts = "、".join(tags.get("contexts", [])[:4])
            avoid = "、".join(tags.get("avoid", [])[:3])
            detail = (
                f"- **{motion_id}**: {item.get('description', '')} | "
                f"文件: {item.get('file_path', '')}"
            )
            if actions:
                detail += f" | 动作: {actions}"
            if emotions:
                detail += f" | 情绪: {emotions}"
            if contexts:
                detail += f" | 场景: {contexts}"
            if avoid:
                detail += f" | 避免: {avoid}"
            lines.append(detail)
        lines.append("")

    lines.extend([
        "## 用户上传素材（优先使用）",
        "优先使用用户上传素材，围绕这些素材设计剧情、场景、道具和动作；只有用户素材无法表达剧情时，才使用本地素材库。",
    ])
    for index, material in enumerate(material_paths, 1):
        path = Path(str(material))
        indexed = indexed_by_file.get(str(material), {})
        material_type = str(indexed.get("type") or _material_type(path))
        uses = indexed.get("intended_uses") or _infer_uses(path, material_type)
        lines.append(
            f"{index}. {path.name} | 类型: {material_type} | 可用于: {', '.join(uses)} | 路径: {material}"
        )
        description = str(indexed.get("description") or "").strip()
        if description:
            lines.append(f"   视觉描述: {description}")
        tags = indexed.get("motion_tags", {})
        if isinstance(tags, dict):
            tag_lines = []
            for label, key in (("动作", "actions"), ("情绪", "emotions"), ("场景", "contexts"), ("角色", "roles")):
                values = tags.get(key, [])
                if isinstance(values, list) and values:
                    tag_lines.append(f"{label}: {'、'.join(str(value) for value in values[:5])}")
            if tag_lines:
                lines.append(f"   {' | '.join(tag_lines)}")
    return "\n".join(lines)


def _describe_material(path: Path) -> dict[str, Any]:
    material_type = _material_type(path)
    base = {
        "file": str(path),
        "name": path.name,
        "type": material_type,
        "asset_kind": _asset_kind_for_path(path, material_type),
        "intended_uses": _infer_uses(path, material_type),
        "description": _fallback_description(path, material_type),
        "analysis_mode": "fallback",
    }
    if material_type == "video":
        base["cat_motion_entry"] = _fallback_cat_motion_entry(path, base)
        base.update(_analyze_video_material(path, base))
    return base


def _analyze_video_material(path: Path, base: dict[str, Any]) -> dict[str, Any]:
    try:
        info = get_video_info(path)
        frames = extract_video_frames(
            path,
            interval=max(0.5, config.frame_interval_seconds),
            max_frames=min(4, config.max_analysis_frames),
        )
        if not frames:
            return {"video_info": info}
        analysis = client.chat_vision_json(
            system_prompt=USER_MATERIAL_ANALYSIS_PROMPT,
            user_text=(
                f"请分析这个用户上传猫meme素材：{path.name}。"
                f"视频时长约{info.get('duration_seconds') or 0:.1f}秒。"
                "请输出适合后续分镜选角的结构化 JSON。"
            ),
            image_paths=frames,
            temperature=0.2,
            max_tokens=1200,
            timeout=120,
        )
        if not isinstance(analysis, dict):
            return {"video_info": info}
        return _normalize_visual_material_analysis(analysis, base, info)
    except Exception as exc:
        return {
            "analysis_error": str(exc),
        }


def _normalize_visual_material_analysis(
    analysis: dict[str, Any],
    base: dict[str, Any],
    info: dict[str, Any],
) -> dict[str, Any]:
    tags = analysis.get("motion_tags", {})
    if not isinstance(tags, dict):
        tags = {}
    entry = _normalize_cat_motion_entry(analysis, base)
    return {
        "asset_kind": str(analysis.get("asset_kind") or base.get("asset_kind") or "cat_motion"),
        "description": entry["description"],
        "intended_uses": _string_list(analysis.get("intended_uses")) or base.get("intended_uses", []),
        "motion_tags": {
            "actions": entry["motion_tags"]["actions"],
            "emotions": entry["motion_tags"]["emotions"],
            "contexts": entry["motion_tags"]["contexts"],
            "roles": _string_list(tags.get("roles")),
            "avoid": entry["motion_tags"]["avoid"],
        },
        "cat_motion_entry": entry,
        "search_keywords": _string_list(analysis.get("search_keywords")),
        "video_info": info,
        "analysis_mode": "vision",
        "model": config.model,
    }


def _normalize_cat_motion_entry(analysis: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    tags = analysis.get("motion_tags", {})
    if not isinstance(tags, dict):
        tags = {}
    fallback_entry = base.get("cat_motion_entry", {})
    if not isinstance(fallback_entry, dict):
        fallback_entry = {}
    fallback_tags = fallback_entry.get("motion_tags", {}) if isinstance(fallback_entry, dict) else {}
    return {
        "description": str(
            analysis.get("description")
            or fallback_entry.get("description")
            or base.get("description")
            or ""
        ).strip(),
        "motion_tags": {
            "actions": _string_list(tags.get("actions")) or _string_list(fallback_tags.get("actions")),
            "emotions": _string_list(tags.get("emotions")) or _string_list(fallback_tags.get("emotions")),
            "contexts": _string_list(tags.get("contexts")) or _string_list(fallback_tags.get("contexts")),
            "avoid": _string_list(tags.get("avoid")) or _string_list(fallback_tags.get("avoid")),
        },
    }


def _cat_motion_entry_for_item(item: dict[str, Any], path: Path) -> dict[str, Any]:
    entry = item.get("cat_motion_entry")
    if isinstance(entry, dict) and entry.get("description"):
        tags = entry.get("motion_tags", {}) if isinstance(entry.get("motion_tags"), dict) else {}
        return {
            "description": str(entry.get("description") or path.name).strip(),
            "motion_tags": {
                "actions": _string_list(tags.get("actions")),
                "emotions": _string_list(tags.get("emotions")),
                "contexts": _string_list(tags.get("contexts")),
                "avoid": _string_list(tags.get("avoid")),
            },
        }
    tags = item.get("motion_tags", {}) if isinstance(item.get("motion_tags"), dict) else {}
    return {
        "description": str(item.get("description") or path.name).strip(),
        "motion_tags": {
            "actions": _string_list(tags.get("actions")),
            "emotions": _string_list(tags.get("emotions")),
            "contexts": _string_list(tags.get("contexts")),
            "avoid": _string_list(tags.get("avoid")),
        },
    }


def _fallback_cat_motion_entry(path: Path, base: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": str(base.get("description") or path.name).strip(),
        "motion_tags": {
            "actions": [],
            "emotions": [],
            "contexts": [],
            "avoid": [],
        },
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _index_by_file(material_index: dict[str, Any] | None) -> dict[str, dict]:
    if not isinstance(material_index, dict):
        return {}
    result = {}
    for item in material_index.get("materials", []) or []:
        if isinstance(item, dict) and item.get("file"):
            result[str(item["file"])] = item
    return result


def _asset_kind_for_path(path: Path, material_type: str) -> str:
    if material_type == "video":
        return "cat_motion"
    if material_type == "image":
        uses = _infer_uses(path, material_type)
        if "背景" in uses:
            return "background"
        if "道具" in uses:
            return "prop"
        return "sticker"
    return "reference"


def _fallback_description(path: Path, material_type: str) -> str:
    uses = "、".join(_infer_uses(path, material_type))
    return f"{path.name}，根据文件名推断可用于{uses}"


def _material_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS or _looks_like_upload_video(path):
        return "video"
    return "unknown"


def _infer_uses(path: Path, material_type: str) -> list[str]:
    name = path.stem.lower()
    if material_type == "image":
        uses = []
        if _has_any(name, BACKGROUND_WORDS):
            uses.append("背景")
        if _has_any(name, PROP_WORDS):
            uses.append("道具")
        if _has_any(name, STICKER_WORDS):
            uses.append("贴纸")
        if not uses:
            uses = ["背景", "道具", "贴纸"]
        return uses

    if material_type == "video":
        uses = []
        if _has_any(name, CAT_MOTION_WORDS):
            uses.append("猫动作")
        if _has_any(name, SOUND_WORDS):
            uses.append("音效")
        uses.append("参考片段")
        if not any(use in uses for use in ("猫动作", "音效")):
            uses.insert(0, "猫动作")
        return uses

    return ["参考素材"]


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word.lower() in text for word in words)


def _looks_like_upload_video(path: Path) -> bool:
    name = path.name.lower()
    return any(
        token in name
        for token in ("_mat_mp4", "_mat_mov", "_mat_webm", "_mat_mkv", "_mat_avi", "uploaded_mp4")
    )
