#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai-metadata-strip-universal — 批量剥离 AI 生成图片的溯源标记（元数据层）

像素零改动。只处理文件容器层的标记：C2PA / EXIF / XMP / IPTC / TC260 等。
不处理像素级隐形水印（SynthID 等），不处理可见角标，不做压缩或转格式。

用法:
    python3 strip.py <源路径> -o <输出目录> [选项]
    python3 strip.py --profile <预设名或路径>

示例:
    python3 strip.py ./images -o ./images_clean
    python3 strip.py photo.png -o ./out --jobs 4
    python3 strip.py ./images -o ./clean --dry-run

依赖:
    外部命令 remove-ai-watermarks（核心引擎，推荐 0.47.0+）。
    脚本本身只用 Python 标准库；PIL 可选——装上则逐字节验证像素。
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------- 常量

TOOL_NAME = "ai-metadata-strip-universal"
VERSION = "1.0.0"
CLI_NAME = "remove-ai-watermarks"
DEFAULT_SUFFIX = "-c"
# 0.47.0 起引擎对不可读输入与残留标记 fail-closed，并先暂存输出再发布。
RECOMMENDED_ENGINE = "0.47.0"

SKILL_ROOT = Path(__file__).resolve().parent.parent
# 约定：<workspace>/skills/<skill> 或 <workspace>/<skill> 都取 workspace 根。
WORKSPACE_ROOT = (
    SKILL_ROOT.parent.parent if SKILL_ROOT.parent.name == "skills" else SKILL_ROOT.parent
)
PROFILE_DIRS = [
    SKILL_ROOT / "profiles",
    Path.home() / ".config" / "ai-metadata-strip-universal" / "profiles",
]

# 引擎 metadata 命令支持的图片扩展名。
IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".jpe", ".jfif",
    ".webp", ".heic", ".heif", ".avif", ".jxl", ".gif",
}
# 这些格式可以交给 PIL 做完整性校验；HEIF/AVIF/JXL 常缺解码插件，只做签名检查。
PIL_VERIFIABLE_EXTS = {".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".webp", ".gif"}

EXIT_OK = 0
EXIT_PARTIAL_FAILURE = 1
EXIT_MISSING_DEPENDENCY = 2
EXIT_USAGE = 3

INSTALL_HINT = """\
找不到命令 '{cli}'。

它是本 skill 的核心引擎，请先安装：

    curl -LsSf https://astral.sh/uv/install.sh | sh
    uv tool install --python 3.12 remove-ai-watermarks

装好后新开一个终端窗口，或先执行： source ~/.local/bin/env
""".format(cli=CLI_NAME)


class ConfigError(Exception):
    """参数或 profile 配置错误。"""


# ---------------------------------------------------------------- 引擎定位

def _exe_name() -> str:
    return CLI_NAME + (".exe" if os.name == "nt" else "")


def find_cli() -> Optional[str]:
    """定位 remove-ai-watermarks 可执行文件。

    依次尝试 PATH、uv tool 目录、pipx、Homebrew、/usr/local/bin 与 Windows
    Scripts 目录。不写死任何绝对路径，保证跨设备、跨 Agent 可用。
    """
    found = shutil.which(CLI_NAME)
    if found:
        return found

    exe = _exe_name()
    home = Path.home()
    candidates: List[Path] = [
        home / ".local" / "bin" / exe,
        home / ".local" / "share" / "uv" / "tools" / CLI_NAME / "bin" / exe,
        Path("/opt/homebrew/bin") / exe,
        Path("/usr/local/bin") / exe,
    ]
    for env_name in ("UV_TOOL_BIN_DIR", "PIPX_BIN_DIR"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(Path(value).expanduser() / exe)
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "Python" / "Scripts" / exe)
            candidates.append(Path(appdata) / "uv" / "tools" / CLI_NAME / "Scripts" / exe)
        candidates.append(home / "AppData" / "Roaming" / "Python" / "Scripts" / exe)
        candidates.append(home / "AppData" / "Roaming" / "uv" / "tools" / CLI_NAME / "Scripts" / exe)

    for cand in candidates:
        if cand.is_file() and os.access(str(cand), os.X_OK):
            return str(cand)
    return None


def run(cmd: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """执行外部命令。不用 shell，避免中文路径和特殊字符的转义问题。"""
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=timeout,
    )


def engine_version(cli: str) -> Optional[str]:
    """读取引擎版本号；失败返回 None。"""
    try:
        proc = run([cli, "--version"], timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return None
    text = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(r"(\d+\.\d+\.\d+)", text)
    return match.group(1) if match else None


def _version_tuple(value: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in value.split(".") if part.isdigit())


def _last_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else "unknown error"


# ---------------------------------------------------------------- profile

PROFILE_KEYS = {
    "profile_version",
    "name",
    "description",
    "source",
    "output",
    "report",
    "archive",
    "date_subdir",
    "existing",
    "suffix",
    "exclude",
    "jobs",
}
EXISTING_MODES = ("overwrite", "reuse", "skip")
# 用户未指定输出目录时的默认落点。
OUTPUT_MODES = ("sibling", "desktop", "downloads")


def resolve_profile_path(spec: str) -> Path:
    """把 profile 名解析成文件路径。

    支持直接给路径；否则依次搜索：
      1. $AI_METADATA_STRIP_PROFILE_DIR（可用 os.pathsep 分隔多个目录）
      2. <skill>/profiles/
      3. ~/.config/ai-metadata-strip-universal/profiles/
    """
    direct = Path(spec).expanduser()
    if direct.is_file():
        return direct.resolve()

    dirs: List[Path] = []
    env_dirs = os.environ.get("AI_METADATA_STRIP_PROFILE_DIR", "")
    for item in env_dirs.split(os.pathsep):
        if item.strip():
            dirs.append(Path(item).expanduser())
    dirs.extend(PROFILE_DIRS)

    filename = spec if spec.endswith(".json") else spec + ".json"
    searched: List[str] = []
    for directory in dirs:
        candidate = directory / filename
        searched.append(str(candidate))
        if candidate.is_file():
            return candidate.resolve()
    raise ConfigError(
        "找不到 profile '{spec}'。已搜索：\n  {paths}\n"
        "也可以直接传 profile 的 .json 路径。".format(
            spec=spec, paths="\n  ".join(searched)
        )
    )


def load_profile(spec: str) -> Tuple[Dict[str, Any], Path]:
    path = resolve_profile_path(spec)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError("读取 profile 失败 {}: {}".format(path, exc))
    if not isinstance(data, dict):
        raise ConfigError("profile 必须是 JSON 对象: {}".format(path))
    unknown = sorted(set(data) - PROFILE_KEYS)
    if unknown:
        raise ConfigError(
            "profile 含未知字段 {}: {}\n可用字段: {}".format(
                unknown, path, ", ".join(sorted(PROFILE_KEYS))
            )
        )
    if data.get("profile_version", 1) != 1:
        raise ConfigError("不支持的 profile_version: {}".format(data.get("profile_version")))
    for key in ("source", "output"):
        if key in data and (not isinstance(data[key], str) or not data[key]):
            raise ConfigError("profile.{} 必须是非空字符串: {}".format(key, path))
    for key in ("name", "description", "report", "archive", "date_subdir", "existing", "suffix"):
        if key in data and not isinstance(data[key], str):
            raise ConfigError("profile.{} 必须是字符串: {}".format(key, path))
    if "jobs" in data and (not isinstance(data["jobs"], int) or data["jobs"] < 0):
        raise ConfigError("profile.jobs 必须是非负整数: {}".format(path))
    if data.get("existing") and data["existing"] not in EXISTING_MODES:
        raise ConfigError("profile.existing 必须是 {} 之一".format("/".join(EXISTING_MODES)))
    if "exclude" in data and not (
        isinstance(data["exclude"], list) and all(isinstance(x, str) for x in data["exclude"])
    ):
        raise ConfigError("profile.exclude 必须是字符串数组")
    return data, path


def expand_template(value: str, base_dir: Optional[Path] = None) -> str:
    """展开 profile 里的路径模板。

    支持环境变量、${HOME}、${SKILL_ROOT}、${WORKSPACE_ROOT}、${PROFILE_DIR}、
    ${CWD}、${YYYY}/${MM}/${DD}/${YYYYMM}，以及 strftime 的 %Y%m 等写法。
    """
    now = datetime.now()
    text = os.path.expandvars(os.path.expanduser(str(value)))
    tokens = {
        "SKILL_ROOT": str(SKILL_ROOT),
        "WORKSPACE_ROOT": str(WORKSPACE_ROOT),
        "PROFILE_DIR": str(base_dir) if base_dir else "",
        "CWD": str(Path.cwd()),
        "YYYY": now.strftime("%Y"),
        "MM": now.strftime("%m"),
        "DD": now.strftime("%d"),
        "YYYYMM": now.strftime("%Y%m"),
    }
    for key, replacement in tokens.items():
        text = text.replace("${" + key + "}", replacement)
    try:
        text = now.strftime(text)
    except ValueError:
        pass
    return text


# ---------------------------------------------------------------- 单文件操作

def _looks_like_image(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            head = handle.read(16)
    except OSError:
        return False
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if head.startswith(b"\xff\xd8\xff"):
        return True
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return True
    if head[4:8] == b"ftyp":  # ISOBMFF: AVIF / HEIF / JXL
        return True
    if head.startswith((b"GIF87a", b"GIF89a")):
        return True
    return False


def unreadable_reason(path: Path) -> Optional[str]:
    """判断文件是否可读为受支持的图片。

    0.40.x 的引擎会把损坏文件原样复制并通过，必须由包装层提前拦截。
    """
    if not path.is_file():
        return "not a regular file"
    if not _looks_like_image(path):
        return "not a recognized image container"
    if path.suffix.lower() in PIL_VERIFIABLE_EXTS:
        try:
            from PIL import Image  # type: ignore
        except ImportError:
            return None
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception as exc:  # noqa: BLE001 — 损坏文件可能抛任意异常
            return "cannot decode image: {}".format(exc)
    return None


def identify(cli: str, path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """读取一张图的元数据层溯源状态。

    使用 --no-visible 只看元数据，避免把可见角标/像素水印误当成清洗残留。
    返回 (报告, 错误)；失败不抛异常，由调用方收敛成 failed。
    """
    try:
        proc = run([cli, "identify", str(path), "--no-visible", "--json"], timeout=120)
    except subprocess.TimeoutExpired:
        return None, "identify timeout"
    except OSError as exc:
        return None, "identify failed: {}".format(exc)
    if proc.returncode != 0:
        return None, "identify failed: {}".format(_last_line(proc.stderr or proc.stdout))
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None, "identify returned invalid JSON"
    if not isinstance(data, dict):
        return None, "identify returned unexpected JSON"
    return data, None


def summarize(report: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """把 identify 的输出压缩成报告里需要的字段，避免报告臃肿。"""
    if report is None:
        return None
    return {
        "is_ai_generated": report.get("is_ai_generated"),
        "platform": report.get("platform"),
        "confidence": report.get("confidence"),
        "ai_source_kind": report.get("ai_source_kind"),
        "markers": report.get("watermarks") or [],
    }


def has_metadata_signal(report: Optional[Dict[str, Any]]) -> bool:
    if not report:
        return False
    return bool(report.get("watermarks") or report.get("is_ai_generated"))


def strip_to_temp(cli: str, src: Path, dst: Path) -> Tuple[Optional[Path], Optional[str]]:
    """把剥离结果写到同目录临时文件。

    临时文件保留原扩展名（引擎按扩展名选路径），成功后再由调用方原子改名。
    这样失败时不会在交付目录留下半成品。
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(
        ".{}.ai-strip-{}{}".format(dst.stem, uuid.uuid4().hex[:8], dst.suffix)
    )
    try:
        proc = run([cli, "metadata", str(src), "--remove", "-o", str(tmp)])
    except subprocess.TimeoutExpired:
        _unlink(tmp)
        return None, "metadata strip timeout"
    except OSError as exc:
        _unlink(tmp)
        return None, "metadata strip failed: {}".format(exc)
    if proc.returncode != 0:
        message = _last_line(proc.stderr or proc.stdout)
        _unlink(tmp)
        return None, "metadata strip failed: {}".format(message)
    if not tmp.is_file():
        return None, "engine reported success but wrote no output"
    return tmp, None


def clean_name(path: Path, suffix: str = DEFAULT_SUFFIX) -> Path:
    """加上 / 保持清洗后缀。已带后缀的不重复添加，保证幂等。"""
    if path.stem.endswith(suffix):
        return path
    return path.with_name(path.stem + suffix + path.suffix)


def pixels_identical(a: Path, b: Path) -> Optional[bool]:
    """逐字节比对像素。返回 None 表示无法验证（PIL 未安装或解码失败）。"""
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return None
    try:
        with Image.open(a) as ia, Image.open(b) as ib:
            if ia.size != ib.size or ia.mode != ib.mode:
                return False
            return ia.tobytes() == ib.tobytes()
    except Exception:  # noqa: BLE001 — 解码失败视为无法验证
        return None


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------- 批处理

def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def collect_files(
    src: Path,
    excluded_dirs: Optional[List[Path]] = None,
    patterns: Optional[List[str]] = None,
) -> List[Path]:
    """收集所有图片。目录递归，文件则单个。

    不过滤清洗后缀文件——是否跳过交给 process_one 决定，报告才能如实记录
    “跳过了多少张”。默认排除输出目录、归档目录，以及 --exclude 通配符。
    """
    if src.is_file():
        return [src] if src.suffix.lower() in IMAGE_EXTS else []
    excluded = [directory.resolve() for directory in (excluded_dirs or []) if directory]
    pattern_list = patterns or []

    def is_excluded(path: Path) -> bool:
        resolved = path.resolve()
        for directory in excluded:
            if resolved == directory or directory in resolved.parents:
                return True
        if pattern_list:
            rel = path.relative_to(src).as_posix()
            name = path.name
            for pattern in pattern_list:
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern):
                    return True
        return False

    return sorted(
        path for path in src.rglob("*")
        if path.is_file()
        and path.suffix.lower() in IMAGE_EXTS
        and not is_excluded(path)
    )


def _new_entry(src: Path, src_root: Path, out_root: Path, suffix: str) -> Dict[str, Any]:
    rel = src.relative_to(src_root) if src != src_root else Path(src.name)
    dst = clean_name(out_root / rel, suffix)
    return {
        "src": str(rel),
        "dst": str(dst.relative_to(out_root)),
        "kind": "image",
        "status": "failed",
        "before": None,
        "after": None,
        "pixels_identical": None,
        "residual": None,
        "error": None,
        "_dst_path": dst,
        "_src_path": src,
    }


def _publish(entry: Dict[str, Any]) -> Dict[str, Any]:
    """把内部路径字段从报告条目里移除。"""
    return {key: value for key, value in entry.items() if not key.startswith("_")}


def _reuse_existing(
    cli: str,
    entry: Dict[str, Any],
    opts: Dict[str, Any],
) -> Dict[str, Any]:
    """复用已存在的输出，但必须先通过残留与像素验证。"""
    src = entry["_src_path"]
    dst = entry["_dst_path"]
    reason = unreadable_reason(dst)
    if reason:
        entry["error"] = "existing output is unreadable: {}".format(reason)
        return entry

    residual = False
    if opts["do_identify"]:
        after, err = identify(cli, dst)
        if after is None:
            entry["error"] = err or "existing output could not be verified"
            return entry
        entry["after"] = summarize(after)
        residual = has_metadata_signal(after)
        entry["residual"] = residual
        if residual:
            entry["error"] = "existing output still carries AI provenance markers"
            return entry
    if opts["do_verify_pixels"]:
        entry["pixels_identical"] = pixels_identical(src, dst)
        if entry["pixels_identical"] is False:
            entry["error"] = "existing output failed pixel verification"
            return entry

    entry["status"] = _success_status(entry, opts)
    entry["reused_existing_output"] = True
    return entry


def _success_status(entry: Dict[str, Any], opts: Dict[str, Any]) -> str:
    if not opts["do_identify"]:
        return "processed"
    return "cleaned" if has_metadata_signal(entry["before"]) else "no_signal"


def process_one(
    cli: str,
    src: Path,
    src_root: Path,
    out_root: Path,
    opts: Dict[str, Any],
) -> Dict[str, Any]:
    """处理单个文件。任何异常都收敛成 failed 状态，绝不中断整批。"""
    entry = _new_entry(src, src_root, out_root, opts["suffix"])
    dst = entry["_dst_path"]
    suffix = opts["suffix"]

    try:
        if src.stem.endswith(suffix) and not opts["include_cleaned"]:
            entry["status"] = "skipped"
            entry["error"] = "already carries the '{}' suffix".format(suffix)
            return entry

        if dst.resolve() == src.resolve():
            entry["error"] = "refusing to overwrite the source file"
            return entry

        if opts["existing"] == "skip" and dst.is_file():
            entry["status"] = "skipped"
            entry["error"] = "output already exists (--existing skip)"
            return entry

        reason = unreadable_reason(src)
        if reason:
            entry["error"] = "unreadable input: {}".format(reason)
            return entry

        if opts["do_identify"]:
            before, err = identify(cli, src)
            if before is None:
                entry["error"] = err or "identify failed"
                return entry
            entry["before"] = summarize(before)

        if opts["existing"] == "reuse" and dst.is_file():
            return _reuse_existing(cli, entry, opts)

        tmp, err = strip_to_temp(cli, src, dst)
        if tmp is None:
            entry["error"] = err
            return entry

        try:
            if opts["do_verify_pixels"]:
                entry["pixels_identical"] = pixels_identical(src, tmp)
                if entry["pixels_identical"] is False:
                    entry["error"] = "pixel verification failed; output not published"
                    return entry

            if opts["do_identify"]:
                after, err = identify(cli, tmp)
                if after is None:
                    entry["error"] = err or "post-strip identify failed"
                    return entry
                entry["after"] = summarize(after)
                entry["residual"] = has_metadata_signal(after)
                if entry["residual"]:
                    entry["error"] = "AI metadata survived: {}".format(
                        ", ".join(entry["after"].get("markers") or []) or "unknown marker"
                    )
                    return entry

            try:
                os.replace(str(tmp), str(dst))
                tmp = None
            except OSError as exc:
                entry["error"] = "cannot publish output: {}".format(exc)
                return entry

            entry["status"] = _success_status(entry, opts)
        finally:
            if tmp is not None:
                _unlink(tmp)

    except Exception as exc:  # noqa: BLE001 — 批处理必须容错
        entry["error"] = "{}: {}".format(type(exc).__name__, exc)

    return entry


def archive_successful_sources(
    results: List[Dict[str, Any]], src_root: Path, out_root: Path, archive_root: Path,
) -> int:
    """仅归档已输出且像素验证通过的源图，绝不覆盖已有归档。"""
    archive_failures = 0
    eligible = {"cleaned", "no_signal", "processed"}
    for entry in results:
        archive: Dict[str, Any] = {"status": "not_eligible", "path": None, "error": None}
        entry["archive"] = archive
        if entry["status"] not in eligible:
            continue
        destination = archive_root / entry["src"]
        try:
            archive["path"] = str(destination.relative_to(src_root))
        except ValueError:
            archive["path"] = str(destination)
        if entry["pixels_identical"] is not True:
            archive["error"] = "source retained because pixel verification did not pass"
            archive_failures += 1
            continue

        source = src_root / entry["src"]
        output = out_root / entry["dst"]
        if not source.is_file():
            archive["error"] = "source file no longer exists"
            archive_failures += 1
            continue
        if not output.is_file():
            archive["error"] = "cleaned output does not exist"
            archive_failures += 1
            continue
        if destination.exists():
            archive["error"] = "archive destination already exists; source retained"
            archive_failures += 1
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            archive["status"] = "moved"
        except Exception as exc:  # noqa: BLE001 — 归档失败不应隐藏
            archive["error"] = "{}: {}".format(type(exc).__name__, exc)
            archive_failures += 1
    return archive_failures


def build_report(
    results: List[Dict[str, Any]],
    src: Path,
    out: Path,
    *,
    engine: Dict[str, Any],
    profile: Optional[str],
    archive_failures: int,
    elapsed_seconds: float,
) -> Dict[str, Any]:
    summary = {
        "total": len(results),
        "cleaned": sum(1 for r in results if r["status"] == "cleaned"),
        "no_signal": sum(1 for r in results if r["status"] == "no_signal"),
        "processed": sum(1 for r in results if r["status"] == "processed"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "pixels_verified": sum(
            1 for r in results
            if r["status"] in ("cleaned", "no_signal", "processed")
            and r["pixels_identical"] is True
        ),
        "pixels_mismatch": sum(1 for r in results if r["pixels_identical"] is False),
        "pixels_unverified": sum(
            1 for r in results
            if r["status"] in ("cleaned", "no_signal", "processed")
            and r["pixels_identical"] is None
        ),
        "residual_failed": sum(
            1 for r in results if r["status"] == "failed" and r.get("residual") is True
        ),
        "archive_failed": archive_failures,
        "elapsed_seconds": round(elapsed_seconds, 2),
    }
    return {
        "tool": TOOL_NAME,
        "version": VERSION,
        "engine": engine,
        "profile": profile,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(src),
        "output": str(out),
        "summary": summary,
        "files": [_publish(r) for r in results],
    }


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".{}.tmp-{}".format(path.name, uuid.uuid4().hex[:8]))
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))
    finally:
        if tmp.exists():
            _unlink(tmp)


# ---------------------------------------------------------------- CLI

class _Parser(argparse.ArgumentParser):
    """参数错误用退出码 3，避免与“依赖缺失 2”混淆。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, "{}: error: {}\n".format(self.prog, message))


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        description="批量剥离 AI 生成图片的溯源标记（元数据层，像素零改动）",
        epilog=(
            "退出码:\n"
            "  0  全部成功\n"
            "  1  有文件失败/归档失败/像素未能验证（启用 --require-pixel-verification 时）\n"
            "  2  依赖缺失（未安装 remove-ai-watermarks）\n"
            "  3  参数或 profile 配置错误\n"
            "\n"
            "输出目录会生成 report.json，字段说明见 references/report-schema.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", nargs="?", help="源文件或目录（目录会递归处理）")
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "-o", "--output-dir", metavar="DIR",
        help="自定义输出目录（与 --output-to 二选一）",
    )
    output_group.add_argument(
        "--output-to", choices=OUTPUT_MODES,
        help="使用默认落点：sibling=输入目录下 cleaned/；desktop=桌面；downloads=下载",
    )
    parser.add_argument(
        "--output-name", metavar="NAME",
        help="与 --output-to 搭配，自定义新建文件夹名",
    )
    parser.add_argument(
        "--profile", metavar="NAME_OR_PATH",
        help="使用预设配置（名称或 .json 路径）；CLI 参数可覆盖预设",
    )
    parser.add_argument(
        "--archive-dir", metavar="DIR",
        help="成功后把源图移入该目录（需输出存在且像素验证通过；不覆盖同名文件）",
    )
    parser.add_argument(
        "--date-subdir", metavar="TEMPLATE",
        help="在输出目录下再按时间分子目录，如 %%Y%%m；支持 ${YYYYMM} 等占位符",
    )
    parser.add_argument(
        "--existing", choices=EXISTING_MODES,
        help="输出已存在时：overwrite（默认）/ reuse（验证后复用）/ skip",
    )
    parser.add_argument(
        "--suffix", metavar="TEXT",
        help="输出文件后缀，默认 {}（已带此后缀的源文件跳过）".format(DEFAULT_SUFFIX),
    )
    parser.add_argument(
        "--exclude", action="append", default=[], metavar="GLOB",
        help="跳过匹配的图片（相对源目录的路径或文件名，可重复）",
    )
    parser.add_argument(
        "-j", "--jobs", type=int, default=0,
        help="并发数，默认 = CPU 核数",
    )
    parser.add_argument(
        "--no-identify", action="store_true",
        help="跳过处理前后的溯源扫描（更快，报告无 before/after/residual）",
    )
    parser.add_argument(
        "--no-verify-pixels", action="store_true",
        help="跳过像素比对（需要 PIL；跳过时报告标注为 null）",
    )
    parser.add_argument(
        "--require-pixel-verification", action="store_true",
        help="像素无法验证（PIL 未安装/解码失败）时视为失败",
    )
    parser.add_argument(
        "--include-cleaned", action="store_true",
        help="连已带清洗后缀的文件一起处理（默认跳过，保证幂等）",
    )
    parser.add_argument("--report", metavar="PATH", help="报告路径（默认 <输出目录>/report.json）")
    parser.add_argument("--no-report", action="store_true", help="不生成报告")
    parser.add_argument("--dry-run", action="store_true", help="只列出将处理的文件，不写任何内容")
    parser.add_argument("--version", action="store_true", help="显示版本并退出")
    parser.add_argument("-q", "--quiet", action="store_true", help="只输出结果摘要")
    return parser


def _profile_value(
    args_value: Any, key: str, profile: Dict[str, Any], profile_dir: Optional[Path],
) -> Tuple[Any, Optional[Path]]:
    if args_value is not None:
        return args_value, None
    if key in profile:
        value = profile[key]
        if isinstance(value, str):
            return expand_template(value, profile_dir), profile_dir
        return value, profile_dir
    return None, None


def default_output_dir(mode: str, src: Path, name: Optional[str] = None) -> Path:
    """按用户选择的默认落点计算输出目录。

    sibling  : 目录输入 → <源目录>/cleaned/；文件输入 → <文件所在目录>/cleaned/
    desktop  : <HOME>/Desktop/<源名>-clean/
    downloads: <HOME>/Downloads/<源名>-clean/
    """
    if name is not None:
        if not name.strip() or name in (".", "..") or "/" in name or "\\" in name:
            raise ConfigError("--output-name 必须是非空的单层文件夹名")

    if mode == "sibling":
        base = src if src.is_dir() else src.parent
        return (base / (name or "cleaned")).resolve()

    home = Path.home()
    base = home / ("Desktop" if mode == "desktop" else "Downloads")
    if not base.is_dir():
        raise ConfigError(
            "找不到 {} 目录：{}。请改用 -o 指定输出目录。".format(
                "桌面" if mode == "desktop" else "下载", base
            )
        )
    default_name = (src.name if src.is_dir() else src.stem) + "-clean"
    return (base / (name or default_name)).resolve()


def build_config(args: argparse.Namespace) -> Dict[str, Any]:
    profile: Dict[str, Any] = {}
    profile_dir: Optional[Path] = None
    profile_name: Optional[str] = None

    if args.profile:
        profile, profile_path = load_profile(args.profile)
        profile_dir = profile_path.parent
        profile_name = profile.get("name") or args.profile

    source_value, source_base = _profile_value(args.source, "source", profile, profile_dir)
    if not source_value:
        raise ConfigError("缺少源路径（位置参数 source 或 profile.source）")
    if args.output_name and not args.output_to:
        raise ConfigError("--output-name 只能与 --output-to 一起使用")

    def to_path(value: Any, base: Optional[Path]) -> Path:
        path = Path(os.path.expanduser(str(value)))
        if not path.is_absolute():
            path = (base or Path.cwd()) / path
        return path.resolve()

    src = to_path(source_value, source_base)

    if args.output_to:
        out = default_output_dir(args.output_to, src, args.output_name)
    else:
        output_value, output_base = _profile_value(
            args.output_dir, "output", profile, profile_dir
        )
        if not output_value:
            raise ConfigError(
                "缺少输出目录。请选择：\n"
                "  -o <目录>                 自定义路径\n"
                "  --output-to sibling       输入目录下新建 cleaned/\n"
                "  --output-to desktop       Desktop/<名称>-clean\n"
                "  --output-to downloads     Downloads/<名称>-clean"
            )
        out = to_path(output_value, output_base)

    date_subdir = args.date_subdir
    if date_subdir is None:
        date_subdir = profile.get("date_subdir")
    if date_subdir:
        expanded_subdir = expand_template(str(date_subdir), profile_dir)
        # 允许 %Y/%m 这样的多级目录
        out = (out / expanded_subdir).resolve()

    report_arg, report_base = _profile_value(args.report, "report", profile, profile_dir)
    if args.no_report:
        report_path: Optional[Path] = None
    elif report_arg:
        report_path = to_path(report_arg, report_base)
    else:
        report_path = out / "report.json"

    archive_arg, archive_base = _profile_value(args.archive_dir, "archive", profile, profile_dir)
    archive_dir = to_path(archive_arg, archive_base) if archive_arg else None
    if archive_dir and archive_dir == out:
        raise ConfigError("归档目录不能等于输出目录")

    existing = args.existing or profile.get("existing") or "overwrite"
    if existing not in EXISTING_MODES:
        raise ConfigError("--existing 必须是 {} 之一".format("/".join(EXISTING_MODES)))

    suffix = args.suffix if args.suffix is not None else profile.get("suffix", DEFAULT_SUFFIX)
    if not suffix or "/" in suffix or "\\" in suffix:
        raise ConfigError("清洗后缀必须是非空、不含路径分隔符的字符串")

    exclude_patterns: List[str] = list(profile.get("exclude") or [])
    exclude_patterns.extend(args.exclude or [])

    jobs = args.jobs if args.jobs > 0 else int(profile.get("jobs") or 0)
    if jobs <= 0:
        jobs = os.cpu_count() or 4

    return {
        "src": src,
        "out": out,
        "report_path": report_path,
        "archive_dir": archive_dir,
        "existing": existing,
        "suffix": suffix,
        "exclude_patterns": exclude_patterns,
        "jobs": jobs,
        "profile": profile_name,
        "do_identify": not args.no_identify,
        "do_verify_pixels": not args.no_verify_pixels,
        "require_pixel_verification": args.require_pixel_verification,
        "include_cleaned": args.include_cleaned,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cli = find_cli()
    if args.version:
        print("{} {}".format(TOOL_NAME, VERSION))
        print("engine: {}".format(
            "{} ({})".format(engine_version(cli) or "unknown", cli) if cli else "not found"
        ))
        return EXIT_OK

    if cli is None:
        sys.stderr.write(INSTALL_HINT)
        return EXIT_MISSING_DEPENDENCY

    try:
        cfg = build_config(args)
    except ConfigError as exc:
        sys.stderr.write("配置错误: {}\n".format(exc))
        return EXIT_USAGE

    engine_ver = engine_version(cli)
    if (
        not args.quiet
        and engine_ver
        and _version_tuple(engine_ver) < _version_tuple(RECOMMENDED_ENGINE)
    ):
        sys.stderr.write(
            "提示: remove-ai-watermarks {} 低于推荐版本 {}；0.47.0 起才对不可读输入与"
            "残留标记 fail-closed。建议执行: uv tool upgrade remove-ai-watermarks\n".format(
                engine_ver, RECOMMENDED_ENGINE
            )
        )

    src: Path = cfg["src"]
    out: Path = cfg["out"]
    archive_dir: Optional[Path] = cfg["archive_dir"]

    if not src.exists():
        sys.stderr.write("源路径不存在: {}\n".format(src))
        return EXIT_PARTIAL_FAILURE

    src_root = src if src.is_dir() else src.parent

    excluded_dirs: List[Path] = []
    if archive_dir:
        excluded_dirs.append(archive_dir)
    if src.is_dir() and out != src and _is_within(out, src):
        excluded_dirs.append(out)

    files = collect_files(src, excluded_dirs, cfg["exclude_patterns"])
    if not files:
        sys.stderr.write("没有找到可处理的图片: {}\n".format(src))
        return EXIT_OK

    if args.dry_run:
        for path in files:
            rel = path.relative_to(src_root) if path != src_root else Path(path.name)
            dst = clean_name(out / rel, cfg["suffix"])
            print("{} -> {}".format(path, dst))
        print("dry-run: {} 个文件，未写入任何内容".format(len(files)))
        return EXIT_OK

    if not args.quiet:
        print("{} v{}".format(TOOL_NAME, VERSION))
        if cfg["profile"]:
            print("  预设    : {}".format(cfg["profile"]))
        print("  引擎    : {} {}".format(CLI_NAME, engine_ver or "unknown"))
        print("  源      : {}".format(src))
        print("  输出    : {}".format(out))
        if archive_dir:
            print("  归档    : {}".format(archive_dir))
        print("  文件数  : {}".format(len(files)))
        print("  并发    : {}".format(cfg["jobs"]))
        print("  已存在  : {}".format(cfg["existing"]))
        print()

    started = datetime.now()
    opts = {
        "do_identify": cfg["do_identify"],
        "do_verify_pixels": cfg["do_verify_pixels"],
        "include_cleaned": cfg["include_cleaned"],
        "existing": cfg["existing"],
        "suffix": cfg["suffix"],
    }

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=cfg["jobs"]) as pool:
        futures = {
            pool.submit(process_one, cli, file_path, src_root, out, opts): file_path
            for file_path in files
        }
        done = 0
        for future in as_completed(futures):
            results.append(future.result())
            done += 1
            if not args.quiet and done % 10 == 0:
                sys.stderr.write("\r  进度: {}/{}".format(done, len(files)))
                sys.stderr.flush()

    if not args.quiet:
        sys.stderr.write("\r" + " " * 30 + "\r")

    results.sort(key=lambda r: r["src"])
    archive_failures = 0
    if archive_dir:
        archive_failures = archive_successful_sources(results, src_root, out, archive_dir)

    elapsed = (datetime.now() - started).total_seconds()
    engine_info = {
        "name": CLI_NAME,
        "version": engine_ver,
        "path": cli,
        "recommended_version": RECOMMENDED_ENGINE,
    }
    report = build_report(
        results, src, out,
        engine=engine_info,
        profile=cfg["profile"],
        archive_failures=archive_failures,
        elapsed_seconds=elapsed,
    )

    if cfg["report_path"] is not None:
        try:
            write_json_atomic(cfg["report_path"], report)
        except OSError as exc:
            sys.stderr.write("写入报告失败 {}: {}\n".format(cfg["report_path"], exc))
            return EXIT_PARTIAL_FAILURE
        if not args.quiet:
            print("报告: {}".format(cfg["report_path"]))

    summary = report["summary"]
    print(
        "完成: 清除 {cleaned} / 无标记 {no_signal} / 已处理 {processed} / "
        "失败 {failed} / 跳过 {skipped}".format(**summary)
    )
    if summary["pixels_verified"]:
        print("像素验证: {} 张逐字节一致".format(summary["pixels_verified"]))
    if summary["pixels_unverified"]:
        print("像素未验证: {} 张（PIL 未安装或无法解码）".format(summary["pixels_unverified"]))
    if summary["pixels_mismatch"]:
        print("⚠️  像素不一致: {} 张（输出未发布）".format(summary["pixels_mismatch"]))
    if summary["residual_failed"]:
        print("⚠️  残留标记: {} 张（输出未发布）".format(summary["residual_failed"]))
    if summary["archive_failed"]:
        print("⚠️  归档失败: {} 张（原图保留在源目录）".format(summary["archive_failed"]))

    if summary["failed"] or summary["archive_failed"]:
        return EXIT_PARTIAL_FAILURE
    if cfg["require_pixel_verification"] and summary["pixels_unverified"]:
        return EXIT_PARTIAL_FAILURE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
