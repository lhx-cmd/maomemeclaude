import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class VideoStreamEventsTest(unittest.TestCase):
    def test_sends_done_even_when_done_is_set_after_final_progress(self):
        done_event = threading.Event()
        done_event.set()
        progress_lock = threading.Lock()
        progress_data = {"current": 9, "total": 9}

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "final_video_session.mp4"
            output.touch()
            result_holder = {"path": str(output), "size_mb": 1.23}

            events = list(
                server._iter_video_stream_events(
                    progress_data=progress_data,
                    progress_lock=progress_lock,
                    done_event=done_event,
                    result_holder=result_holder,
                    sleep_seconds=0,
                )
            )

        self.assertTrue(any(event.startswith("event: progress") for event in events))
        done_events = [event for event in events if event.startswith("event: done")]
        self.assertEqual(len(done_events), 1)
        payload = json.loads(done_events[0].split("data: ", 1)[1])
        self.assertEqual(payload["video_url"], "/assets/generated/output/final_video_session.mp4")

    @patch("server.run_compose_video")
    def test_generate_video_stream_uses_workflow_graph(self, run_workflow):
        server.sessions.clear()
        session_id = "session_video"
        server.sessions[session_id] = {
            "state": "STORYBOARD",
            "theme": "打工人",
            "video_path": None,
            "materials": [],
            "scripts": None,
            "selected_script": None,
            "storyboard": {"scenes": [{"scene_id": 1}]},
            "edit_history": [],
        }

        with tempfile.TemporaryDirectory() as tmp:
            old_generated_dir = server.config.generated_dir
            server.config.generated_dir = Path(tmp)

            def workflow_side_effect(state):
                state["on_video_progress"](1, 1)
                output_path = state["output_path"]
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"video")
                return {
                    "video_path": str(output_path),
                    "video_size_mb": 0,
                    "state": "DONE",
                }

            run_workflow.side_effect = workflow_side_effect
            try:
                client = server.app.test_client()
                response = client.get(
                    f"/api/generate-video-stream?session_id={session_id}",
                    buffered=True,
                )
                body = b"".join(response.response).decode("utf-8")
            finally:
                server.config.generated_dir = old_generated_dir

        self.assertIn("event: progress", body)
        self.assertIn("event: done", body)
        self.assertEqual(server.sessions[session_id]["state"], "DONE")
        run_workflow.assert_called_once()
        self.assertEqual(run_workflow.call_args.args[0]["storyboard"], {"scenes": [{"scene_id": 1}]})


if __name__ == "__main__":
    unittest.main()
