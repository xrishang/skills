# Skills · Claude Code 投资分析 Skill 集合

> 本仓库包含面向 Claude 的投资分析 skills 实现。关于 Agent Skills 标准的说明,见 [agentskills.io](https://agentskills.io)。

## Skills 是什么

Skills 是一组文件夹,内含指令、脚本和资源,Claude 会动态加载它们以提升在专门任务上的表现。Skill 教会 Claude 以可复用方式完成特定任务 —— 无论是按公司品牌规范生成文档、按组织特定工作流分析数据,还是自动化个人事务。

每个 skill 都是自包含的文件夹,内含一个 `SKILL.md`,其中存放 Claude 使用的指令与元数据。可以浏览本仓库的 skills 获取灵感,或理解不同的模式与做法。

了解更多:

- 什么是 Skill?
- 在 Claude 中使用 Skill
- 如何创建自定义 Skill
- 用 Agent Skills 武装真实世界的 Agent

## 本仓库包含什么

本仓库是一个个人/团队 skill 集合,聚焦 **A 股 / 港股投资分析**,覆盖从"全市场选股 → 个股深度分析 → ETF 资金流向分析"的完整投研链路。

当前包含一个主题分组 `stock_skills/`,内含三个 skill:

| Skill | 用途 | 维度 |
|-------|------|------|
| `stock_screener` | 全市场 5000+ A 股选股,4 策略筛 Top N | 技术面 / 基本面 / 资金面 / 超跌反弹 |
| `stock-investment-analysis` | 给一只股票做深度分析,判断是否值得投资 | 公司财务 / 估值 / 技术面 / 宏观 / 行业 / 热点 |
| `etf_analysis` | ETF 资金流向排行 + 行业景气度分析 | 资金面 / 流动性 / 技术面 / 行业面 |

三者既可独立使用,也可组合成完整投研闭环:选股筛出的 Top N 可直接交给个股分析做六维度深度复盘;ETF 分析与个股分析互为补充(ETF 看资金/行业,个股看财务/估值)。

## 目录结构

```
skills/
└── stock_skills/
    ├── README.md                  # stock_skills 主题说明
    ├── etf_analysis/              # ETF 资金流向分析 skill
    │   ├── SKILL.md
    │   ├── scripts/
    │   ├── assets/
    │   └── references/
    ├── stock-investment-analysis/ # 个股投资价值分析 skill
    │   ├── SKILL.md
    │   ├── scripts/
    │   ├── assets/
    │   ├── evals/
    │   └── references/
    └── stock_screener/            # 全市场选股 skill
        ├── SKILL.md
        ├── scripts/
        ├── assets/
        └── references/
```

每个 skill 内部组织一致:`SKILL.md`(指令)+ `scripts/`(抓数据/算指标/画图/生成 PDF)+ `assets/`(报告模板)+ `references/`(框架文档)。

## 数据源

通过 `akshare` 等 Python 库抓取 A 股 / 港股的行情、财报、资金流向、宏观经济数据,所有脚本可本地运行。

## 在 Claude Code / Claude.ai / API 中使用

### Claude Code

可以将本仓库注册为 Claude Code 插件市场:

```
/plugin marketplace add xrishang/skills
```

然后安装并使用其中的 skill。安装后,直接在对话中描述任务即可触发,例如:"分析一下 600519 是否值得投资"、"今天主力净流入 Top 20 的 ETF 有哪些"、"低估值蓝筹选股 Top 10"。

### Claude.ai

付费版 Claude.ai 可直接使用示例 skill。要使用本仓库的 skill 或上传自定义 skill,参见"在 Claude 中使用 Skill"文档。

### Claude API

可通过 Anthropic 的预置 skill 或上传自定义 skill,详见 Skills API 快速入门。

## 创建一个基础 Skill

Skill 的创建很简单 —— 一个文件夹 + 一个 `SKILL.md`,`SKILL.md` 包含 YAML frontmatter 和指令正文。可以用本仓库的模板作为起点:

```markdown
---
name: my-skill-name
description: 清晰描述这个 skill 做什么、何时触发
---

# My Skill Name

[这里写 Claude 在该 skill 激活时要遵循的指令]

## 示例
- 示例用法 1
- 示例用法 2

## 指南
- 指南 1
- 指南 2
```

frontmatter 只需两个字段:

- `name` — skill 的唯一标识(小写,用连字符代替空格)
- `description` — 完整描述这个 skill 做什么以及何时触发

下方的 Markdown 正文是 Claude 要遵循的指令、示例与指南。更多细节见"如何创建自定义 Skill"。

## 免责声明

本仓库内容仅为技术与研究示例,不构成投资建议。市场有风险,决策需自行判断。这些 skill 旨在演示模式与可能性,实际从 Claude 得到的实现和行为可能与示例中展示的有所不同。在关键任务中依赖前,请先在自己的环境中充分测试。
