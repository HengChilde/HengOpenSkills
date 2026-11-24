---
name: ai-metadata-strip-universal
description: >
  通用版：剥离 AI 生成图片的溯源元数据——C2PA Content Credentials、EXIF/XMP
  生成器字段、IPTC DigitalSourceType、中国 TC260 AIGC 标签、PNG 内嵌生成参数。
  纯文件层操作，像素零改动、不重编码、画质无损。用于：图片发布/交付/上架前
  清掉 AI 生成标记；批量清洗素材库的溯源信息；按预设把清洗结果投递到固定目录
  并归档原图。不绑定任何项目路径，适用于任意目录与流水线。
  触发词：去除 AI 元数据、去掉 C2PA、剥离 AI 溯源信息、清理 EXIF 里的 AI 标签、
  图片发布前处理、素材库元数据清洗、strip AI metadata、remove C2PA、clean AI provenance。
  也用于被其他 skill / 流水线内部调用（生成图片后自动清洗元数据）。
  这是元数据层工具：不做压缩、转格式、缩放、调色等任何图片处理；
  不改动像素，因此图像上看得见的角标、以及只看像素才能去掉的隐形水印，
  都不在它的能力范围内。
metadata:
  category: image-pipeline
  version: "1.0.0"
---

# ai-metadata-strip-universal

**把 AI 生成图片的溯源标记清干净——只动文件，不动像素。**

流水线上的原子环节：上游生成图片，下游发布/交付。

## 核心约束：像素零改动

处理前后像素**逐字节相同**，逐张比对并写入报告；ICC 色彩配置与标准元数据默认保留。
文件大小可能因 PNG 重压缩略变，**验证看解码后的像素，不看文件大小**。

一旦它可能改动像素，就不能被安全地放进流水线——你无法预知它会不会毁掉上游刚生成的图。

## 何时用

- 发布、交付、上架前清掉平台可读的 AI 标记
- 批量清洗素材库，同时保留处理前的溯源记录
- 按预设投递到固定目录，并在成功后归档原图
- 作为其他 skill / 流水线的下游环节

**不适用**：像素隐形水印（SynthID 等）、可见角标、压缩/转格式/缩放、视频/音频元数据。
判断标准：**会改像素的需求不在这里**。

## 先确认输出目录

用户没有明确指定成品位置时，**先给出下列选项并等待确认，不要自行猜一个 `-o` 路径**：

| 选项 | 落点 | 命令 |
|---|---|---|
| 原目录内新建 `cleaned/`（推荐） | `<输入目录>/cleaned/` | `--output-to sibling` |
| 桌面 | `~/Desktop/<名称>-clean/` | `--output-to desktop` |
| 下载 | `~/Downloads/<名称>-clean/` | `--output-to downloads` |
| 自定义 | 用户指定 | `-o <目录>` |

文件输入时，`sibling` 落在文件所在目录的 `cleaned/`；`--output-name NAME` 可改新建文件夹名。
如果 profile 已固定输出，不再追问。

## 快速开始

以下命令从 Skill 目录运行。

```bash
# 用户已确认落点后
python3 scripts/strip.py ./images --output-to sibling
python3 scripts/strip.py ./images -o ~/素材库/images_clean
python3 scripts/strip.py ./images --output-to sibling --dry-run
```

常用参数：

| 参数 | 用途 |
|---|---|
| `-o, --output-dir` | 自定义输出目录 |
| `--output-to sibling\|desktop\|downloads` | 使用默认落点 |
| `--output-name NAME` | 自定义默认落点的新文件夹名 |
| `--profile NAME_OR_PATH` | 加载预设 |
| `--archive-dir DIR` | 成功后归档源图 |
| `--existing overwrite\|reuse\|skip` | 已有输出的处理策略 |
| `--dry-run` | 只列出将处理的文件 |

完整参数、退出码与空批次说明见 [references/cli.md](references/cli.md)；
`python3 scripts/strip.py --help` 也可。

## 预设

预设把输入、输出、报告、归档、按月分目录和已有输出策略固化在一份 JSON 里：

```bash
python3 scripts/strip.py --profile example
```

字段、占位符、搜索顺序与归档安全条件见 [references/profiles.md](references/profiles.md)。

## 输出

- **图片** → 输出目录，保持源目录相对结构，文件名加 `-c`（可用 `--suffix` 改）
- **`report.json`** → 结构化报告，默认写在输出目录，可用 `--report` / `--no-report` 调整
- **已带后缀的源文件** → 默认跳过，避免 `-c-c`

报告字段、status 与下游门禁见 [references/report-schema.md](references/report-schema.md)。

## 安全契约

- **先暂存再发布**：像素与残留检查通过后才原子改名；失败不在交付目录留半成品
- **不可读输入直接失败**：签名 + PIL 完整性校验，不把“读不懂”当成“没有标记”
- **残留复检**：`identify --no-visible` 复查输出，仍有元数据则判失败
- **归档有条件**：输出存在、`pixels_identical=true` 才移动源图；同名不覆盖
- **输出目录自动排除**：嵌套在源目录内也不会被下一轮扫描当成输入

## 依赖

外部引擎 [`remove-ai-watermarks`](https://github.com/wiltodelta/remove-ai-watermarks)
推荐 **0.47.0+**；脚本本身只用 Python 标准库；PIL 可选（像素验证）。

安装、升级与版本差异见 [references/upstream.md](references/upstream.md)。

## 已知边界

- SynthID 等像素水印仍在图里，官方验证器仍可能识别为 AI 生成
- 平台自动打标读的是元数据，这部分已清干净；但不是“隐身”
- 清洗后本地无法再检测，报告里的 `before` 是唯一溯源记录，建议保留
- 服务端记录去不掉；中国大陆与印度禁止移除 AI 标识，合规风险自负

## 参考文件

按需读取：

| 文件 | 什么时候看 |
|---|---|
| [references/cli.md](references/cli.md) | 查完整参数、退出码、命令组合 |
| [references/profiles.md](references/profiles.md) | 写预设、配置投递与归档 |
| [references/report-schema.md](references/report-schema.md) | 读报告、写下游门禁 |
| [references/integration.md](references/integration.md) | 接入流水线、被其他 skill 调用 |
| [references/markers.md](references/markers.md) | 查具体清除的标记类型 |
| [references/upstream.md](references/upstream.md) | 排查引擎版本、决定是否升级 |
