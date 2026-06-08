import unittest
from pathlib import Path
from unittest.mock import patch

from agent import workflow_graph


class WorkflowGraphTest(unittest.TestCase):
    @patch("agent.workflow_graph.generate_brief_scripts_streaming")
    def test_generate_briefs_node_preserves_scripts_and_progress(self, generate_briefs):
        generate_briefs.return_value = {
            "scripts": [
                {"version": "high_click", "title": "A"},
                {"version": "high_resonance", "title": "B"},
                {"version": "high_conversion", "title": "C"},
            ],
            "reference_video": "ref.mp4",
        }
        progress_events = []

        result = workflow_graph.run_generate_briefs({
            "session_id": "s1",
            "theme": "打工人周一",
            "reference_structure": {"video_name": "ref.mp4"},
            "materials": ["/tmp/mat.png"],
            "preference": "更搞笑",
            "on_progress": lambda version, script: progress_events.append((version, script)),
        })

        self.assertEqual(result["state"], "GENERATE_SCRIPT")
        self.assertEqual(result["scripts"]["scripts"][0]["title"], "A")
        generate_briefs.assert_called_once()
        self.assertEqual(generate_briefs.call_args.kwargs["theme"], "打工人周一")
        self.assertEqual(generate_briefs.call_args.kwargs["custom_materials"], ["/tmp/mat.png"])

    @patch("agent.workflow_graph.generate_storyboard")
    @patch("agent.workflow_graph.expand_script_detail")
    def test_run_select_to_storyboard_writes_detail_and_storyboard(
        self,
        expand_detail,
        generate_storyboard,
    ):
        expand_detail.return_value = {
            "title": "详细剧本",
            "version_name": "高点击版",
            "scenes": [{"scene_id": 1}],
        }
        generate_storyboard.return_value = {
            "total_duration": 2,
            "scene_count": 1,
            "scenes": [{"scene_id": 1, "subtitle": "hi"}],
            "gaps": {},
        }

        result = workflow_graph.run_select_to_storyboard({
            "session_id": "s1",
            "theme": "补考",
            "reference_structure": {"video_name": "ref.mp4"},
            "materials": [],
            "selected_script": {"version": "high_click", "title": "简略"},
        })

        self.assertEqual(result["state"], "STORYBOARD")
        self.assertEqual(result["selected_script"]["title"], "详细剧本")
        self.assertEqual(result["storyboard"]["scene_count"], 1)
        expand_detail.assert_called_once()
        generate_storyboard.assert_called_once_with(
            selected_script=expand_detail.return_value,
            theme="补考",
            auto_fill_gaps=False,
            review_materials=True,
        )

    @patch("agent.workflow_graph.compose_video")
    @patch("agent.workflow_graph.fill_storyboard_gaps_for_video")
    def test_run_compose_video_writes_done_state(self, fill_storyboard, compose_video):
        output_path = Path("/tmp/final.mp4")
        filled_storyboard = {"scenes": [{"scene_id": 1, "generated_assets": [{"file": "/tmp/bg.png"}]}]}
        fill_storyboard.return_value = filled_storyboard
        compose_video.return_value = output_path
        progress_events = []

        result = workflow_graph.run_compose_video({
            "session_id": "s1",
            "storyboard": {"scenes": [{"scene_id": 1}]},
            "output_path": output_path,
            "on_video_progress": lambda current, total: progress_events.append((current, total)),
        })

        self.assertEqual(result["state"], "DONE")
        self.assertEqual(result["video_path"], str(output_path))
        fill_storyboard.assert_called_once_with({"scenes": [{"scene_id": 1}]})
        compose_video.assert_called_once_with(
            storyboard=filled_storyboard,
            output_path=output_path,
            on_progress=result["on_video_progress"],
        )


if __name__ == "__main__":
    unittest.main()
