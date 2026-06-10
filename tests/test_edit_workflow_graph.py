import unittest
from unittest.mock import patch

from agent import edit_workflow_graph


class EditWorkflowGraphTest(unittest.TestCase):
    @patch("agent.edit_workflow_graph.validate_edit_result")
    @patch("agent.edit_workflow_graph.apply_edit_tools")
    @patch("agent.edit_workflow_graph.plan_edit_tools")
    def test_run_edit_storyboard_plans_applies_and_validates(
        self,
        plan_edit_tools,
        apply_edit_tools,
        validate_edit_result,
    ):
        storyboard = {"scenes": [{"scene_id": 1, "subtitle": "old"}]}
        edit_plan = {
            "intent": "adjust_subtitle",
            "explanation": "改字幕",
            "modifications": [
                {"scene_id": 1, "action": "modify", "field": "subtitle", "new_value": "new"}
            ],
        }
        edited_storyboard = {"scenes": [{"scene_id": 1, "subtitle": "new"}]}
        plan_edit_tools.return_value = edit_plan
        apply_edit_tools.return_value = edited_storyboard
        validate_edit_result.return_value = {"ok": True, "issues": []}

        result = edit_workflow_graph.run_edit_storyboard({
            "session_id": "s1",
            "instruction": "把字幕改成new",
            "storyboard": storyboard,
        })

        self.assertEqual(result["state"], "STORYBOARD")
        self.assertEqual(result["edit_plan"], edit_plan)
        self.assertEqual(result["storyboard"], edited_storyboard)
        self.assertEqual(result["validation"], {"ok": True, "issues": []})
        plan_edit_tools.assert_called_once_with("把字幕改成new", storyboard)
        apply_edit_tools.assert_called_once_with(storyboard, edit_plan)
        validate_edit_result.assert_called_once_with("把字幕改成new", storyboard, edited_storyboard, edit_plan)

    @patch("agent.edit_workflow_graph.validate_edit_result")
    @patch("agent.edit_workflow_graph.apply_edit_tools")
    @patch("agent.edit_workflow_graph.plan_edit_tools")
    def test_run_edit_storyboard_raises_step_error_for_failed_validation(
        self,
        plan_edit_tools,
        apply_edit_tools,
        validate_edit_result,
    ):
        plan_edit_tools.return_value = {"intent": "mixed", "explanation": "无修改", "modifications": []}
        apply_edit_tools.return_value = {"scenes": []}
        validate_edit_result.return_value = {"ok": False, "issues": ["没有生成任何可执行修改"]}

        with self.assertRaises(edit_workflow_graph.EditWorkflowStepError) as ctx:
            edit_workflow_graph.run_edit_storyboard({
                "instruction": "把第1镜字幕改短",
                "storyboard": {"scenes": [{"scene_id": 1}]},
            })

        self.assertEqual(ctx.exception.step, "validate_edit")
        self.assertIn("没有生成任何可执行修改", ctx.exception.message)

    def test_validate_edit_result_detects_unchanged_dialogue_motion_replacement(self):
        original = {
            "scenes": [
                {
                    "scene_id": 4,
                    "dialogues": [
                        {"speaker": "领导", "line": "开会", "motion_id": "4"},
                        {"speaker": "我", "line": "神游", "motion_id": "14"},
                    ],
                }
            ]
        }
        edit_plan = {
            "intent": "replace_dialogue_motion",
            "modifications": [
                {
                    "scene_id": 4,
                    "action": "modify",
                    "field": "replace_dialogue_motion",
                    "new_value": {"slot": "right", "dialogue_index": 1, "avoid_motion_id": "14"},
                }
            ],
        }

        validation = edit_workflow_graph.validate_edit_result(
            "分镜4右侧猫不合适，换掉",
            original,
            original,
            edit_plan,
        )

        self.assertFalse(validation["ok"])
        self.assertIn("镜4右边猫动作没有更换", validation["issues"][0])


if __name__ == "__main__":
    unittest.main()
