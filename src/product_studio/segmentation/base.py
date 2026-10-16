from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class MaskPrediction:
    alpha: np.ndarray  # ROI 原尺寸 uint8，0..255；不是 RGB 重绘结果。
    metadata: dict[str, Any]


class SegmentationProvider(ABC):
    @abstractmethod
    def predict(self, rgb: np.ndarray) -> MaskPrediction:
        """输入选中区域的原始 RGB，返回同尺寸 Alpha 与实际执行记录。"""
