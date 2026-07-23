"""fetch_etf_data.py — 抓取 ETF 资金流向排行 + 行业筛选 + 单只详情

数据源(已验证可用):
- fund_etf_spot_em():1554 只 ETF,含主力净流入-净额/成交额/流通市值/涨跌幅/换手率
- fund_etf_fund_daily_em():1582 只 ETF,含类型分类(指数型-股票/海外/固收/其他)
- fund_etf_hist_sina(symbol):单只 ETF 历史日线(前复权)

两种模式:
1. top-n:全市场按主力净流入排序,取 Top N
2. industry:按名称关键词筛选行业,再按主力净流入排序

使用:
    # 全市场 Top 20
    python scripts/fetch_etf_data.py --mode top-n --top 20 --out-dir ./output/top20

    # 半导体行业
    python scripts/fetch_etf_data.py --mode industry --keyword 半导体 --out-dir ./output/半导体

    # 指定单只 ETF
    python scripts/fetch_etf_data.py --mode single --ticker 512480 --out-dir ./output/512480
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

try:
    import akshare as ak
except ImportError:
    print('错误:需要先 pip install akshare', file=sys.stderr)
    sys.exit(2)


# 常见行业关键词(用于名称匹配)
INDUSTRY_KEYWORDS = {
    '半导体': ['半导体', '芯片', '集成电路', 'IT'],
    '医药': ['医药', '医疗', '生物', '创新药', 'CXO'],
    '新能源': ['新能源', '光伏', '锂电', '电池', '风电', '储能', '碳中和'],
    '消费': ['消费', '食品', '白酒', '家电', '商贸'],
    '科技': ['科技', '互联网', '人工智能', 'AI', 'TMT', '信息', '通信', '计算机'],
    '金融': ['金融', '券商', '证券', '银行', '保险'],
    '军工': ['军工', '国防', '航空'],
    '地产': ['地产', '房地产', '基建'],
    '有色': ['有色', '黄金', '铜', '稀土', '钢铁'],
    '环保': ['环保', '碳中和', '绿电'],
    '宽基': ['沪深300', '中证500', '中证1000', '创业板', '科创50', '上证50', '上证180', '深证'],
    '红利': ['红利', '股息'],
    '海外': ['纳斯达克', '标普', '恒生', '日经', '德国'],
}


def fetch_etf_spot() -> pd.DataFrame:
    """抓全市场 ETF 实时行情 + 资金流向"""
    print('[fetch] 抓取 fund_etf_spot_em...', file=sys.stderr)
    df = ak.fund_etf_spot_em()
    df = df.rename(columns={
        '代码': 'ticker', '名称': 'name', '最新价': 'close',
        '涨跌幅': 'pct_change', '涨跌额': 'change',
        '成交量': 'volume', '成交额': 'amount',
        '主力净流入-净额': 'main_net_inflow', '主力净流入-净占比': 'main_net_pct',
        '超大单净流入-净额': 'super_large_net_inflow', '超大单净流入-净占比': 'super_large_net_pct',
        '大单净流入-净额': 'large_net_inflow', '大单净流入-净占比': 'large_net_pct',
        '中单净流入-净额': 'medium_net_inflow', '中单净流入-净占比': 'medium_net_pct',
        '小单净流入-净额': 'small_net_inflow', '小单净流入-净占比': 'small_net_pct',
        '流通市值': 'float_mcap', '总市值': 'total_mcap',
        '换手率': 'turnover', '量比': 'volume_ratio',
        '最新份额': 'shares', '数据日期': 'data_date',
    })
    # 转数值
    numeric_cols = ['close', 'pct_change', 'change', 'volume', 'amount',
                    'main_net_inflow', 'main_net_pct',
                    'super_large_net_inflow', 'super_large_net_pct',
                    'large_net_inflow', 'large_net_pct',
                    'medium_net_inflow', 'medium_net_pct',
                    'small_net_inflow', 'small_net_pct',
                    'float_mcap', 'total_mcap', 'turnover', 'volume_ratio', 'shares']
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df


def fetch_etf_type() -> pd.DataFrame:
    """抓 ETF 类型分类"""
    print('[fetch] 抓取 fund_etf_fund_daily_em...', file=sys.stderr)
    df = ak.fund_etf_fund_daily_em()
    df = df.rename(columns={'基金代码': 'ticker', '基金简称': 'name', '类型': 'fund_type'})
    return df[['ticker', 'name', 'fund_type']]


def filter_by_industry(df: pd.DataFrame, keyword: str) -> pd.DataFrame:
    """按名称关键词筛选行业 ETF"""
    # 先查内置关键词
    matched_keywords = []
    if keyword in INDUSTRY_KEYWORDS:
        for kw in INDUSTRY_KEYWORDS[keyword]:
            matched_keywords.append(kw)
    else:
        matched_keywords.append(keyword)

    mask = df['name'].str.contains('|'.join(matched_keywords), na=False, regex=True)
    filtered = df[mask].copy()
    # 推断行业标签
    filtered['industry'] = keyword
    print(f'[filter] 关键词={keyword},匹配 {len(filtered)} 只 ETF', file=sys.stderr)
    return filtered


def rank_top_n(df: pd.DataFrame, top: int = 20) -> pd.DataFrame:
    """按主力净流入排序取 Top N"""
    df = df.dropna(subset=['main_net_inflow'])
    df = df.sort_values('main_net_inflow', ascending=False)
    return df.head(top)


def fetch_single_etf_history(ticker: str, days: int = 250) -> pd.DataFrame:
    """抓单只 ETF 历史日线(Sina)"""
    # Sina 格式:sz159xxx / sh510xxx / sh512xxx
    if ticker.startswith('1'):
        sina_symbol = 'sz' + ticker
    elif ticker.startswith('5'):
        sina_symbol = 'sh' + ticker
    else:
        sina_symbol = 'sh' + ticker

    print(f'[fetch] 抓取 fund_etf_hist_sina({sina_symbol})...', file=sys.stderr)
    try:
        df = ak.fund_etf_hist_sina(symbol=sina_symbol)
        if df is None or df.empty:
            return pd.DataFrame()
        # 取最近 days 天
        df = df.tail(days).copy()
        df = df.rename(columns={
            'date': 'date', 'open': 'open', 'high': 'high',
            'low': 'low', 'close': 'close',
            'volume': 'volume', 'amount': 'amount',
        })
        df['date'] = pd.to_datetime(df['date'])
        return df
    except Exception as e:
        print(f'[fetch] 历史数据抓取失败 {ticker}: {type(e).__name__}: {e}', file=sys.stderr)
        return pd.DataFrame()


def build_summary(spot_df: pd.DataFrame, ranked_df: pd.DataFrame,
                  mode: str, keyword: str | None, top: int,
                  etf_type_df: pd.DataFrame | None) -> dict:
    """生成 summary.json 摘要"""
    # 合并类型信息
    if etf_type_df is not None:
        ranked_df = ranked_df.merge(etf_type_df[['ticker', 'fund_type']],
                                    on='ticker', how='left')
    else:
        ranked_df['fund_type'] = None

    records = []
    for _, row in ranked_df.iterrows():
        rec = {
            'ticker': row.get('ticker'),
            'name': row.get('name'),
            'close': row.get('close'),
            'pct_change': row.get('pct_change'),
            'volume': row.get('volume'),
            'amount': row.get('amount'),
            'main_net_inflow': row.get('main_net_inflow'),
            'main_net_pct': row.get('main_net_pct'),
            'super_large_net_inflow': row.get('super_large_net_inflow'),
            'large_net_inflow': row.get('large_net_inflow'),
            'float_mcap': row.get('float_mcap'),
            'total_mcap': row.get('total_mcap'),
            'turnover': row.get('turnover'),
            'shares': row.get('shares'),
            'fund_type': row.get('fund_type'),
            'industry': row.get('industry', keyword),
        }
        records.append(rec)

    summary = {
        'mode': mode,
        'keyword': keyword,
        'top_n': top,
        'total_etfs_in_market': len(spot_df),
        'matched_count': len(ranked_df),
        'ranking_by': 'main_net_inflow',
        'data_date': str(spot_df['data_date'].iloc[0]) if 'data_date' in spot_df.columns and not spot_df.empty else None,
        'etfs': records,
    }
    return summary


def main():
    parser = argparse.ArgumentParser(description='ETF 数据抓取')
    parser.add_argument('--mode', choices=['top-n', 'industry', 'single'],
                        default='top-n', help='模式:全市场Top N / 行业筛选 / 单只')
    parser.add_argument('--top', type=int, default=20, help='Top N(默认 20)')
    parser.add_argument('--keyword', default=None, help='行业关键词(如 半导体/医药/新能源)')
    parser.add_argument('--ticker', default=None, help='单只 ETF 代码(如 512480)')
    parser.add_argument('--out-dir', default='./output/etf', help='输出目录')
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'charts').mkdir(exist_ok=True)

    # 抓全市场 ETF 行情
    spot_df = fetch_etf_spot()

    # 抓类型分类
    try:
        type_df = fetch_etf_type()
    except Exception as e:
        print(f'[fetch] 类型分类抓取失败: {e}', file=sys.stderr)
        type_df = None

    if args.mode == 'top-n':
        ranked_df = rank_top_n(spot_df, args.top)
        keyword = None
        print(f'[mode] 全市场 Top {args.top} by 主力净流入', file=sys.stderr)
    elif args.mode == 'industry':
        if not args.keyword:
            print('错误:industry 模式需要 --keyword 参数', file=sys.stderr)
            sys.exit(1)
        keyword = args.keyword
        filtered = filter_by_industry(spot_df, keyword)
        ranked_df = rank_top_n(filtered, args.top)
        print(f'[mode] 行业={keyword},Top {args.top}', file=sys.stderr)
    elif args.mode == 'single':
        if not args.ticker:
            print('错误:single 模式需要 --ticker 参数', file=sys.stderr)
            sys.exit(1)
        ranked_df = spot_df[spot_df['ticker'] == args.ticker].copy()
        keyword = None
        if ranked_df.empty:
            print(f'错误:找不到 ETF {args.ticker}', file=sys.stderr)
            sys.exit(1)

    # 保存排行 CSV
    ranked_df.to_csv(out_dir / 'etf_ranking.csv', index=False, encoding='utf-8-sig')
    spot_df.to_csv(out_dir / 'etf_spot_all.csv', index=False, encoding='utf-8-sig')

    # 生成 summary.json
    summary = build_summary(spot_df, ranked_df, args.mode, keyword, args.top, type_df)

    # 如果是 single 模式,抓历史价格
    if args.mode == 'single' and args.ticker:
        hist_df = fetch_single_etf_history(args.ticker, days=250)
        if not hist_df.empty:
            hist_df.to_csv(out_dir / 'price_daily.csv', index=False, encoding='utf-8-sig')
            summary['single_etf'] = {
                'ticker': args.ticker,
                'history_rows': len(hist_df),
                'history_start': str(hist_df['date'].iloc[0].date()) if not hist_df.empty else None,
                'history_end': str(hist_df['date'].iloc[-1].date()) if not hist_df.empty else None,
            }
    # 如果是 industry 或 top-n 模式,对 Top 3 抓历史价格
    elif args.mode in ('industry', 'top-n') and len(ranked_df) > 0:
        top3_hist = {}
        for _, row in ranked_df.head(3).iterrows():
            t = row['ticker']
            hist = fetch_single_etf_history(t, days=250)
            if not hist.empty:
                hist.to_csv(out_dir / f'price_{t}.csv', index=False, encoding='utf-8-sig')
                top3_hist[t] = {
                    'name': row['name'],
                    'rows': len(hist),
                    'start': str(hist['date'].iloc[0].date()),
                    'end': str(hist['date'].iloc[-1].date()),
                }
            time.sleep(0.3)
        summary['top3_history'] = top3_hist

    with open(out_dir / 'summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print(f'[fetch] 输出目录: {out_dir}', file=sys.stderr)
    print(f'[fetch] 排行 ETF 数: {len(ranked_df)}', file=sys.stderr)
    print(f'[fetch] summary.json 已生成', file=sys.stderr)


if __name__ == '__main__':
    main()
