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
            result_holder = {
                "path": str(output),
                "size_mb": 1.23,
                "storyboard": {"scenes": [{"scene_id": 1, "cat_motion_id": "23"}]},
            }

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
        self.assertEqual(payload["scenes"][0]["cat_motion_id"], "23")

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
                    "storyboard": {"scenes": [{"scene_id": 1, "cat_motion_id": "23"}]},
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
        self.assertIn('"cat_motion_id": "23"', body)
        self.assertEqual(server.sessions[session_id]["state"], "DONE")
        run_workflow.assert_called_once()
        self.assertEqual(run_workflow.call_args.args[0]["storyboard"], {"scenes": [{"scene_id": 1}]})

    @patch("server.run_compose_video")
    def test_generate_video_stream_returns_unique_video_urls_for_same_session(self, run_workflow):
        server.sessions.clear()
        session_id = "session_video_unique"
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
            generated_paths = []

            def workflow_side_effect(state):
                state["on_video_progress"](1, 1)
                output_path = state["output_path"]
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"video")
                generated_paths.append(output_path)
                return {
                    "video_path": str(output_path),
                    "video_size_mb": 0,
                    "state": "DONE",
                    "storyboard": {"scenes": [{"scene_id": 1}]},
                }

            run_workflow.side_effect = workflow_side_effect
            try:
                client = server.app.test_client()
                first = client.get(
                    f"/api/generate-video-stream?session_id={session_id}",
                    buffered=True,
                )
                second = client.get(
                    f"/api/generate-video-stream?session_id={session_id}",
                    buffered=True,
                )
                first_body = b"".join(first.response).decode("utf-8")
                second_body = b"".join(second.response).decode("utf-8")
            finally:
                server.config.generated_dir = old_generated_dir

        first_payload = _done_payload(first_body)
        second_payload = _done_payload(second_body)
        self.assertNotEqual(first_payload["video_url"], second_payload["video_url"])
        self.assertNotEqual(generated_paths[0].name, generated_paths[1].name)
        self.assertTrue(generated_paths[0].name.startswith(f"final_video_{session_id}_"))
        self.assertTrue(generated_paths[1].name.startswith(f"final_video_{session_id}_"))

    def test_served_mp4_assets_are_not_cached_and_allow_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_assets_root = server.config.assets_root
            server.config.assets_root = Path(tmp)
            output_dir = Path(tmp) / "generated" / "output"
            output_dir.mkdir(parents=True)
            (output_dir / "clip.mp4").write_bytes(b"fake video")
            try:
                response = server.app.test_client().get("/assets/generated/output/clip.mp4")
            finally:
                server.config.assets_root = old_assets_root

        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "video/mp4")
            self.assertIn("no-store", response.headers.get("Cache-Control", ""))
            self.assertEqual(response.headers.get("Accept-Ranges"), "bytes")
        finally:
            response.close()


def _done_payload(body: str) -> dict:
    for event in body.split("\n\n"):
        if event.startswith("event: done"):
            return json.loads(event.split("data: ", 1)[1])
    raise AssertionError("missing done event")


if __name__ == "__main__":
    unittest.main()
