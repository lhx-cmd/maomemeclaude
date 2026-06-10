"""素材缺口检测器 — 识别缺失素材并生成补全方案"""

from __future__ import annotations

import json
from typing import Optional

from .config import config
from .doubao_client import client
from .material_matcher import match_cat_motion, match_stickers


# 缺口检测提示词
GAP_DETECTION_PROMPT = """你是一位视频制作资源管理专家。你的任务是分析分镜脚本，识别哪些镜头存在素材缺口。

素材缺口的类型包括：
1. **背景缺失**: 需要特定场景背景但素材库中没有
2. **道具缺失**: 需要特定道具/物件但素材库中没有
3. **贴纸不足**: 需要的特效贴纸在现有库中找不到合适匹配
4. **猫动作不足**: 需要的猫动作情绪与现有素材不匹配
5. **特效缺失**: 需要的转场/动画特效无法实现

对每个缺口，提供补全建议：
- **结构重排**: 调整镜头顺序降低对缺失素材的依赖
- **文案补全**: 用文字/字幕代替画面表达
- **包装补全**: 用标题条、卖点卡片、现有贴纸替代
- **AIGC生成**: 用Seedream生成（适合：背景、道具、贴纸）
- **现有素材复用**: 裁切、重复利用、局部放大

请以JSON格式输出所有缺口和补全方案。"""


def detect_gaps(storyboard_scenes: list[dict]) -> dict:
    """检测分镜脚本中的素材缺口。

    Args:
        storyboard_scenes: 分镜列表，每个包含 scene_id, description,
                          cat_motion_id, stickers 等字段

    Returns:
        {
            "total_gaps": 3,
            "gaps": [
                {
                    "scene_id": 5,
                    "gap_type": "背景缺失",
                    "description": "...",
                    "severity": "high/medium/low",
                    "fill_strategy": "AIGC生成",
                    "fill_detail": "...",
                    "generation_prompt": "..."  # if AIGC
                }
            ],
            "fill_summary": "..."
        }
    """
    gaps = []

    for scene in storyboard_scenes:
        scene_id = scene.get("scene_id", "?")

        # 检查猫动作匹配质量
        cat_motion_id = scene.get("cat_motion_id")
        cat_score = scene.get("_match_score", 0)

        if cat_motion_id is None:
            gaps.append({
                "scene_id": scene_id,
                "gap_type": "猫动作缺失",
                "description": f"镜头{scene_id}「{scene.get('description', '')}」未匹配到合适的猫动作",
                "severity": "high",
                "fill_strategy": "现有素材复用",
                "fill_detail": "从相似情绪的猫动作中选择替代，或重复使用前面镜头中的动作素材",
                "generation_prompt": None,
            })
        elif cat_score < 3 and cat_score >= 0:
            gaps.append({
                "scene_id": scene_id,
                "gap_type": "猫动作不足",
                "description": f"镜头{scene_id}的猫动作匹配度较低(score={cat_score})",
                "severity": "medium",
                "fill_strategy": "结构重排",
                "fill_detail": "调整镜头顺序，将匹配度高的猫动作放到更核心的位置",
                "generation_prompt": None,
            })

        # 情绪本身不再构成贴纸缺口。贴纸只用于明确的剧情物件/交互，
        # 避免自动补出眼睛、表情脸等无意义装饰。

        # 检查是否需要背景生成
        suggested_bg = scene.get("suggested_background", "")
        if suggested_bg and not _scene_has_asset(scene, "背景"):
            gaps.append({
                "scene_id": scene_id,
                "gap_type": "背景缺失",
                "description": f"镜头{scene_id}需要「{suggested_bg}」背景",
                "severity": "medium",
                "fill_strategy": "AIGC生成",
                "fill_detail": f"使用Seedream生成「{suggested_bg}」卡通背景",
                "generation_prompt": f"A simple cartoon background of {suggested_bg}, "
                                    f"soft colors, minimal detail, flat illustration style, "
                                    f"suitable as video background, no characters",
            })

        # 检查是否需要道具生成
        suggested_prop = scene.get("suggested_prop", "")
        if suggested_prop and not _scene_has_asset(scene, "道具"):
            gaps.append({
                "scene_id": scene_id,
                "gap_type": "道具缺失",
                "description": f"镜头{scene_id}需要「{suggested_prop}」道具",
                "severity": "medium",
                "fill_strategy": "AIGC生成",
                "fill_detail": f"使用Seedream生成「{suggested_prop}」卡通道具",
                "generation_prompt": f"A cute cartoon prop of {suggested_prop}, "
                                    f"isolated object, clean edges, sticker style, "
                                    f"suitable for cat meme video overlay",
            })

    # 生成总结
    high_gaps = [g for g in gaps if g["severity"] == "high"]
    medium_gaps = [g for g in gaps if g["severity"] == "medium"]
    low_gaps = [g for g in gaps if g["severity"] == "low"]

    fill_summary_parts = []
    if high_gaps:
        fill_summary_parts.append(f"{len(high_gaps)}个高优先级缺口（需立即处理）")
    if medium_gaps:
        fill_summary_parts.append(f"{len(medium_gaps)}个中优先级缺口")
    if low_gaps:
        fill_summary_parts.append(f"{len(low_gaps)}个低优先级缺口")
    if not fill_summary_parts:
        fill_summary_parts.append("✅ 所有镜头素材充足")

    return {
        "total_gaps": len(gaps),
        "high_priority": len(high_gaps),
        "medium_priority": len(medium_gaps),
        "low_priority": len(low_gaps),
        "gaps": gaps,
        "fill_summary": "，".join(fill_summary_parts),
    }


def _scene_has_asset(scene: dict, asset_label: str) -> bool:
    if asset_label == "背景" and (scene.get("background_file") or scene.get("background")):
        return True
    return any(
        _asset_matches_label(asset, asset_label)
        for asset in scene.get("generated_assets", [])
        if isinstance(asset, dict) and asset.get("file")
    )


def _asset_matches_label(asset: dict, asset_label: str) -> bool:
    asset_type = str(asset.get("type", ""))
    if asset_label in asset_type:
        return True
    if asset.get("source") == "user":
        kind = str(asset.get("kind", ""))
        if asset_label == "背景" and ("背景" in asset_type or kind == "background"):
            return True
        if asset_label == "道具" and ("道具" in asset_type or kind == "prop"):
            return True
        if asset_label == "贴纸" and ("贴纸" in asset_type or kind == "sticker"):
            return True
    return False


def format_gaps_for_display(gap_report: dict) -> str:
    """将缺口报告格式化为可读文本。"""
    lines = []
    total = gap_report.get("total_gaps", 0)

    if total == 0:
        lines.append("✅ **素材检查**: 所有镜头素材充足，无需补全")
        return "\n".join(lines)

    lines.append(f"⚠️ **素材缺口检测**: {gap_report.get('fill_summary', '')}")
    lines.append("")

    for gap in gap_report.get("gaps", []):
        severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        icon = severity_icon.get(gap["severity"], "⚪")
        lines.append(
            f"{icon} 镜{gap['scene_id']} [{gap['gap_type']}]: "
            f"{gap['description']}"
        )
        lines.append(f"   补全策略: {gap['fill_strategy']} — {gap['fill_detail']}")
        if gap.get("generation_prompt"):
            lines.append(f"   🎨 Seedream prompt: {gap['generation_prompt'][:80]}...")
        lines.append("")

    return "\n".join(lines)
