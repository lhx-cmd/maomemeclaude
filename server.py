"""爆款结构迁移引擎 — Flask Web 服务"""

from __future__ import annotations

import json
import hashlib
import sys
import os
import uuid
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# 确保项目根目录在 Python 路径中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flask import Flask, request, jsonify, send_file, send_from_directory, Response, stream_with_context
from werkzeug.utils import secure_filename

from agent.config import config
from agent.video_analyzer import analyze_video, load_structures, batch_analyze
from agent.script_generator import (
    generate_scripts, format_scripts_for_display,
    generate_scripts_streaming, generate_brief_scripts_streaming,
    expand_script_detail,
)
from agent.storyboard_generator import generate_storyboard, format_storyboard_for_display
from agent.editor import parse_edit_intent, apply_edits, format_edit_summary
from agent.video_composer import compose_video
from agent.workflow_graph import (
    WorkflowStepError,
    run_compose_video,
    run_generate_briefs,
    run_select_to_storyboard,
)
from agent.utils import save_json, load_json

app = Flask(__name__, static_folder="static", static_url_path="/static")

# 会话存储（生产环境应使用 Redis/DB）
sessions: dict[str, dict] = {}

UPLOAD_DIR = config.generated_dir / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv"}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def get_or_create_session(session_id: str | None = None) -> tuple[str, dict]:
    """获取或创建会话。"""
    if session_id and session_id in sessions:
        return session_id, sessions[session_id]
    new_id = session_id or uuid.uuid4().hex[:12]
    sessions[new_id] = {
        "state": "IDLE",
        "theme": "",
        "video_path": None,
        "materials": [],
        "scripts": None,
        "selected_script": None,
        "storyboard": None,
        "storyboard_cache": {},
        "edit_history": [],
    }
    return new_id, sessions[new_id]


# ─── API 路由 ───────────────────────────────────────────

@app.route("/api/health")
def health():
    """健康检查"""
    structures = load_structures()
    return jsonify({
        "status": "ok",
        "model": config.model,
        "structures_loaded": len(structures),
        "structures": list(structures.keys()),
    })


@app.route("/api/session", methods=["POST"])
def create_session():
    """创建新会话"""
    session_id, state = get_or_create_session()
    return jsonify({"session_id": session_id, "state": state["state"]})


@app.route("/api/state")
def get_state():
    """获取当前会话状态"""
    session_id = request.args.get("session_id", "")
    _, state = get_or_create_session(session_id)
    return jsonify({
        "state": state["state"],
        "theme": state["theme"],
        "has_scripts": state["scripts"] is not None,
        "has_storyboard": state["storyboard"] is not None,
        "edit_count": len(state["edit_history"]),
    })


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """分析阶段：匹配爆款结构"""
    session_id = request.form.get("session_id", "")
    theme = request.form.get("theme", "").strip()
    session_id, state = get_or_create_session(session_id)

    if not theme:
        return jsonify({"error": "主题描述是必填的"}), 400

    state["theme"] = theme

    # 处理上传的视频
    video_file = request.files.get("video")
    if video_file and video_file.filename:
        ext = Path(video_file.filename).suffix.lower()
        if ext in ALLOWED_VIDEO_EXTENSIONS:
            filename = secure_filename(video_file.filename)
            video_path = UPLOAD_DIR / f"{session_id}_{filename}"
            video_file.save(str(video_path))
            state["video_path"] = str(video_path)

            # 分析上传的视频
            structure = analyze_video(video_path, save_structure=False)
            state["custom_structure"] = structure
            state["state"] = "ANALYZE"
            return jsonify({
                "state": "ANALYZE",
                "source": "uploaded",
                "video_name": video_path.name,
                "structure": {
                    "narrative_pattern": structure.get("narrative_pattern", ""),
                    "emotional_arc": structure.get("emotional_arc", ""),
                    "hook_type": structure.get("script_structure", {}).get("hook", {}).get("type", ""),
                    "overall_style": structure.get("overall_style_summary", ""),
                },
            })

    # 处理上传的素材
    material_files = request.files.getlist("materials")
    for mf in material_files:
        if mf and mf.filename:
            ext = Path(mf.filename).suffix.lower()
            if ext in ALLOWED_IMAGE_EXTENSIONS or ext in ALLOWED_VIDEO_EXTENSIONS:
                filename = secure_filename(mf.filename)
                mat_path = UPLOAD_DIR / f"{session_id}_mat_{filename}"
                mf.save(str(mat_path))
                state["materials"].append(str(mat_path))

    # 使用内置爆款结构库
    structures = load_structures()
    if not structures:
        # 首次使用，先分析
        batch_analyze()
        structures = load_structures()

    from agent.script_generator import _auto_match_structure
    best = _auto_match_structure(theme, structures)

    state["reference_structure"] = best
    state["state"] = "ANALYZE"

    return jsonify({
        "state": "ANALYZE",
        "source": "builtin",
        "video_name": best.get("video_name", ""),
        "structure": {
            "narrative_pattern": best.get("narrative_pattern", ""),
            "emotional_arc": best.get("emotional_arc", ""),
            "hook_type": best.get("script_structure", {}).get("hook", {}).get("type", ""),
            "overall_style": best.get("overall_style_summary", ""),
        },
        "total_structures": len(structures),
    })


@app.route("/api/generate-scripts", methods=["POST"])
def api_generate_scripts():
    """生成3个候选剧本（并发模式，一次性返回）"""
    data = request.get_json() or {}
    session_id = data.get("session_id", "")
    _, state = get_or_create_session(session_id)

    if not state["theme"]:
        return jsonify({"error": "请先提供主题"}), 400

    preference = data.get("preference", "")
    reference = state.get("reference_structure") or state.get("custom_structure")

    try:
        result = generate_scripts(
            theme=state["theme"],
            reference_structure=reference,
            custom_materials=state.get("materials"),
            user_preferences=preference,
        )
    except Exception as e:
        return jsonify({"error": f"剧本生成失败: {str(e)}"}), 500

    state["scripts"] = result
    state["state"] = "GENERATE_SCRIPT"

    return jsonify({
        "state": "GENERATE_SCRIPT",
        "reference_video": result.get("reference_video", ""),
        "reference_narrative": result.get("reference_narrative", ""),
        "scripts": _summarize_scripts(result),
    })


@app.route("/api/generate-scripts-stream")
def api_generate_scripts_stream():
    """生成3个简略候选剧本（SSE 流式推送，每完成一个版本立即推送）

    Phase 1: 简略版 — 仅标题/hook/叙事弧线/剧情概述，不含详细镜头
    Phase 2: 用户选择后 → POST /api/select-script 展开为详细版+分镜

    前端使用 EventSource 连接，实时接收：
    - event: progress  → 单个版本完成
    - event: done      → 全部完成
    """
    session_id = request.args.get("session_id", "")
    preference = request.args.get("preference", "")
    _, state = get_or_create_session(session_id)

    if not state["theme"]:
        def error_stream():
            yield f"data: {json.dumps({'error': '请先提供主题'})}\n\n"
        return Response(error_stream(), mimetype="text/event-stream")

    reference = state.get("reference_structure") or state.get("custom_structure")

    # 线程间通信
    progress_events: list[dict] = []
    lock = threading.Lock()
    done_event = threading.Event()

    def on_progress(version_key: str, script: dict | None):
        with lock:
            if version_key == "done":
                return
            elif script:
                progress_events.append({
                    "version": version_key,
                    "version_name": script.get("version_name", ""),
                    "title": script.get("title", ""),
                    "hook": script.get("hook", ""),
                    "narrative_arc": script.get("narrative_arc", ""),
                    "target_emotion": script.get("target_emotion", ""),
                    "cta": script.get("cta", ""),
                    "duration_estimate": script.get("duration_estimate", 0),
                    "scene_count_estimate": script.get("scene_count_estimate", 0),
                    "brief_summary": script.get("brief_summary", ""),
                    "error": script.get("error"),
                })

    # 在后台线程运行生成（简略版 Phase 1）
    result_holder = {}

    def run_generation():
        try:
            workflow_state = run_generate_briefs({
                "session_id": session_id,
                "theme": state["theme"],
                "reference_structure": reference,
                "materials": state.get("materials"),
                "preference": preference,
                "on_progress": on_progress,
            })
            result_holder["result"] = workflow_state["scripts"]
        except Exception as e:
            result_holder["error"] = str(e)
        finally:
            done_event.set()

    thread = threading.Thread(target=run_generation, daemon=True)
    thread.start()

    def event_stream():
        last_sent = 0
        while not done_event.is_set() or last_sent < len(progress_events):
            with lock:
                new_events = progress_events[last_sent:]
                last_sent = len(progress_events)

            for evt in new_events:
                yield f"event: progress\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"

            if done_event.is_set():
                # 发送剩余事件后退出
                with lock:
                    remaining = progress_events[last_sent:]
                for evt in remaining:
                    yield f"event: progress\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"

                if "error" in result_holder:
                    yield f"event: error\ndata: {json.dumps({'error': result_holder['error']}, ensure_ascii=False)}\n\n"
                elif "result" in result_holder:
                    r = result_holder["result"]
                    state["scripts"] = r
                    state["state"] = "GENERATE_SCRIPT"
                    done_data = json.dumps({
                        "reference_video": r.get("reference_video", ""),
                        "reference_narrative": r.get("reference_narrative", ""),
                    }, ensure_ascii=False)
                    yield f"event: done\ndata: {done_data}\n\n"
                break

            # 等待新事件（100ms 轮询）
            import time
            time.sleep(0.1)

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _summarize_scripts(result: dict) -> list[dict]:
    """提取剧本摘要列表（兼容简略版和详细版）。"""
    scripts_summary = []
    for s in result.get("scripts", []):
        summary = {
            "version": s.get("version", ""),
            "version_name": s.get("version_name", ""),
            "title": s.get("title", ""),
            "hook": s.get("hook", ""),
            "narrative_arc": s.get("narrative_arc", ""),
            "target_emotion": s.get("target_emotion", ""),
            "cta": s.get("cta", ""),
            "duration_estimate": s.get("duration_estimate", 0),
            "scene_count": len(s.get("scenes", [])),
            "scene_count_estimate": s.get("scene_count_estimate", 0),
            "brief_summary": s.get("brief_summary", ""),
            "scenes": s.get("scenes", []),
            "error": s.get("error"),
        }
        scripts_summary.append(summary)
    return scripts_summary


def _resolve_script_selection(scripts: list[dict], data: dict) -> dict:
    """Resolve a selected script by stable version key, falling back to index."""
    script_version = data.get("script_version")
    if script_version:
        for script in scripts:
            if script.get("version") == script_version:
                return script
        raise ValueError("剧本版本不存在")

    try:
        script_index = int(data.get("script_index", 0))
    except (TypeError, ValueError):
        raise ValueError("剧本编号无效")

    if script_index < 0 or script_index >= len(scripts):
        raise ValueError("剧本编号超出范围")
    return scripts[script_index]


def _storyboard_cache_key(state: dict, brief_script: dict) -> str:
    """Build a stable in-memory cache key for one selected brief script."""
    payload = {
        "theme": state.get("theme", ""),
        "reference": (state.get("reference_structure") or state.get("custom_structure") or {}).get("video_name", ""),
        "materials": state.get("materials") or [],
        "brief_script": brief_script,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _select_script_response(detailed_script: dict, storyboard: dict):
    return jsonify({
        "state": "STORYBOARD",
        "script_title": detailed_script.get("title", ""),
        "script_version": detailed_script.get("version_name", ""),
        "total_duration": storyboard.get("total_duration", 0),
        "scene_count": storyboard.get("scene_count", 0),
        "scenes": _serialize_scenes(storyboard.get("scenes", [])),
        "gaps": storyboard.get("gaps", {}),
        "edit_hints": [
            "开头更抓人一些",
            "减少字幕，增强节奏感",
            "把崩溃镜头提前",
            "加个奶茶贴纸",
            "节奏再快一点",
        ],
    })


@app.route("/api/select-script", methods=["POST"])
def api_select_script():
    """选择简略剧本 → 展开为详细剧本 → 生成分镜

    Phase 2: 将用户选中的简略剧本展开为完整详细剧本（含逐镜头），然后生成分镜脚本。
    """
    data = request.get_json() or {}
    session_id = data.get("session_id", "")
    script_index = data.get("script_index", 0)
    _, state = get_or_create_session(session_id)

    if not state["scripts"]:
        return jsonify({"error": "请先生成剧本"}), 400

    scripts = state["scripts"].get("scripts", [])
    try:
        brief_script = _resolve_script_selection(scripts, data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if brief_script.get("error"):
        return jsonify({"error": "该剧本生成失败，请选择其他剧本"}), 400

    state["selected_script"] = brief_script
    state["state"] = "SELECT"
    cache = state.setdefault("storyboard_cache", {})
    cache_key = _storyboard_cache_key(state, brief_script)
    cached = cache.get(cache_key)
    if cached:
        state["selected_script"] = cached["selected_script"]
        state["storyboard"] = cached["storyboard"]
        state["state"] = "STORYBOARD"
        return _select_script_response(cached["selected_script"], cached["storyboard"])

    try:
        workflow_state = run_select_to_storyboard({
            "session_id": session_id,
            "theme": state["theme"],
            "reference_structure": state.get("reference_structure") or state.get("custom_structure"),
            "materials": state.get("materials"),
            "selected_script": brief_script,
        })
    except WorkflowStepError as e:
        return jsonify({"error": e.message}), 500
    except Exception as e:
        return jsonify({"error": f"分镜生成失败: {str(e)}"}), 500

    detailed_script = workflow_state["selected_script"]
    storyboard = workflow_state["storyboard"]

    state["storyboard"] = storyboard
    state["state"] = "STORYBOARD"
    cache[cache_key] = {
        "selected_script": detailed_script,
        "storyboard": storyboard,
    }

    return _select_script_response(detailed_script, storyboard)


@app.route("/api/edit", methods=["POST"])
def api_edit():
    """自然语言编辑分镜"""
    data = request.get_json() or {}
    session_id = data.get("session_id", "")
    instruction = data.get("instruction", "").strip()
    _, state = get_or_create_session(session_id)

    if not instruction:
        return jsonify({"error": "请输入编辑指令"}), 400

    if not state["storyboard"]:
        return jsonify({"error": "请先生成分镜"}), 400

    try:
        edit_plan = parse_edit_intent(instruction, state["storyboard"])
        state["storyboard"] = apply_edits(state["storyboard"], edit_plan)
        state["edit_history"].append({
            "instruction": instruction,
            "intent": edit_plan.get("intent", ""),
            "explanation": edit_plan.get("explanation", ""),
        })
        state["state"] = "STORYBOARD"
    except Exception as e:
        return jsonify({"error": f"编辑失败: {str(e)}"}), 500

    storyboard = state["storyboard"]

    return jsonify({
        "state": "STORYBOARD",
        "edit_result": {
            "intent": edit_plan.get("intent", ""),
            "explanation": edit_plan.get("explanation", ""),
            "modifications_count": len(edit_plan.get("modifications", [])),
        },
        "total_duration": storyboard.get("total_duration", 0),
        "scene_count": storyboard.get("scene_count", 0),
        "scenes": _serialize_scenes(storyboard.get("scenes", [])),
        "gaps": storyboard.get("gaps", {}),
        "edit_history": state["edit_history"],
    })


@app.route("/api/finalize", methods=["POST"])
def api_finalize():
    """输出最终方案"""
    data = request.get_json() or {}
    session_id = data.get("session_id", "")
    _, state = get_or_create_session(session_id)

    if not state["storyboard"]:
        return jsonify({"error": "没有可输出的分镜"}), 400

    # 保存最终输出
    output_dir = config.generated_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"final_storyboard_{session_id}.json"
    save_json(output_path, state["storyboard"])

    storyboard = state["storyboard"]

    # 生成素材清单
    asset_list = []
    for scene in storyboard.get("scenes", []):
        item = {
            "scene_id": scene["scene_id"],
            "description": scene.get("description", ""),
            "cat_motion_id": scene.get("cat_motion_id"),
            "cat_motion_file": scene.get("cat_motion_file", ""),
            "stickers": [s.get("file", "") for s in scene.get("stickers", [])],
            "generated_assets": scene.get("generated_assets", []),
        }
        asset_list.append(item)

    return jsonify({
        "state": "DONE",
        "output_file": str(output_path),
        "theme": storyboard.get("theme", ""),
        "script_title": storyboard.get("script_title", ""),
        "script_version": storyboard.get("script_version", ""),
        "total_duration": storyboard.get("total_duration", 0),
        "scene_count": storyboard.get("scene_count", 0),
        "scenes": _serialize_scenes(storyboard.get("scenes", [])),
        "asset_list": asset_list,
    })


@app.route("/api/generate-video", methods=["POST"])
def api_generate_video():
    """合成最终视频"""
    data = request.get_json() or {}
    session_id = data.get("session_id", "")
    _, state = get_or_create_session(session_id)

    if not state["storyboard"]:
        return jsonify({"error": "请先生成分镜"}), 400

    output_dir = config.generated_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"final_video_{session_id}.mp4"

    try:
        workflow_state = run_compose_video({
            "session_id": session_id,
            "storyboard": state["storyboard"],
            "output_path": output_path,
        })
        result_path = Path(workflow_state["video_path"])
        state["storyboard"] = workflow_state.get("storyboard", state["storyboard"])
        state["video_path"] = workflow_state["video_path"]
        state["state"] = "DONE"

        return jsonify({
            "state": "DONE",
            "video_url": f"/assets/generated/output/{result_path.name}",
            "video_path": workflow_state["video_path"],
            "file_size_mb": round(result_path.stat().st_size / (1024 * 1024), 2),
        })
    except Exception as e:
        return jsonify({"error": f"视频合成失败: {str(e)}"}), 500


@app.route("/api/generate-video-stream")
def api_generate_video_stream():
    """合成视频（SSE 流式推送进度）"""
    session_id = request.args.get("session_id", "")
    _, state = get_or_create_session(session_id)

    if not state["storyboard"]:
        def error_stream():
            yield f"data: {json.dumps({'error': '请先生成分镜'})}\n\n"
        return Response(error_stream(), mimetype="text/event-stream")

    output_dir = config.generated_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"final_video_{session_id}.mp4"

    # 用于线程间通信
    progress_lock = threading.Lock()
    progress_data = {"current": 0, "total": len(state["storyboard"].get("scenes", []))}
    done_event = threading.Event()
    result_holder = {}

    def on_progress(current: int, total: int):
        with progress_lock:
            progress_data["current"] = current
            progress_data["total"] = total

    def run_compose():
        try:
            workflow_state = run_compose_video({
                "session_id": session_id,
                "storyboard": state["storyboard"],
                "output_path": output_path,
                "on_video_progress": on_progress,
            })
            result_holder["path"] = workflow_state["video_path"]
            result_holder["size_mb"] = workflow_state["video_size_mb"]
            state["storyboard"] = workflow_state.get("storyboard", state["storyboard"])
            state["video_path"] = workflow_state["video_path"]
            state["state"] = "DONE"
        except Exception as e:
            result_holder["error"] = str(e)
        finally:
            done_event.set()

    thread = threading.Thread(target=run_compose, daemon=True)
    thread.start()

    return Response(
        stream_with_context(
            _iter_video_stream_events(
                progress_data=progress_data,
                progress_lock=progress_lock,
                done_event=done_event,
                result_holder=result_holder,
            )
        ),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _iter_video_stream_events(
    progress_data: dict,
    progress_lock: threading.Lock,
    done_event: threading.Event,
    result_holder: dict,
    sleep_seconds: float = 0.2,
):
    """Yield video-generation SSE events without dropping the terminal event."""
    last_current = 0
    while True:
        with progress_lock:
            current = progress_data["current"]
            total = progress_data["total"]

        if current > last_current:
            pct = round(current / total * 100) if total else 0
            yield f"event: progress\ndata: {json.dumps({'current': current, 'total': total, 'percent': pct})}\n\n"
            last_current = current

        if done_event.is_set():
            if "error" in result_holder:
                yield f"event: error\ndata: {json.dumps({'error': result_holder['error']})}\n\n"
            else:
                video_url = f"/assets/generated/output/{Path(result_holder['path']).name}"
                payload = {
                    "video_url": video_url,
                    "file_size_mb": result_holder.get("size_mb", 0),
                }
                yield f"event: done\ndata: {json.dumps(payload)}\n\n"
            break

        time.sleep(sleep_seconds)


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """重置会话"""
    data = request.get_json() or {}
    session_id = data.get("session_id", "")
    if session_id in sessions:
        del sessions[session_id]
    return jsonify({"status": "ok"})


# ─── 静态文件服务 ───────────────────────────────────────

@app.route("/assets/<path:filepath>")
def serve_assets(filepath):
    """服务 assets 目录下的文件"""
    asset_path = config.assets_root / filepath
    if asset_path.exists():
        return send_file(asset_path)
    return jsonify({"error": "file not found"}), 404


@app.route("/")
def index():
    """主页面"""
    return send_file("templates/index.html")


# ─── 辅助函数 ───────────────────────────────────────────

def _serialize_scenes(scenes: list[dict]) -> list[dict]:
    """序列化场景列表（将 Path 对象转为字符串）。"""
    result = []
    for s in scenes:
        item = {
            "scene_id": s.get("scene_id", 0),
            "duration": s.get("duration", 3),
            "description": s.get("description", ""),
            "subtitle": s.get("subtitle", ""),
            "subtitle_style": s.get("subtitle_style", ""),
            "topic_caption": s.get("topic_caption", ""),
            "scene_caption": s.get("scene_caption", ""),
            "dialogues": s.get("dialogues", []),
            "transition": s.get("transition", "硬切"),
            "emotion": s.get("emotion", ""),
            "cat_motion_id": s.get("cat_motion_id"),
            "cat_motion_desc": str(s.get("cat_motion_desc", "")),
            "stickers": [
                {
                    "category": st.get("category", ""),
                    "file": str(st.get("file", "")),
                    "position": st.get("position", ""),
                    "scale": st.get("scale", 180),
                }
                for st in s.get("stickers", [])
            ],
            "generated_assets": s.get("generated_assets", []),
            "notes": s.get("notes", ""),
            "match_score": s.get("_match_score", 0),
            "is_fallback": s.get("_fallback", False),
        }
        result.append(item)
    return result


# ─── 启动 ───────────────────────────────────────────────

if __name__ == "__main__":
    import webbrowser
    import threading

    port = 8080
    print(f"""
╔══════════════════════════════════════════════════════╗
║     🎬 爆款结构迁移引擎 Agent                        ║
║                                                      ║
║     服务地址: http://localhost:{port}                   ║
║     API 文档: http://localhost:{port}/api/health       ║
║                                                      ║
║     已加载 {len(load_structures())} 个爆款视频结构                   ║
║     Model: {config.model}              ║
╚══════════════════════════════════════════════════════╝
""")

    # 自动打开浏览器
    def open_browser():
        webbrowser.open(f"http://localhost:{port}")

    threading.Timer(1.0, open_browser).start()

    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
