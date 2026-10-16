"""诊断不能将缺失信息、错误服务或跳过检查误标为通过。"""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from product_photo import environment as env


def system_stats():
    return {
        "system": {
            "os": "linux", "python_version": "3.12.test", "pytorch_version": "test+cu",
            "comfyui_version": "test", "argv": ["main.py", "private-argument"],
        },
        "devices": [{"name": "test GPU", "type": "cuda", "index": 0, "vram_total": 24 * 1024**3}],
    }


class ComfyUITests(unittest.TestCase):
    def test_valid_api_keeps_only_queue_counts_and_safe_stats(self):
        queue = {"queue_running": [[1, "private-workflow"]], "queue_pending": []}
        with patch.object(env, "get_json", side_effect=[system_stats(), queue]) as get:
            report = env.probe_comfyui("http://192.168.1.171:8188/")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["queue"], {"running_count": 1, "pending_count": 0})
        self.assertEqual(report["workflow_execution"], "unverified")
        self.assertNotIn("private", json.dumps(report))
        self.assertEqual([call.args[0] for call in get.call_args_list], [
            "http://192.168.1.171:8188/system_stats", "http://192.168.1.171:8188/queue",
        ])

    def test_http_success_with_wrong_schema_is_not_passed(self):
        with patch.object(env, "get_json", side_effect=[{"ok": True}, {"queue_running": [], "queue_pending": []}]):
            report = env.probe_comfyui("http://localhost:8188")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["endpoints"]["/system_stats"]["status"], "failed")

    def test_queue_failure_does_not_discard_server_evidence(self):
        with patch.object(env, "get_json", side_effect=[system_stats(), urllib.error.URLError("blocked")]):
            report = env.probe_comfyui("http://localhost:8188")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["system"]["os"], "linux")
        self.assertIn("blocked", report["endpoints"]["/queue"]["error"])

    def test_credentials_and_malformed_urls_are_configuration_errors(self):
        for url in ("localhost:8188", "http://user:password@localhost", "http://localhost:bad", "http://localhost?q=secret"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                env.normalize_base_url(url)

    def test_http_probe_uses_get_and_rejects_non_object(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"[]"
        opener = unittest.mock.MagicMock()
        opener.open.return_value = response
        with patch.object(env.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(ValueError):
                env.get_json("http://localhost:8188/queue", 1)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")


class ProcessAndConfigTests(unittest.TestCase):
    def test_missing_executable_is_warning(self):
        with patch.object(env.subprocess, "run", side_effect=FileNotFoundError("missing")):
            self.assertEqual(env.run_command(["absent-tool"])["status"], "warning")

    def test_hanging_child_is_warning(self):
        with patch.object(env.subprocess, "run", side_effect=subprocess.TimeoutExpired(["tool"], 1)):
            report = env.run_command(["tool"], timeout=1)
        self.assertEqual(report["status"], "warning")
        self.assertIn("TimeoutExpired", report["error"])

    def test_child_crash_is_not_a_successful_import(self):
        with patch.object(env, "run_command", return_value={"status": "warning", "returncode": 7, "stdout": ""}):
            self.assertEqual(env.probe_python_code("test")["status"], "warning")

    def test_import_error_in_json_is_warning(self):
        with patch.object(env, "run_command", return_value={"status": "passed", "stdout": '{"error":"DLL failed"}'}):
            self.assertEqual(env.probe_python_code("test")["status"], "warning")

    def test_missing_package_metadata_is_recorded_as_null(self):
        with patch.object(env.importlib.metadata, "version", side_effect=env.importlib.metadata.PackageNotFoundError("missing")):
            versions = env.package_versions()
        self.assertTrue(all(value is None for value in versions.values()))

    def test_blender_not_on_path_does_not_claim_uninstalled(self):
        with patch.object(env.shutil, "which", return_value=None):
            report = env.probe_executable("blender")
        self.assertEqual(report["installation_status"], "unknown")

    def test_invalid_configuration_fails_before_probing(self):
        invalid_configs = [[], {"schema_version": 2}, {"schema_version": 1, "comfyui": None},
                           {"schema_version": 1, "comfyui": {"timeout_seconds": True}},
                           {"schema_version": 1, "comfyui": {"base_url": 123}}]
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            path = Path(directory) / "config.json"
            for config in invalid_configs:
                path.write_text(json.dumps(config), encoding="utf-8")
                with self.subTest(config=config), self.assertRaises(ValueError):
                    env.load_config(path)

    def test_report_is_utf8_and_replaces_previous_report(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            path = Path(directory) / "reports" / "report.json"
            env.write_report({"message": "未知厚度"}, path)
            env.write_report({"message": "待确认"}, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"message": "待确认"})
            self.assertEqual(list(path.parent.iterdir()), [path])


class AcceptanceTests(unittest.TestCase):
    def _collect(self, root, *, skip_api=False, api_status="passed"):
        imports = {name: {"status": "passed"} for name in ("numpy", "cv2", "PIL", "shapely")}
        torch = {"version": "cpu", "cuda_build": None, "cuda_available": False, "devices": []}
        with patch.object(env, "probe_python_code", side_effect=[{"status": "passed", "data": imports}, {"status": "passed", "data": torch}]), \
             patch.object(env, "probe_nvidia", return_value={"status": "passed"}), \
             patch.object(env, "probe_executable", return_value={"status": "warning", "installation_status": "unknown"}), \
             patch.object(env, "probe_comfyui", return_value={"status": api_status}) as api:
            report = env.collect_report(root, comfyui_url="http://localhost:8188", skip_api=skip_api)
        return report, api

    def test_skip_api_is_incomplete_and_makes_no_request(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            report, api = self._collect(Path(directory), skip_api=True)
        api.assert_not_called()
        self.assertFalse(report["acceptance"]["required_checks_passed"])
        self.assertEqual(report["acceptance"]["status"], "incomplete")

    def test_cpu_client_can_pass_api_checks_without_claiming_cuda_ready(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            report, _ = self._collect(Path(directory))
        self.assertTrue(report["acceptance"]["required_checks_passed"])
        check = next(check for check in report["checks"] if check["name"] == "local_torch_cuda")
        self.assertEqual(check["status"], "warning")
        self.assertEqual(report["acceptance"]["user_confirmation"], "pending")
        self.assertFalse(report["acceptance"]["next_stage_started"])

    def test_failed_api_fails_required_checks(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            report, _ = self._collect(Path(directory), api_status="failed")
        self.assertEqual(report["acceptance"]["status"], "failed")
        self.assertFalse(report["acceptance"]["required_checks_passed"])

    def test_missing_workspace_is_a_required_failure(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            report, _ = self._collect(Path(directory) / "missing")
        self.assertEqual(report["acceptance"]["status"], "failed")

    def test_cli_saves_failed_diagnostic_and_returns_nonzero(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            root = Path(directory)
            report, _ = self._collect(root, api_status="failed")
            with patch.object(env, "collect_report", return_value=report), redirect_stdout(io.StringIO()):
                code = env.main(["--project-root", str(root)])
            saved = json.loads((root / "reports" / "environment.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertEqual(saved["acceptance"]["status"], "failed")

    def test_cli_bad_timeout_has_no_side_effects(self):
        with patch.object(env, "collect_report") as collect, redirect_stderr(io.StringIO()):
            code = env.main(["--timeout", "nan"])
        self.assertEqual(code, 2)
        collect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
