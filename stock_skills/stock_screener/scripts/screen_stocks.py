"""screen_stocks.py — 4 种策略选股

策略:
1. technical:技术面选股(趋势 + 放量 + 换手活跃)
2. fundamental:基本面选股(低 PE + 合理 PB + 大市值)
3. fund_flow:资金面选股(主力净流入 + 净占比强)
4. oversold:超跌反弹(60日跌深 + 今日企稳 + 资金回流)

使用:
    # 技术面 Top 20
    python scripts/screen_stocks.py --strategy technical --top 20 --out-dir ./output/screen

    # 基本面 Top 20
    python scripts/screen_stocks.py --strategy fundamental --top 20 --out-dir ./output/screen

    # 资金面 Top 20
    python scripts/screen_stocks.py --strategy fund_flow --top 20 --out-dir ./output/screen

    # 超跌反弹 Top 20
    python scripts/screen_stocks.py --strategy oversold --top 20 --out-dir ./output/screen

    # 全部 4 策略
    python scripts/screen_stocks.py --strategy all --top 20 --out-dir ./output/screen
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import numpy as np


def load_merged(out_dir: Path) -> pd.DataFrame:
    """加载合并后的全市场数据"""
    csv_path = out_dir / 'spot_merged.csv'
    if not csv_path.exists():
        print(f'错误:找不到 {csv_path},请先跑 fetch_screen_data.py', file=sys.stderr)
        sys.exit(1)
    return pd.read_csv(csv_path, dtype={'ticker': str})


def screen_technical(df: pd.DataFrame, top: int = 20) -> pd.DataFrame:
    """技术面选股:趋势向上 + 放量 + 换手活跃

    条件:
    - 60日涨跌幅 > 10%(中期趋势向上)
    - 今日涨跌幅 > 2%(当日强势)
    - 量比 > 1.5(放量)
    - 换手率 > 3%(活跃)
    - 成交额 > 2 亿(流动性)
    排序:60日涨跌幅 + 今日涨跌幅 + 量比 综合分
    """
    d = df.copy()
    d = d[
        (d['pct_60d'] > 10) &
        (d['pct_change'] > 2) &
        (d['volume_ratio'] > 1.5) &
        (d['turnover'] > 3) &
        (d['amount'] > 2e8)
    ].copy()
    # 综合分:标准化后相加
    for c in ['pct_60d', 'pct_change', 'volume_ratio']:
        d[c + '_z'] = (d[c] - d[c].mean()) / (d[c].std() + 1e-9)
    d['score'] = d['pct_60d_z'] + d['pct_change_z'] + d['volume_ratio_z']
    d = d.sort_values('score', ascending=False).head(top)
    d['strategy'] = 'technical'
    return d


def screen_fundamental(df: pd.DataFrame, top: int = 20) -> pd.DataFrame:
    """基本面选股:低估值 + 合理 PB + 大市值 + 盈利

    条件:
    - PE 10-30(偏低估值,排除亏损和泡沫)
    - PB 1-5(合理,排除破净和高泡沫)
    - 总市值 > 100 亿(大中盘,流动性)
    - 今日涨跌幅 > 0(当日有资金关注)
    排序:PE 升序(越低越便宜)+ 市值降序
    """
    d = df.copy()
    d = d[
        (d['pe'] > 10) & (d['pe'] < 30) &
        (d['pb'] > 1) & (d['pb'] < 5) &
        (d['total_mcap'] > 1e10) &
        (d['pct_change'] > 0)
    ].copy()
    # 综合分:PE 越低越好(取负)+ 市值越大越好
    for c in ['pe', 'total_mcap']:
        d[c + '_z'] = (d[c] - d[c].mean()) / (d[c].std() + 1e-9)
    d['score'] = -d['pe_z'] + d['total_mcap_z']
    d = d.sort_values('score', ascending=False).head(top)
    d['strategy'] = 'fundamental'
    return d


def screen_fund_flow(df: pd.DataFrame, top: int = 20) -> pd.DataFrame:
    """资金面选股:主力净流入大 + 净占比强 + 大中盘

    条件:
    - 主力净流入 > 5000 万
    - 净占比 > 5%
    - 总市值 > 50 亿(排除小盘股资金冲击)
    - 今日涨跌幅 > 1%(资金推动上涨)
    排序:净流入金额
    """
    d = df.copy()
    d = d[
        (d['main_net_inflow'] > 5e7) &
        (d['main_net_pct'] > 5) &
        (d['total_mcap'] > 5e9) &
        (d['pct_change'] > 1)
    ].copy()
    d = d.sort_values('main_net_inflow', ascending=False).head(top)
    d['strategy'] = 'fund_flow'
    return d


def screen_oversold(df: pd.DataFrame, top: int = 20) -> pd.DataFrame:
    """超跌反弹选股:60日跌深 + 今日企稳 + 资金回流

    条件:
    - 60日涨跌幅 < -20%(超跌)
    - 今日涨跌幅 > 0(企稳反弹)
    - 主力净流入 > 0(资金回流)
    - 总市值 > 50 亿(排除小盘股)
    排序:60日跌幅(越跌越反弹潜力)+ 今日涨幅 + 净流入 综合分
    """
    d = df.copy()
    d = d[
        (d['pct_60d'] < -20) &
        (d['pct_change'] > 0) &
        (d['main_net_inflow'] > 0) &
        (d['total_mcap'] > 5e9)
    ].copy()
    # 综合分:60日跌幅越深越好(负数越小越好,取负 → 正)+ 今日涨幅 + 净流入
    for c in ['pct_60d', 'pct_change', 'main_net_inflow']:
        d[c + '_z'] = (d[c] - d[c].mean()) / (d[c].std() + 1e-9)
    d['score'] = -d['pct_60d_z'] + d['pct_change_z'] + d['main_net_inflow_z']
    d = d.sort_values('score', ascending=False).head(top)
    d['strategy'] = 'oversold'
    return d


def to_records(df: pd.DataFrame) -> list[dict]:
    """转成 JSON 可序列化的 records"""
    str_cols = {'ticker', 'name', 'strategy'}
    int_cols = {'volume', 'amount', 'total_mcap', 'float_mcap',
                'main_net_inflow', 'super_large_net_inflow', 'large_net_inflow',
                'medium_net_inflow', 'small_net_inflow'}
    cols = ['ticker', 'name', 'close', 'pct_change', 'pct_60d', 'pct_ytd',
            'volume_ratio', 'turnover', 'amount', 'pe', 'pb',
            'total_mcap', 'float_mcap',
            'main_net_inflow', 'main_net_pct',
            'super_large_net_inflow', 'large_net_inflow',
            'score', 'strategy']
    records = []
    for _, row in df.iterrows():
        rec = {}
        for c in cols:
            if c not in df.columns:
                continue
            v = row[c]
            if pd.isna(v):
                rec[c] = None
                continue
            if c in str_cols:
                # 强制字符串,去掉可能的 .0 后缀
                s = str(v)
                if s.endswith('.0'):
                    s = s[:-2]
                rec[c] = s
                continue
            try:
                fv = float(v)
                if c in int_cols:
                    rec[c] = int(fv)
                else:
                    rec[c] = fv
            except (ValueError, TypeError):
                rec[c] = str(v)
        records.append(rec)
    return records


def main():
    parser = argparse.ArgumentParser(description='选股策略筛选')
    parser.add_argument('--strategy',
                        choices=['technical', 'fundamental', 'fund_flow', 'oversold', 'all'],
                        default='all', help='选股策略')
    parser.add_argument('--top', type=int, default=20, help='每策略 Top N')
    parser.add_argument('--out-dir', default='./output/screen', help='数据目录')
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    df = load_merged(out_dir)
    print(f'[screen] 加载 {len(df)} 只股票', file=sys.stderr)

    strategies = {
        'technical': screen_technical,
        'fundamental': screen_fundamental,
        'fund_flow': screen_fund_flow,
        'oversold': screen_oversold,
    }

    if args.strategy == 'all':
        run_strategies = list(strategies.keys())
    else:
        run_strategies = [args.strategy]

    results = {}
    all_candidates = []
    for name in run_strategies:
        fn = strategies[name]
        result_df = fn(df, args.top)
        records = to_records(result_df)
        results[name] = {
            'count': len(records),
            'description': fn.__doc__.strip().split('\n')[0] if fn.__doc__ else '',
            'candidates': records,
        }
        all_candidates.extend(records)
        print(f'[screen] {name}:筛选出 {len(records)} 只', file=sys.stderr)

    output = {
        'screen_time': str(pd.Timestamp.now()),
        'total_universe': len(df),
        'top_n': args.top,
        'strategies': results,
    }

    with open(out_dir / 'candidates.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    # 每策略单独 CSV
    for name, data in results.items():
        if data['candidates']:
            pd.DataFrame(data['candidates']).to_csv(
                out_dir / f'candidates_{name}.csv',
                index=False, encoding='utf-8-sig'
            )

    print(f'[screen] 输出:{out_dir / "candidates.json"}', file=sys.stderr)
    print(f'[screen] 每策略 CSV 已生成', file=sys.stderr)


if __name__ == '__main__':
    main()
