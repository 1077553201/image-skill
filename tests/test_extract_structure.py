"""独立合成图几何真值测试；真实照片验收另行记录，不以这些测试代替。"""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from product_photo.extract_structure import (
    ExtractionConfig, StructureDetectionError, analyze_image, load_image, main, save_result,
)

BLUE = (180, 110, 15)


def synthetic_disc(count=3, *, center=(256, 270), radius=160, shape=(540, 540)):
    image = np.full((*shape, 3), 255, np.uint8)
    cv2.circle(image, center, radius, BLUE, -1)
    holes = []
    for index in range(count):
        angle = 2 * np.pi * index / max(count, 1)
        point = tuple(np.rint(np.asarray(center) + 90 * np.array([np.cos(angle), np.sin(angle)])).astype(int))
        cv2.circle(image, point, 29, (255, 255, 255), -1)
        holes.append(point)
    return image, holes


class SyntheticGeometryTests(unittest.TestCase):
    def test_circle_center_radius_against_known_geometry(self):
        image, _ = synthetic_disc()
        result = analyze_image(image)[0]
        np.testing.assert_allclose(result.spec["outer_circle"]["center_px"], [256, 270], atol=0.5)
        self.assertLess(abs(result.spec["outer_circle"]["radius_px"] - 160), 1)
        self.assertEqual(result.spec["outer_circle"]["angular_coverage"], 1)
        self.assertLess(result.spec["outer_circle"]["rmse_px"], 1)

    def test_cutout_count_is_detected_not_fixed_at_three(self):
        for count in (0, 1, 2, 3, 4, 6, 8):
            with self.subTest(count=count):
                image, centers = synthetic_disc(count)
                spec = analyze_image(image)[0].spec
                self.assertEqual(spec["cutout_count"], count)
                for expected in centers:
                    self.assertTrue(any(np.linalg.norm(np.asarray(hole["center_px"]) - expected) < 1 for hole in spec["cutouts"]))

    def test_irregular_hole_retains_concavity_and_full_boundary(self):
        image, _ = synthetic_disc(0)
        polygon = np.array([[190, 190], [280, 180], [300, 220], [250, 225], [235, 290], [185, 250]], np.int32)
        cv2.fillPoly(image, [polygon], (255, 255, 255))
        expected = np.zeros(image.shape[:2], np.uint8)
        cv2.fillPoly(expected, [polygon], 255)
        result = analyze_image(image)[0]
        self.assertEqual(result.spec["cutout_count"], 1)
        points = np.asarray(result.spec["cutouts"][0]["contour_px"], np.int32)
        self.assertGreater(len(points), 100)
        self.assertFalse(cv2.isContourConvex(points))
        detected = np.zeros_like(expected)
        cv2.fillPoly(detected, [points], 255)
        iou = np.count_nonzero(expected & detected) / np.count_nonzero(expected | detected)
        self.assertGreater(iou, 0.99)

    def test_metal_small_holes_and_outside_white_are_not_large_cutouts(self):
        image, holes = synthetic_disc(3)
        cv2.circle(image, (256, 270), 18, (210, 210, 210), -1)
        cv2.circle(image, (256, 315), 9, (255, 255, 255), -1)
        cv2.circle(image, (216, 300), 8, (50, 50, 50), -1)
        result = analyze_image(image)[0]
        self.assertEqual(result.spec["cutout_count"], 3)
        self.assertEqual(result.images["product_mask.png"][270, 256], 255)
        self.assertEqual(result.images["product_mask.png"][315, 256], 255)
        self.assertEqual(result.images["product_mask.png"][0, 0], 0)
        for x, y in holes:
            self.assertEqual(result.images["product_mask.png"][y, x], 0)

    def test_large_metal_region_is_not_silently_classified_as_hole(self):
        image, _ = synthetic_disc(0)
        cv2.rectangle(image, (220, 230), (280, 290), (90, 90, 90), -1)
        spec = analyze_image(image)[0].spec
        self.assertEqual(spec["cutout_count"], 0)
        self.assertEqual(spec["status"], "partial_failure")
        self.assertEqual(spec["cutout_detection_status"], "unresolved")
        self.assertTrue(any("insufficient_bright_neutral_background_evidence" in r["reasons"] for r in spec["unclassified_regions"]))

    def test_nearby_discs_auto_and_roi_do_not_mix(self):
        image = np.full((540, 800, 3), 255, np.uint8)
        for center in ((210, 260), (580, 260)):
            cv2.circle(image, center, 180, BLUE, -1)
            cv2.circle(image, (center[0], 340), 35, (255, 255, 255), -1)
        results = analyze_image(image, instance="all")
        self.assertEqual(len(results), 2)
        self.assertEqual([r.spec["cutout_count"] for r in results], [1, 1])
        left = analyze_image(image, roi=(10, 50, 385, 420))[0]
        np.testing.assert_allclose(left.spec["outer_circle"]["center_px"], [210, 260], atol=.5)
        self.assertEqual(left.spec["roi"], [10, 50, 385, 420])
        self.assertEqual(len(left.spec["instances_detected"]), 1)
        self.assertEqual(left.images["product_mask.png"][260, 580], 0)
        self.assertTrue(all(p[0] < 395 for p in left.spec["outer_contour"]))

    def test_joined_discs_request_roi_instead_of_fabricating_circle(self):
        image = np.full((540, 820, 3), 255, np.uint8)
        cv2.circle(image, (230, 260), 180, BLUE, -1)
        cv2.circle(image, (570, 260), 180, BLUE, -1)
        with self.assertRaisesRegex(StructureDetectionError, "roi"):
            analyze_image(image)

    def test_clipped_roi_is_rejected(self):
        image, _ = synthetic_disc()
        with self.assertRaises(StructureDetectionError):
            analyze_image(image, roi=(150, 100, 220, 300))

    def test_normalized_coordinates_reconstruct_original_points(self):
        image, _ = synthetic_disc()
        spec = analyze_image(image)[0].spec
        center = np.asarray(spec["outer_circle"]["center_px"])
        radius = spec["outer_circle"]["radius_px"]
        for hole in spec["cutouts"]:
            recovered = np.asarray(hole["contour_normalized"]) * radius + center
            np.testing.assert_allclose(recovered, hole["contour_px"], atol=1e-10)
        self.assertFalse(spec["geometry_verified"])
        self.assertIsNone(spec["thickness_mm"])
        self.assertEqual(spec["human_review"]["status"], "pending")


class InputAndExportTests(unittest.TestCase):
    def test_invalid_images_are_rejected(self):
        for image in (None, np.zeros((32, 32), np.uint8), np.zeros((32, 32, 3), np.float32), np.zeros((0, 0, 3), np.uint8)):
            with self.subTest(shape=getattr(image, "shape", None)), self.assertRaises(ValueError):
                analyze_image(image)

    def test_invalid_rois_are_not_silently_clamped(self):
        image, _ = synthetic_disc()
        for roi in ((-1, 0, 50, 50), (0, 0, 9999, 50), (1, 1, 0, 50), (0.5, 0, 50, 50), (1, 2, 3)):
            with self.subTest(roi=roi), self.assertRaises(ValueError):
                analyze_image(image, roi=roi)

    def test_empty_background_is_detection_failure(self):
        with self.assertRaises(StructureDetectionError):
            analyze_image(np.full((300, 300, 3), 255, np.uint8))

    def test_invalid_paths_and_corrupted_files(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            root = Path(directory)
            with self.assertRaises(FileNotFoundError):
                load_image(root / "absent.jpg")
            for content in (b"", b"not an image"):
                path = root / "bad.jpg"
                path.write_bytes(content)
                with self.assertRaises(ValueError):
                    load_image(path)

    def test_json_and_four_debug_images_export(self):
        image, _ = synthetic_disc(4)
        result = analyze_image(image)[0]
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            output = Path(directory)
            save_result(result, output)
            spec = json.loads((output / "product_spec.json").read_text(encoding="utf-8"))
            self.assertEqual(spec["cutout_count"], 4)
            self.assertEqual(len(list(output.glob("*.png"))), 4)
            self.assertTrue(all(np.isfinite(spec["outer_circle"][key]) for key in ("radius_px", "rmse_px")))
            mask = cv2.imdecode(np.fromfile(output / "product_mask.png", dtype=np.uint8), 0)
            self.assertEqual(mask.shape, image.shape[:2])
            self.assertEqual(set(np.unique(mask)), {0, 255})

    def test_cli_unicode_path_and_hash(self):
        image, _ = synthetic_disc(2)
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            root = Path(directory)
            source = root / "蓝色测试.png"
            cv2.imencode(".png", image)[1].tofile(source)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main([str(source), "--output-dir", "output"], project_root=root)
            spec = json.loads((root / "output/product_spec.json").read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertEqual(spec["cutout_count"], 2)
            self.assertEqual(len(spec["source_image"]["sha256"]), 64)
            np.testing.assert_array_equal(load_image(source), image)

    def test_failed_cli_saves_no_fake_geometry(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            root = Path(directory)
            source = root / "empty.png"
            cv2.imencode(".png", np.full((300, 300, 3), 255, np.uint8))[1].tofile(source)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main([str(source), "--output-dir", "failed"], project_root=root)
            spec = json.loads((root / "failed/product_spec.json").read_text(encoding="utf-8"))
            self.assertEqual(code, 1)
            self.assertEqual(spec["status"], "failed")
            self.assertIsNone(spec["outer_circle"])
            self.assertEqual(spec["cutouts"], [])
            self.assertFalse(list((root / "failed").glob("*.png")))

    def test_output_reuse_or_file_is_rejected_without_touching_old_data(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            root = Path(directory)
            old_file = root / "previous.json"
            old_file.write_text("preserve", encoding="utf-8")
            for output in (root, old_file):
                with redirect_stderr(io.StringIO()):
                    code = main(["missing.jpg", "--output-dir", str(output)], project_root=root)
                self.assertEqual(code, 2)
                self.assertEqual(old_file.read_text(encoding="utf-8"), "preserve")

    def test_partial_detection_cli_returns_failure_with_evidence(self):
        image, _ = synthetic_disc(0)
        cv2.rectangle(image, (220, 230), (280, 290), (90, 90, 90), -1)
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            root = Path(directory)
            source = root / "ambiguous.png"
            cv2.imencode(".png", image)[1].tofile(source)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main([str(source), "--output-dir", "partial"], project_root=root)
            spec = json.loads((root / "partial/product_spec.json").read_text(encoding="utf-8"))
            self.assertEqual(code, 1)
            self.assertEqual(spec["status"], "partial_failure")
            self.assertIsNotNone(spec["outer_circle"])
            self.assertEqual(spec["cutouts"], [])
            self.assertTrue((root / "partial/debug_overlay.png").is_file())

    def test_invalid_thresholds_are_rejected(self):
        for parameters in ({"min_cutout_area_ratio": 0}, {"min_cutout_area_ratio": float("nan")},
                           {"blue_hue_min": 150}, {"min_neutral_fraction": 2}):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                ExtractionConfig(**parameters)


if __name__ == "__main__":
    unittest.main()
