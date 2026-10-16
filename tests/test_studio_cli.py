from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from product_studio.cli import main
from product_studio.core.schemas import ProductSpec
from product_studio.plugins.planar_geometry.analyzer import to_legacy_spec


class StudioCLITests(unittest.TestCase):
    def execute(self, root, arguments):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(arguments, project_root=root)

    def test_generic_input_metadata_does_not_claim_understanding(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            image = np.full((300, 400, 3), 255, np.uint8)
            cv2.rectangle(image, (60, 80), (330, 240), (0, 0, 210), -1)
            cv2.imencode(".png", image)[1].tofile(root/"ordinary.png")
            code = self.execute(root, ["ordinary.png", "--output-dir", "out", "--strategy", "single_image_concept", "--target-view", "back"])
            self.assertEqual(code, 0)
            spec = json.loads((root/"out/unassigned_001/product_spec.json").read_text(encoding="utf-8"))
            self.assertEqual(spec["geometry_features"], {})
            self.assertEqual(spec["detected_instances"], [])
            self.assertIsNone(spec["product_category"]["value"])
            self.assertIsNone(spec["product_mask"]["value"])
            plan = json.loads((root/"out/unassigned_001/task_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["authenticity_level"], "concept_only")
            self.assertEqual(plan["status"], "blocked")
            manifest = json.loads((root/"out/run_manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["generation_executed"])

    def test_multiple_supplied_instances_export_distinct_skus(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            cv2.imencode(".png", np.full((300, 600, 3), 255, np.uint8))[1].tofile(root/"multi.png")
            code = self.execute(root, ["multi.png", "--roi", "10", "10", "200", "200", "--roi", "300", "10", "200", "200",
                                      "--sku", "SKU-DEVICE", "--sku", "SKU-BAG", "--product-id", "case", "--output-dir", "out"])
            self.assertEqual(code, 0)
            specs = [ProductSpec.from_dict(json.loads((root/f"out/instance_{index:03d}/product_spec.json").read_text(encoding="utf-8"))) for index in (1, 2)]
            self.assertNotEqual(specs[0].product_id, specs[1].product_id)
            for spec, sku in zip(specs, ("SKU-DEVICE", "SKU-BAG")):
                selected = next(instance for instance in spec.detected_instances if instance.instance_id == spec.selected_instance)
                self.assertEqual(selected.sku, sku)
                self.assertFalse(spec.geometry_features)

    def test_planar_cli_preserves_old_files_and_roundtrip_payload(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            image = np.full((500, 500, 3), 255, np.uint8)
            cv2.circle(image, (250, 250), 180, (180, 110, 15), -1)
            cv2.circle(image, (250, 340), 35, (255, 255, 255), -1)
            cv2.imencode(".png", image)[1].tofile(root/"disc.png")
            code = self.execute(root, ["disc.png", "--analyzer", "planar_geometry", "--output-dir", "out"])
            self.assertEqual(code, 0)
            directory = root/"out/instance_001"
            spec = ProductSpec.from_dict(json.loads((directory/"product_spec.json").read_text(encoding="utf-8")))
            old = json.loads((directory/"planar_geometry/product_spec.json").read_text(encoding="utf-8"))
            self.assertEqual(to_legacy_spec(spec), old)
            self.assertEqual(old["cutout_count"], 1)
            self.assertEqual(len(list((directory/"planar_geometry").glob("*.png"))), 4)
            self.assertEqual(spec.product_mask.value["quality"], "partial")
            self.assertEqual(spec.human_review_status, "pending")
            self.assertFalse(spec.verified_facts)

    def test_invalid_roi_and_sku_count_do_not_succeed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            cv2.imencode(".png", np.full((300, 300, 3), 255, np.uint8))[1].tofile(root/"test.png")
            for arguments in (["--roi", "0", "0", "999", "999"], ["--sku", "unbound-sku"]):
                self.assertEqual(self.execute(root, ["test.png", "--output-dir", "out", *arguments]), 2)
                self.assertFalse((root/"out").exists())


if __name__ == "__main__":
    unittest.main()
