# akshare 接口速查与坑点

本文档列出本 skill 用到的 akshare 接口、它们当前是否可用,以及替代方案。akshare 频繁更新,接口名可能变化,如果脚本失败,先来这里找替代。

## 当前数据源策略(2026-07)

环境:Windows + Python 3.13 + akshare 1.18.70。东方财富(`push2his.eastmoney.com`)接口在该环境被服务器拒连,**所有 *_em 后缀接口不可用**。新浪源(sina)可用。

| 数据 | 接口 | 状态 | 备注 |
|---|---|---|---|
| A股日线 | `ak.stock_zh_a_daily(symbol='sh600519', adjust='qfq')` | ✅ sina 源 | 需 sh/sz 前缀 |
| A股实时行情 | `ak.stock_zh_a_spot()` | ⚠️ sina 源,需遍历 70 页 | 慢(约 1.5 分钟),单股查询不实用 |
| A股实时行情(东财) | `ak.stock_zh_a_spot_em()` | ❌ 连接被拒 | 不用 |
| A股个股信息(雪球) | `ak.stock_individual_basic_info_xq(symbol='SH600519')` | ❌ KeyError: 'data' | 返回结构变了 |
| A股个股信息(东财) | `ak.stock_individual_info_em(symbol='600519')` | ❌ 连接被拒 | 不用 |
| A股 PE/PB 历史 | `ak.stock_a_indicator_lg` | ❌ 接口已移除 | akshare 1.18 后无此函数 |
| A股财务摘要 | `ak.stock_financial_abstract(symbol='600519')` | ✅ | 80 行 × 104 列,宽格式 |
| 港股日线 | `ak.stock_hk_daily(symbol='00700', adjust='qfq')` | ✅ sina 源 | 返回全历史,需后期过滤日期 |
| 港股公司基本信息 | `ak.stock_hk_company_profile_em(symbol='00700')` | ✅ | |
| 港股财务报表 | `ak.stock_financial_hk_report_em(stock='00700', symbol='利润表', indicator='报告期')` | ✅ | 长格式,3 张表分别抓 |
| CPI | `ak.macro_china_cpi()` | ✅ | 数据倒序(head 是最新),字段名"全国-同比增长" |
| PPI | `ak.macro_china_ppi_yearly()` | ✅ | 字段名"现值",最新一行可能 NaN,用"前值" |
| LPR | `ak.macro_china_lpr()` | ✅ | 字段名 LPR1Y / LPR5Y,正序(tail 最新) |

## PE/PB 历史分位的替代方案

`stock_a_indicator_lg` 接口移除后,无法直接拿个股 PE/PB 历史。两个替代思路:

1. **代理估值分位**:用股价自身的 N 年分位代替估值分位。在熊市/盘整期准确度尚可,在牛市顶点偏差大。本 skill 当前用这个(`compute_valuation_percentile`)。

2. **自算 PE/PB 历史**:用 价格 × 总股本 / 净利润 TTM 自己算。需要拿到历史股本数(akshare 有 `ak.stock_zh_a_daily` 返回的 outstanding_share 字段)。本 skill MVP 没实现,迭代版本可以加。

## 坑点

1. **Windows 控制台中文乱码**:Windows 默认 GBK 编码,中文打印到 stdout 是乱码,但写入文件用 UTF-8 正常。脚本里所有输出都指定 `encoding='utf-8'`。

2. **akshare 接口字段名变动**:akshare 接口字段名经常变,脚本要写得健壮(用 `.get(field, default)` 而不是直接 `df[field]`)。

3. **新浪源需要 sh/sz 前缀**:A股代码需要加 sh(6/5/9 开头)或 sz(其他)。`stock_a_code_to_symbol` 可以辅助。

4. **港股代码长度**:港股 5 位代码(如 00700),有些接口能接受 700 短码,有些必须 5 位。本 skill 统一用 5 位补零。

5. **CPI 数据倒序**:`macro_china_cpi` 返回 head 是最新数据,tail 是最旧;PPI/LPR 是正序(tail 最新)。处理时要注意。

## 替代数据源(如果 akshare 大面积失效)

- **tushare**:需要注册 token,部分接口需要积分。质量高,A股最推荐。
- **baostock**:免费,A股历史数据质量好。`pip install baostock`。
- **yfinance**:Yahoo Finance,覆盖港股和美股,A股数据不准。
- **efinance**:东方财富,简单易用。

如果用户需要切换数据源,在 `scripts/fetch_data.py` 顶部新增一个 `_impl` 变量,根据值选择不同库调用即可。
