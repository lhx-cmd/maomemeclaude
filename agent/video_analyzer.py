"""爆款视频分析 — 帧提取 + 豆包视觉理解"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .config import config
from .doubao_client import client
from .utils import (
    extract_video_frames,
    get_video_info,
    load_json,
    save_json,
)


# 爆款结构分析的系统提示词
STRUCTURE_ANALYSIS_PROMPT = """你是一位专业的短视频结构分析师。你的任务是通过观察视频的帧序列，分析该视频的爆款结构。

请从以下维度分析这个短视频：

1. **脚本/段落结构**：
   - hook（开头吸引）：时间位置、类型（震惊/疑问/反转/共鸣/冲突）、具体描述
   - development（中段展开）：各段落的时间范围、叙事类型（铺垫/对比/递进/举例）
   - climax（高潮）：时间位置、情绪类型、描述
   - cta（结尾引导）：时间位置、引导类型（互动/关注/共鸣升华）、描述

2. **节奏结构**：
   - 预估镜头切换频率（高/中/低）
   - 整体节奏曲线（如：快-慢-快、慢-快-更快）
   - 高潮在视频中的相对位置（0-1之间）

3. **包装结构**：
   - 字幕样式（字体风格、颜色、位置、描边）
   - 贴纸/特效类型和使用频率
   - 转场方式
   - 封面风格

4. **叙事模式**：整体叙事弧线（如：问题→尝试→失败→崩溃→反转→升华）

5. **情绪曲线**：视频从头到尾的情绪变化轨迹

6. **猫meme素材序列**（如果视频中包含猫meme）：按顺序列出猫的动作类型

请以JSON格式输出分析结果，使用以下结构：
{
  "video_name": "视频文件名",
  "script_structure": {
    "hook": {"time_range": [0, 3], "type": "...", "description": "..."},
    "development": [{"time_range": [3, 15], "type": "...", "description": "..."}],
    "climax": {"time_range": [15, 22], "type": "...", "description": "..."},
    "cta": {"time_range": [22, 30], "type": "...", "description": "..."}
  },
  "rhythm_structure": {
    "shot_frequency": "高/中/低",
    "tempo_curve": "...",
    "climax_position": 0.65
  },
  "packaging_structure": {
    "subtitle_style": "...",
    "sticker_types": ["..."],
    "sticker_density": "...",
    "transitions": ["..."],
    "cover_style": "..."
  },
  "narrative_pattern": "...",
  "emotional_arc": "...",
  "cat_motion_sequence": [1, 2, 3],
  "overall_style_summary": "用一段话概括这个视频的整体风格和成功要素"
}
"""


def analyze_video(
    video_path: Path,
    save_structure: bool = True,
) -> dict:
    """分析单个视频的爆款结构。

    Args:
        video_path: 视频文件路径
        save_structure: 是否自动保存到 assets/baokuan/structure/

    Returns:
        结构化分析结果
    """
    print(f"📹 分析视频: {video_path.name}")

    # Step 1: 获取视频信息
    info = get_video_info(video_path)
    print(f"   时长: {info['duration_seconds']:.1f}s, 大小: {info['file_size_mb']}MB")

    # Step 2: 提取关键帧
    print(f"   🎞️ 提取关键帧...")
    frames = extract_video_frames(video_path)
    print(f"   已提取 {len(frames)} 帧")

    # Step 3: 豆包视觉分析
    print(f"   🤖 豆包 Pro 视觉分析中...")
    user_prompt = (
        f"请分析这个短视频（{info['duration_seconds']:.0f}秒）的帧序列，"
        f"提取其爆款结构。请严格按照JSON格式输出。\n\n"
        f"视频时长约{info['duration_seconds']:.0f}秒，"
        f"帧序列按时间顺序排列，每帧间隔约{config.frame_interval_seconds}秒。"
    )

    try:
        analysis_text = client.chat_vision(
            system_prompt=STRUCTURE_ANALYSIS_PROMPT,
            user_text=user_prompt,
            image_paths=frames,
            temperature=0.3,
            max_tokens=8192,
        )
    except Exception as e:
        print(f"   ⚠️ 视觉分析失败，使用文本模式回退: {e}")
        # 回退：用文本模式（无视觉）进行粗略分析
        analysis_text = _fallback_analysis(video_path, info)

    # Step 4: 解析结果
    try:
        # 尝试提取 JSON（可能包裹在 markdown 代码块中）
        if "```json" in analysis_text:
            json_start = analysis_text.find("```json") + 7
            json_end = analysis_text.find("```", json_start)
            analysis_text = analysis_text[json_start:json_end].strip()
        elif "```" in analysis_text:
            json_start = analysis_text.find("```") + 3
            json_end = analysis_text.find("```", json_start)
            analysis_text = analysis_text[json_start:json_end].strip()

        structure = json.loads(analysis_text)
    except json.JSONDecodeError:
        print(f"   ⚠️ JSON 解析失败，保存原始文本")
        structure = {
            "video_name": video_path.name,
            "raw_analysis": analysis_text,
            "parse_error": True,
        }

    # 补充元信息
    structure["video_name"] = video_path.name
    structure["_meta"] = {
        "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "duration_seconds": info["duration_seconds"],
        "file_size_mb": info["file_size_mb"],
        "frames_analyzed": len(frames),
        "model": config.model,
    }

    # Step 5: 保存
    if save_structure:
        output_path = config.baokuan_structure / f"{video_path.stem}.json"
        save_json(output_path, structure)
        print(f"   ✅ 结构已保存: {output_path.name}")

    return structure


def _fallback_analysis(video_path: Path, info: dict) -> str:
    """回退方案：用文本模式（无视觉）进行粗略的结构猜测。"""
    prompt = f"""你是一位短视频结构分析师。虽然无法直接观看视频，但请根据以下信息推测该视频的可能结构。

视频文件名: {video_path.name}
视频时长: {info['duration_seconds']:.0f}秒
视频大小: {info['file_size_mb']}MB

这类短视频通常遵循以下模式之一：
- 问题→尝试→失败→崩溃→反转→升华
- 震惊hook→铺垫→升级→高潮→CTA
- 日常→冲突→升级→反转→温暖收束

请根据视频时长推测合理的结构，并以JSON格式输出。"""

    return client.chat_text(
        system_prompt=STRUCTURE_ANALYSIS_PROMPT,
        user_message=prompt,
        temperature=0.3,
        max_tokens=4096,
    )


def batch_analyze(video_dir: Optional[Path] = None) -> list[dict]:
    """批量分析目录下的所有视频。

    Args:
        video_dir: 视频目录（默认 assets/baokuan/raw）

    Returns:
        分析结果列表
    """
    video_dir = video_dir or config.baokuan_raw
    videos = sorted(
        p for p in video_dir.glob("*")
        if p.suffix.lower() in (".mp4", ".mov", ".avi", ".webm", ".mkv")
    )

    if not videos:
        print(f"⚠️ 在 {video_dir} 中未找到视频文件")
        return []

    print(f"🎬 批量分析 {len(videos)} 个视频\n")
    results = []
    for i, video_path in enumerate(videos, 1):
        print(f"\n[{i}/{len(videos)}]", end=" ")
        try:
            result = analyze_video(video_path, save_structure=True)
            results.append(result)
        except Exception as e:
            print(f"   ❌ 分析失败: {e}")
            results.append({"video_name": video_path.name, "error": str(e)})

    # 保存批次汇总
    summary_path = config.baokuan_structure / "_batch_summary.json"
    save_json(summary_path, {
        "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_videos": len(videos),
        "successful": len([r for r in results if "error" not in r]),
        "failed": len([r for r in results if "error" in r]),
        "results": [
            {
                "video_name": r.get("video_name", ""),
                "narrative_pattern": r.get("narrative_pattern", ""),
                "emotional_arc": r.get("emotional_arc", ""),
                "error": r.get("error"),
            }
            for r in results
        ],
    })
    print(f"\n📊 批次摘要已保存: {summary_path.name}")

    return results


def load_structures() -> dict[str, dict]:
    """加载所有已分析的结构文件。

    Returns:
        {video_name: structure_dict}
    """
    structures = {}
    structure_dir = config.baokuan_structure
    if not structure_dir.exists():
        return structures

    for f in sorted(structure_dir.glob("*.json")):
        if f.name.startswith("_"):  # 跳过 _batch_summary 等内部文件
            continue
        try:
            data = load_json(f)
            name = data.get("video_name", f.stem)
            structures[name] = data
        except Exception:
            pass

    return structures
