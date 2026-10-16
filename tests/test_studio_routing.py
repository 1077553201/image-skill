import ast
from pathlib import Path
import subprocess
import sys
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from product_studio.analyzers.base import AnalysisOutcome, AnalysisRequest, Analyzer
from product_studio.core.schemas import Evidence, EvidenceStatus as Status, ProductInstance, ProductSpec, SourceImage
from product_studio.core.task_planner import OutputRequest, Strategy, plan_task
from product_studio.plugins import default_registry
from product_studio.plugins.planar_geometry import legacy
from product_studio.plugins.planar_geometry.analyzer import adapt_legacy_spec, to_legacy_spec


def source():
    return SourceImage("s1", "synthetic.png", "a"*64, 500, 500)


def selected_spec():
    instance = ProductInstance("instance_a", "s1", (50, 50, 400, 400), Evidence(True, Status.ESTIMATED, ("s1",), "fixture_roi"), "SKU-A")
    return ProductSpec("product_a", [source()], detected_instances=[instance], selected_instance=instance.instance_id)


class StudioRoutingTests(unittest.TestCase):
    def test_three_non_disc_geometries_skip_specialized_analysis(self):
        for kind in ("rectangular_electronics", "elongated_bottle", "irregular_soft_bag"):
            with self.subTest(kind=kind):
                image = np.full((500, 500, 3), 255, np.uint8)
                if kind == "rectangular_electronics":
                    cv2.rectangle(image, (90, 140), (400, 330), (180, 110, 15), -1)
                elif kind == "elongated_bottle":
                    cv2.ellipse(image, (250, 250), (65, 175), 0, 0, 360, (80, 180, 50), -1)
                else:
                    cv2.fillPoly(image, [np.array([[80, 180], [180, 70], [240, 150], [400, 120], [430, 370], [200, 420], [110, 320]], np.int32)], (40, 130, 230))
                supplied = ProductInstance("item_a", "s1", (50, 30, 420, 430), Evidence(True, Status.ESTIMATED, ("s1",), "synthetic_fixture_roi"), kind)
                routed = default_registry().route(AnalysisRequest([source()], [supplied], "fixture", image=image), "planar_geometry")
                self.assertEqual(routed.records[-1]["status"], "skipped")
                self.assertEqual(len(routed.specs), 1)
                data = routed.specs[0].to_dict()
                self.assertEqual(data["geometry_features"], {})
                self.assertEqual(data["selected_instance"], "item_a")
                self.assertIsNone(data["product_category"]["value"])
                self.assertNotIn("outer_circle", data)
                self.assertNotIn("cutouts", data)

    def test_missing_plugin_does_not_abort_generic_processing(self):
        for name in ("rigid_object", "soft_goods", "transparent_object"):
            result = default_registry().route(AnalysisRequest([source()]), name)
            self.assertEqual(result.records[-1]["status"], "skipped")
            self.assertEqual(result.specs[0].analysis_records[0]["status"], "metadata_only")

    def test_planar_adapter_lossless_and_no_validation_upgrade(self):
        image = np.full((500, 500, 3), 255, np.uint8)
        cv2.circle(image, (250, 250), 180, (180, 110, 15), -1)
        cv2.circle(image, (250, 340), 35, (255, 255, 255), -1)
        old = legacy.analyze_image(image)[0].spec
        new = adapt_legacy_spec(old, source(), product_id="disc")
        self.assertEqual(to_legacy_spec(new), old)
        self.assertEqual(to_legacy_spec(ProductSpec.from_dict(new.to_dict())), old)
        self.assertNotIn("outer_circle", new.to_dict())
        features = new.geometry_features["planar_geometry"].value
        self.assertEqual(features["outer_circle"]["status"], Status.ESTIMATED)
        self.assertEqual(features["outer_contour"]["status"], Status.OBSERVED)
        self.assertEqual(new.unknown_properties["planar_geometry.thickness_mm"].status, Status.UNKNOWN)
        self.assertEqual(new.human_review_status, "pending")
        self.assertFalse(new.verified_facts)

    def test_registry_duplicate_and_plugin_failure_reported(self):
        registry = default_registry()
        with self.assertRaises(ValueError):
            registry.register("generic_product", lambda: None)
        class Broken(Analyzer):
            name = "broken"
            def analyze(self, request):
                raise RuntimeError("fixture failure")
        registry.register("broken", Broken)
        result = registry.route(AnalysisRequest([source()]), "broken")
        self.assertEqual(result.records[-1]["status"], "failed")
        self.assertIn("fixture failure", result.records[-1]["warnings"][0])
        self.assertFalse(result.specs[0].geometry_features)

    def test_generic_and_registry_import_without_cv_libraries(self):
        code = "import sys;sys.path.insert(0,sys.argv[1]);from product_studio.plugins import default_registry;from product_studio.analyzers.base import AnalysisRequest;from product_studio.core.schemas import SourceImage;r=default_registry().route(AnalysisRequest([SourceImage('s','x.png','a'*64,100,100)]));assert r.specs;assert not any(n in sys.modules for n in ('cv2','numpy','PIL'))"
        completed = subprocess.run([sys.executable, "-S", "-c", code, str(ROOT/"src")], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_import_graph_has_no_cycles_or_core_plugin_import(self):
        files = list((ROOT/"src/product_studio").rglob("*.py")) + list((ROOT/"src/product_photo").glob("*.py"))
        graph = {}
        for path in files:
            module = ".".join(path.relative_to(ROOT/"src").with_suffix("").parts)
            if module.endswith(".__init__"):
                module = module[:-9]
            edges = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module:
                    edges.add(node.module)
                    edges.update(node.module + "." + name.name for name in node.names)
                elif isinstance(node, ast.Import):
                    edges.update(alias.name for alias in node.names)
            graph[module] = edges
            if module.startswith(("product_studio.core", "product_studio.analyzers")):
                self.assertFalse(any(edge.startswith(("product_studio.plugins", "product_photo")) for edge in edges), module)
        active, complete = set(), set()
        def visit(module):
            self.assertNotIn(module, active, f"cyclic import: {module}")
            if module in complete:
                return
            active.add(module)
            for dependency in graph[module] & graph.keys():
                visit(dependency)
            active.remove(module)
            complete.add(module)
        for module in graph:
            visit(module)


class TaskPlannerTests(unittest.TestCase):
    def test_source_crop_plan_is_not_execution_or_verified_output(self):
        plan = plan_task(selected_spec(), OutputRequest(Strategy.VISIBLE_CROP))
        self.assertEqual(plan.status, "planned")
        self.assertEqual(plan.authenticity_level, "source_preserving_intent")
        self.assertFalse(plan.output_verified)
        self.assertEqual(plan.execution_status, "not_implemented_in_phase1g")
        self.assertEqual(plan.provenance["source_images"][0]["sha256"], "a"*64)

    def test_no_selected_instance_blocks_all_strategies(self):
        spec = ProductSpec("unselected", [source()])
        for strategy in Strategy:
            with self.subTest(strategy=strategy):
                self.assertEqual(plan_task(spec, OutputRequest(strategy, "back", True)).status, "blocked")

    def test_unseen_view_not_presented_as_real_crop_or_composite(self):
        spec = selected_spec()
        spec.visible_view = Evidence("front", Status.OBSERVED, ("s1",), "provided_view_annotation")
        for strategy in (Strategy.VISIBLE_CROP, Strategy.ORIGINAL_COMPOSITE, Strategy.AI_BACKGROUND):
            self.assertEqual(plan_task(spec, OutputRequest(strategy, "back")).status, "blocked")

    def test_guessed_geometry_and_mask_do_not_pass_formal_route(self):
        spec = selected_spec()
        spec.geometry_features["fictional"] = Evidence({"shape": "guess"}, Status.CONCEPTUAL, ("s1",), "concept")
        spec.product_mask = Evidence({"artifact": "partial.png", "quality": "partial"}, Status.ESTIMATED, ("s1",), "algorithm")
        self.assertEqual(plan_task(spec, OutputRequest(Strategy.ORIGINAL_COMPOSITE)).status, "blocked")
        plan = plan_task(spec, OutputRequest(Strategy.VERIFIED_GEOMETRY_RENDER, "back"))
        self.assertEqual(plan.status, "blocked")
        self.assertEqual(plan.authenticity_level, "requires_verification")

    def test_concept_always_labeled_even_when_explicitly_allowed(self):
        for allow in (False, True):
            plan = plan_task(selected_spec(), OutputRequest(Strategy.SINGLE_IMAGE_CONCEPT, "back", allow))
            self.assertEqual(plan.authenticity_level, "concept_only")
            self.assertEqual(plan.status, "blocked")  # 未接入 Provider。

    def test_multiple_images_do_not_automatically_merge_skus(self):
        spec = selected_spec()
        spec.source_images.append(SourceImage("s2", "other-sku.png", "b"*64, 500, 500))
        plan = plan_task(spec, OutputRequest(Strategy.MULTI_REFERENCE_EDIT))
        self.assertEqual(plan.status, "blocked")
        self.assertEqual(len(plan.provenance["source_images"]), 1)
        self.assertTrue(any("同一商品" in item for item in plan.prerequisites))

    def test_reviewed_model_does_not_mean_renderer_exists(self):
        spec = selected_spec()
        spec.verified_facts = {"geometry_model": Evidence({"asset": "provided.glb", "instance_id": "instance_a"}, Status.HUMAN_VERIFIED, ("s1",), "manual_review", reviewer="user"),
                               "verified_views": Evidence(["front"], Status.HUMAN_VERIFIED, ("s1",), "manual_review", reviewer="user")}
        front = plan_task(spec, OutputRequest(Strategy.VERIFIED_GEOMETRY_RENDER, "front"))
        back = plan_task(spec, OutputRequest(Strategy.VERIFIED_GEOMETRY_RENDER, "back"))
        self.assertEqual(front.authenticity_level, "verified_geometry_basis")
        self.assertEqual(front.status, "blocked")
        self.assertEqual(back.authenticity_level, "requires_verification")
        self.assertFalse(front.output_verified)

    def test_reviewed_assets_cannot_cross_instances_in_same_source(self):
        spec = selected_spec()
        spec.product_mask = Evidence({"artifact": "other-sku.png", "quality": "reviewed_complete", "instance_id": "instance_b"},
                                     Status.HUMAN_VERIFIED, ("s1",), "manual_review", reviewer="user")
        self.assertEqual(plan_task(spec, OutputRequest(Strategy.ORIGINAL_COMPOSITE)).status, "blocked")
        spec.verified_facts = {"geometry_model": Evidence({"asset": "other-sku.glb", "instance_id": "instance_b"},
                                                          Status.HUMAN_VERIFIED, ("s1",), "manual_review", reviewer="user"),
                               "verified_views": Evidence(["front"], Status.HUMAN_VERIFIED, ("s1",), "manual_review", reviewer="user")}
        self.assertEqual(plan_task(spec, OutputRequest(Strategy.VERIFIED_GEOMETRY_RENDER, "front")).authenticity_level, "requires_verification")


if __name__ == "__main__":
    unittest.main()
