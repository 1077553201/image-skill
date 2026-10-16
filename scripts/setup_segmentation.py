"""不写全局依赖；可复用现有包创建独立解释器，并显式下载唯一模型。"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
URL="https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx"
EXPECTED="5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333"


def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,"reconfigure"):stream.reconfigure(encoding="utf-8",errors="replace")
    parser=argparse.ArgumentParser(description="创建复用已安装依赖的推理环境；下载单个 BiRefNet Lite。")
    parser.add_argument("--download",action="store_true",help="显式允许下载权重；平时推理始终离线。")
    args=parser.parse_args()
    env=ROOT/".venv-seg"
    if not env.exists():subprocess.run([sys.executable,"-m","venv","--system-site-packages",str(env)],check=True)
    model=ROOT/"models/segmentation/birefnet-general-lite.onnx"
    if not model.is_file():
        if not args.download:raise ValueError("模型未保存；需要明确使用 --download。")
        model.parent.mkdir(parents=True,exist_ok=True)
        partial=model.with_suffix(".partial")
        with urllib.request.urlopen(URL,timeout=60) as response,partial.open("wb") as stream:
            while chunk:=response.read(1024*1024):stream.write(chunk)
        if hashlib.sha256(partial.read_bytes()).hexdigest()!=EXPECTED:raise ValueError("下载模型校验失败。")
        partial.replace(model)
    if hashlib.sha256(model.read_bytes()).hexdigest()!=EXPECTED:raise ValueError("模型 SHA-256 不正确。")
    manifest={"name":"BiRefNet-general-lite","checkpoint":"bb_swin_v1_tiny-epoch_232","sha256":EXPECTED,
              "size_bytes":model.stat().st_size,"download_url":URL,"license":"MIT",
              "license_source":"https://huggingface.co/ZhengPeng7/BiRefNet_lite",
              "export_source":"https://github.com/danielgatis/rembg/blob/main/rembg/sessions/birefnet_general_lite.py",
              "environment":".venv-seg; system-site-packages reused read-only; no package installations",
              "actual_runtime":"CPUExecutionProvider; GPU not installed/tested"}
    (model.parent/"model_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    print("推理环境和模型已就绪；这是独立前缀、共享依赖的环境，不是完整依赖副本。")
    return 0


if __name__=="__main__":raise SystemExit(main())
