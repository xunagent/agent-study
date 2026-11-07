import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import study
from bind_profile import bind


class ProfileTests(unittest.TestCase):
    def test_explicit_profile_remembered_for_daily(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(study, "Engine") as engine, patch.object(study, "Lark") as lark:
                engine.return_value.daily.return_value = {"action": "read_current"}
                study.main(["--state-dir", directory, "--profile", "personal", "daily"])
                study.main(["--state-dir", directory, "daily"])
                self.assertEqual([c.args for c in lark.call_args_list], [("personal",), ("personal",)])

    def test_secret_sent_only_via_stdin(self):
        runner = Mock(side_effect=[subprocess.CompletedProcess([], 0, "[]", ""), subprocess.CompletedProcess([], 0, "", "")])
        with patch("bind_profile.subprocess.run", runner), contextlib.redirect_stdout(io.StringIO()) as out:
            bind("personal", "cli_test", "feishu", secret_reader=lambda _: "test-secret")
        args, kwargs = runner.call_args
        self.assertNotIn("test-secret", " ".join(args[0]))
        self.assertEqual(kwargs["input"], "test-secret\n")
        self.assertNotIn("test-secret", out.getvalue())

    def test_existing_different_app_not_overwritten(self):
        result = subprocess.CompletedProcess([], 0, json.dumps([{"name": "personal", "appId": "cli_other"}]), "")
        with patch("bind_profile.subprocess.run", return_value=result) as runner:
            with self.assertRaisesRegex(RuntimeError, "another app"):
                bind("personal", "cli_new", "feishu", secret_reader=lambda _: self.fail("Secret should not be requested"))
            self.assertEqual(runner.call_count, 1)
