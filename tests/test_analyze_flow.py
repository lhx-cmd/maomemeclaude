import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class AnalyzeFlowTest(unittest.TestCase):
    def setUp(self):
        server.sessions.clear()

    @patch("server.load_structures")
    def test_builtin_structure_selection_never_reanalyzes_raw_videos(self, load_structures):
        load_structures.side_effect = [
            {},
        ]
        client = server.app.test_client()

        response = client.post(
            "/api/analyze",
            data={"session_id": "s1", "theme": "周一打工人"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("内置爆款结构库为空", response.get_json()["error"])

    @patch("server.analyze_video")
    def test_uploaded_video_is_analyzed_on_demand(self, analyze_video):
        analyze_video.return_value = {
            "video_name": "uploaded.mp4",
            "narrative_pattern": "hook→反转",
            "emotional_arc": "好奇→爆笑",
            "script_structure": {"hook": {"type": "共鸣"}},
            "overall_style_summary": "上传视频结构",
        }
        client = server.app.test_client()

        response = client.post(
            "/api/analyze",
            data={
                "session_id": "s2",
                "theme": "周一打工人",
                "video": (io.BytesIO(b"fake mp4"), "uploaded.mp4"),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["source"], "uploaded")
        analyze_video.assert_called_once()

    @patch("server.analyze_video")
    def test_uploaded_video_request_preserves_uploaded_materials(self, analyze_video):
        analyze_video.return_value = {
            "video_name": "uploaded.mp4",
            "narrative_pattern": "hook→反转",
            "emotional_arc": "好奇→爆笑",
            "script_structure": {"hook": {"type": "共鸣"}},
            "overall_style_summary": "上传视频结构",
        }
        client = server.app.test_client()

        with tempfile.TemporaryDirectory() as tmp:
            old_upload_dir = server.UPLOAD_DIR
            server.UPLOAD_DIR = Path(tmp)
            try:
                response = client.post(
                    "/api/analyze",
                    data={
                        "session_id": "s3",
                        "theme": "周一打工人",
                        "video": (io.BytesIO(b"fake mp4"), "uploaded.mp4"),
                        "materials": (io.BytesIO(b"fake png"), "office_background.png"),
                    },
                    content_type="multipart/form-data",
                )
            finally:
                server.UPLOAD_DIR = old_upload_dir

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["source"], "uploaded")
        analyze_video.assert_called_once()
        state = server.sessions["s3"]
        self.assertEqual(state["custom_structure"]["video_name"], "uploaded.mp4")
        self.assertIsNone(state.get("reference_structure"))
        self.assertEqual(len(state["materials"]), 1)
        self.assertTrue(state["materials"][0].endswith("s3_mat_office_background.png"))

    @patch("server.build_user_material_index")
    @patch("agent.script_generator._auto_match_structure")
    @patch("server.load_structures")
    def test_uploaded_materials_are_indexed_during_analyze(
        self,
        load_structures,
        auto_match,
        build_index,
    ):
        load_structures.return_value = {
            "ref": {
                "video_name": "ref.mp4",
                "narrative_pattern": "hook",
                "emotional_arc": "arc",
                "script_structure": {"hook": {"type": "共鸣"}},
                "overall_style_summary": "style",
            }
        }
        auto_match.return_value = load_structures.return_value["ref"]
        build_index.return_value = {
            "materials": [
                {"file": "/tmp/indexed.mp4", "description": "焦虑赶路猫"}
            ]
        }
        client = server.app.test_client()

        with tempfile.TemporaryDirectory() as tmp:
            old_upload_dir = server.UPLOAD_DIR
            server.UPLOAD_DIR = Path(tmp)
            try:
                response = client.post(
                    "/api/analyze",
                    data={
                        "session_id": "s_index",
                        "theme": "迟到哄女友",
                        "materials": [
                            (io.BytesIO(b"fake mp4"), "anxious_cat.mp4"),
                            (io.BytesIO(b"fake mp4"), "cute_cat.mp4"),
                        ],
                    },
                    content_type="multipart/form-data",
                )
            finally:
                server.UPLOAD_DIR = old_upload_dir

        self.assertEqual(response.status_code, 200)
        state = server.sessions["s_index"]
        self.assertEqual(state["material_index"], build_index.return_value)
        build_index.assert_called_once_with(state["materials"])

    @patch("agent.script_generator._auto_match_structure")
    @patch("server.load_structures")
    def test_uploaded_material_with_chinese_filename_keeps_video_extension(self, load_structures, auto_match):
        load_structures.return_value = {
            "ref": {
                "video_name": "ref.mp4",
                "narrative_pattern": "hook",
                "emotional_arc": "arc",
                "script_structure": {"hook": {"type": "共鸣"}},
                "overall_style_summary": "style",
            }
        }
        auto_match.return_value = load_structures.return_value["ref"]
        client = server.app.test_client()

        with tempfile.TemporaryDirectory() as tmp:
            old_upload_dir = server.UPLOAD_DIR
            server.UPLOAD_DIR = Path(tmp)
            try:
                response = client.post(
                    "/api/analyze",
                    data={
                        "session_id": "s4",
                        "theme": "迟到哄女友",
                        "materials": (io.BytesIO(b"fake mp4"), "小猫动作.mp4"),
                    },
                    content_type="multipart/form-data",
                )
            finally:
                server.UPLOAD_DIR = old_upload_dir

        self.assertEqual(response.status_code, 200)
        state = server.sessions["s4"]
        self.assertEqual(len(state["materials"]), 1)
        self.assertTrue(state["materials"][0].endswith(".mp4"))
        self.assertIn("s4_mat_", Path(state["materials"][0]).name)


if __name__ == "__main__":
    unittest.main()
