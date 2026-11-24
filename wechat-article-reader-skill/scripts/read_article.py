"""优先读取微信正文，并通过得到大脑补齐直读故障。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from biji import BijiAPI, BijiError, Operations, clip_article
from wechat import HOST, read_article

SKILL_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = SKILL_DIR / ".local" / "biji.json"
CONFIG_TEMPLATE = SKILL_DIR / "references" / "biji.example.json"
FALLBACK_CODES = {"BLOCKED", "NETWORK", "PARSE_FAILED"}
INLINE_LIMIT = 6000


def article_link(value):
    url = value.strip()
    if any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError("链接包含空白")
    parts = urlsplit(url)
    if parts.netloc.lower() != HOST or parts.scheme != "https":
        raise ValueError("请提供 HTTPS 公众号文章链接")
    if re.fullmatch(r"/s/[A-Za-z0-9_-]+/?", parts.path):
        key = parts.path.rstrip("/")
    elif parts.path == "/s":
        query = parse_qs(parts.query)
        if not query.get("__biz") or not query.get("mid"):
            raise ValueError("缺少微信文章定位参数")
        key = "/s?" + urlencode([
            (k, query[k][0]) for k in ("__biz", "mid", "idx") if query.get(k)
        ])
    else:
        raise ValueError("请提供公众号文章页链接")
    return url, key


def present_article(result, folder):
    if result["code"] != "OK":
        return result
    text = result["text"]
    if len(text) <= INLINE_LIMIT:
        return {**result, "truncated": False, "char_count": len(text)}

    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest = hashlib.sha256(text.encode()).hexdigest()
    path = folder / (digest + ".md")
    # 先完整写入临时文件，再原子替换，其他进程始终读取完整正文。
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder,
                                     delete=False) as output:
        output.write(text)
    os.replace(output.name, path)
    return {**result, "text": text[:1200], "truncated": True,
            "md_path": str(path), "char_count": len(text)}


def init_config(path):
    """在安装目录准备空白配置，不打开或覆盖已经存在的凭据。"""
    result = {"config_path": str(path)}
    try:
        template = CONFIG_TEMPLATE.read_bytes()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
            file.write(template)
    except FileExistsError:
        return {"code": "BIJI_CONFIG_EXISTS", **result}
    except OSError:
        return {"code": "BIJI_CONFIG_INIT_ERROR", **result}
    return {"code": "BIJI_CONFIG_CREATED", **result}


def config_result(exc, path):
    result = {"code": exc.code, **exc.details}
    if exc.code.startswith("BIJI_CONFIG_"):
        result["config_path"] = str(path)
    return result


def check_connection(path):
    """用只读接口验证鉴权和读取权限，输出仅包含检查状态。"""
    try:
        BijiAPI(path).request("list")
    except BijiError as exc:
        return config_result(exc, path)
    return {"code": "BIJI_CONNECTION_OK"}


def run(url, key, home, *, config_path=CONFIG_PATH, direct_only=False, resume=False, wait_seconds=90):
    direct = {} if resume else read_article(url)
    if not resume and (direct_only or direct["code"] not in FALLBACK_CODES):
        result = {**direct, "source": "wechat", "source_url": url}
        try:
            return present_article(result, home / "articles" / "wechat")
        except OSError:
            return {"code": "LOCAL_STATE_ERROR", "source": "wechat", "source_url": url}

    result = {"source": "biji", "source_url": url, "direct_code": direct.get("code")}
    try:
        api = BijiAPI(config_path)
        store = Operations(home, api.account, key)
        result.update(clip_article(
            api, store, url, resume=resume, wait_seconds=wait_seconds,
        ))
        return present_article(result, home / "articles" / api.account)
    except BijiError as exc:
        result.update(config_result(exc, config_path))
    except (OSError, sqlite3.Error):
        result.pop("text", None)
        result.update(code="LOCAL_STATE_ERROR")
    return result


def main():
    parser = argparse.ArgumentParser(description="读取公众号文章，微信直读失败时使用得到大脑")
    parser.add_argument("url", nargs="?", help="微信公众号文章链接")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--init", action="store_true", help="在本 Skill 目录准备首次启用的空白配置")
    mode.add_argument("--check-connection", action="store_true", help="验证得到大脑配置和读取权限")
    mode.add_argument("--direct-only", action="store_true", help="只读取微信原链接")
    mode.add_argument("--resume", action="store_true", help="只续查本地记录的得到大脑任务或笔记")
    parser.add_argument("--wait-seconds", type=int, default=90, metavar="SECONDS",
                        help="异步任务轮询预算，0 表示提交后立即返回任务 ID（默认 90 秒）")
    args = parser.parse_args()
    if args.init or args.check_connection:
        if args.url is not None:
            parser.error("--init 和 --check-connection 无需文章链接")
        result = init_config(CONFIG_PATH) if args.init else check_connection(CONFIG_PATH)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["code"] in {
            "BIJI_CONFIG_CREATED", "BIJI_CONFIG_EXISTS", "BIJI_CONNECTION_OK",
        } else 2
    if args.url is None:
        parser.error("请提供微信公众号文章链接，或使用 --init / --check-connection")
    if not 0 <= args.wait_seconds <= 600:
        parser.error("--wait-seconds 须介于 0 和 600")

    try:
        url, key = article_link(args.url)
    except ValueError:
        result = {"code": "BAD_LINK", "message": "请提供公开的 HTTPS 微信公众号文章链接"}
    else:
        os.umask(0o077)
        home = Path(os.environ.get("WECHAT_BIJI_READER_HOME", SKILL_DIR / ".local"))
        result = run(url, key, home.expanduser().resolve(), direct_only=args.direct_only,
                     resume=args.resume, wait_seconds=args.wait_seconds)

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["code"] == "OK" else 2


if __name__ == "__main__":
    sys.exit(main())
