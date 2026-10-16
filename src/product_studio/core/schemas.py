"""通用规格与证据状态。这里没有商品形状、颜色或尺寸默认值。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import math
from typing import Any


class EvidenceStatus(str, Enum):
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    HUMAN_VERIFIED = "human_verified"
    UNKNOWN = "unknown"
    CONCEPTUAL = "conceptual"


@dataclass(frozen=True)
class Evidence:
    value: Any = None
    status: EvidenceStatus = EvidenceStatus.UNKNOWN
    sources: tuple[str, ...] = ()
    method: str | None = None
    confidence: float | None = None
    reviewer: str | None = None
    note: str | None = None

    def __post_init__(self):
        if not isinstance(self.status, EvidenceStatus):
            raise ValueError("证据状态必须使用 EvidenceStatus。")
        if self.confidence is not None and (isinstance(self.confidence, bool) or not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1):
            raise ValueError("confidence 必须为 null 或 [0,1] 内的有限数值。")
        if self.status == EvidenceStatus.UNKNOWN:
            if self.value is not None or self.confidence is not None:
                raise ValueError("unknown 的值与置信度必须是 null。")
        elif self.value is None or not self.sources or not self.method:
            raise ValueError("非未知证据必须有值、来源和方法。")
        if self.status == EvidenceStatus.HUMAN_VERIFIED and not self.reviewer:
            raise ValueError("人工确认需要具名 reviewer，不能自动提升验证状态。")
        json.dumps(self.value, allow_nan=False)


@dataclass(frozen=True)
class SourceImage:
    source_id: str
    path: str
    sha256: str
    width_px: int
    height_px: int

    def __post_init__(self):
        if not self.source_id or not self.path or len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("图片必须有标识、路径和有效 SHA-256。")
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("图片宽高必须为正。")


@dataclass(frozen=True)
class ProductInstance:
    instance_id: str
    source_id: str
    roi: tuple[int, int, int, int]
    evidence: Evidence
    sku: str | None = None


@dataclass
class ProductSpec:
    product_id: str
    source_images: list[SourceImage]
    product_category: Evidence = field(default_factory=Evidence)
    detected_instances: list[ProductInstance] = field(default_factory=list)
    selected_instance: str | None = None
    visible_view: Evidence = field(default_factory=Evidence)
    product_mask: Evidence = field(default_factory=Evidence)
    geometry_features: dict[str, Evidence] = field(default_factory=dict)
    appearance_features: dict[str, Evidence] = field(default_factory=dict)
    protected_regions: list[Evidence] = field(default_factory=list)
    verified_facts: dict[str, Evidence] = field(default_factory=dict)
    unknown_properties: dict[str, Evidence] = field(default_factory=dict)
    confidence: dict[str, float | None] = field(default_factory=dict)
    human_review_status: str = "pending"
    analysis_records: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema_version: str = "studio.1g.1"

    def validate(self) -> None:
        if not self.product_id or not self.source_images:
            raise ValueError("规格必须有 product_id 和至少一张来源图。")
        if self.human_review_status not in {"pending", "partially_reviewed", "reviewed", "rejected"}:
            raise ValueError("无效 human_review_status。")
        sources = {source.source_id: source for source in self.source_images}
        if len(sources) != len(self.source_images):
            raise ValueError("source_id 不得重复。")
        instances = {instance.instance_id: instance for instance in self.detected_instances}
        if len(instances) != len(self.detected_instances):
            raise ValueError("同一规格内 instance_id 不得重复。")
        if self.selected_instance is not None and self.selected_instance not in instances:
            raise ValueError("selected_instance 必须指向已记录的实例。")
        for instance in instances.values():
            if not instance.instance_id or instance.source_id not in sources:
                raise ValueError("实例必须关联已记录的来源图。")
            if len(instance.roi) != 4 or any(isinstance(v, bool) or not isinstance(v, int) for v in instance.roi):
                raise ValueError("实例 ROI 必须由四个整数组成。")
            x, y, w, h = instance.roi
            image = sources[instance.source_id]
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > image.width_px or y+h > image.height_px:
                raise ValueError("实例 ROI 超出来源图范围。")
            if instance.evidence.status in {EvidenceStatus.UNKNOWN, EvidenceStatus.CONCEPTUAL}:
                raise ValueError("未知或推测的实例不能作为已检测实例。")
        evidence = [self.product_category, self.visible_view, self.product_mask]
        evidence += list(self.geometry_features.values()) + list(self.appearance_features.values())
        evidence += self.protected_regions + list(self.verified_facts.values()) + list(self.unknown_properties.values())
        evidence += [instance.evidence for instance in instances.values()]
        for fact in evidence:
            if not isinstance(fact, Evidence):
                raise ValueError("属性必须用 Evidence 记录来源和状态。")
            fact.__post_init__()
            if not set(fact.sources).issubset(sources):
                raise ValueError("证据来源必须关联 source_images 中的 source_id。")
        if any(fact.status != EvidenceStatus.HUMAN_VERIFIED for fact in self.verified_facts.values()):
            raise ValueError("verified_facts 只能包含人工确认事实。")
        if any(fact.status != EvidenceStatus.UNKNOWN for fact in self.unknown_properties.values()):
            raise ValueError("unknown_properties 不能保存猜测默认值。")
        for value in self.confidence.values():
            if value is not None and (isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("无效通用置信度。")
        if self.human_review_status == "reviewed" and not self.verified_facts:
            raise ValueError("reviewed 状态必须有人工确认记录。")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        # round-trip 确保只有标准 JSON 类型，元组变数组；不接受 NaN 或任意对象。
        return json.loads(json.dumps(asdict(self), ensure_ascii=False, allow_nan=False))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, allow_nan=False) + "\n"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ProductSpec:
        if value.get("schema_version") != "studio.1g.1":
            raise ValueError("不是 studio.1g.1 规格；旧格式必须通过插件适配，不能猜测。")
        data = dict(value)

        def fact(raw):
            raw = dict(raw)
            raw["status"] = EvidenceStatus(raw["status"])
            raw["sources"] = tuple(raw["sources"])
            return Evidence(**raw)

        data["source_images"] = [SourceImage(**item) for item in data["source_images"]]
        data["detected_instances"] = [ProductInstance(
            instance_id=item["instance_id"], source_id=item["source_id"], roi=tuple(item["roi"]),
            evidence=fact(item["evidence"]), sku=item.get("sku")) for item in data["detected_instances"]]
        for key in ("product_category", "visible_view", "product_mask"):
            data[key] = fact(data[key])
        for key in ("geometry_features", "appearance_features", "verified_facts", "unknown_properties"):
            data[key] = {name: fact(raw) for name, raw in data[key].items()}
        data["protected_regions"] = [fact(item) for item in data["protected_regions"]]
        result = cls(**data)
        result.validate()
        return result

