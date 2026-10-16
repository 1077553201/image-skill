"""将阶段 1A 的完整旧格式适配为命名空间特征；不改变测量算法。"""

from copy import deepcopy

from product_studio.analyzers.base import AnalysisOutcome, AnalysisRequest, Analyzer
from product_studio.analyzers.generic import GenericProductAnalyzer
from product_studio.core.schemas import Evidence, EvidenceStatus as Status, ProductInstance, SourceImage


def adapt_legacy_spec(raw: dict, source: SourceImage, *, product_id: str,
                      instances: list[ProductInstance] | None = None,
                      selected_instance: str | None = None):
    if raw.get("schema_version") != "1a.1" or raw.get("status") == "failed" or not raw.get("outer_circle"):
        raise ValueError("只适配有效的阶段 1A 几何结果；失败结果不能升级为成功。")
    if instances is None:
        instances = [ProductInstance(item["instance_id"], source.source_id, tuple(item["bbox_px"]),
                                    Evidence(True, Status.ESTIMATED, (source.source_id,), "blue_disc_detection",
                                             raw["confidence"]["instance_separation"]))
                     for item in raw["instances_detected"]]
    selected = selected_instance or raw["instance_id"]
    spec = GenericProductAnalyzer().analyze(AnalysisRequest([source], instances, product_id, selected)).specs[0]
    evidence_sources = (source.source_id,)
    features = {
        "outer_contour": Evidence(deepcopy(raw["outer_contour"]), Status.OBSERVED, evidence_sources,
                                  "observed_blue_pixel_boundary").__dict__,
        "outer_circle": Evidence(deepcopy(raw["outer_circle"]), Status.ESTIMATED, evidence_sources,
                                 "least_squares_circle", raw["confidence"]["outer_circle"]).__dict__,
        "visible_apertures": Evidence(deepcopy(raw["cutouts"]), Status.ESTIMATED, evidence_sources,
                                      "enclosed_bright_region_candidates").__dict__,
        "legacy_payload": deepcopy(raw),
    }
    spec.geometry_features["planar_geometry"] = Evidence(features, Status.ESTIMATED, evidence_sources,
                                                          "phase1a_blue_disc_adapter",
                                                          note="仅蓝色近正视圆盘；物理孔口、背面、厚度未验证。")
    spec.unknown_properties["planar_geometry.thickness_mm"] = Evidence()
    spec.unknown_properties["planar_geometry.back_structure"] = Evidence()
    # 旧格式 confidence 包含嵌套说明，与通用标量分数不同，完整保留在命名空间。
    spec.confidence = {"planar_geometry.outer_circle": raw["confidence"]["outer_circle"],
                       "planar_geometry.instance_separation": raw["confidence"]["instance_separation"]}
    spec.warnings.extend(raw["warnings"])
    spec.warnings.append("转换不提升旧几何验证等级；当前 mask 为阶段 1A 部分遮罩。")
    spec.analysis_records.append({"analyzer": "planar_geometry", "variant": "blue_disc_phase1a",
                                  "status": raw["status"], "legacy_schema": "1a.1"})
    spec.validate()
    return spec


def to_legacy_spec(spec) -> dict:
    spec.validate()
    if "planar_geometry" not in spec.geometry_features:
        raise ValueError("普通商品没有旧圆盘格式，不能虚构外圆。")
    return deepcopy(spec.geometry_features["planar_geometry"].value["legacy_payload"])


class PlanarGeometryAnalyzer(Analyzer):
    name = "planar_geometry"

    def analyze(self, request: AnalysisRequest) -> AnalysisOutcome:
        if request.image is None or len(request.source_images) != 1:
            return AnalysisOutcome(self.name, "skipped", warnings=["当前蓝色圆盘变体需要单一来源及其像素图。"])
        from product_studio.plugins.planar_geometry import legacy
        source = request.source_images[0]
        specs, artifacts, warnings = [], [], []
        selected = [item for item in request.instances if not request.selected_instance or item.instance_id == request.selected_instance]
        groups = selected or [None]
        for supplied_instance in groups:
            if supplied_instance and supplied_instance.source_id != source.source_id:
                return AnalysisOutcome(self.name, "skipped", warnings=["实例未关联当前像素来源。"])
            try:
                results = legacy.analyze_image(request.image, source_image=source.path,
                                               roi=supplied_instance.roi if supplied_instance else None,
                                               instance="all")
            except legacy.StructureDetectionError as exc:
                return AnalysisOutcome(self.name, "skipped", warnings=[f"不支持此图的专用几何，保留通用处理：{exc}"])
            if supplied_instance and len(results) != 1:
                return AnalysisOutcome(self.name, "skipped", warnings=["人工实例 ROI 内存在多个圆盘候选，未合并或擅自选择 SKU。"])
            for result in results:
                spec = adapt_legacy_spec(result.spec, source, product_id=request.product_id or "planar_analysis",
                                         instances=request.instances if supplied_instance else None,
                                         selected_instance=supplied_instance.instance_id if supplied_instance else None)
                specs.append(spec)
                artifacts.append(result)
        partial = any(spec.geometry_features[self.name].value["legacy_payload"]["status"] == "partial_failure" for spec in specs)
        return AnalysisOutcome(self.name, "failed" if partial else "processed", specs, artifacts, warnings)

