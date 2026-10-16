"""Install the bundled hash-checked wheel into an explicitly chosen new venv."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import venv
import os
import sys
p=argparse.ArgumentParser();p.add_argument('--venv',type=Path,required=True);a=p.parse_args()
skill=Path(__file__).resolve().parents[1];wheels=list((skill/'runtime').glob('*.whl'))
if len(wheels)!=1:raise SystemExit('Release must include exactly one engine wheel')
wheel=wheels[0];manifest=json.loads((skill/'release_manifest.json').read_text(encoding='utf-8'))
if hashlib.sha256(wheel.read_bytes()).hexdigest()!=manifest['files'][wheel.relative_to(skill).as_posix()]:raise SystemExit('Wheel hash mismatch')
if a.venv.exists() and any(a.venv.iterdir()):raise SystemExit('Choose an empty new venv directory')
venv.EnvBuilder(with_pip=False).create(a.venv)
python=a.venv/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
# pip --python bootstraps an otherwise empty venv; never install into the host.
subprocess.run([sys.executable,'-m','pip','--python',str(python),'install',str(wheel)],check=True)
subprocess.run([str(python),str(skill/'scripts/preflight.py')],check=True)
