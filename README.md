<h1 align="center">HengOpenSkills</h1>

<p align="center"><strong>亨亨的开源 Skill 仓库</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/Agent%20Skills-SKILL.md-27364A?style=flat-square" alt="Agent Skills 格式：SKILL.md" />
  <img src="https://img.shields.io/badge/Skills-3-42766A?style=flat-square" alt="3 个 Skill" />
  <img src="https://img.shields.io/badge/%E6%96%87%E6%A1%A3-%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-D5E7B2?style=flat-square" alt="文档语言：简体中文" />
</p>

<p align="center">
  <a href="#skills">技能清单</a> · <a href="#installation">安装与使用</a> · <a href="#feedback">交流与反馈</a>
</p>

我是亨亨。有些事我会反复交给 AI 做，比如审一篇稿子、弄清一家公司的商业模式。每次都重新交代怎么做挺麻烦，我就把这些步骤整理成了 Skill，自己下次接着用，也放在这里分享。

每个 Skill 都有一份 `SKILL.md`，写着什么时候用、怎么做、最后交付什么。需要的脚本和参考资料也放在同一个目录里。

后续所有的开源 Skill，我都统一更新到这个仓库。

<a id="skills"></a>

## 技能清单

| Skill | 能做什么 | 可以这样问 |
| --- | --- | --- |
| [文章审阅编辑](./article-review-editor-skill/SKILL.md) | 逐句校对已有稿件，找出错字、病句和读起来卡顿的地方，给出尽量保留作者语气的改法。 | 帮我审阅这篇稿子，看看有没有错字、病句和读起来不顺的地方。 |
| [商业模式画布](./business-model-craft-skill/SKILL.md) | 研究一家公司的商业模式，生成九宫格画布数据、中英文分析报告和可在本地预览的网页。 | 用商业模式画布分析 Costco，解释会员费和低毛利是怎么配合的。 |
| [微信公众号文章读取](./wechat-article-reader-skill/SKILL.md) | 读取公开公众号文章的正文和配图，供摘要、分析或翻译。微信直读失败时，可按需配置得到大脑作为备用。 | 读一下这篇公众号文章，帮我概括主要观点，也看看文中的图表。 |

<a id="installation"></a>

## 安装与使用

1. 从 GitHub 下载仓库，找到想用的 Skill 目录。
2. 把**整个目录**复制到你的 AI 工具的 Skills 目录，保留其中的 `SKILL.md`、脚本和参考资料。以 Codex 为例，个人使用放到 `~/.agents/skills/`，只在某个项目使用就放到项目的 `.agents/skills/`。[Codex 官方文档](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)
3. 在对话中选中该 Skill，再发出请求。可以从上表的例子开始。如果 Codex 里没有出现新技能，重启后再试。

如果任务用到外部服务，先看对应 Skill 的说明。比如，公众号文章读取的备用方式有单独的[配置说明](./wechat-article-reader-skill/references/setup.md)。

<a id="feedback"></a>

## 交流与反馈

用起来有哪里卡住，或者有哪个步骤可以做得更顺，欢迎提 Issue。反馈时可以附上 Skill 名称、使用的工具和触发问题的输入，方便复现。

也可以在微信里搜索公众号 **「产品变量」** 找到我。
