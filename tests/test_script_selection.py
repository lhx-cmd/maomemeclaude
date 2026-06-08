import unittest
from unittest.mock import patch

import server


class ScriptSelectionTest(unittest.TestCase):
    def test_selects_script_by_version_when_sse_cards_arrive_out_of_order(self):
        scripts = [
            {"version": "high_click", "title": "click"},
            {"version": "high_resonance", "title": "resonance"},
            {"version": "high_tempo", "title": "tempo"},
        ]

        selected = server._resolve_script_selection(
            scripts,
            {"script_version": "high_resonance", "script_index": 0},
        )

        self.assertEqual(selected["title"], "resonance")

    def test_falls_back_to_index_for_existing_clients(self):
        scripts = [
            {"version": "high_click", "title": "click"},
            {"version": "high_resonance", "title": "resonance"},
        ]

        selected = server._resolve_script_selection(scripts, {"script_index": 1})

        self.assertEqual(selected["title"], "resonance")

    @patch("server.run_select_to_storyboard")
    def test_select_script_uses_workflow_graph_without_changing_response(self, run_workflow):
        server.sessions.clear()
        session_id = "session_select"
        brief = {"version": "high_click", "title": "简略"}
        detailed = {"version": "high_click", "version_name": "高点击版", "title": "详细"}
        storyboard = {
            "total_duration": 2,
            "scene_count": 1,
            "scenes": [{"scene_id": 1, "duration": 2, "subtitle": "hi"}],
            "gaps": {},
        }
        server.sessions[session_id] = {
            "state": "GENERATE_SCRIPT",
            "theme": "补考",
            "video_path": None,
            "materials": [],
            "scripts": {"scripts": [brief]},
            "selected_script": None,
            "storyboard": None,
            "edit_history": [],
            "reference_structure": {"video_name": "ref.mp4"},
        }
        run_workflow.return_value = {
            "selected_script": detailed,
            "storyboard": storyboard,
            "state": "STORYBOARD",
        }

        client = server.app.test_client()
        response = client.post(
            "/api/select-script",
            json={"session_id": session_id, "script_index": 0},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["state"], "STORYBOARD")
        self.assertEqual(payload["script_title"], "详细")
        self.assertEqual(payload["scene_count"], 1)
        run_workflow.assert_called_once()
        self.assertEqual(run_workflow.call_args.args[0]["selected_script"], brief)
        self.assertEqual(server.sessions[session_id]["storyboard"], storyboard)

    @patch("server.run_select_to_storyboard")
    def test_reselecting_same_script_uses_session_cache(self, run_workflow):
        server.sessions.clear()
        session_id = "session_select_cache"
        brief = {"version": "high_click", "title": "简略"}
        detailed = {"version": "high_click", "version_name": "高点击版", "title": "详细"}
        storyboard = {
            "total_duration": 4,
            "scene_count": 1,
            "scenes": [{"scene_id": 1, "duration": 4, "subtitle": "hi"}],
            "gaps": {},
        }
        server.sessions[session_id] = {
            "state": "GENERATE_SCRIPT",
            "theme": "周一",
            "video_path": None,
            "materials": [],
            "scripts": {"scripts": [brief]},
            "selected_script": None,
            "storyboard": None,
            "storyboard_cache": {},
            "edit_history": [],
            "reference_structure": {"video_name": "ref.mp4"},
        }
        run_workflow.return_value = {
            "selected_script": detailed,
            "storyboard": storyboard,
            "state": "STORYBOARD",
        }

        client = server.app.test_client()
        first = client.post(
            "/api/select-script",
            json={"session_id": session_id, "script_version": "high_click"},
        )
        second = client.post(
            "/api/select-script",
            json={"session_id": session_id, "script_version": "high_click"},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["script_title"], "详细")
        run_workflow.assert_called_once()

    @patch("server.run_generate_briefs")
    def test_generate_scripts_stream_uses_workflow_graph(self, run_workflow):
        server.sessions.clear()
        session_id = "session_scripts"
        server.sessions[session_id] = {
            "state": "ANALYZE",
            "theme": "打工人",
            "video_path": None,
            "materials": [],
            "scripts": None,
            "selected_script": None,
            "storyboard": None,
            "edit_history": [],
            "reference_structure": {"video_name": "ref.mp4"},
        }

        def workflow_side_effect(state):
            state["on_progress"]("high_click", {
                "version": "high_click",
                "version_name": "高点击版",
                "title": "周一",
            })
            return {
                "scripts": {
                    "scripts": [
                        {"version": "high_click", "version_name": "高点击版", "title": "周一"}
                    ],
                    "reference_video": "ref.mp4",
                    "reference_narrative": "n",
                },
                "state": "GENERATE_SCRIPT",
            }

        run_workflow.side_effect = workflow_side_effect
        client = server.app.test_client()

        response = client.get(
            f"/api/generate-scripts-stream?session_id={session_id}",
            buffered=True,
        )
        body = b"".join(response.response).decode("utf-8")

        self.assertIn("event: progress", body)
        self.assertIn("event: done", body)
        self.assertEqual(server.sessions[session_id]["state"], "GENERATE_SCRIPT")
        self.assertIsNotNone(server.sessions[session_id]["scripts"])
        run_workflow.assert_called_once()


if __name__ == "__main__":
    unittest.main()
