# 作为原子组件被调用

本 skill 的设计意图不是“一条流水线”，而是**流水线上的一个环节**。这份文档讲怎么把它接进别的流程。

---

## 为什么它适合被组合

| 特性 | 为什么重要 |
|---|---|
| **不碰像素** | 上游刚生成的图，交给它之后还是同一张图。这是能被信任的前提 |
| **结构化输出** | 调用方读 `report.json` 就能决策，不需要解析 stdout |
| **明确退出码** | shell 脚本、CI、其他 agent 都能判断成败 |
| **失败不发布** | 像素不一致、元数据残留、不可读输入都不会留下半成品 |
| **幂等** | 重复运行安全（默认后缀自动跳过） |
| **无业务路径耦合** | 核心脚本不含任何固定目录；投递规则放在 profile 里 |

---

## 退出码

| 码 | 含义 | 调用方该做什么 |
|---|---|---|
| `0` | 全部成功 | 继续下游 |
| `1` | 有文件失败、归档失败，或严格像素验证未通过 | 检查报告里的 `failed` / `archive_failed`，决定是否继续 |
| `2` | 依赖缺失（`remove-ai-watermarks` 未安装） | 提示安装，不要重试 |
| `3` | 参数或 profile 配置错误 | 修正参数/配置，不要重试 |

---

## 调用方式

### 直接处理一个目录

```bash
python3 scripts/strip.py ./generated -o ./ready -q
```

### 使用预设（固定投递 + 归档）

```bash
python3 scripts/strip.py --profile monthly-delivery -q
```

预设从 `<skill>/profiles/`、`~/.config/ai-metadata-strip-universal/profiles/` 或
`$AI_METADATA_STRIP_PROFILE_DIR` 查找。写预设见 [profiles.md](profiles.md)。

### 从 shell 脚本

```bash
#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="/path/to/ai-metadata-strip-universal"

if ! python3 "$SKILL_DIR/scripts/strip.py" ./generated -o ./ready -q; then
    echo "清洗失败，见 ./ready/report.json" >&2
    exit 1
fi

# 零退出码才继续
./publish.sh ./ready
```

### 从另一个 skill

```markdown
## 出图后的清洗

图片生成完成后，调用 ai-metadata-strip-universal 剥掉溯源标记：

    python3 <ai-metadata-strip-universal>/scripts/strip.py ./output -o ./output_clean -q

然后读 `./output_clean/report.json` 的 `summary.failed` 与
`summary.residual_failed`——任一非 0 就不要进入发布环节。

字段含义见 ai-metadata-strip-universal 的 references/report-schema.md。
```

### 从 Python

```python
import json
import subprocess
from pathlib import Path

def strip_metadata(src: Path, out: Path, skill_dir: Path) -> dict:
    """清洗并返回报告。失败时按退出码区分处理。"""
    proc = subprocess.run(
        ["python3", str(skill_dir / "scripts" / "strip.py"), str(src),
         "-o", str(out), "-q"],
        capture_output=True, text=True,
    )
    if proc.returncode == 2:
        raise RuntimeError("缺少核心引擎 remove-ai-watermarks：" + proc.stderr)
    if proc.returncode == 3:
        raise ValueError("strip.py 参数错误：" + proc.stderr)
    if proc.returncode == 1:
        # 有文件失败，但仍生成了报告——读它看是哪些
        pass
    return json.loads((out / "report.json").read_text(encoding="utf-8"))
```

### 从流水线门禁

```python
report = json.loads(Path("ready/report.json").read_text(encoding="utf-8"))
s = report["summary"]

assert s["pixels_mismatch"] == 0, "像素被改动，禁止发布"
assert s["residual_failed"] == 0, "元数据残留，禁止发布"
assert s["failed"] == 0, "有文件处理失败"

published = [
    f["dst"] for f in report["files"]
    if f["status"] in ("cleaned", "no_signal")
]
```

---

## 组合场景

### 配图生产流水线

```
配图 skill  →  ai-metadata-strip-universal  →  发布
```

配图 skill 生成完图，本 skill 清掉 C2PA/EXIF，然后发布。因为不碰像素，配图 skill 不需要担心返工。

### 素材库批处理

```
素材库（N 张）  →  ai-metadata-strip-universal  →  人工审核  →  发布
                 ↓
            report.json（溯源台账）
```

报告同时充当**溯源台账**——原始来源、标记类型都记着，将来要证明“这确实是 AI 生成的”时有据可查。

### 周期性固定投递

```
选片目录  →  ai-metadata-strip-universal --profile monthly  →  当月交付目录
                ↓                          ↓
           report.json              已处理/（原图归档）
```

预设把路径、按月分目录、已有成品复用、成功归档这些规则固化下来，定时任务只需要一条命令。

### 长链条串联

```
写文章 skill → 配图 skill → ai-metadata-strip-universal → 排版 skill → 发布 skill
```

链越长，“不碰像素”和“失败不发布”这两个约束越值钱。

---

## 并发与资源

- 默认并发 = CPU 核数，元数据剥离是纯文件 I/O，天然适合并行
- **历史实测**：137 张 1086×1448 的 PNG，**66.6 秒**（8 并发，引擎 0.40.1，含每文件 2 次进程启动）
- 每个文件要启动 2 次 `remove-ai-watermarks` 进程（identify + strip），这是主要瓶颈
- 大批量且不需要溯源记录时，加 `--no-identify` 可明显加速；此时状态记为 `processed`
- **内存**：无特殊要求。峰值取决于单张图解码，不随文件总数增长

---

## 与其他 skill 协作的注意事项

**1. 它不负责格式转换**

如果下游需要 JPEG 而非 PNG，在**本 skill 之后**做转换——反过来的话，转换工具可能引入新的元数据。

**2. 它不负责可见水印**

如果图片带可见角标，需要先用 `remove-ai-watermarks visible` 去角标，**再**用本 skill 清洗。
顺序反了不会出错（角标在像素上，不受影响），但先做可见水印更符合直觉。

**3. 报告要留住**

清洗后的图已经没有溯源信息了。如果业务需要“这张图的来源证明”，只能靠 `report.json`。
建议把报告一并归档，而不是只保留图片。

**4. 幂等性依赖清洗后缀**

下游若重命名或移动文件，后缀约定可能失效，导致重复处理。重复处理本身无害（结果一致），
但会浪费时间。用 `--suffix` 可对齐下游已有的命名规则。

**5. 严格流水线要打开像素门禁**

PIL 未安装时 `pixels_identical` 为 `null`，归档也不会执行。对“无损”有硬要求的流水线，
安装 PIL 并加 `--require-pixel-verification`，让无法验证直接失败。
