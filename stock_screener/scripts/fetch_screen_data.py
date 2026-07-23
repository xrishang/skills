"""fetch_screen_data.py — 抓全市场 A 股行情 + 资金流向,合并成筛选基础数据

数据源(已验证):
- stock_zh_a_spot_em():5882 只,含 PE/PB/总市值/流通市值/换手率/量比/60日涨跌幅
- stock_individual_fund_flow_rank(indicator='今日'):5287 只,含主力净流入/超大单/大单/中单/小单

一次抓全市场,合并后供 screen_stocks.py 按策略筛选。

使用:
    python scripts/fetch_screen_data.py --out-dir ./output/screen
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

try:
    import akshare as ak
except ImportError:
    print('错误:需要先 pip install akshare', file=sys.stderr)
    sys.exit(2)


def fetch_spot() -> pd.DataFrame:
    """抓全市场 A 股实时行情(East Money)"""
    print('[fetch] 抓取 stock_zh_a_spot_em...(5882 只,约 80 秒)', file=sys.stderr)
    df = ak.stock_zh_a_spot_em()
    df = df.rename(columns={
        '代码': 'ticker', '名称': 'name', '最新价': 'close',
        '涨跌幅': 'pct_change', '涨跌额': 'change',
        '成交量': 'volume', '成交额': 'amount',
        '振幅': 'amplitude', '最高': 'high', '最低': 'low',
        '今开': 'open', '昨收': 'prev_close',
        '量比': 'volume_ratio', '换手率': 'turnover',
        '市盈率-动态': 'pe', '市净率': 'pb',
        '总市值': 'total_mcap', '流通市值': 'float_mcap',
        '涨速': 'speed_5min', '5分钟涨跌': 'pct_5min',
        '60日涨跌幅': 'pct_60d', '年初至今涨跌幅': 'pct_ytd',
    })
    # 过滤 ST/退市/北交所(可选,保留主板+创业板+科创板)
    # ticker 6开头=沪主板,0/3开头=深主板/创业板,4/8开头=北交所,688=科创板
    df = df[df['ticker'].str.match(r'^(60|00|30|688)')].copy()
    # 过滤 ST
    df = df[~df['name'].str.contains('ST|\\*ST|退', na=False)].copy()

    numeric_cols = ['close', 'pct_change', 'change', 'volume', 'amount',
                    'amplitude', 'high', 'low', 'open', 'prev_close',
                    'volume_ratio', 'turnover', 'pe', 'pb',
                    'total_mcap', 'float_mcap', 'speed_5min', 'pct_5min',
                    'pct_60d', 'pct_ytd']
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')

    print(f'[fetch] 过滤后剩余 {len(df)} 只 A 股', file=sys.stderr)
    return df


def fetch_fund_flow() -> pd.DataFrame:
    """抓全市场个股主力资金流向"""
    print('[fetch] 抓取 stock_individual_fund_flow_rank...(5287 只,约 15 秒)', file=sys.stderr)
    df = ak.stock_individual_fund_flow_rank(indicator='今日')
    df = df.rename(columns={
        '代码': 'ticker', '名称': 'name_flow',
        '最新价': 'close_flow', '今日涨跌幅': 'pct_change_flow',
        '今日主力净流入-净额': 'main_net_inflow',
        '今日主力净流入-净占比': 'main_net_pct',
        '今日超大单净流入-净额': 'super_large_net_inflow',
        '今日超大单净流入-净占比': 'super_large_net_pct',
        '今日大单净流入-净额': 'large_net_inflow',
        '今日大单净流入-净占比': 'large_net_pct',
        '今日中单净流入-净额': 'medium_net_inflow',
        '今日中单净流入-净占比': 'medium_net_pct',
        '今日小单净流入-净额': 'small_net_inflow',
        '今日小单净流入-净占比': 'small_net_pct',
    })
    # 仅保留需要的列
    keep_cols = ['ticker', 'main_net_inflow', 'main_net_pct',
                 'super_large_net_inflow', 'super_large_net_pct',
                 'large_net_inflow', 'large_net_pct',
                 'medium_net_inflow', 'medium_net_pct',
                 'small_net_inflow', 'small_net_pct']
    df = df[[c for c in keep_cols if c in df.columns]].copy()
    for c in keep_cols[1:]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df


def merge(spot: pd.DataFrame, flow: pd.DataFrame) -> pd.DataFrame:
    """合并行情 + 资金流向"""
    print(f'[merge] spot={len(spot)} flow={len(flow)}', file=sys.stderr)
    df = spot.merge(flow, on='ticker', how='left')
    print(f'[merge] 合并后 {len(df)} 只', file=sys.stderr)
    return df


def build_summary(merged: pd.DataFrame) -> dict:
    """生成 summary.json"""
    # 基础统计
    total = len(merged)
    valid_pe = merged['pe'].notna().sum()
    valid_flow = merged['main_net_inflow'].notna().sum()

    # 资金面整体
    inflow_count = (merged['main_net_inflow'] > 0).sum()
    outflow_count = (merged['main_net_inflow'] < 0).sum()
    total_inflow = merged['main_net_inflow'].sum()

    # 涨跌幅分布
    up_count = (merged['pct_change'] > 0).sum()
    down_count = (merged['pct_change'] < 0).sum()
    flat_count = (merged['pct_change'] == 0).sum()

    return {
        'data_date': str(pd.Timestamp.now().date()),
        'total_stocks': total,
        'valid_pe_count': int(valid_pe),
        'valid_flow_count': int(valid_flow),
        'fund_flow_summary': {
            'inflow_count': int(inflow_count),
            'outflow_count': int(outflow_count),
            'total_net_inflow': float(total_inflow) if not pd.isna(total_inflow) else None,
        },
        'market_breadth': {
            'up': int(up_count),
            'down': int(down_count),
            'flat': int(flat_count),
        },
        'columns': list(merged.columns),
    }


def main():
    parser = argparse.ArgumentParser(description='选股数据抓取')
    parser.add_argument('--out-dir', default='./output/screen', help='输出目录')
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    spot = fetch_spot()
    spot.to_csv(out_dir / 'spot_all.csv', index=False, encoding='utf-8-sig')

    flow = fetch_fund_flow()
    flow.to_csv(out_dir / 'fund_flow_all.csv', index=False, encoding='utf-8-sig')

    merged = merge(spot, flow)
    merged.to_csv(out_dir / 'spot_merged.csv', index=False, encoding='utf-8-sig')

    summary = build_summary(merged)
    with open(out_dir / 'summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print(f'[fetch] 输出目录: {out_dir}', file=sys.stderr)
    print(f'[fetch] 合并数据 {len(merged)} 只,columns={len(merged.columns)}', file=sys.stderr)
    print(f'[fetch] summary.json 已生成', file=sys.stderr)


if __name__ == '__main__':
    main()
