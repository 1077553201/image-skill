"""只读环境诊断：本机与 ComfyUI 服务端分别记录，不执行工作流。"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


PACKAGE_NAMES = (
    "pip", "setuptools", "torch", "torchvision", "numpy",
    "opencv-python", "opencv-python-headless", "Pillow", "shapely",
)
IMPORT_PROBE = """
import importlib, json
result = {}
for name in ('numpy', 'cv2', 'PIL', 'shapely'):
    try:
        module = importlib.import_module(name)
        result[name] = {'status': 'passed', 'version': str(module.__version__)}
    except Exception as exc:
        result[name] = {'status': 'warning', 'error': type(exc).__name__ + ': ' + str(exc)}
print(json.dumps(result))
"""
TORCH_PROBE = """
import json
try:
    import torch
    result = {
        'version': str(torch.__version__),
        'cuda_build': torch.version.cuda,
        'cuda_available': bool(torch.cuda.is_available()),
        'devices': [],
    }
    for index in range(torch.cuda.device_count()):
        properties = torch.cuda.get_device_properties(index)
        device = {
            'index': index, 'name': properties.name,
            'total_memory_bytes': properties.total_memory,
            'compute_capability': list(torch.cuda.get_device_capability(index)),
        }
        try:
            value = (torch.tensor([1.0], device=f'cuda:{index}') + 1.0).item()
            device['smoke_test'] = 'passed' if value == 2.0 else 'failed'
        except Exception as exc:
            device['smoke_test'] = 'failed'
            device['error'] = type(exc).__name__ + ': ' + str(exc)
        result['devices'].append(device)
    print(json.dumps(result))
except Exception as exc:
    print(json.dumps({'error': type(exc).__name__ + ': ' + str(exc)}))
"""


def run_command(command: list[str], timeout: float = 30) -> dict[str, Any]:
    """不使用 shell；子进程失败或超时不会中断其余诊断。"""
    try:
        process = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False,
        )
        return {
            "status": "passed" if process.returncode == 0 else "warning",
            "returncode": process.returncode,
            "stdout": process.stdout.strip()[-16000:],
            "stderr": process.stderr.strip()[-8000:],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "warning", "error": f"{type(exc).__name__}: {exc}"}


def probe_python_code(code: str) -> dict[str, Any]:
    result = run_command([sys.executable, "-c", code], timeout=45)
    if result["status"] != "passed":
        return {"status": "warning", "process": result}
    # 某些第三方库会向 stdout 打印信息，诊断 JSON 放在最后一行。
    try:
        payload = json.loads(result["stdout"].splitlines()[-1])
        if not isinstance(payload, dict):
            raise ValueError("probe did not return a JSON object")
    except (ValueError, IndexError) as exc:
        return {"status": "warning", "error": str(exc), "process": result}
    return {"status": "warning" if "error" in payload else "passed", "data": payload}


def package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in PACKAGE_NAMES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def probe_nvidia() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"status": "warning", "message": "nvidia-smi 未出现在 PATH，不能据此断定没有 GPU。"}
    result = run_command([
        executable,
        "--query-gpu=index,name,driver_version,memory.total,memory.free",
        "--format=csv,noheader,nounits",
    ])
    devices = []
    if result["status"] == "passed":
        try:
            for row in csv.reader(io.StringIO(result["stdout"])):
                if len(row) != 5:
                    raise ValueError("unexpected nvidia-smi columns")
                index, name, driver, total, free = (value.strip() for value in row)
                devices.append({
                    "index": int(index), "name": name, "driver_version": driver,
                    "memory_total_mib": float(total), "memory_free_mib": float(free),
                })
        except ValueError as exc:
            return {"status": "warning", "error": str(exc), "query": result}
    return {
        "status": "passed" if devices else "warning",
        "executable": executable, "devices": devices, "query": result,
        "note": "驱动存在不代表当前 Python 的 PyTorch 支持 CUDA。",
    }


def probe_executable(name: str, explicit_path: Path | None = None) -> dict[str, Any]:
    executable = str(explicit_path) if explicit_path else shutil.which(name)
    if not executable:
        return {
            "status": "warning", "installation_status": "unknown",
            "message": f"{name} 未出现在 PATH 且未提供路径；是否安装仍待确认。",
        }
    if explicit_path and not explicit_path.is_file():
        return {"status": "warning", "installation_status": "unknown", "error": f"路径不是文件：{explicit_path}"}
    result = run_command([executable, "--version"])
    return {"executable": executable, **result}


def normalize_base_url(value: str) -> str:
    parts = urllib.parse.urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("ComfyUI 地址必须包含 http:// 或 https:// 以及主机地址。")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("ComfyUI 地址不能包含凭据、查询参数或 fragment。")
    _ = parts.port  # 对非法端口给出配置错误，而非悄悄吞掉。
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_json(url: str, timeout: float) -> dict[str, Any]:
    # 局域网请求直连，避免继承机器上的 HTTP 代理；仅 GET，不跟随重定向。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("API 响应超过诊断读取上限（2 MiB）。")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("API 没有返回 JSON 对象。")
    return payload


def probe_comfyui(base_url: str, timeout: float = 10) -> dict[str, Any]:
    """两条实际 GET 路由均通过响应结构检查才判定 API 可用。"""
    result: dict[str, Any] = {
        "base_url": normalize_base_url(base_url), "status": "failed",
        "access": "GET only", "workflow_execution": "unverified", "endpoints": {},
    }
    for route in ("/system_stats", "/queue"):
        try:
            payload = get_json(result["base_url"] + route, timeout)
            if route == "/system_stats":
                system, devices = payload.get("system"), payload.get("devices")
                if not isinstance(system, dict) or not isinstance(devices, list):
                    raise ValueError("system_stats 缺少 system 对象或 devices 数组。")
                if not all(isinstance(system.get(key), str) for key in ("os", "python_version", "pytorch_version")):
                    raise ValueError("system_stats 的 OS/Python/PyTorch 字段不完整。")
                if not all(isinstance(device, dict) for device in devices):
                    raise ValueError("system_stats 的设备格式不正确。")
                # 不存储 argv 等可能含私有参数的信息，也不保存队列中的工作流内容。
                system_keys = ("os", "python_version", "pytorch_version", "comfyui_version", "embedded_python", "deploy_environment")
                device_keys = ("name", "type", "index", "vram_total", "vram_free", "torch_vram_total", "torch_vram_free")
                result["system"] = {key: system[key] for key in system_keys if key in system}
                result["devices"] = [
                    {key: device[key] for key in device_keys if key in device} for device in devices
                ]
            else:
                running, pending = payload.get("queue_running"), payload.get("queue_pending")
                if not isinstance(running, list) or not isinstance(pending, list):
                    raise ValueError("queue 缺少 queue_running/queue_pending 数组。")
                result["queue"] = {"running_count": len(running), "pending_count": len(pending)}
            result["endpoints"][route] = {"status": "passed"}
        except (OSError, ValueError, urllib.error.URLError) as exc:
            result["endpoints"][route] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    if all(endpoint["status"] == "passed" for endpoint in result["endpoints"].values()):
        result["status"] = "passed"
    return result


def resolve_optional_path(value: str | None, root: Path) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def inspect_comfyui_root(root: Path | None) -> dict[str, Any]:
    if root is None:
        return {"status": "warning", "path": None, "message": "未提供本机 ComfyUI 路径；远程服务目录也不能从 API 推断。"}
    return {
        "status": "passed" if root.is_dir() and (root / "main.py").is_file() else "warning",
        "path": str(root), "scope": "machine running this script",
        "main_py_present": (root / "main.py").is_file(),
    }


def check_workspace(root: Path) -> dict[str, Any]:
    try:
        if not root.is_dir():
            raise OSError("项目根目录不存在。")
        with tempfile.TemporaryFile(dir=root):
            pass
        return {"status": "passed", "root": str(root), "writable": True}
    except OSError as exc:
        return {"status": "failed", "root": str(root), "writable": False, "error": str(exc)}


def collect_report(
    project_root: Path,
    *,
    comfyui_url: str,
    timeout: float = 10,
    comfyui_root: Path | None = None,
    blender: Path | None = None,
    skip_api: bool = False,
) -> dict[str, Any]:
    local = {
        "os": platform.system(), "os_release": platform.release(),
        "os_version": platform.version(), "machine": platform.machine(),
        "python": {
            "version": platform.python_version(), "full_version": sys.version,
            "executable": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
            "virtual_env": os.environ.get("VIRTUAL_ENV"),
            "conda_environment": os.environ.get("CONDA_DEFAULT_ENV"),
        },
        "installed_packages": package_versions(),
        "imports": probe_python_code(IMPORT_PROBE),
        "nvidia": probe_nvidia(),
        "pytorch": probe_python_code(TORCH_PROBE),
        "cuda_toolkit": probe_executable("nvcc"),
        "blender": probe_executable("blender", blender),
        "comfyui_root": inspect_comfyui_root(comfyui_root),
    }
    remote = (
        {"status": "skipped", "base_url": normalize_base_url(comfyui_url), "workflow_execution": "unverified"}
        if skip_api else probe_comfyui(comfyui_url, timeout)
    )
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, message: str, required: bool = False) -> None:
        checks.append({"name": name, "status": status, "required": required, "message": message})

    add("python", "passed" if sys.version_info >= (3, 11) else "failed", "本机 Python 至少需要 3.11。", True)
    workspace = check_workspace(project_root)
    add("workspace", workspace["status"], "检查实际项目目录和写入权限。", True)
    add("comfyui_api", remote["status"], "仅验证 API 访问；工作流执行能力仍待阶段 5 验证。", True)
    import_data = local["imports"].get("data", {})
    imports_ok = all(import_data.get(name, {}).get("status") == "passed" for name in ("numpy", "cv2", "PIL"))
    add("vision_packages", "passed" if imports_ok else "warning", "检查 NumPy/OpenCV/Pillow 的实际导入。")
    add("shapely", import_data.get("shapely", {}).get("status", "warning"), "阶段 3 前再确定 Shapely 版本与安装环境。")
    torch_data = local["pytorch"].get("data", {})
    cuda_ok = torch_data.get("cuda_available") and bool(torch_data.get("devices")) and all(
        device.get("smoke_test") == "passed" for device in torch_data.get("devices", [])
    )
    add("local_torch_cuda", "passed" if cuda_ok else "warning", "本机 CUDA 小张量运算；CPU 版不影响通过网络调用远程 ComfyUI。")
    add("nvidia_driver", local["nvidia"]["status"], "本机 NVIDIA 驱动和 GPU 检测。")
    add("cuda_toolkit", local["cuda_toolkit"]["status"], "nvcc 仅按 PATH 检测；未找到不能证明未安装，阶段 0 不需要编译 CUDA。")
    add("blender", local["blender"]["status"], "Blender 仅按显式路径或 PATH 检测；阶段 3 前确认。")
    add("comfyui_directory", local["comfyui_root"]["status"], "本机路径和远程安装路径分别确认。")
    failed = any(check["required"] and check["status"] == "failed" for check in checks)
    complete = all(check["status"] == "passed" for check in checks if check["required"])
    return {
        "schema_version": 1, "project_version": "0.1.0",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {"local": "machine running this script", "remote": "ComfyUI HTTP server"},
        "workspace": workspace, "local": local, "comfyui": remote, "checks": checks,
        "acceptance": {
            "required_checks_passed": complete,
            "status": "failed" if failed else ("required_checks_passed" if complete else "incomplete"),
            "user_confirmation": "pending", "next_stage_started": False,
        },
        "limitations": [
            "此报告不是 QwenImage 工作流、实际生图性能或 RTX 3090 兼容性验证。",
            "远程服务的 CPU 架构、目录、nvcc 与 Blender 状态需要在该机器运行脚本确认。",
            "installed_packages 是当前环境清单，不是经过验证的项目依赖锁文件。",
        ],
    }


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open(encoding="utf-8-sig") as stream:
        config = json.load(stream)
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("配置必须是 schema_version=1 的 JSON 对象。")
    for key in ("comfyui", "tools"):
        if key in config and not isinstance(config[key], dict):
            raise ValueError(f"配置 {key} 必须是对象。")
    comfy = config.get("comfyui", {})
    for key, value in (
        ("comfyui.base_url", comfy.get("base_url")),
        ("comfyui.local_root", comfy.get("local_root")),
        ("tools.blender_executable", config.get("tools", {}).get("blender_executable")),
    ):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"配置 {key} 必须是字符串或 null。")
    timeout = comfy.get("timeout_seconds", 10)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError("timeout_seconds 必须是大于 0、不超过 60 的有限数值。")
    return config


def write_report(report: dict[str, Any], destination: Path) -> None:
    """同一目录内原子替换，避免中断后留下半份 JSON。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None, *, project_root: Path | None = None) -> int:
    # Windows 管道默认编码可能是 GBK；明确使用 UTF-8，报告与终端保持一致。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="阶段 0 环境检测：只读检查，不安装模型、不提交生图任务。")
    parser.add_argument("--project-root", type=Path, default=project_root or Path.cwd())
    parser.add_argument("--config", type=Path, help="JSON 配置文件，默认读取项目 configs/environment.json。")
    parser.add_argument("--comfyui-url", help="覆盖配置中的 ComfyUI API 基础地址。")
    parser.add_argument("--comfyui-root", help="运行脚本这台机器的 ComfyUI 目录，不是远程机器路径。")
    parser.add_argument("--blender", help="Blender 可执行文件路径。")
    parser.add_argument("--timeout", type=float, help="每条 API 请求的超时秒数，范围 (0, 60]。")
    parser.add_argument("--skip-api", action="store_true", help="离线检测；API 验收会明确标记为 skipped。")
    parser.add_argument("--output", default="reports/environment.json", help="报告路径，相对路径按项目根目录解析。")
    args = parser.parse_args(argv)
    root = args.project_root.expanduser().resolve()
    try:
        default_config = root / "configs" / "environment.json"
        config_path = resolve_optional_path(str(args.config), root) if args.config else (default_config if default_config.is_file() else None)
        config = load_config(config_path)
        comfy, tools = config.get("comfyui", {}), config.get("tools", {})
        url = normalize_base_url(args.comfyui_url or comfy.get("base_url") or "http://192.168.1.171:8188")
        timeout = args.timeout if args.timeout is not None else comfy.get("timeout_seconds", 10)
        if not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError("超时秒数必须大于 0 且不超过 60。")
        report = collect_report(
            root, comfyui_url=url, timeout=timeout, skip_api=args.skip_api,
            comfyui_root=resolve_optional_path(args.comfyui_root or comfy.get("local_root"), root),
            blender=resolve_optional_path(args.blender or tools.get("blender_executable"), root),
        )
        destination = resolve_optional_path(args.output, root)
        if destination is None:
            raise ValueError("报告输出路径不能为空。")
        write_report(report, destination)
    except (OSError, ValueError) as exc:
        print(f"环境检测失败：{exc}", file=sys.stderr)
        return 2 if isinstance(exc, ValueError) else 1
    print(f"报告已保存：{destination}")
    print(f"本机：{report['local']['os']} {report['local']['machine']} / Python {report['local']['python']['version']}")
    for check in report["checks"]:
        print(f"[{check['status'].upper()}] {check['name']}: {check['message']}")
    print(f"阶段 0 检查状态：{report['acceptance']['status']}；等待用户确认，未开始下一阶段。")
    return 1 if report["acceptance"]["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
