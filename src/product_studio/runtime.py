"""Installed public CLI; all user paths are explicit or relative to the request file."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import sys


def preflight(config_dir=None):
    import product_studio
    from product_studio.configuration import available_font
    dependencies={name:importlib.metadata.version(name) for name in ('numpy','Pillow','opencv-python-headless')}
    return {'engine_version':importlib.metadata.version('product-photo-system'),
            'python':sys.executable,'python_version':sys.version,'engine_module':str(Path(product_studio.__file__).resolve()),
            'dependencies':dependencies,'sys_path':sys.path,'PYTHONPATH':os.environ.get('PYTHONPATH'),
            'config_dir':str(config_dir) if config_dir else None,'comfyui_base_url':os.environ.get('COMFYUI_BASE_URL'),
            'segmentation_model_configured':bool(os.environ.get('PRODUCT_STUDIO_SEGMENTATION_MODEL')),
            'font_regular':available_font('en'),'font_bold':available_font('en',True),
            'development_checkout_required':False,'models_or_credentials_bundled':False}


def main(argv=None):
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'design':
        from product_studio.creative.design_cli import main as design_main
        return design_main(argv[1:])
    parser=argparse.ArgumentParser(prog='product-studio')
    parser.add_argument('--version',action='version',version=importlib.metadata.version('product-photo-system'))
    sub=parser.add_subparsers(dest='command',required=True)
    run=sub.add_parser('generate');run.add_argument('--request',type=Path,required=True);run.add_argument('--output',type=Path,required=True)
    run.add_argument('--config-dir',type=Path);run.add_argument('--prepare',action='store_true');run.add_argument('--render-only',action='store_true');run.add_argument('--validate',action='store_true');run.add_argument('--remote',action='store_true')
    check=sub.add_parser('preflight');check.add_argument('--config-dir',type=Path);check.add_argument('--output',type=Path)
    verify=sub.add_parser('validate');verify.add_argument('--output',type=Path,required=True);verify.add_argument('--remote',action='store_true')
    export=sub.add_parser('export-asset');export.add_argument('--result',type=Path,required=True);export.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        config_dir=getattr(args,'config_dir',None) or os.environ.get('PRODUCT_STUDIO_CONFIG_DIR')
        if args.command=='preflight':
            report=preflight(config_dir)
            if args.output:args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        elif args.command=='export-asset':
            from product_studio.asset_bundle import export_asset
            report=export_asset(args.result,args.output)
        elif args.command=='validate':
            from product_studio.creative.quality import validate_campaign
            report=validate_campaign(args.output.resolve(),args.output,remote=args.remote)
            if not report['engineering_passed']:return 1
        else:
            from product_studio.creative.executor import execute
            report=execute(args.request.resolve().parent,args.request.resolve(),output_dir=args.output.resolve(),
                           portable=True,config_dir=config_dir,prepare_only=args.prepare,render_only=args.render_only)
            if report['status']=='needs_agent_analysis':print(json.dumps(report,ensure_ascii=False,indent=2));return 2
            if args.validate and not args.prepare:
                from product_studio.creative.quality import validate_campaign
                quality=validate_campaign(args.output.resolve(),args.output,remote=args.remote)
                report['engineering_passed']=quality['engineering_passed']
                if not quality['engineering_passed']:return 1
        print(json.dumps(report,ensure_ascii=False,indent=2));return 0
    except Exception as exc:
        print(json.dumps({'status':'failed','error':type(exc).__name__,'message':str(exc)},ensure_ascii=False),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
