"""视频合成器 — 将分镜脚本合成为最终视频"""

from __future__ import annotations

import subprocess
import tempfile
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .composition_planner import apply_hyperframe_plan
from .config import config
from .hyperframe_layout import build_hyperframe_layout


# macOS 中文字体
FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"
# 视频输出尺寸（16:9 横屏）
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FPS = 30
GREEN_KEY_COLOR = "0x01d900"
GREEN_KEY_SIMILARITY = 0.32
GREEN_KEY_BLEND = 0.08
CAT_ALPHA_FILTER = f"format=rgba,colorkey={GREEN_KEY_COLOR}:{GREEN_KEY_SIMILARITY}:{GREEN_KEY_BLEND}"


@dataclass
class SceneRenderPlan:
    """FFmpeg inputs and filters for one rendered scene."""

    input_paths: list[str]
    filter_complex: str
    video_label: str
    audio_label: str


def _find_font() -> str:
    """查找可用中文字体。"""
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for f in candidates:
        if Path(f).exists():
            return f
    return FONT_PATH  # 回退


def _get_video_duration(video_path: Path) -> float:
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
        return 3.0  # 默认3秒


def _process_scene(
    scene: dict,
    output_path: Path,
    temp_dir: Path,
    scene_index: int,
) -> Path:
    """处理单个镜头：裁剪猫动作 + 叠加字幕 + 叠加贴纸。

    Args:
        scene: 分镜数据
        output_path: 输出文件路径
        temp_dir: 临时目录
        scene_index: 镜头序号

    Returns:
        处理后的视频文件路径
    """
    duration = float(scene.get("duration", 3))
    motion_file = scene.get("cat_motion_file", "")
    subtitle = scene.get("subtitle", "")
    original_motion_file = motion_file

    if not motion_file or not Path(motion_file).exists():
        # 生成纯色背景占位
        motion_file = _create_placeholder_scene(temp_dir, duration, scene)
        original_motion_file = motion_file
    else:
        motion_dur = _get_video_duration(Path(motion_file))
        if motion_dur < duration:
            # 视频太短，循环播放
            motion_file = _loop_video(Path(motion_file), duration, temp_dir, scene_index)

    font = _find_font()
    has_audio = _has_audio_stream(Path(motion_file))
    plan = _build_scene_plan(
        scene=scene,
        motion_file=str(motion_file),
        duration=duration,
        font=font,
        has_audio=has_audio,
        scene_index=scene_index,
        primary_motion_file=str(original_motion_file),
    )

    cmd = ["ffmpeg", "-y"]
    for inp in plan.input_paths:
        if _is_image_file(inp):
            cmd.extend(["-loop", "1", "-t", str(duration)])
        cmd.extend(["-i", inp])
    cmd.extend([
        "-filter_complex", plan.filter_complex,
        "-map", plan.video_label,
        "-map", plan.audio_label,
    ])
    cmd.extend([
        "-c:v", "h264_videotoolbox",
        "-b:v", "3M",
        "-allow_sw", "1",
        "-c:a", "aac",
        "-shortest",
        "-r", str(FPS),
        "-pix_fmt", "yuv420p",
        str(output_path),
    ])

    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=60)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="ignore")
        print(_format_ffmpeg_failure_log(scene, plan, stderr))
        # 降级：生成纯色 + 字幕的简单版本
        _create_simple_scene(subtitle, duration, output_path, font)
    except subprocess.TimeoutExpired:
        print(f"   ⚠️ 镜头{scene['scene_id']}合成超时")
        _create_simple_scene(subtitle, duration, output_path, font)

    return output_path


def _build_scene_plan(
    scene: dict,
    motion_file: str,
    duration: float,
    font: str,
    has_audio: bool,
    scene_index: int,
    primary_motion_file: str | None = None,
) -> SceneRenderPlan:
    """Build the FFmpeg filter graph for a single scene."""
    scene = apply_hyperframe_plan(scene)
    hyperframe_layout = build_hyperframe_layout(scene)
    input_paths = []
    filters = []

    background_file = _find_background_asset(scene)
    if background_file:
        background_index = len(input_paths)
        input_paths.append(background_file)
        filters.append(
            f"[{background_index}:v]"
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},setsar=1,trim=0:{duration},"
            f"setpts=PTS-STARTPTS[bg]"
        )
    else:
        filters.append(
            f"color=c=0x1a1a2e:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d={duration}:r={FPS}[bg]"
        )

    motion_index = len(input_paths)
    input_paths.append(str(motion_file))
    filters.append(_cat_key_filter(motion_index, duration, "cat_keyed"))

    if has_audio and scene.get("use_motion_audio") and not scene.get("audio_muted"):
        filters.append(
            f"[{motion_index}:a]atrim=0:{duration},asetpts=PTS-STARTPTS[a0]"
        )
    else:
        filters.append(f"anullsrc=r=44100:cl=stereo:d={duration}[a0]")

    primary_motion_for_roles = str(primary_motion_file or scene.get("cat_motion_file") or motion_file)
    hyperframe_layout = dict(hyperframe_layout)
    hyperframe_layout["cat_instances"] = _dedupe_renderable_cat_instances(
        hyperframe_layout.get("cat_instances", []),
        primary_motion_for_roles,
    )

    current_video = _append_cat_instance_overlays(
        filters=filters,
        input_paths=input_paths,
        base_label="[bg]",
        primary_cat_label="[cat_keyed]",
        primary_motion_file=primary_motion_for_roles,
        duration=duration,
        cat_instances=hyperframe_layout.get("cat_instances", []),
    )

    stickers = _collect_overlay_stickers(scene)
    total_stickers = len(stickers)
    for sticker_index, sticker in enumerate(stickers):
        sticker_path = sticker.get("file", "")
        if not sticker_path or not Path(sticker_path).exists():
            continue

        input_index = len(input_paths)
        input_paths.append(sticker_path)
        category = sticker.get("category", "")
        x_pos, y_pos, scale = _sticker_position(
            category=category,
            scene_index=scene_index,
            total=total_stickers,
            sticker=sticker,
            sticker_index=sticker_index,
        )
        sticker_label = f"[st{sticker_index}]"
        video_label = f"[v_st{sticker_index}]"
        filters.append(
            f"[{input_index}:v]scale={scale}:-1,format=rgba{sticker_label};"
            f"{current_video}{sticker_label}overlay={x_pos}:{y_pos}:format=auto{video_label}"
        )
        current_video = video_label

    current_video = _append_hyperframe_captions(
        filters=filters,
        current_video=current_video,
        layout=hyperframe_layout,
        font=font,
    )

    subtitle = scene.get("subtitle", "")
    if subtitle:
        safe_subtitle = _escape_drawtext(subtitle)
        subtitle_y = int(VIDEO_HEIGHT * 0.78)
        filters.append(
            f"{current_video}drawtext="
            f"fontfile='{font}':"
            f"text='{safe_subtitle}':"
            f"fontsize=56:"
            f"fontcolor=white:"
            f"bordercolor=black:"
            f"borderw=3:"
            f"x=(w-text_w)/2:"
            f"y={subtitle_y}:"
            f"text_align=center"
            f"[v_final]"
        )
        current_video = "[v_final]"

    return SceneRenderPlan(
        input_paths=input_paths,
        filter_complex=";".join(filters),
        video_label=current_video,
        audio_label="[a0]",
    )


def _cat_key_filter(input_index: int, duration: float, label: str) -> str:
    return (
        f"[{input_index}:v]trim=0:{duration},setpts=PTS-STARTPTS,"
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"{CAT_ALPHA_FILTER}"
        f"[{label}]"
    )


def _dedupe_renderable_cat_instances(
    cat_instances: list[dict],
    primary_motion_file: str,
) -> list[dict]:
    """Keep only cat roles that will render from distinct video sources."""
    if len(cat_instances) <= 1:
        return cat_instances

    filtered = []
    used_keys = set()
    for cat in cat_instances:
        key = _renderable_motion_key(cat, primary_motion_file)
        if key in used_keys:
            continue
        filtered.append(cat)
        used_keys.add(key)
    return filtered or cat_instances[:1]


def _renderable_motion_key(cat: dict, primary_motion_file: str) -> str:
    motion_file = str(cat.get("motion_file") or "").strip()
    if motion_file and Path(motion_file).exists() and not _same_motion_file(motion_file, primary_motion_file):
        return str(Path(motion_file).expanduser().resolve(strict=False))
    if primary_motion_file:
        return str(Path(primary_motion_file).expanduser().resolve(strict=False))
    return "primary"


def _append_cat_instance_overlays(
    filters: list[str],
    input_paths: list[str],
    base_label: str,
    primary_cat_label: str,
    primary_motion_file: str,
    duration: float,
    cat_instances: list[dict],
) -> str:
    """Overlay one or more cat meme instances according to the hyperframe layout."""
    count = max(1, min(len(cat_instances), 3))
    cat_labels = _cat_labels_for_instances(
        filters=filters,
        input_paths=input_paths,
        primary_cat_label=primary_cat_label,
        primary_motion_file=primary_motion_file,
        duration=duration,
        cat_instances=cat_instances[:count],
    )
    if primary_cat_label not in cat_labels:
        filters.append(f"{primary_cat_label}nullsink")
    if count == 1 and not _has_cat_layout_override(cat_instances[0]):
        filters.append(f"{base_label}{cat_labels[0]}overlay=(W-w)/2:(H-h)/2:format=auto[v_cat]")
        return "[v_cat]"

    cat_labels = _split_reused_cat_labels(filters, cat_labels)
    current_video = base_label
    for index in range(count):
        slot = cat_instances[index].get("slot", "center")
        x_pos, y_pos, scale, crop_expr = _cat_instance_position(
            slot=slot,
            count=count,
            cat=cat_instances[index],
        )
        scaled_label = f"[cat_inst{index}]"
        video_label = f"[v_cat{index}]"
        filters.append(
            f"{cat_labels[index]}{crop_expr}scale={scale}:-1{scaled_label};"
            f"{current_video}{scaled_label}overlay={x_pos}:{y_pos}:format=auto{video_label}"
        )
        current_video = video_label
    return current_video


def _cat_labels_for_instances(
    filters: list[str],
    input_paths: list[str],
    primary_cat_label: str,
    primary_motion_file: str,
    duration: float,
    cat_instances: list[dict],
) -> list[str]:
    labels = []
    for index, cat in enumerate(cat_instances):
        motion_file = str(cat.get("motion_file") or "").strip()
        if motion_file and Path(motion_file).exists() and not _same_motion_file(motion_file, primary_motion_file):
            input_index = len(input_paths)
            input_paths.append(motion_file)
            label = f"cat_keyed_role{index}"
            filters.append(_cat_key_filter(input_index, duration, label))
            labels.append(f"[{label}]")
        else:
            labels.append(primary_cat_label)
    return labels or [primary_cat_label]


def _same_motion_file(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return Path(left).expanduser().resolve(strict=False) == Path(right).expanduser().resolve(strict=False)


def _format_ffmpeg_failure_log(scene: dict, plan: SceneRenderPlan, stderr: str) -> str:
    scene_id = scene.get("scene_id", "?")
    input_lines = [
        f"      [{index}] {path}"
        for index, path in enumerate(plan.input_paths)
    ]
    filter_tail = _tail_text(plan.filter_complex, 2400)
    stderr_tail = _tail_text(stderr, 4000)
    return "\n".join([
        f"   ⚠️ 镜头{scene_id}合成失败，已降级为纯字幕片段",
        "   ffmpeg_inputs:",
        *input_lines,
        f"   video_label: {plan.video_label} audio_label: {plan.audio_label}",
        f"   filter_complex_tail: {filter_tail}",
        f"   stderr_tail: {stderr_tail}",
    ])


def _tail_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return "...<truncated>..." + text[-limit:]


def _split_reused_cat_labels(filters: list[str], cat_labels: list[str]) -> list[str]:
    prepared = list(cat_labels)
    for label in sorted(set(cat_labels)):
        positions = [index for index, item in enumerate(cat_labels) if item == label]
        if len(positions) <= 1:
            continue
        base = label.strip("[]")
        split_labels = [f"[{base}_src{i}]" for i in range(len(positions))]
        filters.append(f"{label}split={len(positions)}{''.join(split_labels)}")
        for split_index, original_index in enumerate(positions):
            prepared[original_index] = split_labels[split_index]
    return prepared


def _cat_instance_position(slot: str, count: int, cat: dict | None = None) -> tuple[str, str, int, str]:
    scale = 900 if count == 2 else 760
    crop_expr = "crop=iw*0.62:ih:iw*0.19:0,"
    positions = {
        "left": ("120", "H-h-20"),
        "center": ("(W-w)/2", "H-h-40"),
        "right": ("W-w-120", "H-h-20"),
    }
    x_pos, y_pos = positions.get(slot, positions["center"])
    scale = _resolve_cat_scale(scale, cat)
    return x_pos, y_pos, scale, crop_expr


def _resolve_cat_scale(base_scale: int, cat: dict | None) -> int:
    if not isinstance(cat, dict):
        return base_scale
    if "scale" in cat:
        try:
            return _clamp_int(cat.get("scale"), 360, 1100)
        except (TypeError, ValueError):
            return base_scale
    if "scale_multiplier" in cat:
        try:
            multiplier = float(cat.get("scale_multiplier"))
        except (TypeError, ValueError):
            return base_scale
        return _clamp_int(round(base_scale * multiplier), 360, 1100)
    return base_scale


def _has_cat_layout_override(cat: dict) -> bool:
    return isinstance(cat, dict) and ("scale" in cat or "scale_multiplier" in cat)


def _clamp_int(value, minimum: int, maximum: int) -> int:
    parsed = int(value)
    return max(minimum, min(maximum, parsed))


def _append_hyperframe_captions(
    filters: list[str],
    current_video: str,
    layout: dict,
    font: str,
) -> str:
    label_index = 0

    def next_label(prefix: str) -> str:
        nonlocal label_index
        label_index += 1
        return f"[v_{prefix}{label_index}]"

    topic = str(layout.get("topic_caption", "")).strip()
    if topic:
        topic_box_label = next_label("topic_box")
        filters.append(
            f"{current_video}drawbox=x=88:y=24:w=1744:h=150:"
            f"color=0xffd400@0.96:t=fill{topic_box_label}"
        )
        topic_text_label = next_label("topic_text")
        filters.append(
            f"{topic_box_label}drawtext="
            f"fontfile='{font}':"
            f"text='{_escape_drawtext(topic)}':"
            f"fontsize=76:"
            f"fontcolor=black:"
            f"x=(w-text_w)/2:"
            f"y=58{topic_text_label}"
        )
        current_video = topic_text_label

    scene_caption = str(layout.get("scene_caption", "")).strip()
    if scene_caption:
        scene_label = next_label("scene_caption")
        filters.append(
            f"{current_video}drawtext="
            f"fontfile='{font}':"
            f"text='{_escape_drawtext(scene_caption)}':"
            f"fontsize=58:"
            f"fontcolor=white:"
            f"bordercolor=black:"
            f"borderw=4:"
            f"x=(w-text_w)/2:"
            f"y=205{scene_label}"
        )
        current_video = scene_label

    for index, cat in enumerate(layout.get("cat_instances", [])[:3]):
        speech = str(cat.get("speech", "")).strip()
        if not speech:
            continue
        x_expr, y_expr = _speech_caption_position(cat.get("slot", "center"))
        speech_label = next_label(f"speech{index}")
        filters.append(
            f"{current_video}drawtext="
            f"fontfile='{font}':"
            f"text='“{_escape_drawtext(speech)}”':"
            f"fontsize=52:"
            f"fontcolor={_speech_color(index)}:"
            f"bordercolor=black:"
            f"borderw=3:"
            f"x={x_expr}:"
            f"y={y_expr}{speech_label}"
        )
        current_video = speech_label

    return current_video


def _speech_caption_position(slot: str) -> tuple[str, str]:
    positions = {
        "left": ("80", "430"),
        "center": ("(w-text_w)/2", "360"),
        "right": ("w-text_w-80", "430"),
    }
    return positions.get(slot, positions["center"])


def _speech_color(index: int) -> str:
    return ["0xd8ff42", "0xff66b6", "0x75e7ff"][index % 3]


def _has_audio_stream(video_path: Path) -> bool:
    """检查视频是否有音频流。"""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return "audio" in result.stdout
    except Exception:
        return False


def _loop_video(video_path: Path, target_duration: float, temp_dir: Path, scene_index: int) -> str:
    """循环视频到目标时长。"""
    output = temp_dir / f"looped_{scene_index}.mp4"
    # 计算需要循环的次数
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(video_path),
        "-t", str(target_duration),
        "-c", "copy",
        "-shortest",
        str(output),
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=30)
        return str(output)
    except Exception:
        return str(video_path)


def _create_placeholder_scene(temp_dir: Path, duration: float, scene: dict) -> str:
    """创建纯色背景占位视频。"""
    output = temp_dir / f"placeholder_{scene['scene_id']}.mp4"
    color = "0x1a1a2e"  # 深色背景
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c={color}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d={duration}:r={FPS}",
        "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        "-c:v", "h264_videotoolbox",
        "-c:a", "aac",
        "-shortest",
        str(output),
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=30)
    return str(output)


def _create_simple_scene(subtitle: str, duration: float, output_path: Path, font: str):
    """创建纯色背景 + 字幕的简单版本（降级方案）。"""
    safe_subtitle = subtitle.replace("'", "\\'").replace(":", "\\:").replace("\\", "\\\\")
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x1a1a2e:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d={duration}:r={FPS}",
        "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        "-vf", (
            f"drawtext=fontfile='{font}':"
            f"text='{safe_subtitle}':"
            f"fontsize=56:fontcolor=white:"
            f"bordercolor=black:borderw=3:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:"
            f"text_align=center"
        ),
        "-c:v", "h264_videotoolbox",
        "-c:a", "aac",
        "-allow_sw", "1",
        "-b:v", "3M",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=30)


def _is_image_file(path: str) -> bool:
    """Return True when FFmpeg should treat an input as a still image."""
    return Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}


def _find_background_asset(scene: dict) -> str | None:
    """Find the first generated background image for a scene."""
    explicit = scene.get("background_file") or scene.get("background")
    if explicit and Path(explicit).exists():
        return str(explicit)

    for asset in scene.get("generated_assets", []):
        asset_type = str(asset.get("type", ""))
        asset_file = asset.get("file", "")
        if "背景" in asset_type and asset_file and Path(asset_file).exists():
            return str(asset_file)
    return None


def _collect_overlay_stickers(scene: dict) -> list[dict]:
    """Collect sticker-like overlays, including generated props."""
    overlays = [
        sticker
        for sticker in scene.get("stickers", [])
        if _should_render_sticker(sticker)
    ]
    for asset in scene.get("generated_assets", []):
        asset_type = str(asset.get("type", ""))
        asset_kind = str(asset.get("kind", ""))
        asset_file = asset.get("file", "")
        if ("道具" in asset_type or asset_kind == "prop") and asset_file and Path(asset_file).exists():
            overlays.append({
                "category": "generated-prop",
                "file": asset_file,
                "position": asset.get("position", "bottom_right"),
                "scale": asset.get("scale", 220),
            })
    return overlays


def _should_render_sticker(sticker: dict) -> bool:
    """Final safety gate so decorative expression stickers cannot leak into output."""
    category = str(sticker.get("category", ""))
    file_name = Path(str(sticker.get("file", ""))).stem.lower()
    if category == "emotion-effects":
        allowed_emotion_objects = ("hand", "ok-hand")
        blocked_expression = ("meme-face", "eyes", "poop")
        if any(token in file_name for token in blocked_expression):
            return False
        if not any(token in file_name for token in allowed_emotion_objects):
            return False
    if category == "atmosphere-decor":
        return False
    return True


def _escape_drawtext(text: str) -> str:
    """Escape a string for FFmpeg drawtext."""
    return text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")


def _sticker_position(
    category: str,
    scene_index: int,
    total: int,
    sticker: Optional[dict] = None,
    sticker_index: int = 0,
) -> tuple[str, str, int]:
    """根据贴纸分类决定位置和大小。

    Returns:
        (x_pos, y_pos, scale_width)
    """
    sticker = sticker or {}
    if "x" in sticker and "y" in sticker:
        return str(sticker["x"]), str(sticker["y"]), int(sticker.get("scale", 160))

    explicit_positions = {
        "top_left": ("80", "160"),
        "top_right": ("W-w-80", "160"),
        "center": ("(W-w)/2", "(H-h)/2"),
        "center_left": ("80", "(H-h)/2"),
        "center_right": ("W-w-80", "(H-h)/2"),
        "bottom_left": ("80", "H-h-360"),
        "bottom_right": ("W-w-80", "H-h-360"),
        "near_cat_paw_left": ("(W-w)/2-320", "H-h-300"),
        "near_cat_paw_right": ("(W-w)/2+260", "H-h-300"),
        "desk_left": ("260", "H-h-320"),
        "desk_right": ("W-w-260", "H-h-320"),
        "upper_context_left": ("120", "180"),
        "upper_context_right": ("W-w-120", "180"),
    }
    position = sticker.get("position")
    if position in explicit_positions:
        x_pos, y_pos = explicit_positions[position]
        return x_pos, y_pos, int(sticker.get("scale", 160))

    fixed_positions = [
        ("80", "160"),
        ("W-w-80", "160"),
        ("80", "(H-h)/2"),
        ("W-w-80", "(H-h)/2"),
        ("80", "H-h-360"),
        ("W-w-80", "H-h-360"),
    ]
    category_scale = {
        "emotion-effects": 180,
        "home-daily": 190,
        "campus-study": 180,
        "food-drinks": 190,
        "digital-communication": 180,
        "career-identity": 170,
        "plot-conflict": 180,
        "atmosphere-decor": 200,
        "generated-prop": 220,
    }
    if category == "generated-prop":
        x_pos, y_pos = "W-w-80", "H-h-360"
    else:
        x_pos, y_pos = fixed_positions[sticker_index % len(fixed_positions)]
    return x_pos, y_pos, int(sticker.get("scale", category_scale.get(category, 180)))


def compose_video(
    storyboard: dict,
    output_path: Optional[Path] = None,
    on_progress: Optional[callable] = None,
) -> Path:
    """将分镜脚本合成为最终视频。

    Args:
        storyboard: 分镜脚本（含 scenes 列表）
        output_path: 输出路径（默认 assets/generated/output/final_video.mp4）
        on_progress: 进度回调 (scene_index, total_scenes)

    Returns:
        输出视频文件路径
    """
    if output_path is None:
        output_dir = config.generated_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "final_video.mp4"

    scenes = storyboard.get("scenes", [])
    if not scenes:
        raise ValueError("分镜中没有镜头数据")

    temp_dir = Path(tempfile.mkdtemp(prefix="baokuan_compose_"))
    scene_files = []

    total = len(scenes)
    print(f"🎬 开始合成视频 ({total} 个镜头)...")

    for i, scene in enumerate(scenes):
        scene_id = scene.get("scene_id", i + 1)
        scene_file = temp_dir / f"scene_{scene_id:03d}.mp4"
        print(f"   🎞️ 镜{scene_id}/{total}: {scene.get('description', '')[:50]}...")

        try:
            _process_scene(scene, scene_file, temp_dir, i)
            if scene_file.exists():
                scene_files.append(scene_file)
            else:
                # 降级占位
                font = _find_font()
                _create_simple_scene(
                    scene.get("subtitle", f"Scene {scene_id}"),
                    scene.get("duration", 3),
                    scene_file,
                    font,
                )
                scene_files.append(scene_file)
        except Exception as e:
            print(f"   ❌ 镜{scene_id}处理失败: {e}")
            font = _find_font()
            _create_simple_scene(
                scene.get("subtitle", f"Scene {scene_id}"),
                scene.get("duration", 3),
                scene_file,
                font,
            )
            scene_files.append(scene_file)

        if on_progress:
            on_progress(i + 1, total)

    # 拼接所有镜头
    print(f"   🔗 拼接 {len(scene_files)} 个镜头...")
    _concat_scenes(scene_files, output_path)

    # 清理临时文件
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass

    print(f"   ✅ 视频已生成: {output_path}")
    return output_path


def _concat_scenes(scene_files: list[Path], output_path: Path):
    """拼接多个镜头视频。"""
    # 使用 concat demuxer
    concat_list = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    for sf in scene_files:
        concat_list.write(f"file '{sf.absolute()}'\n")
    concat_list.close()

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list.name,
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=120)
    except subprocess.CalledProcessError:
        # 回退：重新编码拼接
        _concat_scenes_reencode(scene_files, output_path)
    finally:
        Path(concat_list.name).unlink(missing_ok=True)


def _concat_scenes_reencode(scene_files: list[Path], output_path: Path):
    """重新编码拼接（回退方案）。"""
    filter_parts = []
    for i in range(len(scene_files)):
        filter_parts.append(f"[{i}:v][{i}:a]")

    cmd = ["ffmpeg", "-y"]
    for sf in scene_files:
        cmd.extend(["-i", str(sf)])
    cmd.extend([
        "-filter_complex",
        f"{' '.join(filter_parts)}concat=n={len(scene_files)}:v=1:a=1[v][a]",
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "h264_videotoolbox",
        "-allow_sw", "1",
        "-b:v", "3M",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ])
    subprocess.run(cmd, capture_output=True, check=True, timeout=120)
