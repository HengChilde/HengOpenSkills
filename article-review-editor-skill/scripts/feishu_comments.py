#!/usr/bin/env python3
"""用官方飞书 CLI 读取文档，并按内容块写入审阅批注。"""

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

LEVELS = {"必须修正", "建议调整", "可选增强"}


def cli(*args, stdin=None):
    result = subprocess.run(
        ["lark-cli", *args], input=stdin, capture_output=True, text=True,
        encoding="utf-8", timeout=45, check=False,
    )
    if result.returncode:
        try:
            error = json.loads(result.stderr or result.stdout)["error"]
            message = error.get("message") or error.get("type")
        except (ValueError, KeyError, TypeError, AttributeError):
            message = None
        raise ValueError(f"CLI 退出码 {result.returncode}：{str(message or '无结构化错误信息')[:300]}")
    response = json.loads(result.stdout)
    if response.get("ok") is not True:
        raise ValueError("CLI 未返回成功回执")
    return response


class BlockIds(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.ids = set()
        self.feed(content)
        self.close()

    def handle_starttag(self, tag, attrs):
        # DocxXML 的 id 标识内容块，block-id 也可用于兼容显式块标识。
        if tag not in {"comment", "fragment", "excerpt"}:
            self.ids.update(value for key, value in attrs if key in {"id", "block-id"} and value)


def fetch(args):
    url = urlsplit(args.doc)
    if url.scheme != "https" or not url.hostname or url.username or url.password or not (
        url.path.startswith(("/docx/", "/wiki/"))
    ):
        raise ValueError("请提供新版飞书文档或指向新版文档的知识库 HTTPS 链接")
    response = cli("docs", "+fetch", "--doc", url._replace(fragment="").geturl(),
                   "--detail", "with-ids", "--doc-format", "xml", "--as", args.identity)
    doc = response["data"]["document"]
    token, content = doc["document_id"], doc["content"]
    if response.get("identity") != args.identity or not isinstance(token, str) or not token.strip():
        raise ValueError("读稿未返回可复用的文档 ID 或调用身份")
    if not isinstance(content, str) or not BlockIds(content).ids:
        raise ValueError("正文没有可用于批注的块 ID")
    # 快照只保存定位所需内容，不把评论侧栏和大段响应元数据送进会话。
    with args.snapshot.open("x", encoding="utf-8") as out:
        json.dump({"document_id": token, "identity": args.identity, "content": content},
                  out, ensure_ascii=False)
    print(content)
    if doc.get("tips"):
        print(doc["tips"], file=sys.stderr)
    return 0


def plan_items(path, ids):
    plan = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(plan, list):
        raise TypeError("批注清单必须是 JSON 数组")
    items = []
    for number, item in enumerate(plan, 1):
        if not isinstance(item, dict):
            raise TypeError(f"第 {number} 条必须是对象")
        block, level, comment = (item.get(key) for key in ("block_id", "level", "text"))
        if not isinstance(block, str) or block not in ids:
            raise ValueError(f"第 {number} 条的块 ID 不在读稿快照中")
        if not isinstance(level, str) or level not in LEVELS:
            raise ValueError(f"第 {number} 条的批注层级无效")
        if not isinstance(comment, str) or not comment.strip():
            raise ValueError(f"第 {number} 条的批注内容为空")
        body = f"【{level}】{comment.strip()}"
        if len(body) > 1000:
            raise ValueError(f"第 {number} 条的批注超过 1000 字符")
        items.append((block, body))
    return items


def comment_key(token, identity, block, body):
    key_data = json.dumps([token, identity, block, body], ensure_ascii=False)
    return hashlib.sha256(key_data.encode()).hexdigest()


def receipt_path(snapshot):
    return snapshot.with_suffix(snapshot.suffix + ".receipts.jsonl")


def write_receipt(journal, key, comment_id=None, retry=False):
    entry = {"key": key, "comment_id": comment_id}
    if retry:
        entry["retry"] = True
    journal.write(json.dumps(entry, ensure_ascii=False) + "\n")
    journal.flush()
    os.fsync(journal.fileno())


def read_receipts(journal):
    """读取回执并返回每个 key 的最新状态；损坏或冲突的记录直接拒绝。"""
    receipts = {}
    for number, line in enumerate(journal, 1):
        # 末行缺少换行可能是写入中断；继续追加会把两条回执拼成一行。
        if not line.endswith("\n"):
            raise ValueError(f"回执第 {number} 行不完整，已停止，请人工核对")
        if not line.strip():
            raise ValueError(f"回执第 {number} 行为空，已停止，请人工核对")
        try:
            entry = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"回执第 {number} 行不是有效 JSON：{exc}") from None
        if not isinstance(entry, dict):
            raise TypeError(f"回执第 {number} 行必须是对象")
        if set(entry) - {"key", "comment_id", "retry"}:
            raise ValueError(f"回执第 {number} 行包含未知字段")
        key = entry.get("key")
        if not isinstance(key, str) or not key:
            raise ValueError(f"回执第 {number} 行缺少有效批注 key")
        comment_id = entry.get("comment_id")
        if comment_id is not None and (
                not isinstance(comment_id, str) or not comment_id.strip()):
            raise ValueError(f"回执第 {number} 行的评论 ID 无效")
        retry = entry.get("retry")
        if "retry" in entry and retry is not True:
            raise ValueError(f"回执第 {number} 行的重试标记无效")
        if "comment_id" not in entry:
            raise ValueError(f"回执第 {number} 行没有记录状态")
        if comment_id and retry:
            raise ValueError(f"回执第 {number} 行同时包含评论 ID 和重试标记")
        comment_id = comment_id.strip() if isinstance(comment_id, str) else None
        previous = receipts.get(key)
        if retry and (not previous or previous["comment_id"] or previous["retry"]):
            raise ValueError(f"回执第 {number} 行没有对应的待确认记录")
        if previous and previous["comment_id"]:
            # 已确认是终态，不能被待确认或不同评论 ID 覆盖，避免重复发送。
            if comment_id != previous["comment_id"]:
                raise ValueError(f"回执第 {number} 行与已确认记录冲突")
            continue
        receipts[key] = {"comment_id": comment_id, "retry": retry is True}
    return receipts


def load_context(snapshot_path, plan_path):
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    token, identity, content = (
        snapshot.get(key) for key in ("document_id", "identity", "content"))
    if identity not in ("user", "bot") or not isinstance(token, str) or not token.strip():
        raise ValueError("读稿快照缺少有效的文档 ID 或调用身份")
    if not isinstance(content, str):
        raise TypeError("读稿快照缺少正文内容")
    return token, identity, plan_items(plan_path, BlockIds(content).ids)


def lock_journal(journal):
    try:
        fcntl.flock(journal.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise ValueError("同一快照已有另一个写入进程，请稍后重试") from None


def post(args):
    token, identity, items = load_context(args.snapshot, args.plan)
    if not args.apply or not items:
        print(json.dumps({"mode": "apply" if args.apply else "preview", "count": len(items)}))
        return 0

    with receipt_path(args.snapshot).open("a+", encoding="utf-8") as journal:
        # 同一快照只允许一个进程写入。发请求前落盘，避免中断后盲目重发。
        lock_journal(journal)
        journal.seek(0)
        receipts = read_receipts(journal)

        posted, skipped = 0, 0
        for number, (block, body) in enumerate(items, 1):
            key = comment_key(token, identity, block, body)
            state = receipts.get(key)
            if state and state["comment_id"]:
                skipped += 1
                continue
            if state and not state["retry"]:
                error = "这条批注之前的写入状态未确认，请先在飞书核对并用 resolve 记录结果"
            else:
                # 首次发送或消耗一次重试许可：先落新的待确认回执。
                write_receipt(journal, key)
                receipts[key] = {"comment_id": None, "retry": False}
                try:
                    result = cli("drive", "+add-comment", "--doc", token, "--type", "docx",
                                 "--block-id", block, "--content", "-", "--as", identity,
                                 stdin=json.dumps([{"type": "text", "text": body}], ensure_ascii=False))
                    try:
                        comment_id = result["data"]["comment_id"]
                    except (KeyError, TypeError):
                        comment_id = None
                    if not isinstance(comment_id, str) or not comment_id.strip():
                        raise ValueError("成功回执缺少评论 ID")
                    comment_id = comment_id.strip()
                    write_receipt(journal, key, comment_id)
                    receipts[key] = {"comment_id": comment_id, "retry": False}
                    posted += 1
                    continue
                except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError, AttributeError) as exc:
                    error = str(exc) if not isinstance(exc, subprocess.TimeoutExpired) else "CLI 请求超时"
            print(json.dumps({"posted": posted, "skipped": skipped, "check_item": number,
                              "unattempted": len(items) - number, "error": error,
                              "key": key}, ensure_ascii=False))
            return 1
    print(json.dumps({"posted": posted, "skipped": skipped}))
    return 0


def resolve(args):
    token, identity, items = load_context(args.snapshot, args.plan)
    key = args.key
    number = next((
        number
        for number, (block, body) in enumerate(items, 1)
        if comment_key(token, identity, block, body) == key
    ), None)
    if number is None:
        raise ValueError("该 key 不在当前批注清单中")

    path = receipt_path(args.snapshot)
    if not path.exists():
        raise ValueError("尚无回执记录，不能恢复")
    with path.open("a+", encoding="utf-8") as journal:
        # 与 post 共用同一把锁；恢复只追加本地回执，绝不访问飞书。
        lock_journal(journal)
        journal.seek(0)
        receipts = read_receipts(journal)
        state = receipts.get(key)
        if state is None:
            raise ValueError("该批注没有待确认记录，不能恢复")
        if state["comment_id"]:
            raise ValueError("该批注已确认写入，不能恢复")
        if args.comment_id is not None:
            comment_id = args.comment_id.strip()
            if not comment_id:
                raise ValueError("评论 ID 不能为空")
            write_receipt(journal, key, comment_id)
            print(json.dumps({"resolved": "confirmed", "key": key, "line": number,
                              "comment_id": comment_id}, ensure_ascii=False))
        elif args.retry:
            if state["retry"]:
                raise ValueError("该批注已允许重试，等待 post 执行")
            write_receipt(journal, key, retry=True)
            print(json.dumps({"resolved": "retry", "key": key, "line": number},
                             ensure_ascii=False))
        else:
            raise ValueError("请使用 --comment-id 或 --retry 指定恢复方式")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    read = commands.add_parser("read", help="读取带块 ID 的正文并保存快照")
    read.add_argument("--doc", required=True)
    read.add_argument("--snapshot", required=True, type=Path)
    read.add_argument("--identity", choices=("user", "bot"), default="user")
    read.set_defaults(run=fetch)
    write = commands.add_parser("post", help="校验清单或提交段落批注")
    write.add_argument("--snapshot", required=True, type=Path)
    write.add_argument("--plan", required=True, type=Path)
    write.add_argument("--apply", action="store_true", help="实际写入飞书，省略时仅作本地校验")
    write.set_defaults(run=post)
    recover = commands.add_parser("resolve", help="在本地记录待确认批注的核对结果")
    recover.add_argument("--snapshot", required=True, type=Path)
    recover.add_argument("--plan", required=True, type=Path)
    recover.add_argument("--key", required=True, help="post 错误回执中的批注 key")
    choice = recover.add_mutually_exclusive_group(required=True)
    choice.add_argument("--comment-id", help="已在飞书确认存在时填写评论 ID")
    choice.add_argument("--retry", action="store_true", help="已核对未写入时允许下次 post 重试")
    recover.set_defaults(run=resolve)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        return args.run(args)
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError, AttributeError) as exc:
        message = "CLI 请求超时" if isinstance(exc, subprocess.TimeoutExpired) else str(exc)
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
