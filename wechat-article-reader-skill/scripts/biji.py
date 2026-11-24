"""得到大脑 OpenAPI 的剪藏、续查和原文读取。"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import socket
import sqlite3
import ssl
import time
import urllib.error
import urllib.request
from contextlib import closing
from dataclasses import dataclass
from urllib.parse import urlencode

from article_images import note_images

BASE_URL = "https://openapi.biji.com/open/api/v1/resource/note/"
POLL_INTERVAL = 10
REQUEST_TIMEOUT = 15
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
ERROR_CODES = {
    "10000": "BIJI_BAD_REQUEST",
    "10001": "BIJI_AUTH",
    "10100": "BIJI_NOT_FOUND",
    "10201": "BIJI_ACCOUNT_RESTRICTED",
    "10202": "BIJI_RATE_LIMITED",
    "42900": "BIJI_RATE_LIMITED",
}
ERROR_REASONS = {
    "qps_global": "BIJI_RATE_LIMITED",
    "qps_bucket": "BIJI_RATE_LIMITED",
    "quota_day": "BIJI_QUOTA_EXHAUSTED",
    "quota_month": "BIJI_QUOTA_EXHAUSTED",
    "not_member": "BIJI_ACCOUNT_RESTRICTED",
}


class BijiError(Exception):
    def __init__(self, code, *, rejected=False, request_id="", reason="", api_code=""):
        super().__init__(code)
        self.code = code
        self.rejected = rejected
        self.details = {k: v for k, v in {
            "request_id": request_id, "reason": reason, "api_code": api_code,
        }.items() if v}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 认证头只发送给固定的 OpenAPI 主机。
        return None


def as_object(value):
    return value if isinstance(value, dict) else {}


def safe_token(value):
    if type(value) is int:
        value = str(value)
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value):
        return value
    return ""


class BijiAPI:
    def __init__(self, path):
        try:
            with path.open(encoding="utf-8") as config_file:
                # 检查打开的文件本身，配置项只进入请求头。
                if os.fstat(config_file.fileno()).st_mode & 0o077:
                    raise BijiError("BIJI_CONFIG_PERMISSIONS")
                config = as_object(json.load(config_file))
        except FileNotFoundError as exc:
            raise BijiError("BIJI_CONFIG_MISSING") from exc
        except (OSError, ValueError) as exc:
            raise BijiError("BIJI_CONFIG_INVALID") from exc

        client_id = config.get("client_id")
        api_key = config.get("api_key")
        if client_id == "" or api_key == "":
            raise BijiError("BIJI_CONFIG_EMPTY")
        if not safe_token(client_id) or not isinstance(client_id, str):
            raise BijiError("BIJI_CONFIG_INVALID")
        if not isinstance(api_key, str) or not safe_token(api_key):
            raise BijiError("BIJI_CONFIG_INVALID")

        self.account = hashlib.sha256(client_id.encode()).hexdigest()
        self.headers = {"Authorization": api_key, "X-Client-ID": client_id}
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, endpoint, *, payload=None, timeout=REQUEST_TIMEOUT):
        headers = {"Accept": "application/json", **self.headers}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        request = urllib.request.Request(BASE_URL + endpoint, data=body, headers=headers)

        try:
            try:
                response = self.opener.open(request, timeout=timeout)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                status = response.code
                request_id = safe_token(response.headers.get("X-Request-ID"))
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.URLError as exc:
            # DNS 失败等在送出 HTTP 请求前发生，下一轮可以安全提交。
            rejected = isinstance(exc.reason, (
                socket.gaierror, ConnectionRefusedError, ssl.SSLCertVerificationError,
            ))
            raise BijiError("BIJI_NETWORK", rejected=rejected) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise BijiError("BIJI_NETWORK") from exc

        try:
            document = as_object(json.loads(raw)) if len(raw) <= MAX_RESPONSE_BYTES else {}
        except (UnicodeError, ValueError):
            document = {}
        error = as_object(document.get("error"))
        api_code = safe_token(error.get("code")) or safe_token(document.get("code"))
        reason = error.get("reason")
        reason = reason if isinstance(reason, str) and reason in ERROR_REASONS else ""
        request_id = safe_token(document.get("request_id")) or request_id

        if 200 <= status < 300 and document.get("success") is True:
            return as_object(document.get("data"))

        code = ERROR_REASONS.get(reason) or ERROR_CODES.get(api_code)
        if code is None:
            code = {401: "BIJI_AUTH", 403: "BIJI_AUTH", 429: "BIJI_RATE_LIMITED"}.get(
                status, "BIJI_API_ERROR",
            )
        # 服务端 5xx 或响应损坏时，无法确认是否已经创建。
        rejected = status in {401, 403, 429} or (
            status < 500 and code in {
                "BIJI_BAD_REQUEST", "BIJI_AUTH", "BIJI_ACCOUNT_RESTRICTED",
                "BIJI_RATE_LIMITED", "BIJI_QUOTA_EXHAUSTED",
            }
        )
        raise BijiError(
            code, rejected=rejected, request_id=request_id, reason=reason, api_code=api_code,
        )


class Operations:
    """SQLite 的唯一索引让同一应用、同一文章只有一个进程提交。"""

    def __init__(self, home, account, article_key):
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = home / "operations.sqlite3"
        self.key = (account, article_key)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS operations (
                    account TEXT NOT NULL, article TEXT NOT NULL,
                    phase TEXT NOT NULL, identifier TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (account, article)
                )
            """)

    def claim(self, *, resume):
        with closing(sqlite3.connect(self.path)) as db, db:
            if not resume:
                write = db.execute("""
                    INSERT INTO operations (account, article, phase) VALUES (?, ?, 'submitting')
                    ON CONFLICT (account, article) DO UPDATE SET phase = 'submitting'
                    WHERE operations.phase = 'rejected'
                """, self.key)
                if write.rowcount == 1:
                    return "new", ""
            return db.execute(
                "SELECT phase, identifier FROM operations WHERE account = ? AND article = ?",
                self.key,
            ).fetchone() or ("missing", "")

    def advance(self, current, phase, identifier=""):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""
                UPDATE operations SET phase = ?, identifier = ?
                WHERE account = ? AND article = ? AND phase = ?
            """, (phase, identifier, *self.key, current))


@dataclass
class Progress:
    task_id: str = ""
    note_id: str = ""

    def fields(self):
        return {k: v for k, v in vars(self).items() if v}


def string(value):
    return value.strip() if isinstance(value, str) else ""


def read_note(api, note_id):
    data = api.request("detail?" + urlencode({"id": note_id}))
    note = as_object(data.get("note"))
    if not note:
        raise BijiError("BIJI_RESPONSE_INVALID")

    page = as_object(note.get("web_page"))
    original = string(page.get("content"))
    summary = string(page.get("excerpt")) or string(note.get("content"))
    result = {"title": string(note.get("title"))}
    if original:
        return {"code": "OK", "text": original,
                "images": note_images(original, string(page.get("url"))), **result}
    if summary:
        return {"code": "SUMMARY_ONLY", "summary": summary, **result}
    return {"code": "BIJI_NO_ORIGINAL", **result}


def clip_article(api, store, url, *, resume, wait_seconds, clock=time.monotonic, sleep=time.sleep):
    progress = Progress()
    phase, identifier = store.claim(resume=resume)
    if phase == "submitting":
        return {"code": "BIJI_SUBMISSION_UNKNOWN"}
    if phase in {"rejected", "missing", "failed"}:
        return {"code": {
            "rejected": "BIJI_NO_TASK", "missing": "BIJI_NO_TASK", "failed": "BIJI_TASK_FAILED",
        }[phase], **({"task_id": identifier} if identifier else {})}

    try:
        if phase == "new":
            try:
                data = api.request("save", payload={"note_type": "link", "link_url": url})
            except BijiError as exc:
                if exc.rejected:
                    store.advance("submitting", "rejected")
                else:
                    return {"code": "BIJI_SUBMISSION_UNKNOWN", "cause": exc.code, **exc.details}
                raise
            tasks = data.get("tasks")
            task = as_object(tasks[0]) if isinstance(tasks, list) and tasks else {}
            progress.task_id = safe_token(task.get("task_id"))
            progress.note_id = safe_token(data.get("note_id"))
            if progress.note_id:
                store.advance("submitting", "note", progress.note_id)
            elif progress.task_id:
                store.advance("submitting", "task", progress.task_id)
            else:
                return {"code": "BIJI_SUBMISSION_UNKNOWN", "cause": "BIJI_RESPONSE_INVALID"}
        elif phase == "task":
            progress.task_id = identifier
        elif phase == "note":
            progress.note_id = identifier

        if not progress.note_id:
            deadline = clock() + wait_seconds
            while (remaining := deadline - clock()) > 0:
                task = api.request(
                    "task/progress", payload={"task_id": progress.task_id},
                    timeout=min(REQUEST_TIMEOUT, remaining),
                )
                status = task.get("status")
                if status == "success":
                    progress.note_id = safe_token(task.get("note_id"))
                    if not progress.note_id:
                        raise BijiError("BIJI_RESPONSE_INVALID")
                    store.advance("task", "note", progress.note_id)
                    break
                if status == "failed":
                    store.advance("task", "failed", progress.task_id)
                    return {"code": "BIJI_TASK_FAILED", **progress.fields()}
                if status not in ("pending", "processing"):
                    raise BijiError("BIJI_RESPONSE_INVALID")
                remaining = deadline - clock()
                if remaining <= POLL_INTERVAL:
                    break
                sleep(POLL_INTERVAL)
        if not progress.note_id:
            return {"code": "BIJI_PENDING", **progress.fields()}
        return {**read_note(api, progress.note_id), **progress.fields()}
    except BijiError as exc:
        return {"code": exc.code, **exc.details, **progress.fields()}
