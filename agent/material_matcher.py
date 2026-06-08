"""素材匹配器 — 根据场景描述匹配猫动作和贴纸"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .config import config
from .generated_asset_library import asset_index_context
from .utils import load_cat_motions, load_sticker_catalog, find_sticker_files


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
