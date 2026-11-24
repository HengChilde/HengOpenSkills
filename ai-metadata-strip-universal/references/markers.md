# AI 溯源标记速查

本 skill 通过 `remove-ai-watermarks metadata --remove` 清除的标记类型。按「藏在文件哪里」分类。

---

## 一、C2PA Content Credentials

**最有分量的一类**——密码学签名的溯源清单，绑定到文件的精确字节。

| 项 | 说明 |
|---|---|
| 位置 | JPEG APP11 / PNG `caBX` 块 / AVIF、HEIF、WebP、JXL 的结构化容器 |
| 内容 | 生成工具、模型名、数字源类型（`trainedAlgorithmicMedia`）、签名与时间戳 |
| 平台如何用它 | **Meta、TikTok、YouTube 自动标注的主要依据** |
| 脆弱性 | 重编码、截图、元数据剥离都会破坏它 |

**为什么平台认它**：C2PA 是签名的，篡改会验签失败。所以平台把它当作置信度最高的信号。

**注意**：C2PA 被剥离后，XMP 里的 `dcterms:provenance` 可能仍指向 Adobe 云端 manifest store——
凭证理论上可通过网络恢复。工具会把这个标记为 provenance 信号而非 AI 断言。

---

## 二、EXIF / XMP

| 字段 | 常见写入方 |
|---|---|
| `Software` / `CreatorTool` | NovelAI、Reve、Aphrodite 等 |
| XMP `CreatorTool` | 各类生成工具 |
| PNG `tEXt` 块（`Software`/`Source`/`Title`） | NovelAI 等 |

NovelAI 把标识写在 PNG 文本块里，不在 EXIF——所以只看 EXIF 会漏。

---

## 三、IPTC

| 字段 | 含义 |
|---|---|
| `DigitalSourceType` = `trainedAlgorithmicMedia` | 标准化的「AI 生成」声明 |
| `AISystemUsed` / `AIPromptInformation` | IPTC 2025.1 新增 |

**关键**：IPTC 的 `DigitalSourceType` 是**通用标准**，不是某家厂商专属，所以它**不能**用来断定是哪家生成的。

---

## 四、中国 TC260 AIGC 标签

《人工智能生成合成内容标识办法》要求的隐式标识。**有 4 种序列化形式**，只查一种会漏：

| # | 形式 | 位置 |
|---|---|---|
| 1 | `AIGC{...}` 裸 JSON | JPEG APP11 / 非标准 APP 段 |
| 2 | XMP 命名空间 | XMP 包 |
| 3 | JSON | EXIF `UserComment` |
| 4 | `{"AIGC":{...}}` | **标准 PNG 文本块**（如 `Description`） |

第 4 种最容易漏——它藏在普通的 PNG 文本字段里，看起来不像标记。

引擎 0.44.0 起会校验 TC260 `SecurityData` 签名（内置 SM3/SM2），签名有效时作为高置信度归因；
不支持的签名形状会明确报告，而不是猜。

视频侧还有：MP4/MOV 的 `moov.udta.meta.keys/ilst`、MKV/WebM 的 `Segment.Tags.Tag.SimpleTag`、
AVI 的 `LIST/INFO/AIGC`、FLV 的 `script.onMetaData.AIGC`。本 skill 不处理视频，见文末。

---

## 五、厂商私有字段

| 厂商 | 字段 | 特点 |
|---|---|---|
| Samsung | `genAIType` | 未公开的私有字段，写在**文件尾部 trailer**（大图可能超出常规扫描窗口） |
| xAI / Grok | EXIF 签名 | base64 blob + UUID Artist 对 |
| HuggingFace | `hf-job-id` | PNG 文本块 |
| Apple | `photoshop:Credit` | Photos Clean Up 编辑的标记 |
| Amazon Bedrock | C2PA issuer | Nova Canvas / Nova Reel；0.43 起按整词匹配 registry token |
| Dreamina | app-export JSON | 0.46 起从 MP4/MOV 中清除（同一份会写两次） |

---

## 六、PNG 文本块 / 生成参数

Stable Diffusion / ComfyUI 等常把**完整工作流 JSON** 写进 PNG 文本块——包含 prompt、模型、seed 等。
信息量比标签大得多。`identify` 会以 `Embedded generation parameters` 报出来。

---

## 剥离时的工程细节

| 格式 | 剥离方式 | 保真 |
|---|---|---|
| JPEG | 删除目标元数据段，**不重编码熵编码图像扫描** | 无损 |
| PNG / WebP | 走无损输出路径 | 像素无损 |
| HEIC / HEIF / AVIF / JXL | ISOBMFF 层原位清零；0.47 起保持 HEIF item offset | 不重编码像素 |
| GIF | 删元数据扩展块，保留播放相关 APP 块 | 像素无损 |
| ISOBMFF 视频 | 原位清零，保持 box 大小与媒体偏移 | 流拷贝 |

**JPEG 那条很重要**：很多工具“去元数据”的方式是重新保存 JPEG，那会二次压缩、损失画质。
正确的做法是只摘掉 APPn 段，保留原始扫描数据。

---

## 本 skill 不处理的标记

| 类型 | 位置 | 为什么不做 |
|---|---|---|
| **SynthID** | 像素值里 | 需重绘每个像素，有损 + 需 N 卡 |
| **Microsoft InvisMark** | 像素值里 | 同上 |
| **Meta Content Seal** | 像素值里 | 同上 |
| 开放 DWT-DCT 水印 | 像素频域 | 同上 |
| Adobe TrustMark | 像素频域 | 同上 |
| 可见角标 | 像素表层 | 需 inpainting 填充 |
| 视频/音频元数据 | 容器层 | 引擎支持，但本 skill 的像素契约只覆盖图片 |

---

## 上游版本差异

各版本能力与升级建议见 [upstream.md](upstream.md)。
