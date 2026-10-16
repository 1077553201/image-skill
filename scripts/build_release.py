"""Build the standard wheel and complete Skill archive, without model/font binaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parents[1];out=a.output.resolve()
    if out.exists() and any(out.iterdir()):raise SystemExit('Use a new empty release directory')
    out.mkdir(parents=True,exist_ok=True)
    temp=out/'build_tmp';temp.mkdir()
    env={**os.environ, 'TEMP':str(temp), 'TMP':str(temp), 'TMPDIR':str(temp)}
    subprocess.run([sys.executable,'-m','pip','wheel','--no-deps','--no-build-isolation',str(root),'--wheel-dir',str(out)],check=True,env=env)
    wheel=next(out.glob('*.whl'));skill=out/'universal-product-creative'
    shutil.copytree(root/'skills/universal-product-creative',skill,ignore=shutil.ignore_patterns('__pycache__','*.pyc','runtime','release_manifest.json'))
    (skill/'runtime').mkdir();shutil.copyfile(wheel,skill/'runtime'/wheel.name)
    (skill/'configs').mkdir(exist_ok=True)
    shutil.copyfile(root/'src/product_studio/resources/comfyui_template.json',skill/'configs/comfyui.example.json')
    for source,name in [('qwen_image21_api.json','qwen_image21_api.json'),('image_edit_template.json','image_edit.example.json'),('qwen_image21_edit_api.json','qwen_image21_edit_api.json')]:
        shutil.copyfile(root/'src/product_studio/resources'/source,skill/'configs'/name)
    files={f.relative_to(skill).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in skill.rglob('*') if f.is_file()}
    (skill/'release_manifest.json').write_text(json.dumps({'engine_wheel':wheel.name,'files':files,'fonts_models_keys_included':False},indent=2),encoding='utf-8')
    archive=out/'universal-product-creative.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for f in skill.rglob('*'):
            if f.is_file():z.write(f,f.relative_to(out))
    print(json.dumps({'wheel':str(wheel),'skill':str(archive),'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest()},indent=2))


if __name__=='__main__':main()
