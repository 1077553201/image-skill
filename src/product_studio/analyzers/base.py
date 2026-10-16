"""分析器契约。输入元数据或明确实例，不预设形状，也不绑定生成 Provider。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from product_studio.core.schemas import ProductInstance, ProductSpec, SourceImage


@dataclass
class AnalysisRequest:
    source_images: list[SourceImage]
    instances: list[ProductInstance] = field(default_factory=list)
    product_id: str | None = None
    selected_instance: str | None = None
    image: Any = None  # 只有明确选择需要像素的插件时才使用；核心不导入 NumPy。


@dataclass
class AnalysisOutcome:
    analyzer: str
    status: str  # processed / skipped / failed
    specs: list[ProductSpec] = field(default_factory=list)
    artifacts: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Analyzer(ABC):
    name: str

    @abstractmethod
    def analyze(self, request: AnalysisRequest) -> AnalysisOutcome:
        """未知、不支持或失败必须明确记录，不返回伪造成功。"""

