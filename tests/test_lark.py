import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from agent_study.lark import Lark, RemoteError


class PreviewTests(unittest.TestCase):
    def test_remote_jpeg_and_png_exports_are_accepted(self):
        for suffix, header in ((".jpg", b"\xff\xd8\xff\xe0"), (".png", b"\x89PNG\r\n\x1a\n")):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as temporary:
                def export(command, **kwargs):
                    stem = command[command.index("--output") + 1]
                    self.assertEqual(Path(stem).suffix, "")
                    path = Path(kwargs["cwd"]) / (stem + suffix)
                    path.write_bytes(header + b"test fixture")
                    return subprocess.CompletedProcess(command, 0, json.dumps({"ok": True, "data": {"preview_image_path": stem + suffix}}), "")
                with patch("agent_study.lark.subprocess.run", side_effect=export):
                    path = Lark().preview("test-board", Path(temporary))
                    self.assertTrue(path.endswith(suffix))

    def test_export_path_cannot_leave_private_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.CompletedProcess([], 0, json.dumps({"ok": True, "data": {"preview_image_path": "../unexpected.jpg"}}), "")
            with patch("agent_study.lark.subprocess.run", return_value=result):
                with self.assertRaises(RemoteError): Lark().preview("board", Path(temporary))
