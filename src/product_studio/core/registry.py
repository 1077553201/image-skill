"""分析器按名称显式注册。核心不知道圆盘规则，也不按类别强制几何测量。"""

from dataclasses import dataclass, replace
from typing import Callable
from uuid import uuid4

from product_studio.analyzers.base import AnalysisOutcome, AnalysisRequest, Analyzer
from product_studio.core.schemas import ProductSpec


@dataclass
class RoutingResult:
    specs: list[ProductSpec]
    records: list[dict]
    artifacts: list


class AnalyzerRegistry:
    def __init__(self):
        self._factories: dict[str, Callable[[], Analyzer]] = {}

    def register(self, name: str, factory: Callable[[], Analyzer]) -> None:
        if not name or name in self._factories or not callable(factory):
            raise ValueError("分析器名称必须唯一且 factory 可调用。")
        self._factories[name] = factory

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._factories)

    def _analyze(self, name: str, request: AnalysisRequest) -> AnalysisOutcome:
        if name not in self._factories:
            return AnalysisOutcome(name, "skipped", warnings=["分析器未实现或未注册。"])
        try:
            analyzer = self._factories[name]()
            if not isinstance(analyzer, Analyzer) or analyzer.name != name:
                raise ValueError("注册工厂返回的分析器不符合接口或名称不一致。")
            outcome = analyzer.analyze(request)
            if outcome.analyzer != name or outcome.status not in {"processed", "skipped", "failed"}:
                raise ValueError("分析器返回无效状态。")
            for spec in outcome.specs:
                spec.validate()
            if outcome.status == "processed" and not outcome.specs:
                raise ValueError("processed 不能返回空结果。")
            if outcome.status == "skipped" and (outcome.specs or outcome.artifacts):
                raise ValueError("skipped 不能携带伪造的已分析结果。")
            return outcome
        except Exception as exc:
            return AnalysisOutcome(name, "failed", warnings=[f"{type(exc).__name__}: {exc}"])

    def route(self, request: AnalysisRequest, analyzer: str = "generic_product") -> RoutingResult:
        request = replace(request, product_id=request.product_id or f"product_{uuid4().hex}")
        generic = self._analyze("generic_product", request)
        if generic.status != "processed":
            raise ValueError("通用输入校验/处理失败：" + "; ".join(generic.warnings))
        if analyzer == "generic_product":
            return RoutingResult(generic.specs, [{"analyzer": analyzer, "status": "metadata_only"}], [])
        specialized = self._analyze(analyzer, request)
        record = {"analyzer": analyzer, "status": specialized.status, "warnings": specialized.warnings}
        # 只路由一个明确选择的插件，不合并不同检测器自行猜测的实例标识。
        specs = specialized.specs or generic.specs
        for spec in specs:
            spec.analysis_records.append(record.copy())
            spec.warnings.extend(specialized.warnings)
        return RoutingResult(specs, [{"analyzer": "generic_product", "status": "metadata_only"}, record], specialized.artifacts)

