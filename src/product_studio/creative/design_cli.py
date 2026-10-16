"""Explicit design artifacts and user attestation; never submits generation."""
import argparse
import json
from pathlib import Path
from .design_workflow import DesignSession


def main(argv=None):
    parser = argparse.ArgumentParser(prog='product-studio design')
    parser.add_argument('--session', type=Path, required=True)
    sub = parser.add_subparsers(dest='action', required=True)
    create = sub.add_parser('init'); create.add_argument('--binding', type=Path, required=True)
    put = sub.add_parser('put'); put.add_argument('--kind', required=True); put.add_argument('--file', type=Path, required=True)
    for name in ('approve-concept', 'approve-page'):
        command = sub.add_parser(name); command.add_argument('--id', required=True)
        command.add_argument('--reviewer', required=True); command.add_argument('--statement', required=True)
    sub.add_parser('status')
    handoff = sub.add_parser('handoff'); handoff.add_argument('--id', required=True)
    handoff.add_argument('--result', type=Path, required=True)
    args = parser.parse_args(argv)
    session = DesignSession(args.session)
    try:
        if args.action == 'init':
            data = session.create(json.loads(args.binding.read_text(encoding='utf-8')), 'agent', 'Explicit asset selected')
        elif args.action == 'put':
            data = session.put(args.kind, json.loads(args.file.read_text(encoding='utf-8')))
        elif args.action == 'approve-concept':
            data = session.approve_concept(args.id, args.reviewer, args.statement)
        elif args.action == 'approve-page':
            data = session.approve_page(args.id, args.reviewer, args.statement)
        elif args.action == 'handoff':
            data = session.handoff(args.id, args.result)
        else:
            data = session.load()
        print(json.dumps(data, ensure_ascii=False, indent=2)); return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status':'blocked', 'error':str(exc)}, ensure_ascii=False)); return 1


if __name__ == '__main__':
    raise SystemExit(main())
