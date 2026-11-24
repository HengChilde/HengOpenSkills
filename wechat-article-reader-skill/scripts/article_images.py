"""提取正文图片，以及按需下载供视觉查看的副本。"""

from __future__ import annotations

import argparse
import http.client
import json
import re
import tempfile
import urllib.error
import urllib.request
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

IMAGE_HOSTS = {"mmbiz.qpic.cn", "mmbiz.qlogo.cn", "get-notes.umiwi.com"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MARKDOWN_IMAGE = re.compile(
    r'!\[(?P<alt>[^\]\n]*)\]\(\s*(?:<(?P<wrapped>[^>\s]+)>|(?P<bare>[^()\s]+))'
    r'(?:[ \t]+(?:"[^"\n]*"|\'[^\'\n]*\'))?\s*\)'
)


def normalize_image_url(value, base_url=""):
    if not isinstance(value, str):
        return ""
    value = unescape(value).strip()
    if not value or any(char.isspace() or ord(char) < 32 for char in value):
        return ""
    if value.startswith("//"):
        value = "https:" + value
    try:
        parts = urlsplit(urljoin(base_url, value))
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return ""
        if parts.username is not None or parts.password is not None or parts.port is not None:
            return ""
    except ValueError:
        return ""
    return parts._replace(scheme="https", fragment="").geturl()


def add_html_image(images, attributes, base_url=""):
    alt = attributes.get("alt") or ""
    for attribute in ("data-src", "src"):
        url = normalize_image_url(attributes.get(attribute), base_url)
        if url:
            images.setdefault(url, {"url": url, "alt": alt})
            return


class ImageMarkup(HTMLParser):
    def __init__(self, images, base_url):
        super().__init__()
        self.images = images
        self.base_url = base_url

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            add_html_image(self.images, dict(attrs), self.base_url)


def note_images(markup, base_url=""):
    images = {}
    parser = ImageMarkup(images, base_url)
    cursor = 0
    for match in MARKDOWN_IMAGE.finditer(markup):
        # 按正文中的顺序收集 Markdown 图片及 HTML 图片。
        parser.feed(markup[cursor:match.start()])
        url = normalize_image_url(match["wrapped"] or match["bare"], base_url)
        if url:
            images.setdefault(url, {"url": url, "alt": unescape(match["alt"])})
        cursor = match.end()
    parser.feed(markup[cursor:])
    parser.close()
    return list(images.values())


def is_image_host(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "https" and parts.netloc.lower() in IMAGE_HOSTS


class ImageRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_image_host(newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def image_extension(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return ""


def fetch_image(url, folder, index, opener):
    url = normalize_image_url(url)
    if not is_image_host(url):
        return {"code": "UNSUPPORTED_IMAGE_HOST"}
    request = urllib.request.Request(url, headers={"Accept": "image/*"})
    try:
        with opener.open(request, timeout=15) as response:
            data = response.read(MAX_IMAGE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        return {"code": "IMAGE_HTTP_ERROR", "http_status": exc.code}
    except (OSError, http.client.HTTPException):
        return {"code": "IMAGE_NETWORK_ERROR"}
    if len(data) > MAX_IMAGE_BYTES:
        return {"code": "IMAGE_TOO_LARGE"}
    extension = image_extension(data)
    if not extension:
        return {"code": "UNSUPPORTED_IMAGE_FORMAT"}
    path = folder / f"image-{index}.{extension}"
    try:
        path.write_bytes(data)
    except OSError:
        return {"code": "IMAGE_LOCAL_ERROR"}
    return {"code": "OK", "path": str(path)}


def main():
    parser = argparse.ArgumentParser(description="下载选中的正文图片供本地视觉查看")
    parser.add_argument("urls", nargs="+", help="从文章结果的 images 字段选择图片 URL")
    args = parser.parse_args()
    folder = Path(tempfile.mkdtemp(prefix="wechat-article-images-")).resolve()
    opener = urllib.request.build_opener(ImageRedirect())
    results = [{"index": index, **fetch_image(url, folder, index, opener)}
               for index, url in enumerate(args.urls, 1)]
    print(json.dumps(results, ensure_ascii=False))
    return 0 if any(result["code"] == "OK" for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
