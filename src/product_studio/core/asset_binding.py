"""标准库资产绑定校验；通用核心不依赖任何分割模型或商品形状。"""

import hashlib
import json
from pathlib import Path


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


def mask_version(source_id,source_sha256,instance_id,roi,mask_sha256):
    binding = {"source_id":source_id,"source_sha256":source_sha256,"instance_id":instance_id,
               "roi":list(roi),"mask_sha256":mask_sha256}
    return hashlib.sha256(json.dumps(binding,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def reviewed_mask_is_current(value,source,instance,reviewer):
    try:
        if not isinstance(value,dict) or value.get("source_id")!=source.source_id or value.get("source_sha256")!=source.sha256 or value.get("instance_id")!=instance.instance_id or value.get("roi")!=list(instance.roi):
            return False
        actual = file_sha256(value["artifact"])
        if actual!=value["mask_sha256"] or file_sha256(source.path)!=source.sha256:
            return False
        version = mask_version(source.source_id,source.sha256,instance.instance_id,instance.roi,actual)
        if value.get("mask_version")!=version or file_sha256(value["rgba_artifact"])!=value["rgba_sha256"]:
            return False
        record = json.loads(Path(value["review_record"]).read_text(encoding="utf-8"))
        return record.get("approved") is True and record.get("scope")=="mask_only" and record.get("reviewer")==reviewer and bool(reviewer) and all(record.get(key)==value.get(key) for key in
                   ("source_id","source_sha256","instance_id","roi","mask_sha256","mask_version","rgba_sha256"))
    except (OSError,ValueError,TypeError,KeyError):
        return False
