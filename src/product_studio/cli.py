"""阶段 1G 描述与规划入口；显式选插件，不执行抠图模型或生成后端。"""

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

from product_studio.analyzers.base import AnalysisRequest
from product_studio.core.schemas import Evidence, EvidenceStatus, ProductInstance, SourceImage
from product_studio.core.task_planner import OutputRequest, Strategy, plan_task
from product_studio.plugins import default_registry


def main(argv=None, *, project_root=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Universal AI Product Photography Studio，阶段 1G 描述与任务规划。")
    parser.add_argument("image")
    parser.add_argument("--analyzer", default="generic_product", help="默认通用元数据；planar_geometry 为现有蓝色圆盘插件；未实现插件明确跳过。")
    parser.add_argument("--roi", action="append", nargs=4, type=int, metavar=("X", "Y", "W", "H"), help="可重复：人工提供实例矩形，不是自动分割。")
    parser.add_argument("--sku", action="append", help="可选，与每个 ROI 一一对应；不自动合并相同或不同 SKU。")
    parser.add_argument("--selected-instance", help="选择 --roi 提供的实例，例如 instance_001；默认各实例分别处理。")
    parser.add_argument("--product-id")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--strategy", choices=[strategy.value for strategy in Strategy])
    parser.add_argument("--target-view")
    parser.add_argument("--allow-concept", action="store_true")
    args = parser.parse_args(argv)
    root = Path(project_root or Path.cwd()).resolve()
    source_path = (root / args.image).resolve()
    output = (root / args.output_dir).resolve() if args.output_dir else root / "data/intermediate" / f"studio_{uuid4().hex[:12]}"
    try:
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError("输出目录必须为空，避免混入旧结果。")
        if args.sku and len(args.sku) != len(args.roi or []):
            raise ValueError("--sku 数量必须与 --roi 数量一致。")
        # 这里只读取/校验图像元数据；核心数据模型和通用路由依然只依赖标准库。
        from PIL import Image
        with Image.open(source_path) as opened:
            width, height = opened.size
            opened.verify()
        source = SourceImage("source_001", str(source_path), hashlib.sha256(source_path.read_bytes()).hexdigest(), width, height)
        instances = [ProductInstance(f"instance_{index+1:03d}", source.source_id, tuple(roi),
                                     Evidence(True, EvidenceStatus.ESTIMATED, (source.source_id,), "user_supplied_roi",
                                              note="矩形实例由用户指定，未自动分割，也不是像素遮罩。"),
                                     args.sku[index] if args.sku else None) for index, roi in enumerate(args.roi or [])]
        request = AnalysisRequest([source], instances, args.product_id, args.selected_instance)
        if args.analyzer == "planar_geometry":
            from product_studio.plugins.planar_geometry.legacy import load_image
            request.image = load_image(source_path)
        routed = default_registry().route(request, args.analyzer)
        output.mkdir(parents=True, exist_ok=True)
        paths = []
        for index, spec in enumerate(routed.specs):
            destination = output / (spec.selected_instance or f"unassigned_{index+1:03d}")
            destination.mkdir()
            if routed.artifacts:
                from product_studio.plugins.planar_geometry.legacy import save_result
                artifact = routed.artifacts[index]
                artifact.spec["source_image"]["sha256"] = source.sha256
                legacy_dir = destination / "planar_geometry"
                save_result(artifact, legacy_dir)
                feature = spec.geometry_features["planar_geometry"]
                value = deepcopy(feature.value)
                value["legacy_payload"] = deepcopy(artifact.spec)
                spec.geometry_features["planar_geometry"] = replace(feature, value=value)
                spec.product_mask = Evidence({"artifact": "planar_geometry/product_mask.png", "quality": "partial", "instance_id": spec.selected_instance},
                                             EvidenceStatus.ESTIMATED, (source.source_id,), "phase1a_partial_mask",
                                             note="内壁保留，中心小孔未抠除，不是完整生产遮罩。")
            (destination / "product_spec.json").write_text(spec.to_json(), encoding="utf-8")
            if args.strategy:
                plan = plan_task(spec, OutputRequest(Strategy(args.strategy), args.target_view, args.allow_concept))
                (destination / "task_plan.json").write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            paths.append(str((destination / "product_spec.json").relative_to(output)))
        manifest = {"phase": "1G", "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                    "source_images": [asdict(source)], "routing": routed.records, "specs": paths,
                    "capability_scope": "metadata_and_explicit_plugin_analysis_and_planning_only",
                    "generation_executed": False}
        (output / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"通用规格 {len(routed.specs)} 份；路由记录：{routed.records}")
        print(f"输出：{output}；没有执行图像生成，所有结果仍待审核。")
        return 1 if any(record.get("status") == "failed" for record in routed.records) else 0
    except (OSError, ValueError, ImportError) as exc:
        print(f"阶段 1G 处理失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
