import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from product_studio.creative.quality import validate_campaign


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--remote',action='store_true')
    a=p.parse_args();r=validate_campaign(ROOT,a.output,remote=a.remote)
    print(json.dumps({'product_id':r['product_id'],'engineering_passed':r['engineering_passed'],'image_count':r['image_count'],'report':str(a.output/'quality_report.json')},ensure_ascii=False))
    return 0 if r['engineering_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
