import argparse
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

from PIL import Image

from product_studio.segmentation.pipeline import segment,correct_mask,review_mask


def main(argv=None,*,project_root=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,"reconfigure"):stream.reconfigure(encoding="utf-8",errors="replace")
    parser=argparse.ArgumentParser(description="阶段 2A 通用抠图、外部 mask 修正与具名版本审核。")
    commands=parser.add_subparsers(dest="command",required=True)
    run=commands.add_parser("segment")
    run.add_argument("image")
    selection=run.add_mutually_exclusive_group(required=True)
    selection.add_argument("--roi",nargs=4,type=int,metavar=("X","Y","W","H"))
    selection.add_argument("--single-instance",action="store_true",help="用户明确声明整张图片是一个实例，自动模型不证明这个声明。")
    run.add_argument("--instance-id")
    run.add_argument("--keep-point",action="append",nargs=2,type=int,metavar=("X","Y"),help="若 ROI 仍包含多个分离区域，明确点选目标连通区；可重复以保留多个真实部分。")
    run.add_argument("--spec",type=Path,help="可选的 studio.1g.1 或 1a.1 规格，必须绑定该来源/实例。")
    run.add_argument("--model",type=Path,default=Path("models/segmentation/birefnet-general-lite.onnx"))
    run.add_argument("--threads",type=int,default=4)
    run.add_argument("--risk",action="append",default=[],choices=("transparent","reflective","internal_openings","complex_background"))
    run.add_argument("--output-dir",type=Path)
    fix=commands.add_parser("correct")
    fix.add_argument("result",type=Path)
    fix.add_argument("--mask",type=Path,required=True)
    fix.add_argument("--coordinates",choices=("source","roi"),required=True)
    fix.add_argument("--output-dir",type=Path)
    review=commands.add_parser("review",help="审核人明确检查预览后才能使用；助手不自动调用审核真实样例。")
    review.add_argument("result",type=Path,nargs="?")
    review.add_argument("--request-file",type=Path,help="使用生成的版本绑定审核请求，避免手抄来源和长 SHA；仍需具名确认。")
    review.add_argument("--reviewer",required=True)
    review.add_argument("--source-id")
    review.add_argument("--instance-id")
    review.add_argument("--mask-version")
    args=parser.parse_args(argv)
    root=Path(project_root or Path.cwd()).resolve()
    try:
        if args.command=="review":
            if args.request_file:
                if any((args.result,args.source_id,args.instance_id,args.mask_version)):raise ValueError("审核请求文件与手工绑定参数不能混用。")
                request=json.loads((root/args.request_file).read_text(encoding="utf-8"))
                if request.get("schema_version")!="mask_review_request.2a.1" or request.get("scope")!="mask_only":raise ValueError("审核请求文件无效。")
                result_path=Path(request["result"])
                source_id,instance_id,version=request["expected_source_id"],request["expected_instance_id"],request["expected_version"]
            else:
                if not all((args.result,args.source_id,args.instance_id,args.mask_version)):raise ValueError("需审核请求文件，或完整 result/source-id/instance-id/mask-version。")
                result_path=root/args.result;source_id,instance_id,version=args.source_id,args.instance_id,args.mask_version
            record=review_mask(result_path,reviewer=args.reviewer,expected_source_id=source_id,
                               expected_instance_id=instance_id,expected_version=version)
            print(f"已确认该来源/实例/遮罩版本，仅 mask：{record['mask_version']}")
            return 0
        output=(root/args.output_dir).resolve() if args.output_dir else root/"data/intermediate"/f"segmentation_{uuid4().hex[:12]}"
        if args.command=="correct":
            result=correct_mask(root/args.result,root/args.mask,args.coordinates,output)
        else:
            if not 1<=args.threads<=32:raise ValueError("threads 范围为 1..32。")
            source=root/args.image
            with Image.open(source) as image:width,height=image.size
            roi=args.roi or [0,0,width,height]
            instance=args.instance_id or "instance_"+hashlib.sha256(json.dumps(roi).encode()).hexdigest()[:12]
            if output.exists() and any(output.iterdir()):raise ValueError("输出目录非空。")
            from product_studio.segmentation.provider import BiRefNetLiteProvider
            provider=BiRefNetLiteProvider(root/args.model,args.threads)
            result=segment(source,roi,instance,output,provider,spec_path=root/args.spec if args.spec else None,risks=args.risk,keep_points=args.keep_point or [])
        print(f"输出：{output}")
        print(f"来源={result['binding']['source_id']} 实例={result['instance_id']} mask_version={result['binding']['mask_version']}")
        print(f"自动质检={result['quality']['automatic_status']}；人工审核=pending。")
        return 1 if result["quality"]["automatic_status"]=="failed" else 0
    except (OSError,ValueError,KeyError,ImportError) as exc:
        print(f"抠图处理失败：{type(exc).__name__}: {exc}",file=sys.stderr)
        return 2


if __name__=="__main__":raise SystemExit(main())
