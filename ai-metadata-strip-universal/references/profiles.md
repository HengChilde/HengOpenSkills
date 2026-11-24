# 预设（profiles）

通用 CLI 解决“怎么处理一张图”；预设解决“这条流水线的输入、成品、报告和归档分别在哪”。
预设是一份 JSON，不含任何可执行逻辑，也不改变剥离行为。

---

## 什么时候该用预设

适合：

- 周期性任务：每月把选片目录清洗到当月交付目录
- 固定投递：成品必须落到某个共享盘/云盘路径，报告必须留在源目录
- 成功后归档原图：确认像素无损后才移动源文件
- 多环节流水线：上下游只认路径约定，不认命令行参数

不适合：一次性处理、临时目录、需要频繁改路径的实验。

---

## 加载方式

```bash
python3 scripts/strip.py --profile <名称或 .json 路径>
```

搜索顺序：

1. `--profile` 直接给存在的文件路径
2. `$AI_METADATA_STRIP_PROFILE_DIR`（可用 `:` 分隔多个目录）
3. `<skill>/profiles/`
4. `~/.config/ai-metadata-strip-universal/profiles/`

名称会自动补 `.json`。找不到时退出码 **3**，并列出所有搜索过的路径。

CLI 参数优先于预设。例如预设里写了 `output`，命令行仍可用 `-o` 或
`--output-to sibling|desktop|downloads` 覆盖。

---

## 字段

| 字段 | 必需 | 说明 |
|---|---|---|
| `profile_version` | 否 | 目前只支持 `1` |
| `name` | 否 | 显示名；缺省用文件名 |
| `description` | 否 | 给人看的说明 |
| `source` | ✅ | 源文件或目录；可被位置参数覆盖 |
| `output` | ✅ | 输出目录；可被 `-o` / `--output-to` 覆盖 |
| `report` | 否 | 报告路径；缺省 `<output>/report.json` |
| `archive` | 否 | 成功后源图移入的目录 |
| `date_subdir` | 否 | 在 `output` 下再按时间分子目录，如 `%Y%m` |
| `existing` | 否 | `overwrite`（默认）/ `reuse` / `skip` |
| `suffix` | 否 | 清洗后缀，默认 `-c` |
| `exclude` | 否 | 通配符数组，匹配相对源目录的路径或文件名 |
| `jobs` | 否 | 并发数；缺省 = CPU 核数 |

未知字段会直接报错，避免拼写错误被静默忽略。`source` / `output` 允许由 CLI
（位置参数、`-o`、`--output-to`）补齐；两者都没有来源时才报错。

### 路径与占位符

相对路径以 **profile 文件所在目录** 为基准（CLI 参数则相对当前工作目录）。
支持：

| 写法 | 展开为 |
|---|---|
| `${HOME}` | 用户主目录 |
| `${SKILL_ROOT}` | 本 skill 目录 |
| `${WORKSPACE_ROOT}` | skill 的父级工作区根（父目录名为 `skills` 时再上一级） |
| `${PROFILE_DIR}` | profile 文件所在目录 |
| `${CWD}` | 执行时的当前目录 |
| `${YYYY}` `${MM}` `${DD}` `${YYYYMM}` | 执行时的年月日 |
| `%Y` `%m` `%d` 等 | strftime 写法，与上一条等价 |

`date_subdir`、`output`、`report` 都会展开；`report` 里用 `%Y%m-report.json`
即可生成按月报告。展开在**每个进程启动时**执行一次，跨月运行时自动落到新月份。

---

## 示例

```json
{
  "profile_version": 1,
  "name": "monthly-delivery",
  "source": "${WORKSPACE_ROOT}/素材库/选片",
  "output": "${HOME}/交付盘/成品",
  "date_subdir": "%Y%m",
  "report": "${WORKSPACE_ROOT}/素材库/选片/报告/%Y%m-report.json",
  "archive": "${WORKSPACE_ROOT}/素材库/选片/已处理",
  "existing": "reuse",
  "suffix": "-c",
  "exclude": ["draft_*", "*.tmp.png"]
}
```

执行效果：

```
素材库/选片/a.png
  → ${HOME}/交付盘/成品/202610/a-c.png
  → 报告写入 素材库/选片/报告/202610-report.json
  → 成功且像素验证通过后，原图移到 素材库/选片/已处理/a.png
```

随 Skill 提供的 [profiles/example.json](../profiles/example.json) 是可复制模板，字段含义与上表一致。

---

## `existing` 的三种语义

| 值 | 行为 | 适用 |
|---|---|---|
| `overwrite` | 总是重新剥离并原子替换输出 | 一次性批处理、允许重跑 |
| `reuse` | 输出已存在时先验证残留与像素，通过则复用，不重新剥离 | 断点续跑、固定投递（默认行为在预设里常设为此） |
| `skip` | 输出已存在时记为 `skipped`，不验证也不覆盖 | 只补缺、不碰已有成品 |

`reuse` 验证失败时**不会**退回覆盖，而是把该文件记为 `failed`，交给人判断。
这样固定投递目录里的异常不会被静默“修好”。

---

## 归档安全条件

只有同时满足以下条件才移动源图：

1. `status` 为 `cleaned` / `no_signal` / `processed`
2. 输出文件确实存在
3. `pixels_identical` 为 `true`

任一不满足，源图留在原目录；同名归档目标已存在时也不覆盖，记入
`files[].archive.error` 与 `summary.archive_failed`。因此**没装 PIL 时不会归档**
（无法证明像素无损），这是有意的保守设计。
