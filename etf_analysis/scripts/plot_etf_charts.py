"""plot_etf_charts.py — ETF 图表:资金流向 + 价格趋势 + 行业对比

生成:
- fund_flow_rank.png — 主力净流入排行条形图
- price_trend.png — Top 3 价格走势(MA20/60 叠加)
- industry_compare.png — 行业内 ETF 规模 + 成交额对比

使用:
    python scripts/plot_etf_charts.py --out-dir ./output/半导体
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC']
plt.rcParams['axes.unicode_minus'] = False


def plot_fund_flow_rank(indicators: dict, out_path: Path) -> None:
    """主力净流入排行条形图"""
    results = indicators.get('results', [])
    if not results:
        return
    # 按主力净流入排序(不是加权分)
    sorted_r = sorted(results, key=lambda x: x.get('fund_flow', {}).get('main_net_inflow', 0) or 0)
    names = [f"{r['ticker']}\n{r['name'][:8]}" for r in sorted_r]
    inflows = [r.get('fund_flow', {}).get('main_net_inflow', 0) or 0 for r in sorted_r]
    inflows_yi = [x / 1e8 for x in inflows]  # 转亿元

    colors = ['#c0392b' if x < 0 else '#27ae60' for x in inflows_yi]

    fig, ax = plt.subplots(figsize=(10, max(4, len(names) * 0.35)))
    bars = ax.barh(names, inflows_yi, color=colors, edgecolor='white')
    ax.axvline(0, color='#333', linewidth=0.8)
    ax.set_xlabel('主力净流入(亿元)', fontsize=10)
    ax.set_title('ETF 主力资金净流入排行', fontsize=13, color='#1a3a5c')
    ax.grid(axis='x', alpha=0.3, linestyle='--')

    # 数值标签
    for bar, v in zip(bars, inflows_yi):
        x_pos = v + (0.05 if v >= 0 else -0.05)
        ha = 'left' if v >= 0 else 'right'
        ax.text(x_pos, bar.get_y() + bar.get_height()/2, f'{v:.2f}',
                va='center', ha=ha, fontsize=9, color='#333')

    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f'[plot] {out_path}', file=sys.stderr)


def plot_price_trend(out_dir: Path, indicators: dict, top_n: int = 3) -> None:
    """Top 3 ETF 价格走势 + 均线"""
    results = indicators.get('results', [])[:top_n]
    if not results:
        return

    fig, axes = plt.subplots(min(len(results), top_n), 1, figsize=(10, 4 * min(len(results), top_n)))
    if len(results) == 1:
        axes = [axes]

    for ax, r in zip(axes, results):
        ticker = r['ticker']
        price_file = out_dir / f'price_{ticker}.csv'
        if not price_file.exists():
            ax.text(0.5, 0.5, f'{ticker} 无历史数据', ha='center', va='center', transform=ax.transAxes)
            ax.set_title(f"{r['name']}", fontsize=10)
            continue
        df = pd.read_csv(price_file)
        df['date'] = pd.to_datetime(df['date'])
        df = df.tail(120)  # 近 120 日

        ax.plot(df['date'], df['close'], color='#2c5282', linewidth=1.2, label='收盘价')
        if len(df) >= 20:
            ax.plot(df['date'], df['close'].rolling(20).mean(),
                    color='#e67e22', linewidth=1, label='MA20')
        if len(df) >= 60:
            ax.plot(df['date'], df['close'].rolling(60).mean(),
                    color='#27ae60', linewidth=1, label='MA60')

        ax.set_title(f"{r['name']} ({ticker})", fontsize=10, color='#1a3a5c')
        ax.legend(loc='best', fontsize=8)
        ax.grid(alpha=0.3, linestyle='--')
        ax.tick_params(axis='x', rotation=30)

    plt.tight_layout()
    out_path = out_dir / 'charts' / 'price_trend.png'
    out_path.parent.mkdir(exist_ok=True)
    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f'[plot] {out_path}', file=sys.stderr)


def plot_industry_compare(indicators: dict, out_path: Path) -> None:
    """行业内 ETF 规模 + 成交额对比"""
    results = indicators.get('results', [])
    if not results:
        return
    names = [f"{r['ticker']}" for r in results]
    mcap = [r.get('liquidity', {}).get('total_mcap', 0) or 0 / 1e8 for r in results]
    amount = [r.get('liquidity', {}).get('amount', 0) or 0 / 1e8 for r in results]

    x = np.arange(len(names))
    width = 0.35
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x - width/2, mcap, width, label='总规模(亿元)', color='#2c5282')
    ax.bar(x + width/2, amount, width, label='成交额(亿元)', color='#e67e22')
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=45, fontsize=8)
    ax.set_ylabel('亿元', fontsize=10)
    ax.set_title('ETF 规模 vs 成交额对比', fontsize=13, color='#1a3a5c')
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f'[plot] {out_path}', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='ETF 图表')
    parser.add_argument('--out-dir', default='./output/etf', help='数据目录')
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    indicators_path = out_dir / 'indicators.json'
    if not indicators_path.exists():
        print(f'错误:找不到 {indicators_path}', file=sys.stderr)
        sys.exit(1)

    with open(indicators_path, encoding='utf-8') as f:
        indicators = json.load(f)

    charts_dir = out_dir / 'charts'
    charts_dir.mkdir(exist_ok=True)

    plot_fund_flow_rank(indicators, charts_dir / 'fund_flow_rank.png')
    plot_price_trend(out_dir, indicators, top_n=3)
    plot_industry_compare(indicators, charts_dir / 'industry_compare.png')

    print('[plot] 全部图表生成完成', file=sys.stderr)


if __name__ == '__main__':
    main()
