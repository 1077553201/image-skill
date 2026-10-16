"""阶段 1A：蓝色近正视圆盘的可见二维几何，保留原始轮廓，不推断 3D。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

import cv2
import numpy as np


class StructureDetectionError(ValueError):
    """输入有效，但图像证据不足以可靠提取几何。"""


@dataclass(frozen=True)
class ExtractionConfig:
    blue_hue_min: int = 85
    blue_hue_max: int = 135
    blue_saturation_min: int = 65
    blue_value_min: int = 30
    neutral_saturation_max: int = 70
    neutral_value_min: int = 180
    min_product_area_px: float = 500
    min_cutout_area_ratio: float = 0.02
    max_cutout_area_ratio: float = 0.25
    min_neutral_fraction: float = 0.8
    min_ellipse_axis_ratio: float = 0.85
    max_circle_rmse_ratio: float = 0.035

    def __post_init__(self) -> None:
        if not 0 <= self.blue_hue_min < self.blue_hue_max <= 179:
            raise ValueError("蓝色 H 阈值必须满足 0 <= min < max <= 179。")
        for name in ("blue_saturation_min", "blue_value_min", "neutral_saturation_max", "neutral_value_min"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
                raise ValueError(f"{name} 必须是 [0,255] 内的整数。")
        numeric = (self.min_product_area_px, self.min_cutout_area_ratio, self.max_cutout_area_ratio,
                   self.min_neutral_fraction, self.min_ellipse_axis_ratio, self.max_circle_rmse_ratio)
        if not all(np.isfinite(value) for value in numeric):
            raise ValueError("检测阈值必须是有限数值。")
        if self.min_product_area_px <= 0 or not 0 < self.min_cutout_area_ratio < self.max_cutout_area_ratio < 1:
            raise ValueError("商品面积必须为正；镂空面积比例必须满足 0 < min < max < 1。")
        if not 0 < self.min_neutral_fraction <= 1 or not 0 < self.min_ellipse_axis_ratio <= 1 or not 0 < self.max_circle_rmse_ratio < 1:
            raise ValueError("中性色比例、椭圆轴比和圆拟合误差阈值不合法。")


@dataclass
class AnalysisResult:
    spec: dict[str, Any]
    images: dict[str, np.ndarray]


def validate_image(image: np.ndarray) -> None:
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("输入必须是非空 uint8 三通道 BGR 图像。")
    if min(image.shape[:2]) < 16:
        raise ValueError("图像宽高至少为 16 像素。")


def load_image(path: Path) -> np.ndarray:
    """fromfile/imdecode 支持 Windows 中文路径；不重采样、不改变坐标。"""
    if not path.is_file():
        raise FileNotFoundError(f"图片不存在或不是文件：{path}")
    encoded = np.fromfile(path, dtype=np.uint8)
    if encoded.size == 0:
        raise ValueError("图片文件为空。")
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("文件无法解码为图片。")
    validate_image(image)
    return image


def validate_roi(roi: tuple[int, int, int, int] | None, shape: tuple[int, ...]) -> tuple[int, int, int, int]:
    height, width = shape[:2]
    if roi is None:
        return 0, 0, width, height
    if len(roi) != 4 or any(isinstance(value, bool) or not isinstance(value, (int, np.integer)) for value in roi):
        raise ValueError("ROI 必须是四个整数：x y width height。")
    x, y, w, h = map(int, roi)
    if x < 0 or y < 0 or w < 16 or h < 16 or x + w > width or y + h > height:
        raise ValueError("ROI 必须完整位于图像内，宽高至少 16；不自动裁剪错误 ROI。")
    return x, y, w, h


def circle_metrics(contour: np.ndarray) -> dict[str, Any]:
    """中心化代数最小二乘拟合；原始轮廓始终保留，圆只作为近似摘要。"""
    points = contour[:, 0, :].astype(np.float64)
    origin = points.mean(axis=0)
    shifted = points - origin
    matrix = np.column_stack((2 * shifted, np.ones(len(points))))
    fitted, _, rank, _ = np.linalg.lstsq(matrix, (shifted * shifted).sum(axis=1), rcond=None)
    radius_squared = fitted[2] + np.dot(fitted[:2], fitted[:2])
    if rank != 3 or radius_squared <= 0:
        raise StructureDetectionError("外轮廓不足以拟合圆。请提供完整商品 ROI。")
    center = origin + fitted[:2]
    radius = float(np.sqrt(radius_squared))
    residual = np.abs(np.linalg.norm(points - center, axis=1) - radius)
    ellipse_center, axes, angle = cv2.fitEllipse(contour)
    axis_ratio = min(axes) / max(axes)
    angles = np.mod(np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0]), 2 * np.pi)
    coverage = len(np.unique(np.minimum((angles * 36 / (2 * np.pi)).astype(int), 35))) / 36
    return {
        "center_px": center.tolist(), "radius_px": radius,
        "rmse_px": float(np.sqrt(np.mean(residual**2))),
        "p95_abs_error_px": float(np.percentile(residual, 95)),
        "max_abs_error_px": float(residual.max()), "angular_coverage": coverage,
        "ellipse": {"center_px": list(ellipse_center), "diameters_px": list(axes),
                    "rotation_deg": float(angle), "axis_ratio": float(axis_ratio)},
    }


def detect_instances(image: np.ndarray, roi: tuple[int, int, int, int], config: ExtractionConfig):
    x, y, w, h = roi
    hsv = cv2.cvtColor(image[y:y+h, x:x+w], cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (config.blue_hue_min, config.blue_saturation_min, config.blue_value_min),
                       (config.blue_hue_max, 255, 255))
    contours, _ = cv2.findContours(blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    candidates, rejected = [], []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < config.min_product_area_px or len(contour) < 5:
            continue
        bx, by, bw, bh = cv2.boundingRect(contour)
        metrics = circle_metrics(contour)
        reasons = []
        if bx == 0 or by == 0 or bx + bw == w or by + bh == h:
            reasons.append("轮廓触及图像/ROI 边界，可能被截断")
        if metrics["ellipse"]["axis_ratio"] < config.min_ellipse_axis_ratio:
            reasons.append("轮廓不是近正视圆盘，或多个商品连成一片")
        if metrics["rmse_px"] / metrics["radius_px"] > config.max_circle_rmse_ratio:
            reasons.append("圆拟合残差过大")
        if metrics["angular_coverage"] < 0.95:
            reasons.append("外边界角度覆盖不足")
        if reasons:
            rejected.append({"bbox_px": [bx+x, by+y, bw, bh], "reasons": reasons})
            continue
        global_contour = contour + np.array([[[x, y]]], dtype=np.int32)
        metrics["center_px"] = (np.asarray(metrics["center_px"]) + [x, y]).tolist()
        metrics["ellipse"]["center_px"] = (np.asarray(metrics["ellipse"]["center_px"]) + [x, y]).tolist()
        candidates.append({"contour": global_contour, "area": area, "metrics": metrics,
                           "bbox_px": [bx+x, by+y, bw, bh]})
    candidates.sort(key=lambda candidate: (candidate["metrics"]["center_px"][0], candidate["metrics"]["center_px"][1]))
    if not candidates:
        detail = json.dumps(rejected, ensure_ascii=False) if rejected else "未找到满足阈值的蓝色圆盘"
        raise StructureDetectionError(f"无法可靠分离或定位商品：{detail}。请配置包含完整单个商品的 --roi x y width height。")
    full_blue = np.zeros(image.shape[:2], dtype=np.uint8)
    full_blue[y:y+h, x:x+w] = blue
    return candidates, rejected, full_blue


def contour_data(contour: np.ndarray, center: np.ndarray, radius: float) -> dict[str, Any]:
    points = contour[:, 0, :]
    moments = cv2.moments(contour)
    centroid = [moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]]
    return {
        "contour_px": points.tolist(),
        "contour_normalized": ((points - center) / radius).tolist(),
        "area_px2": float(cv2.contourArea(contour)),
        "center_px": centroid, "center_normalized": ((np.asarray(centroid) - center) / radius).tolist(),
        "bbox_px": list(cv2.boundingRect(contour)),
    }


def detect_cutouts(image, blue, envelope, center, radius, disk_area, config):
    # 只在当前实例的实际轮廓内部寻找封闭非蓝区域，不把图外白背景算作孔。
    non_blue = cv2.bitwise_and(envelope, cv2.bitwise_not(blue))
    contours, _ = cv2.findContours(non_blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    neutral = cv2.inRange(hsv, (0, 0, config.neutral_value_min), (179, config.neutral_saturation_max, 255))
    distance_inside = cv2.distanceTransform(envelope, cv2.DIST_L2, 5)
    accepted, excluded, warnings = [], [], []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area <= 0:
            continue
        region = np.zeros_like(envelope)
        cv2.drawContours(region, [contour], -1, 255, cv2.FILLED)
        pixels = region > 0
        ratio = area / disk_area
        fraction = float(np.count_nonzero(neutral[pixels]) / np.count_nonzero(pixels))
        margin = float(distance_inside[pixels].min())
        reasons = []
        if ratio < config.min_cutout_area_ratio:
            reasons.append("below_large_cutout_area_threshold")
        if ratio > config.max_cutout_area_ratio:
            reasons.append("area_too_large_or_merged")
        if fraction < config.min_neutral_fraction:
            reasons.append("insufficient_bright_neutral_background_evidence")
        if margin < max(2.0, radius * 0.005):
            reasons.append("not_safely_enclosed_by_product")
        if reasons:
            # 保存可见中心区域的位置与排除原因，不识别金属件、螺丝或小孔的类别。
            if area >= 16:
                excluded.append({"bbox_px": list(cv2.boundingRect(contour)), "area_px2": area,
                                 "area_ratio": ratio, "neutral_fraction": fraction, "reasons": reasons})
            if ratio >= config.min_cutout_area_ratio:
                warnings.append("大型非蓝区域未通过开口证据检查，需人工审核，未强行填入 cutouts。")
            continue
        data = contour_data(contour, center, radius)
        data.update({"area_ratio": ratio, "neutral_fraction": fraction, "boundary_margin_px": margin,
                     "confidence": min(0.95, fraction), "geometry_verified": False,
                     "interpretation": "visible_background_aperture_candidate"})
        accepted.append((contour, data))
    accepted.sort(key=lambda item: (item[1]["center_px"][1], item[1]["center_px"][0]))
    for index, (_, data) in enumerate(accepted, 1):
        data["cutout_id"] = f"cutout_{index:03d}"
    return accepted, excluded, warnings


def make_debug_images(image, envelope, contour, metrics, cutouts, instance_id, roi):
    center = tuple(np.rint(metrics["center_px"]).astype(int))
    radius = int(round(metrics["radius_px"]))
    outer = image.copy()
    cv2.drawContours(outer, [contour], -1, (0, 220, 0), 2)
    cv2.circle(outer, center, radius, (255, 0, 255), 1)
    cv2.drawMarker(outer, center, (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
    overlay, mask = image.copy(), envelope.copy()
    colors = ((0, 200, 255), (0, 80, 255), (220, 80, 180), (60, 220, 60), (255, 160, 60))
    for index, (hole_contour, data) in enumerate(cutouts):
        color = colors[index % len(colors)]
        cv2.drawContours(overlay, [hole_contour], -1, color, 2)
        cv2.drawContours(mask, [hole_contour], -1, 0, cv2.FILLED)
        position = tuple(np.rint(data["center_px"]).astype(int))
        cv2.putText(overlay, f"H{index+1}", position, cv2.FONT_HERSHEY_SIMPLEX, .65, color, 2, cv2.LINE_AA)
    debug = overlay.copy()
    cv2.drawContours(debug, [contour], -1, (0, 220, 0), 2)
    cv2.circle(debug, center, radius, (255, 0, 255), 1)
    cv2.drawMarker(debug, center, (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
    x, y, w, h = roi
    cv2.rectangle(debug, (x, y), (x+w-1, y+h-1), (160, 160, 160), 1)
    cv2.rectangle(debug, (0, 0), (image.shape[1]-1, 110), (255, 255, 255), -1)
    lines = (
        f"{instance_id} | detected large apertures: {len(cutouts)} | NOT HUMAN VERIFIED",
        f"center=({metrics['center_px'][0]:.2f},{metrics['center_px'][1]:.2f}) px; R={metrics['radius_px']:.2f} px",
        f"circle RMSE={metrics['rmse_px']:.2f} px | green=observed boundary; magenta=circle fit",
        "Contours show visible openings; central parts retained; thickness unknown.",
    )
    for index, line in enumerate(lines):
        cv2.putText(debug, line, (10, 24+index*25), cv2.FONT_HERSHEY_SIMPLEX, .48, (30, 30, 30), 1, cv2.LINE_AA)
    return {"outer_contour.png": outer, "cutouts_overlay.png": overlay,
            "product_mask.png": mask, "debug_overlay.png": debug}


def analyze_image(
    image: np.ndarray,
    *,
    source_image: str = "in_memory",
    roi: tuple[int, int, int, int] | None = None,
    instance: str = "left",
    config: ExtractionConfig | None = None,
) -> list[AnalysisResult]:
    validate_image(image)
    config = config or ExtractionConfig()
    if instance not in {"left", "right", "all"}:
        raise ValueError("instance 必须是 left、right 或 all。")
    search_roi = validate_roi(roi, image.shape)
    candidates, rejected, blue = detect_instances(image, search_roi, config)
    indices = list(range(len(candidates))) if instance == "all" else [0 if instance == "left" else len(candidates)-1]
    metadata = [{"instance_id": f"instance_{i+1:03d}", "bbox_px": candidate["bbox_px"],
                 "center_px": candidate["metrics"]["center_px"]} for i, candidate in enumerate(candidates)]
    results = []
    for index in indices:
        candidate = candidates[index]
        contour, metrics = candidate["contour"], candidate["metrics"]
        center, radius = np.asarray(metrics["center_px"]), metrics["radius_px"]
        envelope = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.drawContours(envelope, [contour], -1, 255, cv2.FILLED)
        cutouts, excluded, warnings = detect_cutouts(image, blue, envelope, center, radius, candidate["area"], config)
        warnings.extend([
            "白色封闭区域仅作为可见背景开口候选；白色涂层/高光仍可能混淆，须人工确认。",
            "可见开口轮廓不等同于已验证的前表面加工孔口；暗色内壁、厚度和背面未恢复。",
            "中心金属件、螺丝和小区域保留原图；未分类，也未纳入大型 cutouts。",
            "product_mask 仅去除大型可见开口；中心小孔尚未抠除，不是生产级完整抠图。",
        ])
        if rejected:
            warnings.append("存在无法可靠识别的蓝色区域；实例数量仅计入可靠分离的候选，请检查 rejected_regions。")
        if not cutouts:
            warnings.append("未检出满足当前阈值的大型开口；可能无孔、阈值不适用或识别遗漏，需审核。")
        if metrics["ellipse"]["axis_ratio"] < 0.99 or metrics["rmse_px"] / radius > 0.006:
            warnings.append("原始外边界偏离理想圆；保留观测轮廓，未做透视校正。")
        circle_confidence = float(np.clip(1 - metrics["rmse_px"] / radius / config.max_circle_rmse_ratio, 0, 0.95))
        actual_roi = list(roi) if roi is not None else candidate["bbox_px"]
        instance_id = f"instance_{index+1:03d}"
        unresolved_cutouts = [region for region in excluded if region["area_ratio"] >= config.min_cutout_area_ratio]
        spec = {
            "schema_version": "1a.1", "status": "partial_failure" if rejected or unresolved_cutouts else "detected_unverified",
            "source_image": {"path": source_image, "width_px": image.shape[1], "height_px": image.shape[0]},
            "instance_id": instance_id, "roi": actual_roi, "search_roi": list(search_roi),
            "coordinate_system": {"origin": "full_source_image_top_left", "x": "right", "y": "down",
                                  "units": "pixels", "roi_format": "x,y,width,height; end exclusive",
                                  "normalized": "(point_px - outer_circle.center_px) / outer_circle.radius_px",
                                  "contour_closure": "closed; last point connects to first"},
            "instances_detected": metadata, "rejected_regions": rejected,
            "outer_circle": {**metrics, "confidence": circle_confidence, "interpretation": "approximate_circle_fit"},
            "outer_contour": contour[:, 0, :].tolist(),
            "outer_contour_normalized": ((contour[:, 0, :] - center) / radius).tolist(),
            "outer_area_px2": candidate["area"],
            "cutouts": [data for _, data in cutouts], "cutout_count": len(cutouts),
            "cutout_detection_status": "unresolved" if unresolved_cutouts else (
                "detected_unverified" if cutouts else "no_large_apertures_detected"),
            "unclassified_regions": excluded,
            "confidence": {"type": "heuristic_evidence_score_not_calibrated_probability",
                           "instance_separation": 0.9 if not rejected else 0.5,
                           "outer_circle": circle_confidence,
                           "cutouts": {data["cutout_id"]: data["confidence"] for _, data in cutouts}},
            "geometry_verified": False, "human_review": {"status": "pending", "reviewer": None},
            "thickness_mm": None, "back_structure": "unknown", "perspective_correction": "not_applied",
            "warnings": list(dict.fromkeys(warnings)), "parameters": asdict(config),
            "runtime": {"opencv": cv2.__version__, "numpy": np.__version__},
        }
        results.append(AnalysisResult(spec, make_debug_images(image, envelope, contour, metrics, cutouts, instance_id, actual_roi)))
    return results


def save_result(result: AnalysisResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, image in result.images.items():
        success, encoded = cv2.imencode(".png", image)
        if not success:
            raise OSError(f"无法编码调试图片：{filename}")
        encoded.tofile(output_dir / filename)
    result.spec["artifacts"] = {filename: {"path": filename, "coordinates": "full_source_image"} for filename in result.images}
    (output_dir / "product_spec.json").write_text(
        json.dumps(result.spec, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None, *, project_root: Path | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="阶段 1A：蓝色近正视圆盘的可见轮廓与大型开口，CPU 运行。")
    parser.add_argument("image", help="参考图路径；相对路径按项目根目录解析。")
    parser.add_argument("--instance", choices=("left", "right", "all"), default="left")
    parser.add_argument("--roi", nargs=4, type=int, metavar=("X", "Y", "W", "H"))
    parser.add_argument("--output-dir", type=Path, help="输出目录；默认在 data/intermediate 中新建唯一任务目录。")
    parser.add_argument("--min-cutout-area-ratio", type=float, default=0.02)
    parser.add_argument("--min-neutral-fraction", type=float, default=0.8)
    args = parser.parse_args(argv)
    root = (project_root or Path.cwd()).resolve()
    source = (root / args.image).resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = ((root / args.output_dir).resolve() if args.output_dir else
              root / "data" / "intermediate" / f"{source.stem}_{timestamp}_{uuid4().hex[:8]}")
    # 不复用有产物的目录，防止失败重跑后遗留旧图，被误认为新的成功结果。
    try:
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            print(f"输出路径不是空目录，请指定新目录，避免混用任务结果：{output}", file=sys.stderr)
            return 2
    except OSError as exc:
        print(f"无法检查输出目录：{exc}", file=sys.stderr)
        return 2
    try:
        config = ExtractionConfig(min_cutout_area_ratio=args.min_cutout_area_ratio,
                                  min_neutral_fraction=args.min_neutral_fraction)
        image = load_image(source)
        results = analyze_image(image, source_image=str(source), roi=tuple(args.roi) if args.roi else None,
                                instance=args.instance, config=config)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        for result in results:
            result.spec["source_image"]["sha256"] = digest
            result.spec["analyzed_at_utc"] = datetime.now(timezone.utc).isoformat()
            destination = output / result.spec["instance_id"] if args.instance == "all" else output
            save_result(result, destination)
            print(f"{result.spec['instance_id']}: 大型开口 {result.spec['cutout_count']} 个，圆拟合 RMSE {result.spec['outer_circle']['rmse_px']:.2f} px；待人工审核。")
        print(f"产物目录：{output}")
        if any(result.spec["status"] == "partial_failure" for result in results):
            print("部分几何识别失败：有未可靠分离的蓝色区域或无法判定的大型区域，请检查 warnings。", file=sys.stderr)
            return 1
        return 0
    except (OSError, ValueError, cv2.error) as exc:
        failure = {
            "schema_version": "1a.1", "status": "failed", "source_image": {"path": str(source)},
            "instance_id": None, "roi": args.roi, "outer_circle": None, "outer_contour": [],
            "cutouts": [], "confidence": None, "geometry_verified": False, "thickness_mm": None,
            "warnings": [f"{type(exc).__name__}: {exc}"],
        }
        try:
            output.mkdir(parents=True, exist_ok=True)
            (output / "product_spec.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as write_error:
            print(f"失败报告也无法写入：{write_error}", file=sys.stderr)
        print(f"分析失败：{exc}\n失败报告目录：{output}", file=sys.stderr)
        return 1 if isinstance(exc, StructureDetectionError) else 2


if __name__ == "__main__":
    raise SystemExit(main())

