# 飞书审阅交付

用官方 `lark-cli` 和已经配置好的调用身份。默认用 `user`，用户指定应用身份时用 `bot`。读取和批注沿用同一身份。沙箱内若出现 Keychain 或域名解析错误，按环境权限使用获准的沙箱外执行。

## 会话返回

飞书链接优先用轻量 Markdown 读取，只取正文和读取提示。CLI 失败时按 `lark-doc-flow` 的读稿说明兜底。

```bash
lark-cli docs +fetch --doc '<飞书链接>' --as user --doc-format markdown --jq '.data.document | {content,tips}'
```

## 批注在飞书里

用户明确选择飞书批注后，在临时目录保存一次读稿快照。`read` 的标准输出是带块 ID 的正文，用它同时审阅和定位。以下命令从 Skill 目录运行，`<临时目录>` 须事先创建。

```bash
python3 scripts/feishu_comments.py read --doc '<飞书链接>' --snapshot '<临时目录>/document.json'
```

审阅后只生成一份 JSON 清单。每条提供真实 `block_id`、`level` 和简短 `text`。同一问题只写一条，正文块已提供位置上下文，通常只需引用会引起歧义的关键词。`text` 从问题或改法直接写起，层级前缀由脚本添加。

```json
[
  {"block_id":"blk_example","level":"必须修正","text":"‘进获客’多了一个‘进’，改为‘获客’。"},
  {"block_id":"blk_other","level":"建议调整","text":"这里可以补一句，说明这项推演成立的条件。"}
]
```

将清单保存为 `<临时目录>/comments.json`。以下命令一次提交清单。省略 `--apply` 可仅在本地校验。脚本会在开始写入前校验整份清单，每条均锚定到明确的块 ID。

```bash
python3 scripts/feishu_comments.py post --snapshot '<临时目录>/document.json' --plan '<临时目录>/comments.json' --apply
```

`posted` 是本次收到成功回执的条数，`skipped` 是同一快照中已确认提交的相同批注数。失败时还会输出 `check_item`（清单行号）、`unattempted`（后续未尝试条数）、`key`（该条稳定的批注 key）和 `error`。脚本在发送前先写入待确认回执；只有拿到可用评论 ID 才记为成功。超时、CLI 异常或成功回执缺少评论 ID 都会停在该条，不自动重发。保留原快照和回执，避免用新快照重发整批。若读稿后正文已变动，先重新核对受影响的块和既有批注。

## 核对与本地恢复

遇到 `check_item` 时，先在飞书核对该行对应的批注是否已经存在。需要取评论 ID 时，用与读稿相同的身份查询：

```bash
lark-cli drive +list-comments --url '<原飞书链接>' --as user --comment-scope partial --solved-status all --need-relation
```

读稿使用 `bot` 时改用 `--as bot`。对照批注位置和正文；结果有后续页时用返回的分页 token 加 `--page-token` 继续。若仍无法确认是否写入，保留待确认状态，并在会话说明。

核对后，用 `resolve` 按 `key` 二选一记录结果。两条命令都必须使用与 `post` 相同的快照和清单，并从 Skill 目录运行：

```bash
# 已在飞书确认存在：填入该批注的评论 ID
python3 scripts/feishu_comments.py resolve --snapshot '<临时目录>/document.json' --plan '<临时目录>/comments.json' --key '<key>' --comment-id '<评论 ID>'

# 已核对确实未写入：明确允许下一次 post 重试该条
python3 scripts/feishu_comments.py resolve --snapshot '<临时目录>/document.json' --plan '<临时目录>/comments.json' --key '<key>' --retry
```

核对要求：

- 只对 `post` 错误回执给出的 `key` 操作，且该 key 必须仍在当前清单中处于待确认状态；不存在或已确认的条目会被拒绝。
- `--comment-id` 只填飞书里已存在、确属这条批注的评论 ID，不能用占位值。
- `--retry` 仅用于确认飞书里确实没有写入。它只是允许下一次 `post` 重试，不会立即发送；下一次 `post` 会先写入新的待确认回执消耗这次许可，若再次超时仍会停止，需要重新核对。
- `resolve` 只在同一把快照锁下追加本地回执，绝不调用飞书。回执损坏或冲突时会拒绝并停止，不要手工改回执来绕过。
- 旧版只含 `key` 和 `comment_id` 的回执仍按同样规则读取，可继续用 `resolve` 恢复。

继续方式：确认评论已存在后，重跑原 `post` 命令；该条会按已确认跳过，只继续它后面的条目。允许重试后同样重跑原 `post` 命令；只有该待确认条会被重新发送，成功后继续后续条目。

在会话给整体编辑判断、文档链接和批注结果。将无法定位、未写入或需核实写入状态的意见留在会话说明。已写入的批注只报告数量。若官方 CLI 读取失败，使用 `lark-doc-flow` 继续读取和审阅，拿不到可靠块 ID 或无法写入时，把对应意见以会话清单交付。
