from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from product_studio.core.schemas import Evidence, EvidenceStatus as Status, ProductInstance, ProductSpec, SourceImage
from product_studio.analyzers.base import AnalysisRequest
from product_studio.analyzers.generic import GenericProductAnalyzer


def source():
    return SourceImage("source_1", "synthetic.png", "a" * 64, 800, 600)


class StudioSchemaTests(unittest.TestCase):
    def test_generic_schema_has_no_required_geometry(self):
        spec = ProductSpec("product_a", [source()])
        data = spec.to_dict()
        self.assertEqual(data["geometry_features"], {})
        self.assertNotIn("outer_circle", data)
        self.assertNotIn("cutouts", data)
        self.assertIsNone(data["product_category"]["value"])
        self.assertEqual(ProductSpec.from_dict(data).to_dict(), data)

    def test_five_evidence_states_remain_distinct(self):
        for status in Status:
            fact = Evidence() if status == Status.UNKNOWN else Evidence("test", status, ("source_1",), "test_method", reviewer="user" if status == Status.HUMAN_VERIFIED else None)
            spec = ProductSpec("p", [source()], appearance_features={"test": fact})
            self.assertEqual(ProductSpec.from_dict(spec.to_dict()).appearance_features["test"].status, status)

    def test_unknown_cannot_contain_default_value_or_score(self):
        for arguments in ({"value": 3}, {"confidence": .9}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                Evidence(**arguments)

    def test_verification_needs_named_reviewer(self):
        with self.assertRaises(ValueError):
            Evidence(True, Status.HUMAN_VERIFIED, ("source_1",), "review")
        estimated = Evidence(True, Status.ESTIMATED, ("source_1",), "algorithm")
        with self.assertRaises(ValueError):
            ProductSpec("p", [source()], verified_facts={"guess": estimated}).validate()

    def test_bad_reference_and_selection_fail(self):
        with self.assertRaises(ValueError):
            ProductSpec("p", [source()], selected_instance="absent").validate()
        with self.assertRaises(ValueError):
            ProductSpec("p", [source()], visible_view=Evidence("front", Status.OBSERVED, ("wrong",), "annotated")).validate()

    def test_nonfinite_values_and_wrong_schema_fail(self):
        with self.assertRaises(ValueError):
            Evidence(float("nan"), Status.ESTIMATED, ("source_1",), "test")
        with self.assertRaises(ValueError):
            ProductSpec.from_dict({"schema_version": "1a.1"})

    def test_generic_does_not_invent_one_instance(self):
        outcome = GenericProductAnalyzer().analyze(AnalysisRequest([source()]))
        self.assertEqual(outcome.status, "processed")
        self.assertEqual(outcome.specs[0].detected_instances, [])
        self.assertIsNone(outcome.specs[0].selected_instance)
        self.assertEqual(outcome.specs[0].analysis_records[0]["status"], "metadata_only")

    def test_two_supplied_instances_keep_distinct_skus(self):
        evidence = Evidence(True, Status.ESTIMATED, ("source_1",), "supplied_roi")
        instances = [ProductInstance("a", "source_1", (0, 0, 200, 200), evidence, "SKU-A"),
                     ProductInstance("b", "source_1", (300, 0, 200, 200), evidence, "SKU-B")]
        outcome = GenericProductAnalyzer().analyze(AnalysisRequest([source()], instances=instances, product_id="task"))
        self.assertEqual([spec.product_id for spec in outcome.specs], ["task/a", "task/b"])
        self.assertEqual([spec.selected_instance for spec in outcome.specs], ["a", "b"])
        for spec in outcome.specs:
            self.assertEqual([i.sku for i in spec.detected_instances], ["SKU-A", "SKU-B"])
            self.assertFalse(spec.geometry_features)
        outcome.specs[0].detected_instances.pop()
        self.assertEqual(len(outcome.specs[1].detected_instances), 2)


if __name__ == "__main__":
    unittest.main()
