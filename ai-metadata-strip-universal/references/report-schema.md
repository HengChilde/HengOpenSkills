# report.json 结构与消费方式

脚本默认在输出目录生成 `report.json`。这份文件是**下游消费本 skill 结果的唯一接口**。

---

## 完整结构

```json
{
  "tool": "ai-metadata-strip-universal",
  "version": "1.0.0",
  "engine": {
    "name": "remove-ai-watermarks",
    "version": "0.47.0",
    "path": "/path/to/remove-ai-watermarks",
    "recommended_version": "0.47.0"
  },
  "profile": "monthly-delivery",
  "generated_at": "2026-10-20T15:31:41.902+00:00",
  "source": "/path/to/images",
  "output": "/path/to/images_clean",
  "summary": {
    "total": 137,
    "cleaned": 135,
    "no_signal": 2,
    "processed": 0,
    "failed": 0,
    "skipped": 0,
    "pixels_verified": 137,
    "pixels_mismatch": 0,
    "pixels_unverified": 0,
    "residual_failed": 0,
    "archive_failed": 0,
    "elapsed_seconds": 28.4
  },
  "files": [
    {
      "src": "images/a.png",
      "dst": "images/a-c.png",
      "kind": "image",
      "status": "cleaned",
      "before": {
        "is_ai_generated": true,
        "platform": "OpenAI (ChatGPT / GPT Image / DALL·E / Sora)",
        "confidence": "high",
        "ai_source_kind": "generated",
        "markers": [
          "C2PA Content Credentials (OpenAI)",
          "SynthID watermark (present according to OpenAI provenance)"
        ]
      },
      "after": {
        "is_ai_generated": null,
        "platform": null,
        "confidence": "none",
        "ai_source_kind": null,
        "markers": []
      },
      "pixels_identical": true,
      "residual": false,
      "archive": { "status": "moved", "path": "已处理/a.png", "error": null },
      "error": null
    }
  ]
}
```

---

## 顶层字段

| 字段 | 含义 |
|---|---|
| `tool` / `version` | 本 skill 的名称与版本 |
| `engine` | 实际调用的 `remove-ai-watermarks` 版本、路径与推荐版本 |
| `profile` | 使用的预设名；未使用预设时为 `null` |
| `generated_at` | UTC 时间戳 |
| `source` / `output` | 本次运行的源与输出绝对路径 |
| `summary` | 聚合计数 |
| `files` | 逐文件明细 |

---

## summary 字段

| 字段 | 含义 |
|---|---|
| `total` | 收集到的图片总数（含跳过的） |
| `cleaned` | 原有 AI 元数据标记、已清除并发布 |
| `no_signal` | 本来就没检测到 AI 元数据（文件照常输出） |
| `processed` | 跳过了溯源扫描（`--no-identify`），无法判断原来是否有标记 |
| `failed` | 处理失败、像素不一致、残留标记或输出不可发布 |
| `skipped` | 已带清洗后缀，或 `--existing skip` 命中已有输出 |
| `pixels_verified` | 已发布文件中逐字节验证通过的数量 |
| `pixels_mismatch` | **像素不一致的数量——非 0 即为异常，应当中断流水线** |
| `pixels_unverified` | 已发布但无法验证像素的数量（PIL 未安装或解码失败） |
| `residual_failed` | 因输出仍含 AI 元数据而失败的数量 |
| `archive_failed` | 未能归档的数量；非 0 时原图仍保留在源目录 |
| `elapsed_seconds` | 墙钟耗时 |

---

## files[].status 取值

| 值 | 含义 | 输出目录里有文件吗 |
|---|---|---|
| `cleaned` | 原有 AI 标记，已清除 | ✅ |
| `no_signal` | 本来就没有 AI 标记 | ✅（照常输出，保证目录完整） |
| `processed` | 用了 `--no-identify`，只保证引擎执行成功 | ✅ |
| `skipped` | 已带后缀，或 `--existing skip` 命中已有输出 | ❌ |
| `failed` | 处理/验证失败，原因见 `error` | ❌（原子发布保证） |

下游成功集合应为 `cleaned` + `no_signal`；只有明确接受“未做溯源扫描”时才加入 `processed`。

---

## before / after

`before` 是处理前 `identify --no-visible` 的结果摘要，`after` 是处理后的。
`--no-visible` 表示只看元数据层，不受可见角标与像素水印干扰。

| 子字段 | 含义 |
|---|---|
| `is_ai_generated` | `true` / `null`（引擎从不断言 `false`） |
| `platform` | 归因到的平台或标签体系 |
| `confidence` | `high` / `medium` / `none` |
| `ai_source_kind` | `generated`（全合成）/ `enhanced`（真实照片上的 AI 编辑）/ `null` |
| `markers` | 具体标记名称列表 |

**`before` 为什么必须保留**：原图的 C2PA 被清掉了，但“这张是 OpenAI 生成的、带 SynthID”
这个事实记在这里。将来如果需要证明来源（平台合规披露、内部审计、权利说明），
**这是唯一的依据**。清洗后工具自己也无法再检测，所以这份报告别删。

`after.is_ai_generated` 通常为 `null`（没有任何信号了），这正是清洗成功的标志。
用 `--no-identify` 运行时，`before`、`after`、`residual` 都为 `null`。

---

## pixels_identical / residual

| 字段 | 值 | 含义 |
|---|---|---|
| `pixels_identical` | `true` | 逐字节验证通过 |
| | `false` | **像素不一致——异常，输出未发布** |
| | `null` | 无法验证（PIL 未安装、该文件被跳过/失败） |
| `residual` | `true` | 剥离后仍检测到 AI 元数据——异常，输出未发布 |
| | `false` | 剥离后未检测到元数据标记 |
| | `null` | 未做复检（`--no-identify` 或文件失败） |

---

## files[].archive

只有启用 `--archive-dir` 或 profile 里的 `archive` 时才有这个字段：

| `archive.status` | 含义 |
|---|---|
| `moved` | 源图已移入归档目录 |
| `not_eligible` | 状态不符、像素未验证通过、输出缺失或目标已存在；源图保留 |

`archive.path` 是相对源目录的归档目标路径。`archive.error` 记录不移动的具体原因。

---

## 下游消费示例

### 作为流水线的门禁

```python
import json

report = json.load(open("./images_clean/report.json"))
s = report["summary"]

# 完整性门禁：像素被动过就中断
if s["pixels_mismatch"] > 0:
    raise RuntimeError(f"像素校验失败 {s['pixels_mismatch']} 张，流水线中断")

# 残留门禁：清洗没清干净就中断
if s["residual_failed"] > 0:
    raise RuntimeError(f"{s['residual_failed']} 张仍有 AI 元数据残留")

# 成功率门禁
if s["failed"] > 0:
    raise RuntimeError(f"{s['failed']} 张处理失败")

# 严格流水线：不接受“无法验证像素”
if s["pixels_unverified"] > 0:
    raise RuntimeError(f"{s['pixels_unverified']} 张像素未验证")

publish([f["dst"] for f in report["files"] if f["status"] in ("cleaned", "no_signal")])
```

### 生成溯源台账

```python
import json

report = json.load(open("./images_clean/report.json"))

ledger = [
    {
        "file": f["dst"],
        "origin_platform": f["before"]["platform"] if f["before"] else None,
        "had_markers": f["before"]["markers"] if f["before"] else [],
        "cleaned_at": report["generated_at"],
        "engine": report["engine"]["version"],
    }
    for f in report["files"]
    if f["status"] == "cleaned"
]

json.dump(ledger, open("./provenance-ledger.json", "w"), ensure_ascii=False, indent=2)
```

### 按来源筛选

```python
openai_files = [f for f in report["files"]
                if f["before"] and "OpenAI" in (f["before"]["platform"] or "")]
```

---

## 注意

- 报告用 `ensure_ascii=False` 写入，**中文路径是可读的**
- `src` / `dst` 都是**相对路径**（相对源目录 / 输出目录）
- 报告写入是原子的：不会留下半截 JSON
- 报告路径可用 `--report` 自定义，或用 `--no-report` 关闭
