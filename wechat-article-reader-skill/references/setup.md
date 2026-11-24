# 配置与排障

## 首次使用向导

用户主动要求开启得到大脑时，从第 1 步开始。若用户只是想读文章，先尝试直读。直读失败且尚未开启备用方式时，告诉用户启用后的行为，并让用户选择是否开启：

> 微信这次没返回正文。你可以开启得到大脑作为备用方式。以后直读失败时，我会把公众号链接保存到你的得到大脑私有笔记，再从那里读取正文。要现在配置吗？

### 1. 准备本机配置文件

助手在包含 `SKILL.md` 的安装目录执行以下命令，并把返回的 `config_path` 作为可打开的路径发给用户。这个路径取决于用户实际装在哪里。

```bash
python3 scripts/read_article.py --init
```

`BIJI_CONFIG_CREATED` 表示已创建空白文件，`BIJI_CONFIG_EXISTS` 表示已有文件。命令会保留已有配置。如果用户已经配过，可直接到第 3 步。安装目录只读或多人共用时，用用户自己的可写安装副本再初始化。

### 2. 创建应用并填写两个字段

引导用户在自己登录的浏览器和编辑器里完成以下操作：

1. 打开并登录 [得到大脑开放平台](https://www.biji.com/openapi)，点击「创建应用」，名称可以填「公众号文章读取器」。如果页面提供权限选项，选择读取笔记（`note.content.read`）和新增或修改笔记（`note.content.write`）。[官方快速上手](https://doc.biji.com/docs/WLUjwn3noiPMBWkFOPkcTqcnn6e/) · [权限说明](https://doc.biji.com/docs/WOxgwObNNiyMHWk1dl0cJqSxnEd)
2. 在同一个应用里找到 **Client ID** 和 **API Key**，通常分别以 `cli_` 和 `gk_live_` 开头。API Key 生成时只显示一次，保持页面打开，直接复制到本机编辑器。已有同一应用的两个值时，可复用。 [官方配置说明](https://doc.biji.com/docs/Bu4swmKK0ifgU9kKsNicURbznve/) · [API Key 管理说明](https://doc.biji.com/docs/RvpewA9dBi1tZQkMeclclYfqn2c)
3. 打开第 1 步给出的 `.local/biji.json`，把 Client ID 写到 `client_id`，把 API Key 写到 `api_key`。保留双引号和逗号，保存文件。

```json
{
  "client_id": "在本机填入 Client ID",
  "api_key": "在本机填入 API Key"
}
```

助手可以这样结束这一步：

> 两项都填好并保存后，回复「已填写」就行。我会做一次只读连接检查。请把两个值留在本机文件里。

如果链接点不开，让用户用本机编辑器打开完整路径。在 macOS 或 Linux 上，也可以在实际 Skill 目录运行 `nano .local/biji.json`。在聊天、截图或命令里都只使用占位值。

### 3. 检查连接并回到原任务

收到「已填写」后，由助手在同一 Skill 目录运行：

```bash
python3 scripts/read_article.py --check-connection
```

- `BIJI_CONNECTION_OK` 表示鉴权和读取权限通过。检查查询一次笔记列表，输出只包含状态。写入权限在实际剪藏时由平台验证。
- 如果用户已经同意开启备用方式，继续处理原来读不到的文章。没有待处理文章时，结束配置，等用户发链接。
- 如果检查失败，按下方状态表给用户一个明确的下一步。用户修正后再检查，从出错那一步继续。

每个安装副本使用自己目录内的配置。环境变量 `WECHAT_BIJI_READER_HOME` 可以另指定任务和正文的存放位置。

## 分发 Skill

分发时打包 `SKILL.md`、`scripts/` 的 Python 文件和 `references/` 的文档及空白模板。每位安装者用 `--init` 生成自己的配置。完整压缩 Skill 目录会包含本机的 `.local/`，其中可能有凭据和阅读记录。

## 状态处理

| 状态 | 处理 |
|---|---|
| `BIJI_CONFIG_MISSING`、`BIJI_CONFIG_EMPTY` | 初始化当前安装副本，让用户打开命令返回的文件路径并填好两个字段。 |
| `BIJI_CONFIG_INVALID` | 请用户按模板检查双引号、逗号、两个字段名以及复制时带入的空格。 |
| `BIJI_CONFIG_PERMISSIONS` | 把配置设为仅当前用户可读写，例如在 macOS 或 Linux 上运行 `chmod 600 .local/biji.json`。 |
| `BIJI_CONFIG_INIT_ERROR` | 检查 Skill 目录的写入权限和空白模板是否齐全。 |
| `BIJI_AUTH` | 请用户确认两个值来自同一个应用，凭据有效，且应用已开通所需权限。 |
| `BIJI_ACCOUNT_RESTRICTED` | 在开放平台查看当前账号的 API 使用状态。用户仍可使用直读模式。 |
| `BIJI_RATE_LIMITED`、`BIJI_QUOTA_EXHAUSTED` | 查看开放平台额度。已有任务 ID 时用 `--resume`。 |
| `BIJI_PENDING` | 任务已保存，等待处理完成后续查。 |
| `BIJI_NO_TASK` | 此链接当前没有可续查的任务，可重新执行普通读取。 |
| `BIJI_SUBMISSION_UNKNOWN` | 请求可能已到达平台或仍在提交。先检查得到大脑最近笔记和原进程，再判断后续操作。自动流程保留同一链接的认领记录。 |
| `BIJI_TASK_FAILED` | 剪藏任务失败，可以请用户提供原文，或按用户指示查看其已有剪藏。 |
| `BIJI_NO_ORIGINAL`、`SUMMARY_ONLY` | 剪藏详情缺少正文，根据结果说明有无摘要。 |
| `BIJI_NOT_FOUND` | 已记录的笔记不可读取，可到得到大脑检查状态。 |
| `BIJI_NETWORK`、`BIJI_API_ERROR`、`BIJI_RESPONSE_INVALID` | 检查网络或稍后续查。有返回 `request_id` 时可用它查问题。 |
| `LOCAL_STATE_ERROR` | 检查本机状态目录和写入权限。 |

[开放平台](https://www.biji.com/openapi) · [接口与错误码](https://doc.biji.com/docs/WOxgwObNNiyMHWk1dl0cJqSxnEd)
