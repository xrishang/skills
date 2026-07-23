---
name: stock-screener
author: kade.xing
description: 全市场 A 股选股 skill,从 5000+ 只股票中按 4 种策略筛选 Top N。策略包括:技术面选股(趋势/放量/换手活跃)、基本面选股(低 PE/合理 PB/大市值蓝筹)、资金面选股(主力净流入/净占比强)、超跌反弹选股(60日跌深+今日企稳+资金回流)。当用户提到"选股"、"筛选股票"、"今天哪些股票放量上涨"、"低估值蓝筹有哪些"、"主力净流入 Top N"、"超跌反弹选股"、或想从全市场找出符合条件的股票时,使用这个 skill。与 stock-investment-analysis(单只深度分析)不同,这个 skill 是"全市场扫描 + 多策略筛选 + Top N 推荐",选出的 Top N 可再调用 stock-investment-analysis 做完整六维度深度分析。
---

# 全市场选股 Skill

## 这个 skill 在做什么

从全市场 5000+ 只 A 股中,按 4 种策略筛选出符合条件的 Top N 股票。**与 stock-investment-analysis 的区别**:那个 skill 是给一只股票做深度分析(六维度),这个 skill 是"全市场扫描 + 多策略筛选 + Top N 推荐"。

4 种选股策略:

1. **技术面选股** — 趋势向上 + 放量 + 换手活跃(适合趋势跟踪)
2. **基本面选股** — 低 PE + 合理 PB + 大市值蓝筹(适合价值投资)
3. **资金面选股** — 主力净流入大 + 净占比强(适合跟随聪明钱)
4. **超跌反弹选股** — 60日跌深 + 今日企稳 + 资金回流(适合抄底)

**为什么是这 4 种策略**:技术面找"强势股",基本面找"便宜好公司",资金面找"机构加仓的票",超跌找"跌深反弹"。4 种策略覆盖不同的投资风格(趋势/价值/跟庄/抄底),用户可以单策略用,也可以 4 策略交叉验证(同时出现在多个策略里的股票更值得关注)。

## 工作流总览

1. **抓全市场数据** — 跑 `scripts/fetch_screen_data.py`,抓 5882 只 A 股的实时行情(PE/PB/市值/换手率/量比/60日涨跌幅)+ 主力资金流向(净流入/超大单/大单)
2. **4 策略筛选** — 跑 `scripts/screen_stocks.py --strategy all`,4 种策略各筛选 Top N,输出 `candidates.json`
3. **画图** — (可选)跑 `scripts/plot_screen_charts.py`,生成 4 策略 Top N 对比图
4. **写筛选报告** — 读 `candidates.json`,按 `assets/screen_report_template.md` 写 Markdown 报告,列出 4 策略 Top N + 交叉验证
5. **对 Top 3 跑完整六维度分析** — 调用 `stock-investment-analysis` skill 的脚本(fetch_data + compute_indicators + plot_charts + project_future),对每只 Top 3 生成完整 PDF 报告
6. **生成 PDF** — 跑 `scripts/generate_pdf.py`,把筛选报告 + Top 3 个股报告合并,输出 `全市场选股报告_{{YYYY-MM-DD}}.pdf`(文件名含日期,对应"今天选了哪些票"这个问题)。Top 3 每只个股的 PDF 按 `stock-investment-analysis` 的命名规则(`公司名(代码)投资分析报告.pdf`)生成

## 调用脚本的具体方式

### 1. 抓全市场数据

```bash
python scripts/fetch_screen_data.py --out-dir ./output/screen
```

输出:
- `spot_all.csv` — 全市场 A 股实时行情(5882 只,23 列)
- `fund_flow_all.csv` — 全市场主力资金流向(5287 只,15 列)
- `spot_merged.csv` — 合并后数据(5086 只,33 列,筛选基础)
- `summary.json` — 市场概览(总股票数/PE 有效数/资金流向统计/涨跌家数)

**数据源**:
- `stock_zh_a_spot_em()` — 5882 只,含 PE/PB/总市值/流通市值/换手率/量比/60日涨跌幅/年初至今涨跌幅
- `stock_individual_fund_flow_rank(indicator='今日')` — 5287 只,含主力净流入/超大单/大单/中单/小单

**过滤规则**:自动剔除 ST/*ST/退市股,保留主板(60/00)+ 创业板(30)+ 科创板(688)。

### 2. 4 策略筛选

```bash
# 单策略
python scripts/screen_stocks.py --strategy technical --top 20 --out-dir ./output/screen
python scripts/screen_stocks.py --strategy fundamental --top 20 --out-dir ./output/screen
python scripts/screen_stocks.py --strategy fund_flow --top 20 --out-dir ./output/screen
python scripts/screen_stocks.py --strategy oversold --top 20 --out-dir ./output/screen

# 全部 4 策略
python scripts/screen_stocks.py --strategy all --top 20 --out-dir ./output/screen
```

输出:
- `candidates.json` — 4 策略 Top N 结果汇总
- `candidates_technical.csv` / `candidates_fundamental.csv` / `candidates_fund_flow.csv` / `candidates_oversold.csv` — 各策略单独 CSV

### 3. 对 Top 3 跑完整六维度分析

对筛选出的 Top 3(用户指定策略或综合排名),调用 `stock-investment-analysis` skill:

```bash
# 假设 Top 3 是 601138、000636、601179
for ticker in 601138 000636 601179; do
    python C:/Users/26841/.claude/skills/stock-investment-analysis/scripts/fetch_data.py --ticker $ticker --out-dir ./output/$ticker
    python C:/Users/26841/.claude/skills/stock-investment-analysis/scripts/compute_indicators.py --ticker $ticker --out-dir ./output/$ticker
    python C:/Users/26841/.claude/skills/stock-investment-analysis/scripts/plot_charts.py --ticker $ticker --out-dir ./output/$ticker
    python C:/Users/26841/.claude/skills/stock-investment-analysis/scripts/project_future.py --ticker $ticker --out-dir ./output/$ticker
done
```

然后对每只写完整六维度报告 + 生成 PDF。

## 4 种策略详解

### 策略 1:技术面选股 — "趋势 + 放量"

**筛选条件**:
- 60日涨跌幅 > 10%(中期趋势向上)
- 今日涨跌幅 > 2%(当日强势)
- 量比 > 1.5(放量)
- 换手率 > 3%(活跃)
- 成交额 > 2 亿(流动性)

**排序**:60日涨幅 + 今日涨幅 + 量比 综合分(标准化后相加)

**适合**:趋势跟踪策略,找"强势股"。注意:可能选到已经涨高的票,追高风险。

### 策略 2:基本面选股 — "低估值蓝筹"

**筛选条件**:
- PE 10-30(偏低估值,排除亏损 PE<0 和泡沫 PE>30)
- PB 1-5(合理,排除破净 PB<1 和高泡沫 PB>5)
- 总市值 > 100 亿(大中盘,流动性)
- 今日涨跌幅 > 0(当日有资金关注)

**排序**:PE 越低越好 + 市值越大越好 综合分

**适合**:价值投资,找"便宜好公司"。注意:低 PE 可能是周期股顶部(周期股陷阱)。

### 策略 3:资金面选股 — "主力加仓"

**筛选条件**:
- 主力净流入 > 5000 万
- 净占比 > 5%
- 总市值 > 50 亿(排除小盘股资金冲击)
- 今日涨跌幅 > 1%(资金推动上涨)

**排序**:主力净流入金额降序

**适合**:跟随聪明钱,找"机构加仓的票"。注意:单日净流入不代表持续,需观察多日。

### 策略 4:超跌反弹 — "跌深 + 企稳 + 回流"

**筛选条件**:
- 60日涨跌幅 < -20%(超跌)
- 今日涨跌幅 > 0(企稳反弹)
- 主力净流入 > 0(资金回流)
- 总市值 > 50 亿(排除小盘股)

**排序**:60日跌幅越深 + 今日涨幅 + 净流入 综合分

**适合**:抄底策略,找"跌深反弹"。注意:超跌可能继续跌,需等技术面止跌确认。

## 交叉验证

4 策略筛选完后,找出**同时出现在多个策略里的股票**——这种股票更值得关注。例如:
- 同时出现在 fundamental + fund_flow → "低估值 + 主力加仓"= 价值 + 资金共振,强信号
- 同时出现在 oversold + fund_flow → "超跌 + 资金回流"= 抄底信号
- 同时出现在 technical + fund_flow → "趋势 + 资金"= 强势股确认

## 报告输出结构

参考 `assets/screen_report_template.md`:

```markdown
# 全市场选股报告 — {{日期}}
## 一句话结论
{{4 策略 Top N + 交叉验证 + 推荐}}

## 市场概览
| 指标 | 数值 |
|---|---|
| 总股票数 | 5086 |
| 涨/跌/平 | 2957/1894/161 |
| 主力净流入总额 | -130 亿 |
| 净流入/流出家数 | 2317/2650 |

## 4 策略 Top N

### 策略 1:技术面(趋势 + 放量)
[Top N 列表 + 简要理由]

### 策略 2:基本面(低估值蓝筹)
[Top N 列表]

### 策略 3:资金面(主力加仓)
[Top N 列表]

### 策略 4:超跌反弹
[Top N 列表]

## 交叉验证
[同时出现在多个策略的股票]

## Top 3 推荐(跑完整六维度分析)
### 1. {{ticker}} {{name}}
[完整六维度分析]
### 2. ...
### 3. ...

## 数据局限性说明
[...]
```

## 重要原则

1. **策略不等于必胜**:4 种策略是"筛选工具"不是"印钞机",每种策略都有失效场景
2. **交叉验证比单策略更可靠**:同时出现在多个策略里的股票,信号更强
3. **单日数据有噪音**:技术面/资金面都是当日快照,需多日确认
4. **Top 3 必须跑完整分析**:筛选只是第一步,投资决策前要用 stock-investment-analysis 做六维度深度分析
5. **不做投资建议**:报告末尾加免责声明

## 何时不用全套流程

- 用户只想要"今天主力净流入 Top 10"→ 只跑 fund_flow 策略
- 用户只想要"低 PE 蓝筹"→ 只跑 fundamental 策略
- 用户给一只股票想做深度分析 → 用 stock-investment-analysis,不用这个 skill

## 依赖

```
akshare matplotlib pandas markdown pypdf
```

还需系统装了 Edge 或 Chrome(生成 PDF 用)。
