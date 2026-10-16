"""Universal product campaign CLI: data changes only, never edit core code for a SKU."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from product_studio.creative.executor import execute


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',type=Path,required=True)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--prepare',action='store_true',help='Validate input, select/segment asset, emit Agent handoff or Creative Plan; no AI generation')
    group.add_argument('--render-only',action='store_true',help='Use existing successful backgrounds only')
    args=parser.parse_args()
    try:
        state=execute(ROOT,args.request,prepare_only=args.prepare,render_only=args.render_only)
        print(json.dumps(state,ensure_ascii=False,indent=2))
        return 2 if state['status']=='needs_agent_analysis' else 0
    except Exception as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
