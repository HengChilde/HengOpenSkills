# CLI 参考

```bash
python3 scripts/strip.py <源文件或目录> -o <输出目录> [选项]
python3 scripts/strip.py <源文件或目录> --output-to sibling|desktop|downloads [选项]
python3 scripts/strip.py --profile <名称或 .json 路径> [选项]
```

`--help` 与本文内容一致；本文多了退出码与空批次说明。

---

## 参数

| 参数 | 说明 |
|---|---|
| `source` | 源文件或目录（目录递归） |
| `-o, --output-dir DIR` | 自定义输出目录；与 `--output-to` 二选一 |
| `--output-to sibling\|desktop\|downloads` | 使用默认落点（见下） |
| `--output-name NAME` | 自定义 `--output-to` 新建的文件夹名 |
| `--profile NAME_OR_PATH` | 加载预设；CLI 参数可覆盖预设 |
| `--archive-dir DIR` | 成功后把源图移入该目录 |
| `--date-subdir TEMPLATE` | 输出目录下按时间分目录，如 `%Y%m` |
| `--existing overwrite\|reuse\|skip` | 输出已存在时覆盖（默认）/验证后复用/跳过 |
| `--suffix TEXT` | 清洗后缀，默认 `-c` |
| `--exclude GLOB` | 跳过匹配的图片（相对源目录路径或文件名，可重复） |
| `-j, --jobs N` | 并发数，默认 CPU 核数 |
| `--include-cleaned` | 连已带清洗后缀的文件也重新处理 |
| `--no-identify` | 跳过溯源扫描；状态记为 `processed`，无 `before` |
| `--no-verify-pixels` | 跳过像素比对；`pixels_identical=null` |
| `--require-pixel-verification` | 像素无法验证时视为失败 |
| `--report PATH` | 报告路径，默认 `<输出目录>/report.json` |
| `--no-report` | 不生成报告 |
| `--dry-run` | 只列出将处理的文件，不写任何内容 |
| `--version` | 显示 Skill 与引擎版本 |
| `-q, --quiet` | 只输出结果摘要 |

---

## 输出目录的默认落点

| `--output-to` | 落点 |
|---|---|
| `sibling` | 目录输入：`<源目录>/cleaned/`；文件输入：`<文件所在目录>/cleaned/` |
| `desktop` | `~/Desktop/<源名>-clean/` |
| `downloads` | `~/Downloads/<源名>-clean/` |

- 源名为目录名或文件名（不含扩展名）
- `--output-name NAME` 可覆盖默认文件夹名
- `Desktop` / `Downloads` 不存在时退出 3，并提示改用 `-o`
- `--output-to` 与 `-o` 互斥；`--output-name` 只能和 `--output-to` 一起用
- 预设里的 `output` 会被 `--output-to` / `-o` 覆盖

`--output-to sibling` 的输出在源目录内，通用版会自动排除该目录，不会二次扫描。

---

## 退出码

| 码 | 含义 |
|---|---|
| `0` | 全部成功，或源目录没有可处理图片 |
| `1` | 有文件失败、归档失败，或严格像素验证未通过 |
| `2` | 依赖缺失（`remove-ai-watermarks`） |
| `3` | 参数或 profile 配置错误 |

源目录为空时返回 `0` 并提示。没有文件可处理，不等于清洗失败；这与引擎
`batch` 命令在 0.47 的空批次退出 2 不同，调用方不要混淆。

---

## 常见组合

```bash
# 单文件，默认在文件所在目录新建 cleaned/
python3 scripts/strip.py photo.png --output-to sibling

# 目录 + 并发
python3 scripts/strip.py ./images --output-to sibling -j 4

# 先看计划
python3 scripts/strip.py ./images --output-to sibling --dry-run

# 预设投递 + 成功后归档
python3 scripts/strip.py --profile monthly-delivery

# 大批量、不需要 before 记录
python3 scripts/strip.py ./images -o ./clean --no-identify

# 严格流水线：像素必须可验证
python3 scripts/strip.py ./images -o ./clean --require-pixel-verification
```

---

## 状态与报告

`cleaned` / `no_signal` / `processed` / `skipped` / `failed` 的含义、
`summary` 字段与下游门禁见 [report-schema.md](report-schema.md)。
