"""公共工具函数 — 帧提取、JSON 读写、图片编码"""

from __future__ import annotations

import json
import base64
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .config import config


def extract_video_frames(
    video_path: Path,
    output_dir: Optional[Path] = None,
    interval: Optional[float] = None,
    max_frames: Optional[int] = None,
) -> list[Path]:
    """使用 ffmpeg 从视频中提取关键帧。

    Args:
        video_path: 视频文件路径
        output_dir: 输出目录（默认临时目录）
        interval: 帧间隔秒数（默认从 config 读取）
        max_frames: 最大帧数（默认从 config 读取）

    Returns:
        提取的帧文件路径列表
    """
    interval = interval or config.frame_interval_seconds
    max_frames = max_frames or config.max_analysis_frames

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="baokuan_frames_"))
    output_dir.mkdir(parents=True, exist_ok=True)

    # 先获取视频时长
    duration = get_video_duration(video_path)
    if duration is None:
        # 回退：直接按 fps 提取
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", f"fps=1/{interval}",
            "-q:v", "2",
            "-frames:v", str(max_frames),
            str(output_dir / "frame_%04d.jpg"),
        ]
    else:
        # 均匀采样
        total_frames = min(int(duration / interval), max_frames)
        if total_frames < 1:
            total_frames = 1
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", f"fps=1/{interval}",
            "-q:v", "2",
            "-frames:v", str(total_frames),
            str(output_dir / "frame_%04d.jpg"),
        ]

    subprocess.run(cmd, capture_output=True, check=True)

    frames = sorted(output_dir.glob("frame_*.jpg"))
    return frames


def get_video_duration(video_path: Path) -> Optional[float]:
    """获取视频时长（秒）。"""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except Exception:
        return None


def get_video_info(video_path: Path) -> dict:
    """获取视频基本信息。"""
    info = {
        "file_name": video_path.name,
        "file_size_mb": round(video_path.stat().st_size / (1024 * 1024), 2),
        "duration_seconds": get_video_duration(video_path),
    }
    return info


def image_to_base64(image_path: Path) -> str:
    """将图片编码为 base64 data URL。"""
    ext = image_path.suffix.lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp"}
    mime = mime_map.get(ext, "image/jpeg")
    data = image_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def load_json(path: Path) -> dict | list:
    """加载 JSON 文件。"""
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict | list, indent: int = 2):
    """保存 JSON 文件（自动创建父目录）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=indent),
        encoding="utf-8",
    )


def load_cat_motions() -> dict:
    """加载猫动作素材描述。"""
    path = config.cat_motions_dir / "descriptions.json"
    return load_json(path)


def load_sticker_catalog() -> list:
    """加载贴纸目录。"""
    path = config.stickers_dir / "descriptions.json"
    return load_json(path)


def find_sticker_files(category_folder: str) -> list[Path]:
    """获取某个贴纸分类下的所有贴纸文件路径。"""
    cat_dir = config.stickers_dir / category_folder
    if not cat_dir.exists():
        return []
    return sorted(cat_dir.glob("*.png")) + sorted(cat_dir.glob("*.jpg"))


def find_sticker_by_keyword(keyword: str) -> list[dict]:
    """根据关键词搜索贴纸。

    Returns:
        [{"category": "...", "file_path": Path, "description": "..."}, ...]
    """
    catalog = load_sticker_catalog()
    results = []
    for cat in catalog:
        cat_folder = cat["folder"]
        cat_desc = cat.get("description", "")
        if keyword in cat_desc or keyword in cat["category"]:
            files = find_sticker_files(cat_folder)
            for f in files:
                results.append({
                    "category": cat["category"],
                    "folder": cat_folder,
                    "file_path": f,
                    "description": cat_desc,
                })
    return results
