# 上游引擎版本与能力

本 skill 只是编排层，真正解析和剥离标记的是
[`remove-ai-watermarks`](https://github.com/wiltodelta/remove-ai-watermarks)。
它的版本差异会直接影响“能不能信任成功退出”。

---

## 安装与升级

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --python 3.12 remove-ai-watermarks

# 已安装
uv tool upgrade remove-ai-watermarks

# 查看
remove-ai-watermarks --version
python3 scripts/strip.py --version   # 同时显示 skill 与引擎版本
```

脚本会在每次运行时把引擎版本写入报告的 `engine` 字段；低于
`engine.recommended_version` 时提示升级，但不阻塞。

---

## 版本矩阵（截至 2026-10-20）

| 版本 | 新能力 | 与本 skill 的关系 |
|---|---|---|
| 0.47.0 | 不可读输入报错、空批次退出 2、输出暂存验证、失败不留新文件、HEIF 原位清零保 offset | **推荐下限**；包装层也自行做了 fail-closed |
| 0.46.0 | `mcp` server（identify/remove/batch）、Kling H.264 SEI 视频标记、Dreamina 导出 JSON、保留透明通道 | 视频不在范围；透明通道保留对图片有利 |
| 0.45.1 | SDXL + Z-Image 显存流式加载、`--cpu-offload` | 仅像素水印链路，与元数据无关 |
| 0.45.0 | Dola / WorkBuddy 可见标记；豆包、三星、微软、元宝、即梦布局覆盖 | 可见标记不在范围 |
| 0.44.0 | TC260 `SecurityData` 签名校验（内置 SM3/SM2）、C2PA soft-binding registry 扩到 53 条 | `before` 的平台归因更可信 |
| 0.43.0 | Vidu / Wan 标记、Amazon Bedrock C2PA 归因、Google Photos AI 编辑、OpenCV 5 | 元数据归因覆盖更广 |
| 0.42.0 | OpenArt 可见标记、通用“AI生成”兜底 | 可见标记不在范围 |
| 0.41.0 | 可选源管线分类器（OpenAI / Google 导出） | 独立 API，不进入 `identify`，未接入 |
| ≤ 0.40.x | 对不可读文件“原样复制 + 退出 0” | **已知漏洞**；本 skill 用签名 + PIL 校验提前拦截 |

---

## 为什么推荐 0.47.0+

0.47.0 把输出发布改成了 fail-closed：

1. 不可读的图片/视频直接报错，不再伪装成“没有标记”
2. 输出先写入暂存文件，重新扫描通过后才发布
3. 剥离失败不会在目标位置留下新文件
4. HEIF 通过原位清零 provenance box 保留 item offset

即使在旧版本上，本 skill 也会：

- 用文件签名 + PIL `verify()` 判断输入是否可读
- 剥离到同目录临时文件，复检元数据残留与像素一致后才原子改名
- 失败时清理临时文件，不发布半成品

所以旧引擎不会造成“静默损坏”，但升级后可以少一层兜底、并获得 HEIF/GIF 等格式修复。

---

## 上游还提供但本 skill 不做的能力

| 能力 | 命令 | 为什么不做 |
|---|---|---|
| 可见角标去除 | `visible` | 会改像素，与无损承诺冲突 |
| 像素隐形水印去除（SynthID 等） | `invisible` | 有损，需要 GPU |
| 视频/音频元数据 | `metadata` / `video` | 本 skill 的像素契约只覆盖图片 |
| MCP server | `mcp` | 通用性与零依赖编排层不需要常驻服务 |
| 源管线分类 | `classify` | 不是溯源标记剥离，且需要额外模型 |

需要这些能力时直接调用上游命令，或把它们做成独立 skill，不要塞进本 skill
破坏“只动文件、不动像素”的原子性。

---

## 本机验证

2026-10-21：0.40.1 → **0.47.0**。

- `evals/smoke_test.py`：12/12 通过
- 真实产品实拍 14 张 JPEG：`failed=0`、`pixels_verified=14`、耗时 5.12 秒
- 报告 `engine.version` 与 `recommended_version` 均为 0.47.0

---

## 升级检查清单

升级引擎后，可在项目源码根目录运行回归测试。

```bash
python3 evals/smoke_test.py
```

重点确认 C9（坏文件 fail-closed）、C16（残留/像素不发布）、C13（profile + 归档）
仍然通过；这三条最容易受引擎退出码或输出行为变化影响。
