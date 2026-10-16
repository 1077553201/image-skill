"""Mock transport tests; real image-edit evidence lives in phase4c reports."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from product_studio.providers.image_guided import ImageGuidedCreativeEditProvider, _previews


def png(color="brown"):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()


class Transport:
    def __init__(self, source, info):
        self.source = source
        self.info = info
        self.calls = []
        self.uploads = []
        self.upload_response = {"name": "real.png", "subfolder": "concept", "type": "input"}
        self.submission = {"prompt_id": "actual-test-id", "node_errors": {}}
        self.history_error = False
        self.wrong_output_type = False
        self.wrong_reference = False
        self.submission_exception = False
        self.submitted_graph = None
        self.wrong_history_graph = False

    def upload(self, raw, filename, mime):
        self.uploads.append((raw, filename, mime))
        return json.dumps(self.upload_response).encode()

    def __call__(self, route, payload=None):
        self.calls.append((route, payload))
        if route == "/queue":
            result = {"queue_running": [[1, "other-user-job"]], "queue_pending": []}
        elif route == "/object_info":
            result = self.info
        elif route == "/prompt":
            if self.submission_exception:
                raise TimeoutError("submission transport closed before a response")
            self.submitted_graph = payload["prompt"]
            result = self.submission
        elif route.startswith("/history/"):
            status = {"completed": True, "status_str": "error" if self.history_error else "success", "messages": [["execution_error", {"exception_message": "simulated model error"}]] if self.history_error else []}
            result = {"actual-test-id": {"prompt": [0, "actual-test-id", {} if self.wrong_history_graph else self.submitted_graph], "status": status, "outputs": {"save": {"images": [{"filename": "out.png", "subfolder": "", "type": "input" if self.wrong_output_type else "output"}]}}}}
        elif route.startswith("/view?"):
            kind = parse_qs(urlsplit(route).query)["type"][0]
            return (png("white") if self.wrong_reference else self.source) if kind == "input" else png("tan")
        else:
            raise AssertionError("Unexpected request " + route)
        return json.dumps(result).encode()


class ImageGuidedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.png"
        self.source.write_bytes(png())
        self.graph = {
            "load": {"class_type": "LoadImage", "inputs": {"image": "placeholder"}},
            "cond": {"class_type": "TextEncodeQwenImage21", "inputs": {"prompt": "x", "negative_prompt": "", "images.image_1": ["load", 0]}},
            "sampler": {"class_type": "KSampler", "inputs": {"seed": 1, "latent_image": ["cond", 2]}},
            "save": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x", "images": ["sampler", 0]}},
        }
        self.workflow = self.root / "graph.json"
        self.workflow.write_text(json.dumps(self.graph), encoding="utf-8")
        self.config = {
            "capability": "image_guided_creative_edit", "base_url": "http://test.invalid:8188",
            "workflow_path": "graph.json", "workflow_sha256": hashlib.sha256(self.workflow.read_bytes()).hexdigest(),
            "mapping": {key: {"node": node, "class_type": self.graph[node]["class_type"], "input": field} for key, node, field in [("prompt", "cond", "prompt"), ("negative_prompt", "cond", "negative_prompt"), ("seed", "sampler", "seed"), ("prefix", "save", "filename_prefix"), ("reference_image", "load", "image")]},
            "output_node": "save", "timeout_seconds": 3, "poll_seconds": 0,
        }
        self.info = {node["class_type"]: {"input": {"required": {key: ["STRING", {}] for key in node["inputs"]}}} for node in self.graph.values()}
        self.config_path = self.root / "config.json"
        self.transport = Transport(self.source.read_bytes(), self.info)

    def provider(self):
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        return ImageGuidedCreativeEditProvider(self.config_path, transport=self.transport, upload_transport=self.transport.upload)

    def generate(self, **kwargs):
        return self.provider().generate(self.source, "A fashion concept", seed=10, output_dir=self.root / "out", instance_id="bag", **kwargs)

    def test_success_records_reference_and_workflow_and_pending_concept(self):
        original = self.workflow.read_bytes()
        output, record = self.generate(expected_size_px=[64, 64])
        self.assertTrue(output.is_file())
        self.assertEqual(record["truth_mode"], "concept_creative")
        self.assertEqual(record["human_review_status"], "pending")
        self.assertFalse(record["identity_verified"])
        self.assertEqual(record["source_sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertTrue(record["upload"]["reference_bytes_verified"])
        self.assertEqual(record["prompt_id"], "actual-test-id")
        self.assertEqual(record["instance_id"], "bag")
        self.assertTrue(record["history_workflow_matches_submission"])
        self.assertEqual(self.workflow.read_bytes(), original)
        self.assertEqual((output.parent / "input_original.png").read_bytes(), self.source.read_bytes())
        graph = json.loads((output.parent / "submitted_workflow.json").read_text())
        self.assertEqual(graph["load"]["inputs"]["image"], "concept/real.png")
        self.assertEqual(graph["sampler"]["inputs"]["latent_image"], ["cond", 2])
        self.assertEqual(graph["cond"]["inputs"]["images.image_1"], ["load", 0])
        self.assertTrue((output.parent / "queue_before.json").is_file())
        self.assertFalse(any(route in {"/interrupt", "/queue/delete"} for route, _ in self.transport.calls))

    def test_strict_mode_is_rejected_without_upload_or_output(self):
        with self.assertRaisesRegex(ValueError, "strict_product"):
            self.generate(truth_mode="strict_product")
        self.assertFalse(self.transport.calls)
        self.assertFalse((self.root / "out").exists())

    def test_bad_seed_is_rejected_before_upload(self):
        with self.assertRaisesRegex(ValueError, "uint64"):
            self.provider().generate(self.source, "concept", seed=-1, output_dir=self.root / "out")
        self.assertFalse(self.transport.calls)
        self.assertFalse(self.transport.uploads)

    def test_history_must_match_the_actual_submitted_workflow(self):
        self.transport.wrong_history_graph = True
        with self.assertRaisesRegex(RuntimeError, "history does not match"):
            self.generate()
        self.assertFalse((self.root / "out/generated.png").exists())

    def test_timeout_retains_prompt_id_and_does_not_resubmit(self):
        self.config["timeout_seconds"] = 0
        with self.assertRaises(TimeoutError):
            self.generate()
        record = json.loads((self.root / "out/execution.json").read_text())
        self.assertEqual(record["status"], "timed_out_pending_remote")
        self.assertEqual(record["prompt_id"], "actual-test-id")
        self.assertEqual(sum(route == "/prompt" for route, _ in self.transport.calls), 1)

    def test_server_error_saves_history_without_a_success_image(self):
        self.transport.history_error = True
        with self.assertRaisesRegex(RuntimeError, "Remote concept edit failed"):
            self.generate()
        self.assertTrue((self.root / "out/history.json").is_file())
        self.assertFalse((self.root / "out/generated.png").exists())

    def test_upload_reference_hash_must_match(self):
        self.transport.wrong_reference = True
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            self.generate()
        self.assertFalse(any(route == "/prompt" for route, _ in self.transport.calls))

    def test_upload_path_cannot_traverse(self):
        self.transport.upload_response["subfolder"] = "../outside"
        with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
            self.generate()

    def test_actual_output_cannot_be_input_asset(self):
        self.transport.wrong_output_type = True
        with self.assertRaisesRegex(RuntimeError, "actual output"):
            self.generate()

    def test_submission_rejection_is_saved_and_not_successful(self):
        self.transport.submission = {"node_errors": {"cond": "invalid"}}
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            self.generate()
        record = json.loads((self.root / "out/execution.json").read_text())
        self.assertEqual(record["status"], "submission_rejected")

    def test_uncertain_submission_does_not_auto_retry(self):
        self.transport.submission_exception = True
        with self.assertRaises(TimeoutError):
            self.generate()
        record = json.loads((self.root / "out/execution.json").read_text())
        self.assertEqual(record["status"], "submission_uncertain_no_retry")
        self.assertEqual(sum(route == "/prompt" for route, _ in self.transport.calls), 1)

    def test_expected_size_is_checked(self):
        with self.assertRaisesRegex(RuntimeError, "size"):
            self.generate(expected_size_px=[1024, 1024])

    def test_nonempty_output_does_not_overwrite(self):
        output, _ = self.generate()
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "nonempty"):
            self.generate()
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), digest)

    def test_configuration_needs_explicit_capability_and_hash(self):
        self.config["capability"] = "background_only"
        with self.assertRaisesRegex(ValueError, "explicitly declare"):
            self.provider()
        self.config["capability"] = "image_guided_creative_edit"
        self.config["workflow_sha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.provider()

    def test_bad_mapping_is_rejected(self):
        self.config["mapping"]["prompt"]["input"] = "invented_parameter"
        with self.assertRaisesRegex(ValueError, "mapping"):
            self.provider()

    def test_missing_input_and_bad_image(self):
        self.source.unlink()
        with self.assertRaises(FileNotFoundError):
            self.generate()
        self.source.write_bytes(b"not a picture")
        with self.assertRaises(OSError):
            self.generate()

    def test_reference_is_exactly_one_configured_loader(self):
        graph = deepcopy(self.graph)
        graph["second"] = graph["load"]
        self.workflow.write_text(json.dumps(graph), encoding="utf-8")
        self.config.pop("workflow_sha256")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.provider()

    def test_remote_schema_mismatch_is_a_recorded_failure(self):
        del self.transport.info["TextEncodeQwenImage21"]
        with self.assertRaisesRegex(ValueError, "Remote node"):
            self.generate()
        self.assertFalse(any(route == "/prompt" for route, _ in self.transport.calls))

    def test_concept_preview_is_separate_from_untouched_generated_image(self):
        output, _ = self.generate()
        original = output.read_bytes()
        _previews(self.source, output, output.parent)
        self.assertEqual(output.read_bytes(), original)
        self.assertTrue((output.parent / "concept_preview.png").is_file())
        self.assertTrue((output.parent / "comparison.png").is_file())


if __name__ == "__main__":
    unittest.main()
