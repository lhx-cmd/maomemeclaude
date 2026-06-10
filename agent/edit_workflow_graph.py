"""LangGraph workflow for natural-language storyboard edits.

The graph is intentionally local and request-scoped. It does not store
checkpoints or sessions; Flask still owns the in-memory session state.
"""

from __future__ import annotations

import copy
import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .editor import apply_edits, parse_edit_intent


class EditWorkflowState(TypedDict, total=False):
    session_id: str
    state: str
    instruction: str
    storyboard: dict
    original_storyboard: dict
    edit_plan: dict
    validation: dict
    error: str


class EditWorkflowStepError(RuntimeError):
    """Exception carrying a user-facing edit workflow error."""

    def __init__(self, step: str, message: str):
        super().__init__(message)
        self.step = step
        self.message = message


def run_edit_storyboard(state: EditWorkflowState) -> EditWorkflowState:
    """Run the edit workflow graph for one natural-language instruction."""
    graph = _build_edit_graph()
    return graph.invoke(dict(state))


def plan_edit_tools(instruction: str, storyboard: dict) -> dict:
    """Tool: convert natural language into a concrete edit plan."""
    return parse_edit_intent(instruction, storyboard)


def apply_edit_tools(storyboard: dict, edit_plan: dict) -> dict:
    """Tool: apply a concrete edit plan to a storyboard copy."""
    return apply_edits(copy.deepcopy(storyboard), edit_plan)


def validate_edit_result(
    instruction: str,
    original_storyboard: dict,
    edited_storyboard: dict,
    edit_plan: dict,
) -> dict:
    """Tool: lightweight validation that the edit did something plausible."""
    issues = []
    modifications = edit_plan.get("modifications", []) if isinstance(edit_plan, dict) else []
    if not modifications:
        issues.append("没有生成任何可执行修改")
    if edit_plan.get("intent") == "swap_dialogue_lines":
        issues.extend(_validate_dialogue_swap(original_storyboard, edited_storyboard, edit_plan))

    issues.extend(_validate_dialogue_motion_replacements(original_storyboard, edited_storyboard, edit_plan))
    issues.extend(_validate_render_control_modifications(edited_storyboard, edit_plan))

    if edited_storyboard == original_storyboard and modifications and not issues:
        issues.append("编辑计划未改变分镜内容")

    return {
        "ok": not issues,
        "issues": issues,
    }


def _build_edit_graph():
    graph = StateGraph(EditWorkflowState)
    graph.add_node("plan_edit", _plan_edit_node)
    graph.add_node("apply_edit", _apply_edit_node)
    graph.add_node("validate_edit", _validate_edit_node)
    graph.add_edge(START, "plan_edit")
    graph.add_edge("plan_edit", "apply_edit")
    graph.add_edge("apply_edit", "validate_edit")
    graph.add_edge("validate_edit", END)
    return graph.compile()


def _plan_edit_node(state: EditWorkflowState) -> dict[str, Any]:
    start_time = time.time()
    storyboard = state.get("storyboard", {})
    instruction = state.get("instruction", "")
    try:
        edit_plan = plan_edit_tools(instruction, storyboard)
    except Exception as exc:
        raise EditWorkflowStepError("plan_edit", f"编辑意图解析失败: {exc}") from exc
    print(f"   ⏱ LangGraph node plan_edit 耗时 {time.time() - start_time:.1f}秒")
    return {
        "original_storyboard": copy.deepcopy(storyboard),
        "edit_plan": edit_plan,
    }


def _apply_edit_node(state: EditWorkflowState) -> dict[str, Any]:
    start_time = time.time()
    try:
        storyboard = apply_edit_tools(state.get("storyboard", {}), state.get("edit_plan", {}))
    except Exception as exc:
        raise EditWorkflowStepError("apply_edit", f"编辑应用失败: {exc}") from exc
    print(f"   ⏱ LangGraph node apply_edit 耗时 {time.time() - start_time:.1f}秒")
    return {
        "storyboard": storyboard,
        "state": "STORYBOARD",
    }


def _validate_edit_node(state: EditWorkflowState) -> dict[str, Any]:
    start_time = time.time()
    validation = validate_edit_result(
        state.get("instruction", ""),
        state.get("original_storyboard", {}),
        state.get("storyboard", {}),
        state.get("edit_plan", {}),
    )
    print(f"   ⏱ LangGraph node validate_edit 耗时 {time.time() - start_time:.1f}秒")
    if not validation.get("ok", False):
        message = "；".join(str(issue) for issue in validation.get("issues", []) if issue)
        raise EditWorkflowStepError("validate_edit", message or "编辑结果未通过校验")
    return {
        "validation": validation,
    }


def _validate_dialogue_swap(original_storyboard: dict, edited_storyboard: dict, edit_plan: dict) -> list[str]:
    issues = []
    for modification in edit_plan.get("modifications", []) or []:
        if modification.get("field") != "swap_dialogue_lines":
            continue
        scene_id = modification.get("scene_id")
        original_scene = _find_scene(original_storyboard.get("scenes", []), scene_id)
        edited_scene = _find_scene(edited_storyboard.get("scenes", []), scene_id)
        if not original_scene or not edited_scene:
            issues.append(f"镜{scene_id}不存在，无法校验台词互换")
            continue
        original_dialogues = _dialogue_lines(original_scene)
        edited_dialogues = _dialogue_lines(edited_scene)
        if len(original_dialogues) < 2 or len(edited_dialogues) < 2:
            issues.append(f"镜{scene_id}不足两条猫头台词")
            continue
        if edited_dialogues[:2] != [original_dialogues[1], original_dialogues[0]]:
            issues.append(f"镜{scene_id}两只猫台词没有正确互换")
    return issues


def _validate_render_control_modifications(edited_storyboard: dict, edit_plan: dict) -> list[str]:
    issues = []
    for modification in edit_plan.get("modifications", []) or []:
        field = modification.get("field")
        if field not in {"audio_muted", "cat_layout_overrides"}:
            continue
        scene_id = modification.get("scene_id")
        edited_scene = _find_scene(edited_storyboard.get("scenes", []), scene_id)
        if not edited_scene:
            issues.append(f"镜{scene_id}不存在，无法校验渲染控制")
            continue
        if field == "audio_muted" and bool(edited_scene.get("audio_muted")) is not bool(modification.get("new_value")):
            issues.append(f"镜{scene_id}音频静音没有生效")
        if field == "cat_layout_overrides":
            missing = _missing_cat_layout_overrides(
                edited_scene.get("cat_layout_overrides"),
                modification.get("new_value"),
            )
            if missing:
                issues.append(f"镜{scene_id}猫布局没有生效: {', '.join(missing)}")
    return issues


def _validate_dialogue_motion_replacements(
    original_storyboard: dict,
    edited_storyboard: dict,
    edit_plan: dict,
) -> list[str]:
    issues = []
    for modification in edit_plan.get("modifications", []) or []:
        if modification.get("field") != "replace_dialogue_motion":
            continue
        scene_id = modification.get("scene_id")
        value = modification.get("new_value") if isinstance(modification.get("new_value"), dict) else {}
        slot = str(value.get("slot") or "")
        slot_label = _slot_label(slot)
        try:
            dialogue_index = int(value.get("dialogue_index", -1))
        except (TypeError, ValueError):
            dialogue_index = -1
        original_scene = _find_scene(original_storyboard.get("scenes", []), scene_id)
        edited_scene = _find_scene(edited_storyboard.get("scenes", []), scene_id)
        if not original_scene or not edited_scene:
            issues.append(f"镜{scene_id}不存在，无法校验猫动作更换")
            continue
        original_motion = _dialogue_motion_id(original_scene, dialogue_index)
        edited_motion = _dialogue_motion_id(edited_scene, dialogue_index)
        expected_motion = str(value.get("motion_id") or "")
        if dialogue_index < 0 or not original_motion:
            issues.append(f"镜{scene_id}{slot_label}猫不存在，无法校验动作更换")
            continue
        if not edited_motion or edited_motion == original_motion:
            issues.append(f"镜{scene_id}{slot_label}猫动作没有更换")
            continue
        if expected_motion and edited_motion != expected_motion:
            issues.append(f"镜{scene_id}{slot_label}猫动作不是预期 motion#{expected_motion}")
    return issues


def _missing_cat_layout_overrides(actual, expected) -> list[str]:
    if not isinstance(expected, dict):
        return []
    if not isinstance(actual, dict):
        actual = {}
    missing = []
    for slot, expected_slot in expected.items():
        if not isinstance(expected_slot, dict):
            continue
        actual_slot = actual.get(slot)
        if not isinstance(actual_slot, dict):
            missing.append(str(slot))
            continue
        for key, expected_value in expected_slot.items():
            if str(actual_slot.get(key)) != str(expected_value):
                missing.append(f"{slot}.{key}")
    return missing


def _find_scene(scenes: list[dict], scene_id: Any) -> dict | None:
    for scene in scenes:
        if scene.get("scene_id") == scene_id:
            return scene
    return None


def _dialogue_lines(scene: dict) -> list[str]:
    lines = []
    for dialogue in scene.get("dialogues", []) or []:
        if isinstance(dialogue, dict):
            lines.append(str(dialogue.get("line") or ""))
    return lines


def _dialogue_motion_id(scene: dict, dialogue_index: int) -> str:
    dialogues = scene.get("dialogues", []) or []
    if dialogue_index < 0 or dialogue_index >= len(dialogues):
        return ""
    dialogue = dialogues[dialogue_index]
    if not isinstance(dialogue, dict):
        return ""
    return str(dialogue.get("motion_id") or "")


def _slot_label(slot: str) -> str:
    return {
        "left": "左边",
        "right": "右边",
        "center": "中间",
    }.get(slot, "")
