"""plot_charts.py — 生成股价趋势、技术指标、财务趋势、估值分位图表

输入: fetch_data.py / compute_indicators.py 生成的 output/<ticker>/ 目录
输出: 4 张 PNG(在 output/<ticker>/charts/ 下)

matplotlib 在 Windows 下中文需要 SimHei 字体。脚本会自动尝试设置。
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # 无头模式
import matplotlib.pyplot as plt
from matplotlib import font_manager


def setup_chinese_font():
    """Windows 下用 SimHei 显示中文。失败则警告但不退出"""
    candidates = ['SimHei', 'Microsoft YaHei', 'Microsoft JhengHei', 'Arial Unicode MS', 'sans-serif']
    for name in candidates:
        try:
            font_manager.findfont(name, fallback_to_default=False)
            plt.rcParams['font.sans-serif'] = [name]
            plt.rcParams['axes.unicode_minus'] = False
            return name
        except Exception:
            continue
    plt.rcParams['axes.unicode_minus'] = False
    return None


setup_chinese_font()


def plot_price_trend(price_df: pd.DataFrame, out_path: Path, ticker: str):
    """股价走势 + 均线 + 成交量"""
    df = price_df.sort_values('date').reset_index(drop=True).copy()
    df['date'] = pd.to_datetime(df['date'])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), gridspec_kw={'height_ratios': [3, 1]}, sharex=True)

    close = df['close'].astype(float)
    ax1.plot(df['date'], close, color='#333333', linewidth=1.2, label='收盘价')

    for p, color in [(60, '#2E86AB'), (120, '#A23B72'), (250, '#F18F01')]:
        if len(df) >= p:
            ax1.plot(df['date'], close.rolling(p).mean(), label=f'MA{p}', linewidth=1.0, alpha=0.85, color=color)

    ax1.set_title(f'{ticker} 股价走势与均线')
    ax1.set_ylabel('价格')
    ax1.legend(loc='upper left', fontsize=9)
    ax1.grid(True, alpha=0.3)

    # 成交量
    colors = ['#e74c3c' if c < o else '#27ae60' for o, c in zip(df['open'].astype(float), close)]
    ax2.bar(df['date'], df['volume'].astype(float), color=colors, width=1.0, alpha=0.7)
    ax2.set_ylabel('成交量')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close()


def plot_technical_indicators(price_df: pd.DataFrame, out_path: Path, ticker: str):
    """MACD + RSI 副图"""
    df = price_df.sort_values('date').reset_index(drop=True).copy()
    df['date'] = pd.to_datetime(df['date'])
    close = df['close'].astype(float)

    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True,
                              gridspec_kw={'height_ratios': [2, 1, 1]})

    # 1. 收盘价
    axes[0].plot(df['date'], close, color='#333333', linewidth=1.2)
    axes[0].set_title(f'{ticker} 价格 / MACD / RSI')
    axes[0].set_ylabel('价格')
    axes[0].grid(True, alpha=0.3)

    # 2. MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = (dif - dea) * 2

    axes[1].plot(df['date'], dif, label='DIF', color='#2E86AB', linewidth=1)
    axes[1].plot(df['date'], dea, label='DEA', color='#F18F01', linewidth=1)
    colors = ['#e74c3c' if h < 0 else '#27ae60' for h in hist]
    axes[1].bar(df['date'], hist, color=colors, width=1.0, alpha=0.6, label='MACD Hist')
    axes[1].axhline(0, color='gray', linewidth=0.5)
    axes[1].set_ylabel('MACD')
    axes[1].legend(loc='upper left', fontsize=9)
    axes[1].grid(True, alpha=0.3)

    # 3. RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    axes[2].plot(df['date'], rsi, color='#A23B72', linewidth=1.2)
    axes[2].axhline(70, color='red', linestyle='--', linewidth=0.7, alpha=0.6)
    axes[2].axhline(30, color='green', linestyle='--', linewidth=0.7, alpha=0.6)
    axes[2].fill_between(df['date'], 30, 70, alpha=0.08, color='gray')
    axes[2].set_ylabel('RSI(14)')
    axes[2].set_xlabel('日期')
    axes[2].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close()


def plot_financial_trends(financials: dict, market: str, out_path: Path, ticker: str):
    """财务指标多年趋势。A股和港股数据格式不同"""
    fig, ax = plt.subplots(figsize=(11, 5))

    if market == 'A':
        series = financials.get('series', {})
        dates = financials.get('dates', [])
        # 取最近 8 个季度,正序(旧到新)
        if dates:
            dates_chrono = list(reversed(dates))[:8]
            for metric, color, label in [
                ('ROE', '#A23B72', 'ROE(%)'),
                ('毛利率', '#2E86AB', '毛利率(%)'),
                ('净利率', '#F18F01', '净利率(%)'),
            ]:
                vals = series.get(metric, [])
                if vals:
                    vals_chrono = list(reversed(vals[:8]))
                    # 把 None 转 nan
                    vals_clean = [float(v) if v is not None else np.nan for v in vals_chrono]
                    ax.plot(range(len(dates_chrono)), vals_clean, marker='o', label=label, color=color, linewidth=1.5)
            ax.set_xticks(range(len(dates_chrono)))
            ax.set_xticklabels(dates_chrono, rotation=45, ha='right', fontsize=8)

    elif market == 'HK':
        # 港股用 history 列表(已倒序,需要反转为正序)
        for metric_key, color, label in [
            ('revenue', '#2E86AB', '营收(亿)'),
            ('net_profit_attributable', '#A23B72', '归母净利润(亿)'),
            ('gross_profit', '#F18F01', '毛利(亿)'),
        ]:
            if metric_key in financials and 'history' in financials[metric_key]:
                hist = financials[metric_key]['history']
                hist_chrono = list(reversed(hist))[:8]
                dates = [h[0][:7] for h in hist_chrono]  # YYYY-MM
                vals = [float(h[1]) / 1e8 if h[1] else np.nan for h in hist_chrono]  # 转亿
                ax.plot(range(len(dates)), vals, marker='o', label=label, color=color, linewidth=1.5)
                ax.set_xticks(range(len(dates)))
                ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)

    ax.set_title(f'{ticker} 关键财务指标趋势')
    ax.set_ylabel('数值')
    ax.legend(loc='best', fontsize=9)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close()


def plot_valuation_percentile(price_df: pd.DataFrame, out_path: Path, ticker: str):
    """价格历史分位(代理估值分位)"""
    df = price_df.sort_values('date').reset_index(drop=True).copy()
    df['date'] = pd.to_datetime(df['date'])
    close = df['close'].astype(float)

    fig, ax = plt.subplots(figsize=(11, 4.5))

    # 用 3 年数据画图
    plot_df = df.tail(750) if len(df) >= 750 else df
    plot_close = plot_df['close'].astype(float)

    ax.plot(plot_df['date'], plot_close, color='#333333', linewidth=1.2, label='收盘价')

    # 52 周高低
    if len(plot_df) >= 250:
        recent = plot_df.tail(250)
        ax.axhline(recent['high'].astype(float).max(), color='red', linestyle='--', alpha=0.5, label='52周高')
        ax.axhline(recent['low'].astype(float).min(), color='green', linestyle='--', alpha=0.5, label='52周低')

    # 当前价标记
    latest = close.iloc[-1]
    ax.axhline(latest, color='orange', linestyle=':', alpha=0.7, label=f'当前价 {latest:.2f}')

    ax.set_title(f'{ticker} 价格历史区间(估值代理)')
    ax.set_ylabel('价格')
    ax.legend(loc='best', fontsize=9)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close()


# ---------- 主流程 ----------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticker', required=True)
    parser.add_argument('--out-dir', default=None)
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else Path('./output') / args.ticker
    charts_dir = out_dir / 'charts'
    charts_dir.mkdir(parents=True, exist_ok=True)

    indicators_path = out_dir / 'indicators.json'
    if not indicators_path.exists():
        print(f'错误: 找不到 {indicators_path},请先运行 compute_indicators.py', file=sys.stderr)
        sys.exit(1)

    with open(indicators_path, 'r', encoding='utf-8') as f:
        indicators = json.load(f)

    market = indicators.get('market')

    price_path = out_dir / 'price_daily.csv'
    if price_path.exists():
        price_df = pd.read_csv(price_path, encoding='utf-8')
        price_df['date'] = pd.to_datetime(price_df['date'])

        print(f'[plot] 生成 price_trend.png...')
        plot_price_trend(price_df, charts_dir / 'price_trend.png', args.ticker)
        print(f'[plot] 生成 technical_indicators.png...')
        plot_technical_indicators(price_df, charts_dir / 'technical_indicators.png', args.ticker)
        print(f'[plot] 生成 valuation_percentile.png...')
        plot_valuation_percentile(price_df, charts_dir / 'valuation_percentile.png', args.ticker)
    else:
        print('警告: price_daily.csv 不存在,跳过价格相关图表', file=sys.stderr)

    financials = indicators.get('financials', {})
    if financials:
        print(f'[plot] 生成 financial_trends.png...')
        plot_financial_trends(financials, market, charts_dir / 'financial_trends.png', args.ticker)
    else:
        print('警告: 无财务数据,跳过 financial_trends.png', file=sys.stderr)

    print(f'\n[plot_charts] 输出目录: {charts_dir}', file=sys.stderr)


if __name__ == '__main__':
    main()
