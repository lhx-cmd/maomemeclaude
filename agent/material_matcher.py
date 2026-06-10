"""素材匹配器 — 根据场景描述匹配猫动作和贴纸"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .config import config
from .generated_asset_library import asset_index_context
from .utils import load_cat_motions, load_sticker_catalog, find_sticker_files


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv"}

STICKER_FILE_KEYWORDS = {
    "手机": ["phone", "phone-in-hand", "cartoon-phone"],
    "玩手机": ["phone-in-hand", "phone"],
    "刷视频": ["phone-in-hand", "phone"],
    "聊天": ["phone", "phone-in-hand"],
    "消息": ["phone", "phone-in-hand"],
    "通知": ["phone", "phone-in-hand"],
    "电脑": ["computer", "keyboard"],
    "办公": ["computer", "keyboard", "phone"],
    "补考": ["exam", "paper", "book", "pen"],
    "考试": ["exam", "paper", "book", "pen"],
    "试卷": ["exam", "paper"],
    "翻书": ["book", "pen"],
    "作业": ["book", "paper", "pen"],
    "闹钟": ["clock"],
    "迟到": ["clock"],
    "奶茶": ["milk", "tea", "cup"],
    "外卖": ["food", "drink"],
}

BACKGROUND_CUES = ("背景", "办公室", "工位", "会议室", "教室", "宿舍", "茶水间", "卧室", "通勤", "车内", "background", "office", "room", "meeting", "classroom", "dorm")
PROP_CUES = ("咖啡", "奶茶", "杯", "手机", "电脑", "键盘", "书", "试卷", "笔", "闹钟", "coffee", "tea", "cup", "phone", "computer", "keyboard", "book", "paper", "pen", "clock")
STICKER_CUES = ("贴纸", "表情", "气泡", "消息", "通知", "sticker", "emoji", "bubble", "message")
CAT_MOTION_CUES = ("猫", "动作", "meme", "cat", "motion")


def match_user_materials(
    scene: dict,
    user_materials: list[str] | None,
    user_material_index: dict[str, Any] | None = None,
) -> list[dict]:
    """Match user-uploaded files to a scene before local/AIGC assets."""
    if not user_materials:
        return []

    scene_text = " ".join(
        str(scene.get(key, ""))
        for key in ("description", "subtitle", "emotion", "suggested_background", "suggested_prop")
        if scene.get(key)
    ).lower()
    matches = []
    used_files = set()
    indexed_match = _best_indexed_user_cat_motion(scene_text, user_materials, user_material_index)
    if indexed_match:
        matches.append(indexed_match)
        used_files.add(indexed_match["file"])

    for material in user_materials:
        if material in used_files:
            continue
        path = Path(str(material))
        suffix = path.suffix.lower()
        name = path.stem.lower()
        if suffix in IMAGE_EXTENSIONS:
            if _material_matches(name, scene_text, scene.get("suggested_background", ""), BACKGROUND_CUES):
                matches.append(_user_match("background", material, "文件名与背景/场景语义匹配"))
                used_files.add(material)
                continue
            if _material_matches(name, scene_text, scene.get("suggested_prop", ""), PROP_CUES):
                matches.append(_user_match("prop", material, "文件名与道具语义匹配"))
                used_files.add(material)
                continue
            if _material_matches(name, scene_text, "", STICKER_CUES):
                matches.append(_user_match("sticker", material, "文件名与贴纸/信息提示语义匹配"))
                used_files.add(material)
        elif suffix in VIDEO_EXTENSIONS or _looks_like_upload_video(path):
            if _material_matches(name, scene_text, "", CAT_MOTION_CUES):
                matches.append(_user_match("cat_motion", material, "文件名与猫动作语义匹配"))
                used_files.add(material)
            elif _material_matches(name, scene_text, "", ("audio", "sound", "voice", "音频", "声音")):
                matches.append(_user_match("audio", material, "文件名与音频语义匹配"))
                used_files.add(material)
            else:
                matches.append(_user_match("cat_motion", material, "用户上传视频优先作为猫动作素材"))
                used_files.add(material)

    return _dedupe_user_matches(matches, used_files)


def _best_indexed_user_cat_motion(
    scene_text: str,
    user_materials: list[str],
    user_material_index: dict[str, Any] | None,
) -> dict | None:
    indexed = _indexed_materials_by_file(user_material_index)
    if not indexed:
        return None

    candidates = []
    for material in user_materials:
        item = indexed.get(str(material))
        if not item:
            continue
        path = Path(str(material))
        material_type = str(item.get("type") or _material_type_from_path(path))
        asset_kind = str(item.get("asset_kind") or "")
        if material_type != "video" and asset_kind != "cat_motion":
            continue
        if asset_kind and asset_kind != "cat_motion":
            continue
        score = _score_indexed_material(scene_text, item)
        candidates.append((score, material, item))

    if not candidates:
        return None
    candidates.sort(key=lambda value: value[0], reverse=True)
    best_score, file_path, item = candidates[0]
    if best_score <= 0:
        return None
    description = _indexed_motion_description(item, Path(str(file_path)))
    return {
        "kind": "cat_motion",
        "file": str(file_path),
        "motion_id": str(item.get("motion_id") or _motion_id_for_indexed_file(user_material_index, str(file_path)) or "user"),
        "source": "user",
        "reason": f"视觉描述匹配：{description[:40]}",
        "description": description,
        "score": best_score,
        "motion_tags": item.get("motion_tags", {}),
    }


def _motion_id_for_indexed_file(user_material_index: dict[str, Any] | None, file_path: str) -> str:
    if not isinstance(user_material_index, dict):
        return ""
    motion_index = 0
    for item in user_material_index.get("materials", []) or []:
        if not isinstance(item, dict):
            continue
        material_file = str(item.get("file") or "").strip()
        if not material_file:
            continue
        path = Path(material_file)
        material_type = str(item.get("type") or _material_type_from_path(path))
        asset_kind = str(item.get("asset_kind") or "")
        if material_type != "video" and asset_kind != "cat_motion":
            continue
        if asset_kind and asset_kind != "cat_motion":
            continue
        current_id = f"user:{motion_index}"
        if material_file == file_path:
            return current_id
        motion_index += 1
    return ""


def _indexed_materials_by_file(user_material_index: dict[str, Any] | None) -> dict[str, dict]:
    if not isinstance(user_material_index, dict):
        return {}
    result = {}
    for item in user_material_index.get("materials", []) or []:
        if isinstance(item, dict) and item.get("file"):
            result[str(item["file"])] = item
    return result


def _score_indexed_material(scene_text: str, item: dict) -> int:
    searchable = [_indexed_motion_description(item)]
    entry = item.get("cat_motion_entry", {})
    entry_tags = entry.get("motion_tags", {}) if isinstance(entry, dict) else {}
    tags = item.get("motion_tags", {})
    if isinstance(tags, dict):
        for values in tags.values():
            if isinstance(values, list):
                searchable.extend(str(value) for value in values)
            elif values:
                searchable.append(str(values))
    if isinstance(entry_tags, dict):
        for values in entry_tags.values():
            if isinstance(values, list):
                searchable.extend(str(value) for value in values)
            elif values:
                searchable.append(str(values))
    keywords = item.get("search_keywords", [])
    if isinstance(keywords, list):
        searchable.extend(str(keyword) for keyword in keywords)
    material_text = " ".join(searchable).lower()
    score = 0
    for token in _scene_tokens(scene_text):
        if token and token in material_text:
            score += 3 if len(token) >= 2 else 1
    for cue_group in (
        ("焦虑", "慌张", "着急", "迟到", "赶路", "堵车", "骑车"),
        ("老板", "领导", "讲话", "催", "开会", "布置"),
        ("撒娇", "可爱", "求饶", "女友", "恋爱"),
        ("崩溃", "哭", "破防", "无语"),
    ):
        if any(cue in scene_text for cue in cue_group) and any(cue in material_text for cue in cue_group):
            score += 5
    avoid = []
    if isinstance(tags, dict) and isinstance(tags.get("avoid"), list):
        avoid = [str(item).lower() for item in tags.get("avoid", [])]
    if any(token and token in scene_text for token in avoid):
        score -= 10
    return score


def _indexed_motion_description(item: dict, path: Path | None = None) -> str:
    entry = item.get("cat_motion_entry", {})
    if isinstance(entry, dict) and entry.get("description"):
        return str(entry.get("description") or "").strip()
    if item.get("description"):
        return str(item.get("description") or "").strip()
    return path.name if path else ""


def _scene_tokens(text: str) -> list[str]:
    tokens = []
    for raw in text.replace("，", " ").replace("。", " ").replace("、", " ").split():
        raw = raw.strip().lower()
        if raw:
            tokens.append(raw)
    chinese_keywords = (
        "焦虑", "慌张", "着急", "迟到", "赶路", "堵车", "骑车", "摩托", "老板", "领导",
        "讲话", "开会", "催", "撒娇", "可爱", "求饶", "女友", "恋爱", "崩溃", "哭",
        "破防", "无语", "放松", "开心", "工作", "办公", "电脑", "奶茶", "咖啡",
    )
    tokens.extend(keyword for keyword in chinese_keywords if keyword in text)
    return tokens


def _material_type_from_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS or _looks_like_upload_video(path):
        return "video"
    return "unknown"


def _user_match(kind: str, file_path: str, reason: str) -> dict:
    return {
        "kind": kind,
        "file": file_path,
        "source": "user",
        "reason": reason,
    }


def _material_matches(name: str, scene_text: str, target_text: str, cues: tuple[str, ...]) -> bool:
    combined = f"{scene_text} {target_text}".lower()
    for cue in cues:
        cue_lower = cue.lower()
        if cue_lower in name and (cue_lower in combined or _semantic_cue_matches(cue_lower, combined)):
            return True
    return False


def _semantic_cue_matches(cue: str, text: str) -> bool:
    groups = [
        ("office", ("办公室", "工位", "办公", "会议")),
        ("background", ("背景", "场景")),
        ("room", ("房间", "宿舍", "卧室", "会议室", "茶水间")),
        ("coffee", ("咖啡", "续命")),
        ("tea", ("奶茶", "饮料")),
        ("cup", ("杯", "咖啡", "奶茶", "饮料")),
        ("phone", ("手机", "消息", "通知", "聊天")),
        ("computer", ("电脑", "办公", "工位")),
        ("keyboard", ("键盘", "电脑", "办公")),
    ]
    for token, aliases in groups:
        if cue == token and any(alias in text for alias in aliases):
            return True
    return False


def _dedupe_user_matches(matches: list[dict], used_files: set[str]) -> list[dict]:
    del used_files
    selected = []
    seen_kinds = set()
    for match in matches:
        kind = match["kind"]
        if kind in seen_kinds and kind in {"background", "prop", "cat_motion", "audio"}:
            continue
        selected.append(match)
        seen_kinds.add(kind)
    return selected


def _looks_like_upload_video(path: Path) -> bool:
    name = path.name.lower()
    return any(
        token in name
        for token in ("_mat_mp4", "_mat_mov", "_mat_webm", "_mat_mkv", "_mat_avi", "uploaded_mp4")
    )


def match_cat_motion(
    scene_description: str,
    required_emotion: str = "",
    required_context: str = "",
    required_action: str = "",
) -> Optional[dict]:
    """根据场景描述匹配最合适的猫动作素材。

    匹配策略：
    1. 关键词在 description、motion_tags 中的出现次数
    2. required_* 参数提供硬性约束
    3. 返回得分最高的匹配

    Args:
        scene_description: 场景描述文本
        required_emotion: 需要的情绪标签（如 "震惊"、"崩溃"）
        required_context: 需要的场景标签（如 "办公"、"校园"）
        required_action: 需要的动作标签（如 "敲电脑"、"瞪眼"）

    Returns:
        {"motion_id": "15", "file_path": Path, "description": "...", "tags": {...}, "score": 5}
    """
    cat_motions = load_cat_motions()
    catalog = list(cat_motions.items())

    best_match = None
    best_score = -1

    # 合并搜索文本
    search_text = f"{scene_description} {required_emotion} {required_context} {required_action}".lower()

    for motion_id, motion_data in catalog:
        score = 0
        tags = motion_data.get("motion_tags", {})
        desc = motion_data.get("description", "").lower()

        # 检查 avoid 标签（硬性排除）
        avoid_tags = [t.lower() for t in tags.get("avoid", [])]
        should_skip = False
        for avoid in avoid_tags:
            if avoid in search_text and "默认避用" not in avoid:
                should_skip = True
                break
        if should_skip:
            continue

        # 描述匹配
        desc_words = set(desc)
        search_words = set(search_text.split())
        score += len(desc_words & search_words)

        # 标签匹配
        all_tag_values = []
        for tag_list in tags.values():
            if isinstance(tag_list, list):
                all_tag_values.extend([t.lower() for t in tag_list])

        for tag_val in all_tag_values:
            if tag_val in search_text:
                score += 2
            # 部分匹配
            for sw in search_words:
                if len(sw) >= 2 and sw in tag_val:
                    score += 0.5

        # 情绪匹配加权
        if required_emotion:
            emotions = [e.lower() for e in tags.get("emotions", [])]
            for e in emotions:
                if required_emotion.lower() in e or e in required_emotion.lower():
                    score += 5

        # 场景匹配加权
        if required_context:
            contexts = [c.lower() for c in tags.get("contexts", [])]
            for c in contexts:
                if required_context.lower() in c or c in required_context.lower():
                    score += 5

        # 动作匹配加权
        if required_action:
            actions = [a.lower() for a in tags.get("actions", [])]
            for a in actions:
                if required_action.lower() in a or a in required_action.lower():
                    score += 5

        if score > best_score:
            best_score = score
            best_match = {
                "motion_id": motion_id,
                "file_path": config.cat_motions_dir / f"{motion_id}.mp4",
                "description": motion_data.get("description", ""),
                "tags": tags,
                "score": score,
            }

    return best_match


def match_stickers(
    scene_description: str,
    emotion: str = "",
    mood: str = "",
    max_results: int = 3,
) -> list[dict]:
    """根据场景和情绪匹配合适的贴纸。

    Args:
        scene_description: 场景描述
        emotion: 情绪关键词（如 "震惊"、"无语"、"崩溃"）
        mood: 氛围关键词（如 "温馨"、"紧张"、"搞笑"）
        max_results: 最多返回几个贴纸

    Returns:
        [{"category": "...", "folder": "...", "file_path": Path, "description": "..."}, ...]
    """
    catalog = load_sticker_catalog()

    # 情绪到贴纸分类的映射
    emotion_category_map = {
        "震惊": ["emotion-effects", "digital-communication"],
        "无语": ["emotion-effects"],
        "崩溃": ["emotion-effects", "medical-emergency"],
        "生气": ["emotion-effects", "plot-conflict"],
        "开心": ["emotion-effects", "atmosphere-decor"],
        "可爱": ["emotion-effects", "atmosphere-decor"],
        "害怕": ["emotion-effects", "medical-emergency"],
        "尴尬": ["emotion-effects"],
        "疑问": ["emotion-effects"],
        "委屈": ["emotion-effects"],
        "温馨": ["atmosphere-decor", "home-daily"],
        "搞笑": ["emotion-effects", "plot-conflict"],
        "紧张": ["emotion-effects", "plot-conflict", "medical-emergency"],
    }

    # 场景到贴纸分类的映射
    context_category_map = {
        "办公": ["digital-communication", "career-identity"],
        "学校": ["campus-study"],
        "考试": ["campus-study", "medical-emergency"],
        "家里": ["home-daily"],
        "吃饭": ["food-drinks"],
        "通勤": ["transport-travel"],
        "医院": ["medical-emergency"],
        "旅行": ["transport-travel"],
        "吵架": ["plot-conflict", "emotion-effects"],
        "反转": ["plot-conflict", "emotion-effects"],
    }

    # 确定要搜索的分类
    search_folders = set()

    if emotion:
        for emo_key, folders in emotion_category_map.items():
            if emo_key in emotion or emotion in emo_key:
                search_folders.update(folders)

    if mood:
        for mood_key, folders in emotion_category_map.items():
            if mood_key in mood or mood in mood_key:
                search_folders.update(folders)

    for ctx_key, folders in context_category_map.items():
        if ctx_key in scene_description:
            search_folders.update(folders)

    # 如果没有匹配到分类，搜索所有
    if not search_folders:
        search_folders = {cat["folder"] for cat in catalog}

    results = []
    for folder in search_folders:
        files = find_sticker_files(folder)
        ranked_files = _rank_sticker_files(files, scene_description)
        for f in ranked_files[:8]:  # 每个分类最多取8个候选，再统一按相关性截断
            results.append({
                "category": folder,
                "folder": folder,
                "file_path": f,
                "description": f.stem,
                "score": _sticker_file_score(f, scene_description),
            })
            if len(results) >= max_results * 3:
                break
        if len(results) >= max_results * 3:
            break

    # 简单去重和限制
    seen = set()
    unique_results = []
    for r in results:
        key = r["file_path"].name
        if key not in seen:
            seen.add(key)
            unique_results.append(r)

    unique_results.sort(key=lambda r: r.get("score", 0), reverse=True)
    return unique_results[:max_results]


def _rank_sticker_files(files: list[Path], scene_description: str) -> list[Path]:
    return sorted(files, key=lambda path: _sticker_file_score(path, scene_description), reverse=True)


def _sticker_file_score(path: Path, scene_description: str) -> float:
    name = path.stem.lower()
    score = 0.0
    for cue, file_keywords in STICKER_FILE_KEYWORDS.items():
        if cue in scene_description:
            for priority, keyword in enumerate(file_keywords):
                if keyword in name:
                    score += 10 - priority
    if "phone-in-hand" in name and any(cue in scene_description for cue in ("玩手机", "刷视频", "聊天", "消息", "手机")):
        score += 8
    if "mouse" in name and not any(cue in scene_description for cue in ("鼠标", "电脑", "游戏", "办公")):
        score -= 6
    if "meme-face" in name or "eyes" in name:
        score -= 8
    return score


def build_material_context() -> str:
    """构建素材上下文字符串，用于发送给 LLM 做剧本生成。"""
    cat_motions = load_cat_motions()
    sticker_catalog = load_sticker_catalog()

    # 猫动作摘要
    motion_lines = ["## 可用猫动作素材 (cat-motions)"]
    for mid, data in sorted(cat_motions.items(), key=lambda x: int(x[0])):
        tags = data.get("motion_tags", {})
        emotions = ", ".join(tags.get("emotions", [])[:3])
        contexts = ", ".join(tags.get("contexts", [])[:3])
        motion_lines.append(
            f"- **motion#{mid}**: {data['description'][:60]}... "
            f"[情绪: {emotions}] [场景: {contexts}]"
        )

    # 贴纸摘要
    sticker_lines = ["\n## 可用贴纸分类 (stickers)"]
    for cat in sticker_catalog:
        sticker_lines.append(
            f"- **{cat['folder']}** ({cat['category']}): {cat['count']}个, "
            f"用途: {cat['description'][:80]}"
        )

    generated_context = asset_index_context("background", limit=30)
    return "\n".join(motion_lines) + "\n" + "\n".join(sticker_lines) + "\n" + generated_context
