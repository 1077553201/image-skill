"""单个实际 Provider：离线 BiRefNet Lite ONNX，明确 CPU 执行。"""

import hashlib
from pathlib import Path
import time

import numpy as np
from PIL import Image

from product_studio.segmentation.base import MaskPrediction, SegmentationProvider

MODEL_SHA256 = "5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333"
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx"


class BiRefNetLiteProvider(SegmentationProvider):
    def __init__(self, model_path: Path, threads: int = 4):
        if not model_path.is_file():
            raise FileNotFoundError(f"离线模型不存在：{model_path}。运行 setup_segmentation.py 获取唯一受支持的权重。")
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if digest != MODEL_SHA256:
            raise ValueError("模型 SHA-256 不匹配，禁止用未知权重冒充已验证版本。")
        if not isinstance(threads,int) or isinstance(threads,bool) or not 1<=threads<=32:raise ValueError("threads 必须在 1..32。")
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # CPU arena 会长期保留该高分辨率网络的大块内存；关闭以便单次任务后释放。
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        self.session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0]
        self.metadata = {"provider": "birefnet_lite_onnx", "model": "BiRefNet-general-lite",
                         "checkpoint": "bb_swin_v1_tiny-epoch_232", "model_sha256": digest,
                         "model_path": str(model_path.resolve()), "model_url": MODEL_URL,
                         "license": "MIT", "runtime": ort.__version__, "execution_providers": self.session.get_providers(),
                         "input_name": self.input.name, "input_shape": self.input.shape,
                         "threads": threads, "offline": True}
        self.metadata["memory_policy"]="CPU arena disabled; memory pattern disabled; single sequential session"

    def predict(self, rgb: np.ndarray) -> MaskPrediction:
        if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or min(rgb.shape[:2]) < 16:
            raise ValueError("模型输入必须是至少 16x16 的 uint8 RGB。")
        start = time.perf_counter()
        height, width = rgb.shape[:2]
        resized = np.asarray(Image.fromarray(rgb).resize((1024, 1024), Image.Resampling.LANCZOS), dtype=np.float32)
        scaled = resized / max(float(resized.max()), 1e-6)
        mean = np.array([.485, .456, .406], np.float32)
        std = np.array([.229, .224, .225], np.float32)
        tensor = ((scaled - mean) / std).transpose(2, 0, 1)[None].astype(np.float32)
        logits = self.session.run(None, {self.input.name: tensor})[0][0, 0]
        probability = 1 / (1 + np.exp(-np.clip(logits, -80, 80)))
        low, high = float(probability.min()), float(probability.max())
        if not np.isfinite(probability).all() or high - low < 1e-6:
            raise ValueError("模型没有返回有效的前景/背景区分信号。")
        # rembg 的该 checkpoint 使用 sigmoid 后 min-max，再 LANCZOS 恢复 ROI 尺寸。
        mask = np.rint((probability-low) / (high-low) * 255).astype(np.uint8)
        alpha = np.asarray(Image.fromarray(mask).resize((width, height), Image.Resampling.LANCZOS)).copy()
        metadata = {**self.metadata, "inference_seconds": time.perf_counter()-start,
                    "transform": {"roi_size_px": [width, height], "model_size_px": [1024, 1024],
                                  "roi_to_model_scale": [1024/width, 1024/height],
                                  "restore": "LANCZOS; no hole filling or largest-component filtering"},
                    "sigmoid_range": [low, high], "alpha_is_probability": False,
                    "alpha_interpretation": "segmentation confidence matte; not calibrated physical translucency"}
        return MaskPrediction(alpha, metadata)
