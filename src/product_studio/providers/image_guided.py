"""Explicit concept-only image editing through a user-supplied ComfyUI graph.

This provider is separate from the background-only provider. It deliberately
sends a real product reference to an editing model; no pixel identity is claimed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont, ImageOps


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ImageGuidedCreativeEditProvider:
    """One-reference image edit; workflow IDs and model names remain configuration."""

    capability = "image_guided_creative_edit"

    def __init__(self, config_path, *, transport=None, upload_transport=None):
        config_path = Path(config_path).resolve()
        self.config = json.loads(config_path.read_text(encoding="utf-8"))
        if self.config.get("capability") != self.capability:
            raise ValueError("Configuration must explicitly declare image_guided_creative_edit")
        self.base = (os.environ.get('COMFYUI_BASE_URL') or self.config.get('base_url') or '').rstrip('/')
        parsed = urlparse(self.base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid ComfyUI HTTP(S) base URL")
        workflow = Path(self.config["workflow_path"])
        self.workflow_path = (config_path.parent / workflow).resolve() if not workflow.is_absolute() else workflow.resolve()
        data = self.workflow_path.read_bytes()
        self.template_hash = _sha(data)
        expected = self.config.get("workflow_sha256")
        if expected and expected != self.template_hash:
            raise ValueError("Workflow SHA-256 does not match the configured original")
        self.template = json.loads(data)
        if not isinstance(self.template, dict) or "nodes" in self.template:
            raise ValueError("Expected an API prompt graph, not a UI workflow")
        self.transport = transport or self._http
        self.upload_transport = upload_transport or self._upload
        self.mapping = self.config["mapping"]
        required = {"prompt", "negative_prompt", "seed", "prefix", "reference_image"}
        if not required.issubset(self.mapping):
            raise ValueError("Missing editable workflow mapping")
        for key, mapping in self.mapping.items():
            node = self.template.get(mapping["node"])
            if not node or node.get("class_type") != mapping["class_type"] or mapping["input"] not in node.get("inputs", {}):
                raise ValueError("Invalid workflow mapping: " + key)
        loaders = [key for key, node in self.template.items() if node.get("class_type", "").startswith("LoadImage")]
        if loaders != [self.mapping["reference_image"]["node"]]:
            raise ValueError("This provider requires exactly one configured reference-image loader")
        if self.config["output_node"] not in self.template:
            raise ValueError("Configured output node is absent")

    def _http(self, route, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.base + route, data=body, headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.config.get("request_timeout_seconds", 30)) as response:
                return response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ComfyUI HTTP {exc.code} {route}: {detail[:12000]}") from exc

    def _request(self, route, payload=None):
        return json.loads(self.transport(route, payload))

    def _upload(self, raw: bytes, filename: str, mime: str):
        boundary = "productstudio" + uuid4().hex
        parts = []
        for name, value in (("type", "input"), ("overwrite", "false"), ("subfolder", "product_studio_concept")):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
        parts.extend([raw, f"\r\n--{boundary}--\r\n".encode()])
        request = Request(self.base + "/upload/image", data=b"".join(parts), headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
        try:
            with urlopen(request, timeout=self.config.get("request_timeout_seconds", 30)) as response:
                return response.read()
        except HTTPError as exc:
            raise RuntimeError(f"ComfyUI upload HTTP {exc.code}: " + exc.read().decode("utf-8", errors="replace")[:12000]) from exc

    def prepare(self, uploaded_path, prompt, negative_prompt, seed, prefix, *, object_info=None):
        if not isinstance(prompt, str) or not prompt.strip() or not isinstance(negative_prompt, str):
            raise ValueError("A nonempty editing instruction and string negative prompt are required")
        if type(seed) is not int or not 0 <= seed < 2**64:
            raise ValueError("Seed must be a uint64")
        graph = deepcopy(self.template)
        values = {"reference_image": uploaded_path, "prompt": prompt, "negative_prompt": negative_prompt, "seed": seed, "prefix": prefix}
        if object_info is not None:
            for node in graph.values():
                if node["class_type"] not in object_info:
                    raise ValueError("Remote node is unavailable: " + node["class_type"])
        for key, value in values.items():
            mapping = self.mapping[key]
            if object_info is not None:
                inputs = object_info[mapping["class_type"]].get("input", {})
                declared = {**inputs.get("required", {}), **inputs.get("optional", {})}
                if mapping["input"] not in declared:
                    raise ValueError("Remote parameter is unavailable: " + key)
            graph[mapping["node"]]["inputs"][mapping["input"]] = value
        return graph

    def generate(self, reference_image, prompt, negative_prompt="", *, seed, output_dir,
                 truth_mode="concept_creative", instance_id=None, expected_size_px=None):
        if truth_mode != "concept_creative":
            raise ValueError("Image-guided editing only permits concept_creative; strict_product is prohibited")
        # Validate editable values before any upload, queue action, or output writes.
        self.prepare("pending_upload", prompt, negative_prompt, seed, "validation_only")
        source = Path(reference_image).resolve()
        raw = source.read_bytes()
        if len(raw) > 64 * 1024 * 1024:
            raise ValueError("Reference image exceeds 64 MiB")
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if image.format not in {"JPEG", "PNG"}:
                raise ValueError("This provider accepts JPEG/PNG reference images")
            source_size = list(image.size)
            source_format = image.format
        out = Path(output_dir).resolve()
        if out.exists() and any(out.iterdir()):
            raise ValueError("Output directory is nonempty; existing image-edit history must be retained")
        out.mkdir(parents=True, exist_ok=True)
        suffix, mime = (".jpg", "image/jpeg") if source_format == "JPEG" else (".png", "image/png")
        (out / ("input_original" + suffix)).write_bytes(raw)
        record = {
            "provider": "comfyui", "capability": self.capability, "truth_mode": truth_mode,
            "status": "preparing", "started_at_utc": _now(), "base_url": self.base,
            "source_image": str(source), "source_sha256": _sha(raw), "source_size_px": source_size,
            "source_id": "source_" + _sha(raw)[:16], "instance_id": instance_id,
            "input_snapshot": "input_original" + suffix, "prompt": prompt, "negative_prompt": negative_prompt,
            "seed": seed, "workflow_template_sha256": self.template_hash, "prompt_id": None,
            "product_image_sent_to_AI": True, "product_pixels_may_be_redrawn": True,
            "identity_verified": False, "human_review_status": "pending", "asset_human_review_status": "pending",
        }
        start = time.monotonic()

        def event(name, **values):
            with (out / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"at": _now(), "event": name, **values}, ensure_ascii=False) + "\n")
            _save(out / "execution.json", record)

        try:
            event("started")
            queue = self._request("/queue")
            _save(out / "queue_before.json", queue)
            event("queue_inspected", running=len(queue.get("queue_running", [])), pending=len(queue.get("queue_pending", [])))
            upload = json.loads(self.upload_transport(raw, _sha(raw)[:24] + suffix, mime))
            _save(out / "upload_response.json", upload)
            name = upload.get("name")
            subfolder = upload.get("subfolder", "")
            if upload.get("type") != "input" or not isinstance(name, str) or not isinstance(subfolder, str):
                raise RuntimeError("Invalid reference-upload response")
            remote_path = PurePosixPath(subfolder) / name
            if not name or "/" in name or "\\" in name or remote_path.is_absolute() or ".." in remote_path.parts or "\\" in subfolder:
                raise RuntimeError("Unsafe path in reference-upload response")
            uploaded_raw = self.transport("/view?" + urlencode({"filename": name, "subfolder": subfolder, "type": "input"}), None)
            if _sha(uploaded_raw) != _sha(raw):
                raise RuntimeError("Uploaded reference bytes do not match the source SHA-256")
            record["upload"] = {**upload, "uploaded_reference_sha256": _sha(uploaded_raw), "reference_bytes_verified": True}
            event("reference_uploaded_and_verified")
            info = self._request("/object_info")
            graph = self.prepare(str(remote_path), prompt, negative_prompt, seed, "product_studio_concept_" + uuid4().hex, object_info=info)
            _save(out / "submitted_workflow.json", graph)
            record["submitted_workflow_sha256"] = _sha(json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
            record["model_nodes"] = {key: node for key, node in graph.items() if "Loader" in node["class_type"]}
            record["status"] = "submitting"
            event("submitting")
            submission = self._request("/prompt", {"prompt": graph, "client_id": str(uuid4())})
            _save(out / "submission.json", submission)
            if submission.get("error") or submission.get("node_errors") or not submission.get("prompt_id"):
                record["status"] = "submission_rejected"
                raise RuntimeError("Image-edit graph was rejected: " + json.dumps(submission, ensure_ascii=False))
            pid = submission["prompt_id"]
            record.update(prompt_id=pid, status="submitted")
            event("submitted", prompt_id=pid)
            print("ComfyUI concept edit submitted " + pid, flush=True)
            while True:
                if time.monotonic() - start > self.config.get("timeout_seconds", 1800):
                    record["status"] = "timed_out_pending_remote"
                    raise TimeoutError("Concept edit timed out; remote task was not interrupted or resubmitted. prompt_id=" + pid)
                history = self._request("/history/" + pid)
                if pid in history:
                    item = history[pid]
                    _save(out / "history.json", item)
                    status = item.get("status", {})
                    if status.get("status_str") == "error" or any(message[0] in {"execution_error", "execution_interrupted"} for message in status.get("messages", [])):
                        raise RuntimeError("Remote concept edit failed: " + json.dumps(status, ensure_ascii=False))
                    if status.get("completed"):
                        if status.get("status_str") != "success":
                            raise RuntimeError("Remote concept edit ended without success")
                        returned_prompt = item.get("prompt")
                        if not isinstance(returned_prompt, list) or len(returned_prompt) < 3 or returned_prompt[2] != graph:
                            raise RuntimeError("Remote history does not match the submitted image-edit graph")
                        record["history_workflow_matches_submission"] = True
                        outputs = item.get("outputs", {}).get(self.config["output_node"], {}).get("images", [])
                        if len(outputs) != 1 or outputs[0].get("type") != "output":
                            raise RuntimeError("Expected one actual output image, not an input or temp asset")
                        output = outputs[0]
                        generated = self.transport("/view?" + urlencode({key: output.get(key, "") for key in ("filename", "subfolder", "type")}), None)
                        with Image.open(io.BytesIO(generated)) as image:
                            image.load()
                            if image.format != "PNG":
                                raise RuntimeError("Expected a generated PNG")
                            size = list(image.size)
                            if expected_size_px is not None and size != list(expected_size_px):
                                raise RuntimeError("Generated size does not match the configured expected size")
                        (out / "generated.png").write_bytes(generated)
                        record.update(status="succeeded", output_image=output, output_sha256=_sha(generated), actual_size_px=size)
                        event("downloaded", sha256=_sha(generated))
                        break
                time.sleep(self.config.get("poll_seconds", 2))
        except Exception as exc:
            if record["status"] == "submitting":
                record["status"] = "submission_uncertain_no_retry"
            elif record["status"] not in {"timed_out_pending_remote", "submission_rejected"}:
                record["status"] = "failed"
            record["error"] = {"type": type(exc).__name__, "message": str(exc)}
            event("error", error=record["error"])
            raise
        finally:
            record["elapsed_seconds"] = time.monotonic() - start
            record["finished_at_utc"] = _now()
            _save(out / "execution.json", record)
        return out / "generated.png", record


def _previews(source: Path, generated: Path, out: Path):
    font = ImageFont.load_default(size=20)
    with Image.open(generated) as opened:
        concept = opened.convert("RGB")
    preview = Image.new("RGB", (concept.width, concept.height + 48), "#202020")
    preview.paste(concept, (0, 0))
    ImageDraw.Draw(preview).text((16, concept.height + 12), "CONCEPT EDIT - identity not verified", font=font, fill="white")
    preview.save(out / "concept_preview.png")
    comparison = Image.new("RGB", (1280, 700), "#eeeeee")
    for index, (path, title) in enumerate(((source, "SOURCE PHOTO"), (generated, "CONCEPT EDIT / HUMAN REVIEW PENDING"))):
        with Image.open(path) as image:
            tile = ImageOps.contain(image.convert("RGB"), (620, 630))
        comparison.paste(tile, (index * 640 + (640 - tile.width) // 2, 48 + (630 - tile.height) // 2))
        ImageDraw.Draw(comparison).text((index * 640 + 16, 12), title, font=font, fill="#202020")
    comparison.save(out / "comparison.png")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Actual ComfyUI image-guided concept-edit probe; never strict product output")
    parser.add_argument("--config", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--negative-prompt", default="")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--instance-id")
    parser.add_argument("--truth-mode", choices=["concept_creative", "strict_product"], default="concept_creative")
    parser.add_argument("--expected-size", type=int, nargs=2)
    args = parser.parse_args(argv)
    try:
        provider = ImageGuidedCreativeEditProvider(args.config)
        generated, record = provider.generate(args.image, args.prompt, args.negative_prompt, seed=args.seed,
                                              output_dir=args.output, instance_id=args.instance_id,
                                              truth_mode=args.truth_mode, expected_size_px=args.expected_size)
        _previews(generated.parent / record["input_snapshot"], generated, generated.parent)
    except Exception as exc:
        parser.exit(1, f"Image-guided concept edit failed: {type(exc).__name__}: {exc}\n")
    print(json.dumps({"output": str(generated), "prompt_id": record["prompt_id"], "truth_mode": record["truth_mode"], "asset_human_review_status": "pending"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
