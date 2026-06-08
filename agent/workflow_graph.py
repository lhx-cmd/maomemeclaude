"""LangGraph workflow shell for the main generation flow.

This module deliberately keeps graph nodes coarse-grained. Existing business
functions still own prompts, material matching, AIGC filling, and video
composition; LangGraph only provides a structured execution wrapper.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from .script_generator import expand_script_detail, generate_brief_scripts_streaming
from .storyboard_generator import fill_storyboard_gaps_for_video, generate_storyboard
from .video_composer import compose_video


ProgressCallback = Callable[[str, Optional[dict]], None]
VideoProgressCallback = Callable[[int, int], None]


class WorkflowState(TypedDict, total=False):
    session_id: str
    state: str
    theme: str
    reference_structure: dict
    materials: list[str]
    preference: str
    scripts: dict
    selected_script: dict
    storyboard: dict
    output_path: Path
    video_path: str
    video_size_mb: float
    error: str
    on_progress: ProgressCallback
    on_video_progress: VideoProgressCallback


class WorkflowStepError(RuntimeError):
    """Exception that preserves the user-facing error message for a graph node."""

    def __init__(self, step: str, message: str):
        super().__init__(message)
        self.step = step
        self.message = message


def run_generate_briefs(state: WorkflowState) -> WorkflowState:
    """Run the graph node that generates brief candidate scripts."""
    return _run_graph(("generate_briefs",), state)


def run_select_to_storyboard(state: WorkflowState) -> WorkflowState:
    """Run detail expansion followed by storyboard generation."""
    return _run_graph(("expand_detail", "build_storyboard"), state)


def run_compose_video(state: WorkflowState) -> WorkflowState:
    """Run the video composition graph node."""
    return _run_graph(("compose_video",), state)


def _run_graph(node_names: tuple[str, ...], state: WorkflowState) -> WorkflowState:
    graph = _build_graph(node_names)
    return graph.invoke(dict(state))


def _build_graph(node_names: tuple[str, ...]):
    graph = StateGraph(WorkflowState)
    node_map = {
        "generate_briefs": _generate_briefs_node,
        "expand_detail": _expand_detail_node,
        "build_storyboard": _build_storyboard_node,
        "compose_video": _compose_video_node,
    }

    for node_name in node_names:
        graph.add_node(node_name, node_map[node_name])

    graph.add_edge(START, node_names[0])
    for left, right in zip(node_names, node_names[1:]):
        graph.add_edge(left, right)
    graph.add_edge(node_names[-1], END)
    return graph.compile()


def _generate_briefs_node(state: WorkflowState) -> dict[str, Any]:
    start_time = time.time()
    scripts = generate_brief_scripts_streaming(
        theme=state.get("theme", ""),
        reference_structure=state.get("reference_structure"),
        custom_materials=state.get("materials"),
        user_preferences=state.get("preference", ""),
        on_progress=state.get("on_progress"),
    )
    print(f"   ⏱ LangGraph node generate_briefs 耗时 {time.time() - start_time:.1f}秒")
    return {
        "scripts": scripts,
        "state": "GENERATE_SCRIPT",
    }


def _expand_detail_node(state: WorkflowState) -> dict[str, Any]:
    start_time = time.time()
    try:
        detailed_script = expand_script_detail(
            brief_script=state.get("selected_script", {}),
            theme=state.get("theme", ""),
            reference_structure=state.get("reference_structure"),
            custom_materials=state.get("materials"),
        )
    except Exception as exc:
        raise WorkflowStepError("expand_detail", f"剧本展开失败: {exc}") from exc
    print(f"   ⏱ LangGraph node expand_detail 耗时 {time.time() - start_time:.1f}秒")

    return {
        "selected_script": detailed_script,
        "state": "SELECT",
    }


def _build_storyboard_node(state: WorkflowState) -> dict[str, Any]:
    start_time = time.time()
    try:
        storyboard = generate_storyboard(
            selected_script=state.get("selected_script", {}),
            theme=state.get("theme", ""),
            auto_fill_gaps=False,
            review_materials=True,
        )
    except Exception as exc:
        raise WorkflowStepError("build_storyboard", f"分镜生成失败: {exc}") from exc
    print(f"   ⏱ LangGraph node build_storyboard 耗时 {time.time() - start_time:.1f}秒")

    return {
        "storyboard": storyboard,
        "state": "STORYBOARD",
    }


def _compose_video_node(state: WorkflowState) -> dict[str, Any]:
    start_time = time.time()
    try:
        storyboard = fill_storyboard_gaps_for_video(state.get("storyboard", {}))
        result = compose_video(
            storyboard=storyboard,
            output_path=state.get("output_path"),
            on_progress=state.get("on_video_progress"),
        )
    except Exception as exc:
        raise WorkflowStepError("compose_video", f"视频合成失败: {exc}") from exc
    print(f"   ⏱ LangGraph node compose_video 耗时 {time.time() - start_time:.1f}秒")

    result_path = Path(result)
    return {
        "storyboard": storyboard,
        "video_path": str(result_path),
        "video_size_mb": round(result_path.stat().st_size / (1024 * 1024), 2) if result_path.exists() else 0,
        "state": "DONE",
    }
