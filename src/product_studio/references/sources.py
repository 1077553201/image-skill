"""Small, bounded reference collector. No browser automation or access-control bypass."""
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import http.client
import io
import ipaddress
import json
from pathlib import Path
import re
import socket
import ssl
from urllib.parse import urlsplit, urlunsplit, urljoin
import zipfile

from PIL import Image, ImageDraw, ImageOps


AMAZON = {"amazon." + suffix for suffix in (
    "com", "co.uk", "de", "fr", "it", "es", "co.jp", "ca", "com.au",
    "nl", "se", "pl", "com.be", "com.mx", "com.br", "in", "ae", "sa", "sg")}
EBAY = {"ebay." + suffix for suffix in ("com", "co.uk", "de", "com.au", "ca", "fr", "it", "es", "nl", "ie", "at", "ch")}
CDN = {"m.media-amazon.com", "images-na.ssl-images-amazon.com", "images-eu.ssl-images-amazon.com", "i.ebayimg.com"}
ALLOWED = AMAZON | EBAY | {"www." + h for h in AMAZON | EBAY} | CDN
VOID = {"img", "source", "meta", "link", "br", "hr", "input", "area", "base", "embed", "wbr"}


def checked_url(url):
    if not isinstance(url, str) or any(ord(c) <= 32 for c in url) or "\\" in url:
        raise ValueError("Invalid reference URL")
    p = urlsplit(url)
    if p.scheme != "https" or p.username is not None or p.password is not None or p.port not in (None, 443):
        raise ValueError("Only public HTTPS references on port 443 are allowed")
    if p.hostname not in ALLOWED:
        raise ValueError("Reference host is not allowlisted")
    return p


def normalize_url(url):
    p = checked_url(url)
    host = p.hostname.removeprefix("www.")
    if host in AMAZON:
        m = re.search(r"/(?:dp|gp/product)/([A-Za-z0-9]{10})(?:/|$)", p.path)
        if not m:
            raise ValueError("Amazon URL must contain an ASIN")
        return {"kind": "amazon", "product_id": m[1].upper(), "url": f"https://www.{host}/dp/{m[1].upper()}"}
    if host in EBAY:
        m = re.fullmatch(r"/itm/(?:[^/]+/)?([0-9]{9,15})/?", p.path)
        if not m:
            raise ValueError("eBay URL must contain an item ID")
        return {"kind": "ebay", "product_id": m[1], "url": f"https://www.{host}/itm/{m[1]}"}
    raise ValueError("Input must be a supported product-page URL")


def public_addresses(host):
    addresses = sorted({x[4][0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("DNS resolved to a non-public address")
    return addresses


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # Connect to the validated numeric address, while preserving certificate/SNI host.
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


class PublicReferenceHTTP:
    def get(self, url, *, max_bytes=20_000_000, redirects=4):
        for _ in range(redirects + 1):
            p = checked_url(url)
            addresses = public_addresses(p.hostname)
            connection = _PinnedHTTPS(p.hostname, addresses[0], 30)
            try:
                connection.request("GET", urlunsplit(("", "", p.path or "/", p.query, "")), headers={
                    "User-Agent": "ProductStudioReferenceResearch/0.1", "Accept-Encoding": "identity"})
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader("Location")
                    if not location:
                        raise ValueError("Redirect missing Location")
                    url = urljoin(url, location)
                    checked_url(url)  # Revalidate every redirect, including its eventual DNS.
                    continue
                if response.status != 200:
                    raise RuntimeError(f"Reference HTTP {response.status}")
                if int(response.getheader("Content-Length", "0")) > max_bytes:
                    raise ValueError("Reference response too large")
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise ValueError("Reference response exceeded limit")
                return body, {"final_url": url, "content_type": response.getheader("Content-Type", ""),
                              "connected_ip": addresses[0], "bytes": len(body), "dns_pinned": True}
            finally:
                connection.close()
        raise ValueError("Too many reference redirects")


class _ScopedImages(HTMLParser):
    def __init__(self, kind):
        super().__init__(convert_charrefs=True)
        self.kind = kind
        self.stack = []
        self.images = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        marker = (d.get("id", "") + " " + d.get("class", "")).lower()
        scope = self.stack[-1][1] if self.stack else None
        if self.kind == "amazon" and ("aplus" in marker or d.get("id") in {"contentGrid_feature_div", "productDescription_feature_div"}):
            scope = "detail_or_aplus"
        if self.kind == "ebay" and ("ux-image-carousel" in marker or "ux-image-magnify" in marker):
            scope = "gallery"
        if tag == "img" and (scope or d.get("id") == "landingImage"):
            url = d.get("data-src") or d.get("src", "")
            self.images.append({"url": url, "role": scope or "main", "provenance": "scoped_html_img", "alt": d.get("alt")})
        if tag not in VOID:
            self.stack.append((tag, scope))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def extract_images(html, kind):
    if any(token in html.lower() for token in ("validatecaptcha", "enter the characters you see below", "pardon our interruption")):
        raise RuntimeError("Reference access challenge; supply screenshots, no bypass attempted")
    assets = []
    if kind == "amazon":
        # Parse the actual gallery's JSON payload, never all image URLs in the page.
        match = re.search(r"'colorImages':\s*\{\s*'initial':\s*A\.\$\.parseJSON\('((?:\\.|[^'\\])*)'\)", html)
        if match:
            try:
                gallery = json.loads(match[1])
            except json.JSONDecodeError:
                gallery = json.loads(match[1].replace("\\'", "'").replace("\\\\", "\\"))
            for item in gallery:
                url = item.get("hiRes") or item.get("large")
                if url:
                    assets.append({"url": url, "role": "main" if item.get("variant") == "MAIN" else "gallery",
                                   "provenance": "ImageBlockATF.colorImages.initial", "variant": item.get("variant"), "alt": item.get("altText")})
    parser = _ScopedImages(kind)
    parser.feed(html)
    assets += [x for x in parser.images if not (x["role"] == "main" and assets)]
    # eBay schema.org Product images are another explicit product source.
    if kind == "ebay":
        for script in re.findall(r'<script[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', html, re.S | re.I):
            try:
                decoded = json.loads(script)
            except ValueError:
                continue
            for node in decoded if isinstance(decoded, list) else [decoded]:
                if isinstance(node, dict) and node.get("@type") == "Product":
                    images = node.get("image", [])
                    for image in images if isinstance(images, list) else [images]:
                        url = image.get("url") if isinstance(image, dict) else image
                        assets.append({"url": url, "role": "gallery", "provenance": "schema.org.Product.image"})
    unique = {}
    for asset in assets:
        try:
            p = checked_url(asset["url"])
            if p.hostname not in CDN:
                continue
        except (ValueError, TypeError):
            continue
        unique.setdefault(asset["url"], asset)
    return list(unique.values())


def _save_asset(body, folder, metadata, index):
    sha = hashlib.sha256(body).hexdigest()
    with Image.open(io.BytesIO(body)) as im:
        if im.width * im.height > 40_000_000 or min(im.size) < 64:
            raise ValueError("Reference image dimensions unsuitable")
        im.load()
        size = list(im.size)
        suffix = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(im.format)
        if not suffix:
            raise ValueError("Unsupported reference image format")
    name = f"ref_{index:02d}_{sha[:12]}{suffix}"
    (folder / name).write_bytes(body)
    return {**metadata, "asset_id": f"ref_{index:02d}", "path": str((folder / name).resolve()),
            "sha256": sha, "size_px": size, "bytes": len(body), "internal_analysis_only": True,
            "semantic_role": "not_yet_visually_analyzed"}


def contact_sheet(assets, path):
    width, height = 360, 340
    sheet = Image.new("RGB", (width * 4, height * ((len(assets) + 3) // 4)), "#ededee")
    draw = ImageDraw.Draw(sheet)
    for i, a in enumerate(assets):
        x, y = (i % 4) * width, (i // 4) * height
        with Image.open(a["path"]) as im:
            tile = ImageOps.contain(im.convert("RGB"), (340, 285))
        sheet.paste(tile, (x + (width - tile.width) // 2, y + 8 + (285 - tile.height) // 2))
        draw.text((x + 12, y + 301), f'{a["asset_id"]} | {a["role"]} | {a["size_px"][0]}x{a["size_px"][1]}', fill="black")
    sheet.save(path)


def collect(output_dir, *, url=None, local=None, screenshot=False, http=None, saved_html=None):
    if (url is None) == (local is None):
        raise ValueError("Choose exactly one URL or local source")
    out = Path(output_dir).resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError("Reference output must be empty; preserve prior research")
    source = normalize_url(url) if url else {"kind": "screenshot" if screenshot else "local", "path": str(Path(local).resolve())}
    out.mkdir(parents=True, exist_ok=True)
    catalog = {"schema_version": "reference.4a.1", "source": source, "assets": [], "missing_assets": [],
               "collected_at": datetime.now(timezone.utc).isoformat(), "competitor_pixels_allowed_in_final": False}
    client = http or PublicReferenceHTTP()
    try:
        if url:
            if saved_html is None:
                body, response = client.get(source["url"], max_bytes=5_000_000)
            else:
                body = Path(saved_html).read_bytes()
                response = {"from_saved_html": str(Path(saved_html).resolve()), "not_a_new_page_request": True}
            (out / "page.html").write_bytes(body)
            catalog["page"] = {**response, "sha256": hashlib.sha256(body).hexdigest()}
            discovered = extract_images(body.decode("utf-8", errors="replace"), source["kind"])
            if not discovered:
                raise RuntimeError("No reliable product gallery found; supply screenshots")
            for item in discovered[:40]:
                try:
                    raw, response = client.get(item["url"])
                    asset = _save_asset(raw, out, {**item, "http": response}, len(catalog["assets"]) + 1)
                    if asset["sha256"] not in {x["sha256"] for x in catalog["assets"]}:
                        catalog["assets"].append(asset)
                except Exception as exc:
                    catalog["missing_assets"].append({"url": item["url"], "error": str(exc)})
            if not any(x["role"] == "detail_or_aplus" for x in catalog["assets"]):
                catalog["missing_assets"].append({"role": "detail_or_aplus", "reason": "No accessible detail/A+ images in fetched HTML; gallery completeness beyond this response is unknown"})
        else:
            p = Path(local)
            entries = []
            if p.suffix.lower() == ".zip":
                # Read bytes only: never extract archive paths, symlinks, or arbitrary files.
                with zipfile.ZipFile(p) as z:
                    if len(z.infolist()) > 200:
                        raise ValueError("Too many ZIP entries")
                    total = 0
                    for info in z.infolist():
                        if info.is_dir() or Path(info.filename).suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
                            continue
                        if ".." in Path(info.filename.replace("\\", "/")).parts or info.filename.startswith(("/", "\\")) or ":" in info.filename:
                            raise ValueError("Unsafe ZIP path")
                        total += info.file_size
                        if info.file_size > 20_000_000 or total > 150_000_000:
                            raise ValueError("ZIP image budget exceeded")
                        entries.append((info.filename, z.read(info)))
            else:
                files = sorted(p.iterdir()) if p.is_dir() else [p]
                files = [f for f in files if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
                if len(files) > 40:
                    raise ValueError("At most 40 local reference images")
                for f in files:
                    if f.stat().st_size > 20_000_000:
                        raise ValueError("Local image too large")
                    entries.append((str(f.resolve()), f.read_bytes()))
            for name, body in entries:
                catalog["assets"].append(_save_asset(body, out, {"origin": name, "role": source["kind"], "provenance": "user_supplied"}, len(catalog["assets"]) + 1))
        if not catalog["assets"]:
            raise RuntimeError("No usable reference images")
        contact_sheet(catalog["assets"], out / "reference_contact_sheet.png")
        catalog["status"] = "collected_with_gaps" if catalog["missing_assets"] else "collected"
    except Exception as exc:
        catalog.update(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
        raise
    finally:
        (out / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    return catalog
