"""project_future.py — 基于历史数据外推的财务预测与价格推演

输入: compute_indicators.py 生成的 indicators.json + fetch_data.py 生成的 summary.json
输出: projections.json + charts/projection_chart.png

所有预测基于纯历史数据外推(CAGR + 利润率趋势 + 估值倍数 + 技术面关键位),
不联网、不接受用户假设。预测不等于承诺,实际结果可能显著偏离。

使用:
    python scripts/project_future.py --ticker 01956.HK --out-dir ./output/01956.HK
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

# 中文字体
def setup_chinese_font():
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


# ── 数据提取 ──────────────────────────────────────────────

def extract_annual_data(indicators: dict, market: str) -> dict:
    """从 indicators.json 提取年度数据点。

    A股: financials.series + financials.dates。dates 含 "1231" 的是年报累计值。
    HK: financials.*.history，日期含 "12-31" 的是年度值。
    """
    fin = indicators.get('financials', {})
    annual = {}

    if market == 'A':
        dates = fin.get('dates', [])
        series = fin.get('series', {})
        fy_indices = [(i, d) for i, d in enumerate(dates) if str(d).endswith('1231')]
        for metric, vals in series.items():
            points = []
            for idx, date_str in fy_indices:
                if idx < len(vals) and vals[idx] is not None:
                    year = str(date_str)[:4]
                    points.append((year, float(vals[idx])))
            if points:
                annual[metric] = list(reversed(points))  # oldest-first
        return _map_a_share_metrics(annual)

    elif market == 'HK':
        hk_metrics = {
            'revenue': 'revenue',
            'gross_profit': 'gross_profit',
            'operating_profit': 'operating_profit',
            'net_profit_attributable': 'net_profit_attributable',
            'eps': 'eps',
        }
        for src_key, dst_key in hk_metrics.items():
            if src_key in fin and 'history' in fin[src_key]:
                points = []
                for date_str, val in fin[src_key]['history']:
                    if '12-31' in str(date_str) and val is not None:
                        year = str(date_str)[:4]
                        points.append((year, float(val)))
                if points:
                    annual[dst_key] = list(reversed(points))
        for key in ['equity_attributable', 'total_assets', 'total_liabilities', 'net_assets']:
            if key in fin and 'latest_value' in fin[key]:
                annual[f'{key}_latest'] = fin[key]['latest_value']
        return annual

    return annual


def _map_a_share_metrics(annual: dict) -> dict:
    name_map = {
        '营业总收入': 'revenue',
        '归母净利润': 'net_profit_attributable',
        '毛利率': 'gross_margin',
        'ROE': 'roe',
        '资产负债率': 'debt_ratio',
        '经营现金流': 'operating_cashflow',
    }
    return {name_map.get(k, k): v for k, v in annual.items()}


# ── CAGR 与趋势 ────────────────────────────────────────────

def compute_cagr(annual_values: list) -> float | None:
    """CAGR(百分比)。符号变化时回退到平均 YoY 增速。"""
    vals = [(y, v) for y, v in annual_values if v is not None]
    if len(vals) < 2:
        return None
    oldest, latest = vals[0][1], vals[-1][1]
    n_years = len(vals) - 1
    if oldest == 0:
        return None
    # 符号变化(亏损→盈利):CAGR 无定义
    if (oldest < 0) != (latest < 0):
        return _avg_yoy_growth(vals)
    cagr = (abs(latest) / abs(oldest)) ** (1.0 / n_years) - 1
    # 亏损收窄时,绝对值缩小 = 好事,报告为负增长(亏损在缩小)
    if oldest < 0 and latest < 0 and abs(latest) < abs(oldest):
        cagr = -cagr
    return round(cagr * 100, 2)


def _avg_yoy_growth(vals: list) -> float | None:
    """平均 YoY 增速(百分比),用于符号变化时的回退。"""
    growths = []
    for i in range(1, len(vals)):
        prev, curr = vals[i - 1][1], vals[i][1]
        if prev != 0 and (prev > 0) == (curr > 0):
            growths.append((curr - prev) / abs(prev) * 100)
    if not growths:
        return None
    return round(sum(growths) / len(growths), 2)


def compute_margin_trends(annual_data: dict) -> dict:
    """逐年算毛利率/营业利润率/净利率,简单斜率判断趋势。"""
    rev_points = annual_data.get('revenue', [])
    if not rev_points:
        return {}
    rev_map = {year: val for year, val in rev_points}
    results = {}

    for margin_name, metric_key in [
        ('gross', 'gross_profit'),
        ('operating', 'operating_profit'),
        ('net', 'net_profit_attributable'),
    ]:
        points = annual_data.get(metric_key, [])
        if not points:
            # A股没有 gross_profit,但有 gross_margin ratio
            if margin_name == 'gross' and 'gross_margin' in annual_data:
                margins = annual_data['gross_margin']
            else:
                continue
        else:
            margins = []
            for year, val in points:
                rev = rev_map.get(year)
                if rev and rev != 0:
                    margins.append((year, round(val / rev * 100, 2)))

        if len(margins) >= 2:
            slope = (margins[-1][1] - margins[0][1]) / (len(margins) - 1)
            trend = 'stable' if abs(slope) < 1.0 else ('improving' if slope > 0 else 'deteriorating')
        else:
            slope = None
            trend = 'insufficient_data'

        results[margin_name] = {
            'by_year': margins,
            'trend': trend,
            'slope': round(slope, 2) if slope is not None else None,
        }
    return results


# ── 情景生成 ──────────────────────────────────────────────

def generate_scenarios(annual_data: dict, cagr_revenue: float | None,
                       margin_trends: dict, indicators: dict) -> dict:
    rev_points = annual_data.get('revenue', [])
    if not rev_points:
        return {'error': 'No revenue data'}
    latest_year = int(rev_points[-1][0])
    latest_rev = rev_points[-1][1]

    # 营收增速
    if cagr_revenue is not None:
        base_growth = cagr_revenue / 100.0
    else:
        yoy = indicators.get('financials', {}).get('营收同比增速')
        base_growth = (yoy / 100.0) if yoy else 0.05

    bull_growth = base_growth * 1.3
    bear_growth = max(base_growth * 0.7, -0.30)

    # 净利率
    net_data = margin_trends.get('net', {})
    latest_net_margin = (net_data['by_year'][-1][1]
                         if net_data.get('by_year')
                         else indicators.get('financials', {}).get('净利率_latest', 10.0))
    margin_slope = net_data.get('slope', 0) or 0

    # 毛利率
    gross_data = margin_trends.get('gross', {})
    latest_gross = (gross_data['by_year'][-1][1]
                    if gross_data.get('by_year')
                    else indicators.get('financials', {}).get('毛利率_latest', 50.0))
    gross_slope = gross_data.get('slope', 0) or 0

    def cap_margin(m, lo=-100, hi=90):
        return max(lo, min(hi, m))

    projection_years = [latest_year + i for i in range(1, 4)]
    scenarios = {}

    for name, rev_growth, m_delta, g_delta in [
        ('bull', bull_growth, margin_slope * 1.15 + 0.5, gross_slope * 1.15 + 0.3),
        ('base', base_growth, margin_slope, gross_slope),
        ('bear', bear_growth, margin_slope * 0.5 - 1.0, gross_slope * 0.5 - 0.5),
    ]:
        revs, nps, gms = [], [], []
        prev_rev, prev_nm, prev_gm = latest_rev, latest_net_margin, latest_gross
        for _ in projection_years:
            proj_rev = prev_rev * (1 + rev_growth)
            revs.append(round(proj_rev, 2))
            proj_nm = cap_margin(prev_nm + m_delta, -100, 50)
            nps.append(round(proj_rev * proj_nm / 100, 2))
            prev_rev, prev_nm = proj_rev, proj_nm
            proj_gm = cap_margin(prev_gm + g_delta, 0, 90)
            gms.append(round(proj_gm, 2))
            prev_gm = proj_gm
        scenarios[name] = {'revenue': revs, 'net_profit': nps, 'gross_margin': gms}

    assumptions = {}
    for name, growth, delta in [
        ('bull', bull_growth, margin_slope * 1.15 + 0.5),
        ('base', base_growth, margin_slope),
        ('bear', bear_growth, margin_slope * 0.5 - 1.0),
    ]:
        assumptions[name] = {
            'revenue_growth': round(growth * 100, 2),
            'margin_change': f'{"+" if delta >= 0 else ""}{delta:.1f}pp/yr',
        }

    # 判断是否亏损公司(最新年净利润 < 0)
    np_points = annual_data.get('net_profit_attributable', [])
    is_loss_making = bool(np_points) and np_points[-1][1] < 0

    breakeven = _compute_breakeven(scenarios, projection_years, is_loss_making)

    return {
        'cagr_revenue': cagr_revenue,
        'scenarios': scenarios,
        'key_assumptions': assumptions,
        'breakeven_year': breakeven,
        'projection_years': [str(y) for y in projection_years],
    }


def _compute_breakeven(scenarios: dict, projection_years: list,
                        is_loss_making: bool) -> str | None:
    """亏损公司:找最早盈亏平衡的场景和年份。盈利公司:返回 None。"""
    if not is_loss_making:
        return None
    for scenario_name in ['bull', 'base', 'bear']:
        sc = scenarios.get(scenario_name, {})
        for i, np_val in enumerate(sc.get('net_profit', [])):
            if np_val > 0:
                return f'{projection_years[i]} ({scenario_name} scenario)'
    return None


# ── 股本推导 ──────────────────────────────────────────────

def _derive_shares(indicators: dict, summary: dict, annual_data: dict) -> float | None:
    # 港股:从 EPS / 净利润反推
    eps_points = annual_data.get('eps')
    np_points = annual_data.get('net_profit_attributable')
    if eps_points and np_points:
        latest_eps = eps_points[-1][1]
        latest_np = np_points[-1][1]
        if abs(latest_eps) > 0.001:
            return round(abs(latest_np / latest_eps), 0)
    # A股:从 realtime 取
    rt = summary.get('realtime', {})
    if isinstance(rt, dict):
        for key in ['总股本', 'total_shares', '总股本（股）']:
            val = rt.get(key)
            if val:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
    return None


# ── 技术面关键位 ──────────────────────────────────────────

def _compute_technical_levels(tech: dict, current_price: float) -> dict:
    support, resistance = [], []
    low_52w = tech.get('low_52w')
    high_52w = tech.get('high_52w')
    if low_52w:
        support.append(low_52w)
    if high_52w:
        resistance.append(high_52w)
    for ma_key, dir_key in [('MA60', 'price_vs_MA60'), ('MA120', 'price_vs_MA120'), ('MA250', 'price_vs_MA250')]:
        ma_val = tech.get(ma_key)
        if ma_val:
            pos = tech.get(dir_key, '')
            if '上方' in pos:
                resistance.append(ma_val)
            elif '下方' in pos:
                support.append(ma_val)
    support = sorted(set(s for s in support if s and s < current_price))
    resistance = sorted(set(r for r in resistance if r and r > current_price))
    trend = tech.get('trend', '')
    macd_sig = tech.get('MACD_signal', '')
    if '多头' in trend or '金叉' in macd_sig:
        confirm = '偏多:趋势向上'
    elif '空头' in trend or '死叉' in macd_sig:
        confirm = '偏空:趋势向下'
    else:
        confirm = '中性:区间震荡'
    return {
        'support': [round(s, 4) for s in support[:3]],
        'resistance': [round(r, 4) for r in resistance[:3]],
        'trend_confirmation': confirm,
    }


# ── 价格推演 ──────────────────────────────────────────────

def project_price(indicators: dict, summary: dict, annual_data: dict,
                  financial_proj: dict) -> dict:
    current_price = summary.get('latest_price', {}).get('close')
    if current_price is None:
        return {'error': 'No current price'}
    tech = indicators.get('technical', {})
    shares = _derive_shares(indicators, summary, annual_data)
    np_points = annual_data.get('net_profit_attributable', [])
    is_profitable = bool(np_points) and np_points[-1][1] > 0
    valuation_method = 'technical_only'
    price_scenarios = {}

    # PE 法(盈利 + PE 有效 + 股本可推导)
    pe_pb = indicators.get('latest_pe_pb', {}) or {}
    current_pe = pe_pb.get('pe_ttm')
    if is_profitable and shares and shares > 0 and current_pe and current_pe > 0:
        valuation_method = 'PE'
        for name in ['bull', 'base', 'bear']:
            sc = financial_proj.get('scenarios', {}).get(name, {})
            proj_np_list = sc.get('net_profit', [])
            proj_np = proj_np_list[0] if proj_np_list else None
            if proj_np is not None:
                proj_eps = proj_np / shares
                target_pe = current_pe
                target_price = proj_eps * target_pe
                price_scenarios[name] = {
                    'target_price': round(target_price, 2),
                    'upside': round((target_price - current_price) / current_price * 100, 2),
                    'drivers': [f'预测EPS={proj_eps:.2f}', f'目标PE={target_pe:.1f}'],
                }

    # PS 法(亏损或 PE 不可用)
    if not price_scenarios and shares and shares > 0:
        valuation_method = 'PS'
        rev_points = annual_data.get('revenue', [])
        latest_rev = rev_points[-1][1] if rev_points else None
        if latest_rev:
            current_ps = current_price * shares / latest_rev
            for name, ps_factor in [('bull', 1.2), ('base', 1.0), ('bear', 0.8)]:
                sc = financial_proj.get('scenarios', {}).get(name, {})
                proj_rev_list = sc.get('revenue', [latest_rev])
                proj_rev = proj_rev_list[0] if proj_rev_list else latest_rev
                target_ps = current_ps * ps_factor
                target_price = target_ps * proj_rev / shares
                price_scenarios[name] = {
                    'target_price': round(target_price, 2),
                    'upside': round((target_price - current_price) / current_price * 100, 2),
                    'drivers': [f'目标PS={target_ps:.2f}', f'预测营收={proj_rev / 1e8:.2f}亿'],
                }

    technical_levels = _compute_technical_levels(tech, current_price)

    # 纯技术面回退
    if not price_scenarios:
        valuation_method = 'technical_only'
        support = technical_levels.get('support', [])
        resistance = technical_levels.get('resistance', [])
        for name, target in [
            ('bull', resistance[0] if resistance else current_price * 1.2),
            ('base', current_price),
            ('bear', support[0] if support else current_price * 0.8),
        ]:
            price_scenarios[name] = {
                'target_price': round(target, 2),
                'upside': round((target - current_price) / current_price * 100, 2),
                'drivers': ['技术面:突破阻力' if name == 'bull' else
                            ('技术面:区间震荡' if name == 'base' else '技术面:跌破支撑')],
            }

    return {
        'current_price': current_price,
        'shares_outstanding': shares,
        'valuation_method': valuation_method,
        'scenarios': price_scenarios,
        'technical_levels': technical_levels,
    }


# ── 交叉验证 + 跟踪触发点 ──────────────────────────────────

def generate_cross_validation(financial_proj: dict, price_proj: dict) -> list:
    bullets = []
    scenarios = price_proj.get('scenarios', {})
    fin_scenarios = financial_proj.get('scenarios', {})
    for name in ['bull', 'base', 'bear']:
        fin_sc = fin_scenarios.get(name, {})
        price_sc = scenarios.get(name, {})
        rev = fin_sc.get('revenue', [None])
        rev = rev[0] if rev else None
        np_val = fin_sc.get('net_profit', [None])
        np_val = np_val[0] if np_val else None
        target = price_sc.get('target_price')
        upside = price_sc.get('upside')
        if rev is not None and target is not None:
            rev_str = f'{rev / 1e8:.2f}亿' if abs(rev) > 1e6 else f'{rev:.2f}'
            np_str = (f'{np_val / 1e8:.2f}亿' if np_val and abs(np_val) > 1e6
                      else (f'{np_val:.2f}' if np_val else 'N/A'))
            bullets.append(
                f'{name}: 预测营收 {rev_str}, 净利 {np_str}, '
                f'目标价 {target:.2f} ({upside:+.1f}%)')
    breakeven = financial_proj.get('breakeven_year')
    if breakeven:
        bullets.append(f'盈亏平衡: {breakeven}。若提前兑现,估值从 PS 切换到 PE。')
    return bullets


def generate_tracking_triggers(financial_proj: dict, price_proj: dict,
                                indicators: dict) -> list:
    triggers = []
    breakeven = financial_proj.get('breakeven_year')
    if breakeven:
        triggers.append('半年报/年报:营收增速维持 + 亏损收窄幅度 >5pp')
        triggers.append(f'盈亏平衡进度:目标 {breakeven},关注季度净利润是否转正')
    else:
        triggers.append('半年报/年报:营收增速和利润率稳定性')
    support = price_proj.get('technical_levels', {}).get('support', [])
    resistance = price_proj.get('technical_levels', {}).get('resistance', [])
    if support:
        triggers.append(f'技术面:跌破支撑 {support[0]:.2f} 确认悲观情景')
    if resistance:
        triggers.append(f'技术面:站上阻力 {resistance[0]:.2f} 确认乐观情景')
    triggers.append('宏观/行业:利率变化、政策方向、竞争对手动态')
    return triggers


def compute_confidence(annual_data: dict, indicators: dict) -> str:
    n_years = len(annual_data.get('revenue', []))
    tech = indicators.get('technical', {})
    has_ma250 = 'MA250' in tech and tech.get('MA250') is not None
    has_pe = (indicators.get('latest_pe_pb') or {}).get('pe_ttm') is not None
    score = 0
    if n_years >= 5:
        score += 2
    elif n_years >= 3:
        score += 1
    if has_ma250:
        score += 1
    if has_pe:
        score += 1
    if score >= 4:
        return 'high'
    elif score >= 2:
        return 'medium'
    else:
        return 'low'


# ── 图表 ──────────────────────────────────────────────────

def plot_projection_chart(annual_data: dict, financial_proj: dict,
                          out_path: Path, ticker: str):
    """历史 + 3场景预测营收/净利润对比柱状图。"""
    rev_points = annual_data.get('revenue', [])
    np_points = annual_data.get('net_profit_attributable', [])
    if not rev_points:
        return

    hist_years = [p[0] for p in rev_points]
    hist_rev = [p[1] / 1e8 for p in rev_points]  # 转亿
    hist_np = []
    np_map = {y: v for y, v in np_points} if np_points else {}
    for y in hist_years:
        v = np_map.get(y)
        hist_np.append(v / 1e8 if v else 0)

    proj_years = financial_proj.get('projection_years', [])
    scenarios = financial_proj.get('scenarios', {})

    all_years = hist_years + proj_years
    n_hist = len(hist_years)
    n_proj = len(proj_years)
    x = np.arange(len(all_years))
    width = 0.2

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # 营收
    ax1.bar(x[:n_hist], hist_rev, width=0.5, color='#2c5282', label='历史营收', zorder=3)
    colors = {'bull': '#48bb78', 'base': '#ecc94b', 'bear': '#e53e3e'}
    labels = {'bull': '乐观', 'base': '中性', 'bear': '悲观'}
    for i, name in enumerate(['bear', 'base', 'bull']):
        revs = scenarios.get(name, {}).get('revenue', [])
        if revs:
            revs_yi = [r / 1e8 for r in revs]
            offset = (i - 1) * width
            ax1.bar(x[n_hist:] + offset, revs_yi, width=width, color=colors[name],
                    alpha=0.7, label=f'{labels[name]}预测', zorder=3)
    ax1.set_ylabel('营收（亿元）')
    ax1.set_title(f'{ticker} 营收预测')
    ax1.legend(fontsize=9)
    ax1.grid(axis='y', alpha=0.3, zorder=0)
    ax1.axvline(x=n_hist - 0.5, color='gray', linestyle='--', alpha=0.5)

    # 净利润
    ax2.bar(x[:n_hist], hist_np, width=0.5, color='#2c5282', label='历史净利', zorder=3)
    for i, name in enumerate(['bear', 'base', 'bull']):
        nps = scenarios.get(name, {}).get('net_profit', [])
        if nps:
            nps_yi = [n / 1e8 for n in nps]
            offset = (i - 1) * width
            ax2.bar(x[n_hist:] + offset, nps_yi, width=width, color=colors[name],
                    alpha=0.7, label=f'{labels[name]}预测', zorder=3)
    ax2.set_ylabel('净利润（亿元）')
    ax2.set_title(f'{ticker} 净利润预测')
    ax2.legend(fontsize=9)
    ax2.grid(axis='y', alpha=0.3, zorder=0)
    ax2.axvline(x=n_hist - 0.5, color='gray', linestyle='--', alpha=0.5)
    ax2.axhline(y=0, color='black', linewidth=0.5)

    plt.xticks(x, all_years, fontsize=9)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close()


# ── 主流程 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='历史外推财务预测与价格推演')
    parser.add_argument('--ticker', required=True, help='股票代码')
    parser.add_argument('--out-dir', default=None, help='输出目录(默认 ./output/<ticker>/)')
    parser.add_argument('--no-chart', action='store_true', help='不生成图表')
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else Path('./output') / args.ticker
    indicators_path = out_dir / 'indicators.json'
    summary_path = out_dir / 'summary.json'

    if not indicators_path.exists():
        print(f'错误: 找不到 {indicators_path},请先运行 compute_indicators.py', file=sys.stderr)
        sys.exit(1)
    if not summary_path.exists():
        print(f'错误: 找不到 {summary_path},请先运行 fetch_data.py', file=sys.stderr)
        sys.exit(1)

    with open(indicators_path, 'r', encoding='utf-8') as f:
        indicators = json.load(f)
    with open(summary_path, 'r', encoding='utf-8') as f:
        summary = json.load(f)

    market = indicators.get('market', summary.get('market', 'A'))

    annual_data = extract_annual_data(indicators, market)
    n_years = len(annual_data.get('revenue', []))
    cagr_revenue = compute_cagr(annual_data.get('revenue', []))
    cagr_np = compute_cagr(annual_data.get('net_profit_attributable', []))
    margin_trends = compute_margin_trends(annual_data)
    financial_proj = generate_scenarios(annual_data, cagr_revenue, margin_trends, indicators)
    price_proj = project_price(indicators, summary, annual_data, financial_proj)
    cross_val = generate_cross_validation(financial_proj, price_proj)
    tracking = generate_tracking_triggers(financial_proj, price_proj, indicators)
    confidence = compute_confidence(annual_data, indicators)

    projections = {
        'ticker': args.ticker,
        'projection_time': pd.Timestamp.now().isoformat(),
        'data_years_available': n_years,
        'method_note': '纯历史外推,不考虑外部冲击、管理层变动、政策变化等不可预测因素',
        'financial_projection': {
            'cagr_revenue': cagr_revenue,
            'cagr_net_profit': cagr_np,
            'margin_trends': {
                name: {'trend': d['trend'], 'slope': d.get('slope')}
                for name, d in margin_trends.items()
            },
            'scenarios': financial_proj.get('scenarios', {}),
            'projection_years': financial_proj.get('projection_years', []),
            'key_assumptions': financial_proj.get('key_assumptions', {}),
            'breakeven_year': financial_proj.get('breakeven_year'),
        },
        'price_projection': price_proj,
        'cross_validation': cross_val,
        'tracking_triggers': tracking,
        'confidence': confidence,
    }

    with open(out_dir / 'projections.json', 'w', encoding='utf-8') as f:
        json.dump(projections, f, ensure_ascii=False, indent=2, default=str)

    if not args.no_chart:
        charts_dir = out_dir / 'charts'
        charts_dir.mkdir(parents=True, exist_ok=True)
        try:
            plot_projection_chart(annual_data, financial_proj,
                                 charts_dir / 'projection_chart.png', args.ticker)
        except Exception as e:
            print(f'警告: 图表生成失败: {e}', file=sys.stderr)

    # stdout 输出 JSON 摘要(Claude 读)
    print(json.dumps(projections, ensure_ascii=False, indent=2, default=str))
    print(f'\n[project_future] 输出: {out_dir / "projections.json"}', file=sys.stderr)
    if not args.no_chart:
        print(f'[project_future] 图表: {out_dir / "charts" / "projection_chart.png"}', file=sys.stderr)


if __name__ == '__main__':
    main()
