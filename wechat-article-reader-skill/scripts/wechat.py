"""从公开的微信文章页读取标题和正文。"""

from __future__ import annotations

import http.client
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlsplit

from article_images import add_html_image

HOST = "mp.weixin.qq.com"
MAX_PAGE_BYTES = 8 * 1024 * 1024
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
             "meta", "param", "source", "track", "wbr"}
BLOCK_TAGS = {"address", "article", "blockquote", "br", "div", "h1", "h2", "h3", "h4",
              "h5", "h6", "li", "p", "pre", "section", "tr"}
IGNORED_TAGS = {"script", "style", "template", "noscript", "svg"}


class WeChatRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != "https" or target.netloc.lower() != HOST:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ArticlePage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.body = []
        self.heading = []
        self.visible = []
        self.metadata_title = ""
        self.images = {}
        self.has_body_image = False
        self.body_closed = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get("id")
        inside, ignored, heading = self.stack[-1][1:4] if self.stack else (False, False, False)
        body_root = element_id == "js_content"
        inside = inside or body_root
        # 正文容器可能因微信前端的渲染流程带有属性。过滤脚本等独立元素。
        ignored = ignored or tag in IGNORED_TAGS
        heading = heading or element_id == "activity-name" or tag == "title"

        if tag == "meta" and attributes.get("property") == "og:title":
            self.metadata_title = attributes.get("content") or self.metadata_title
        if inside:
            if tag == "img" and not ignored:
                self.has_body_image = True
                add_html_image(self.images, attributes)
            if tag in BLOCK_TAGS and not ignored:
                self.body.append("\n")
        if tag not in VOID_TAGS:
            self.stack.append((tag, inside, ignored, heading, body_root))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] != tag:
                continue
            _, inside, ignored, _, body_root = self.stack[index]
            if inside and tag in BLOCK_TAGS and not ignored:
                self.body.append("\n")
            if body_root:
                self.body_closed = True
            del self.stack[index:]
            break

    def handle_data(self, data):
        inside, ignored, heading = self.stack[-1][1:4] if self.stack else (False, False, False)
        if ignored:
            return
        if heading:
            self.heading.append(data)
        if inside:
            self.body.append(data)
        else:
            self.visible.append(data)

    def result(self, final_url):
        visible = " ".join(" ".join(self.visible).split())
        path = urlsplit(final_url).path
        # 先识别有明确访问限制的页面，再判断是否有可用正文。
        if any(s in visible for s in ("付费后阅读", "付费后阅读全文", "购买后阅读", "剩余内容需付费")):
            return {"code": "PAID"}
        if path == "/mp/wappoc_appmsgcaptcha":
            return {"code": "BLOCKED"}
        text = "\n\n".join(line for raw in "".join(self.body).splitlines()
                            if (line := re.sub(r"[\t \u00a0]+", " ", raw).strip()))
        title = self.metadata_title or " ".join("".join(self.heading).split())
        images = list(self.images.values())
        if text and self.body_closed:
            return {"code": "OK", "title": title, "text": text, "images": images}
        notices = {
            "BLOCKED": ("环境异常", "访问过于频繁", "完成验证", "进行验证"),
            "DELETED": ("该内容已被发布者删除", "该内容已删除", "文章已被删除"),
            "PRIVATE": ("该内容仅限", "仅部分用户可见", "仅对指定用户可见", "无权查看"),
            "UNAVAILABLE": ("此内容因违规无法查看", "该内容无法查看", "此内容已被屏蔽"),
        }
        for code, markers in notices.items():
            if any(marker in visible for marker in markers):
                return {"code": code}
        if self.body_closed and self.has_body_image:
            return {"code": "IMAGE_ONLY", "title": title, "images": images}
        return {"code": "PARSE_FAILED"}


def read_article(url):
    opener = urllib.request.build_opener(WeChatRedirect())
    request = urllib.request.Request(url, headers={
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    })
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(MAX_PAGE_BYTES + 1)
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code in (403, 429):
            return {"code": "BLOCKED"}
        if exc.code == 401:
            return {"code": "PRIVATE"}
        if exc.code in (404, 410):
            return {"code": "UNAVAILABLE"}
        return {"code": "NETWORK", "http_status": exc.code}
    except (OSError, http.client.HTTPException):
        return {"code": "NETWORK"}

    if len(raw) > MAX_PAGE_BYTES:
        return {"code": "PARSE_FAILED", "message": "页面超过直读大小上限"}
    page = ArticlePage()
    page.feed(raw.decode("utf-8-sig", errors="replace"))
    page.close()
    return page.result(final_url)
