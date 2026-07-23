"""analyze_etf.py — ETF 分析:技术指标 + 资金面 + 流动性 + 行业估值

读取 fetch_etf_data.py 生成的 summary.json + price_*.csv,
输出 indicators.json,包含:
- 技术指标:MA/MACD/RSI/KDJ
- 资金面指标:主力净流入/净占比/超大单/大单/中单/小单
- 流动性指标:规模/成交额/换手率/量比
- 行业估值:跟踪指数 PE 分位(如可获取)
- 信号解读

使用:
    python scripts/analyze_etf.py --out-dir ./output/半导体
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import numpy as np


def compute_ma(close: pd.Series, periods: list[int]) -> dict:
    """计算简单移动平均"""
    result = {}
    for p in periods:
        if len(close) >= p:
            ma = close.rolling(p).mean().iloc[-1]
            result[f'MA{p}'] = round(float(ma), 4) if not pd.isna(ma) else None
        else:
            result[f'MA{p}'] = None
    return result


def compute_macd(close: pd.Series) -> dict:
    """计算 MACD:EMA12 / EMA26 / DIF / DEA / MACD柱"""
    if len(close) < 35:
        return {'DIF': None, 'DEA': None, 'MACD': None, 'signal': '数据不足'}
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_bar = (dif - dea) * 2
    signal = '金叉' if dif.iloc[-1] > dea.iloc[-1] else '死叉'
    if len(dif) >= 2 and dif.iloc[-1] * dif.iloc[-2] < 0:
        signal += '(刚过零轴)'
    return {
        'DIF': round(float(dif.iloc[-1]), 4),
        'DEA': round(float(dea.iloc[-1]), 4),
        'MACD': round(float(macd_bar.iloc[-1]), 4),
        'signal': signal,
    }


def compute_rsi(close: pd.Series, period: int = 14) -> dict:
    """计算 RSI"""
    if len(close) < period + 1:
        return {'RSI': None, 'signal': '数据不足'}
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(period).mean().iloc[-1]
    avg_loss = loss.rolling(period).mean().iloc[-1]
    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    sig = '超买' if rsi > 70 else ('超卖' if rsi < 30 else '中性')
    return {'RSI': round(float(rsi), 2), 'signal': sig}


def compute_kdj(close: pd.Series, high: pd.Series, low: pd.Series,
                n: int = 9) -> dict:
    """计算 KDJ"""
    if len(close) < n:
        return {'K': None, 'D': None, 'J': None, 'signal': '数据不足'}
    low_n = low.rolling(n).min()
    high_n = high.rolling(n).max()
    rsv = (close - low_n) / (high_n - low_n) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d
    sig = '超买' if j.iloc[-1] > 100 else ('超卖' if j.iloc[-1] < 0 else '中性')
    if len(k) >= 2 and k.iloc[-1] > d.iloc[-1] and k.iloc[-2] <= d.iloc[-2]:
        sig += '(金叉)'
    elif len(k) >= 2 and k.iloc[-1] < d.iloc[-1] and k.iloc[-2] >= d.iloc[-2]:
        sig += '(死叉)'
    return {
        'K': round(float(k.iloc[-1]), 2),
        'D': round(float(d.iloc[-1]), 2),
        'J': round(float(j.iloc[-1]), 2),
        'signal': sig,
    }


def compute_technical(price_df: pd.DataFrame) -> dict:
    """计算技术指标"""
    if price_df.empty or len(price_df) < 5:
        return {'error': '历史数据不足'}
    close = price_df['close'].astype(float)
    high = price_df['high'].astype(float) if 'high' in price_df.columns else close
    low = price_df['low'].astype(float) if 'low' in price_df.columns else close

    ma = compute_ma(close, [5, 10, 20, 60, 120, 250])
    macd = compute_macd(close)
    rsi = compute_rsi(close, 14)
    kdj = compute_kdj(close, high, low, 9)

    current = float(close.iloc[-1])
    # 52 周高低
    if len(close) >= 250:
        high_52w = float(close.rolling(250).max().iloc[-1])
        low_52w = float(close.rolling(250).min().iloc[-1])
    elif len(close) >= 60:
        high_52w = float(close.max())
        low_52w = float(close.min())
    else:
        high_52w = float(close.max())
        low_52w = float(close.min())
    price_position = (current - low_52w) / (high_52w - low_52w) * 100 if high_52w > low_52w else 50

    # 趋势判断
    trend = '未知'
    if ma.get('MA60') and ma.get('MA250'):
        if current > ma['MA60'] > ma['MA250']:
            trend = '多头排列'
        elif current < ma['MA60'] < ma['MA250']:
            trend = '空头排列'
        else:
            trend = '震荡'
    elif ma.get('MA20'):
        if current > ma['MA20']:
            trend = '短多'
        else:
            trend = '短空'

    return {
        'current_price': round(current, 4),
        'MA': ma,
        'MACD': macd,
        'RSI': rsi,
        'KDJ': kdj,
        '52w_high': round(high_52w, 4),
        '52w_low': round(low_52w, 4),
        'price_position_pct': round(float(price_position), 2),
        'trend': trend,
        'data_days': len(close),
    }


def analyze_fund_flow(etf: dict) -> dict:
    """分析资金面"""
    inflow = etf.get('main_net_inflow')
    pct = etf.get('main_net_pct')
    super_large = etf.get('super_large_net_inflow')
    large = etf.get('large_net_inflow')
    medium = etf.get('medium_net_inflow')
    small = etf.get('small_net_inflow')

    if inflow is None:
        return {'error': '资金流数据缺失'}

    # 信号解读
    if inflow > 0:
        direction = '净流入'
        if pct is not None and pct > 10:
            strength = '强'
        elif pct is not None and pct > 3:
            strength = '中'
        else:
            strength = '弱'
    else:
        direction = '净流出'
        if pct is not None and pct < -10:
            strength = '强'
        elif pct is not None and pct < -3:
            strength = '中'
        else:
            strength = '弱'

    # 主导力量
    dominant = '未知'
    if super_large is not None and large is not None:
        total_large = abs(super_large) + abs(large)
        if total_large > 0:
            if abs(super_large) > abs(large):
                dominant = '超大单主导'
            else:
                dominant = '大单主导'

    return {
        'main_net_inflow': float(inflow),
        'main_net_pct': float(pct) if pct is not None else None,
        'super_large_net_inflow': float(super_large) if super_large is not None else None,
        'large_net_inflow': float(large) if large is not None else None,
        'medium_net_inflow': float(medium) if medium is not None else None,
        'small_net_inflow': float(small) if small is not None else None,
        'direction': direction,
        'strength': strength,
        'dominant': dominant,
    }


def analyze_liquidity(etf: dict) -> dict:
    """分析流动性"""
    amount = etf.get('amount')
    volume = etf.get('volume')
    total_mcap = etf.get('total_mcap')
    float_mcap = etf.get('float_mcap')
    turnover = etf.get('turnover')
    shares = etf.get('shares')

    # 流动性等级
    liquidity_grade = '低'
    if amount is not None:
        if amount > 1e9:  # >10 亿
            liquidity_grade = '高'
        elif amount > 2e8:  # >2 亿
            liquidity_grade = '中'

    # 规模等级
    scale_grade = '小'
    if total_mcap is not None:
        if total_mcap > 1e10:  # >100 亿
            scale_grade = '大'
        elif total_mcap > 2e9:  # >20 亿
            scale_grade = '中'

    return {
        'amount': float(amount) if amount is not None else None,
        'volume': float(volume) if volume is not None else None,
        'total_mcap': float(total_mcap) if total_mcap is not None else None,
        'float_mcap': float(float_mcap) if float_mcap is not None else None,
        'turnover': float(turnover) if turnover is not None else None,
        'shares': float(shares) if shares is not None else None,
        'liquidity_grade': liquidity_grade,
        'scale_grade': scale_grade,
    }


def analyze_industry(etf: dict, keyword: str | None) -> dict:
    """分析行业面(基于已有信息,不联网)"""
    name = etf.get('name', '')
    industry = etf.get('industry', keyword)

    # 推断跟踪指数
    tracking_index = None
    index_hints = {
        '沪深300': '沪深300', '中证500': '中证500', '中证1000': '中证1000',
        '创业板': '创业板', '科创50': '科创50', '上证50': '上证50',
        '半导体': '国证半导体芯片', '芯片': '中证全指半导体',
        '医药': '中证医药', '医疗': '中证医疗',
        '新能源': '中证新能源', '光伏': '中证光伏', '电池': '中证电池',
        '消费': '中证主要消费', '白酒': '中证白酒',
        '券商': '中证全指证券', '银行': '中证银行',
        '军工': '中证军工', '有色': '有色金属',
        '红利': '上证红利', '科技': '中证科技',
    }
    for hint, idx in index_hints.items():
        if hint in name:
            tracking_index = idx
            break

    return {
        'industry': industry,
        'name': name,
        'tracking_index': tracking_index,
        'note': '行业 PE 分位需联网获取,当前环境暂不可用',
    }


def score_fund_flow(flow: dict) -> tuple[int, str]:
    """资金面打分(1-5)"""
    inflow = flow.get('main_net_inflow')
    pct = flow.get('main_net_pct')
    if inflow is None:
        return 3, '数据缺失'
    if inflow > 0 and pct is not None and pct > 10:
        return 5, '主力强净流入,资金面极佳'
    if inflow > 0 and pct is not None and pct > 3:
        return 4, '主力中等净流入'
    if inflow > 0:
        return 3, '主力弱净流入'
    if inflow < 0 and pct is not None and pct < -10:
        return 1, '主力强净流出,资金面恶化'
    if inflow < 0 and pct is not None and pct < -3:
        return 2, '主力中等净流出'
    return 3, '资金流向中性'


def score_liquidity(liq: dict) -> tuple[int, str]:
    """流动性打分"""
    grade = liq.get('liquidity_grade')
    scale = liq.get('scale_grade')
    amount = liq.get('amount')
    if amount is None:
        return 3, '数据缺失'
    if grade == '高' and scale == '大':
        return 5, '高流动性 + 大规模'
    if grade == '高' or scale == '大':
        return 4, '流动性好或规模大'
    if grade == '中':
        return 3, '流动性适中'
    return 2, '流动性偏低'


def score_technical(tech: dict) -> tuple[int, str]:
    """技术面打分"""
    if 'error' in tech:
        return 3, '技术指标数据不足'
    trend = tech.get('trend', '')
    rsi = tech.get('RSI', {}).get('RSI', 50)
    macd_sig = tech.get('MACD', {}).get('signal', '')
    pos = tech.get('price_position_pct', 50)

    if '多头' in trend and '金叉' in macd_sig:
        return 5, f'多头排列 + MACD 金叉,价格位置 {pos}%'
    if '多头' in trend:
        return 4, f'多头排列,价格位置 {pos}%'
    if '短多' in trend and rsi is not None and rsi < 70:
        return 4, f'短多 + RSI {rsi}'
    if '空头' in trend:
        return 2, f'空头排列,价格位置 {pos}%'
    return 3, f'震荡,价格位置 {pos}%'


def main():
    parser = argparse.ArgumentParser(description='ETF 分析')
    parser.add_argument('--out-dir', default='./output/etf', help='数据目录')
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    summary_path = out_dir / 'summary.json'
    if not summary_path.exists():
        print(f'错误:找不到 {summary_path}', file=sys.stderr)
        sys.exit(1)

    with open(summary_path, encoding='utf-8') as f:
        summary = json.load(f)

    keyword = summary.get('keyword')
    etfs = summary.get('etfs', [])

    results = []
    for etf in etfs:
        ticker = etf.get('ticker')
        print(f'[analyze] {ticker} {etf.get("name")}', file=sys.stderr)

        # 技术分析(如果有历史价格文件)
        price_file = out_dir / f'price_{ticker}.csv'
        tech = {}
        if price_file.exists():
            price_df = pd.read_csv(price_file)
            tech = compute_technical(price_df)
        else:
            tech = {'error': '无历史价格文件'}

        flow = analyze_fund_flow(etf)
        liq = analyze_liquidity(etf)
        ind = analyze_industry(etf, keyword)

        flow_score, flow_reason = score_fund_flow(flow)
        liq_score, liq_reason = score_liquidity(liq)
        tech_score, tech_reason = score_technical(tech)

        # 行业面打分(基于 keyword 推断,保守给中性)
        ind_score = 3
        ind_reason = f'行业={keyword or "未知"},跟踪指数={ind.get("tracking_index") or "未知"}'

        result = {
            'ticker': ticker,
            'name': etf.get('name'),
            'close': etf.get('close'),
            'pct_change': etf.get('pct_change'),
            'technical': tech,
            'fund_flow': flow,
            'liquidity': liq,
            'industry': ind,
            'scores': {
                'fund_flow': flow_score,
                'liquidity': liq_score,
                'technical': tech_score,
                'industry': ind_score,
            },
            'score_reasons': {
                'fund_flow': flow_reason,
                'liquidity': liq_reason,
                'technical': tech_reason,
                'industry': ind_reason,
            },
        }
        results.append(result)

    # 加权评分(资金面 35% + 流动性 25% + 技术面 20% + 行业面 20%)
    weights = {'fund_flow': 0.35, 'liquidity': 0.25, 'technical': 0.20, 'industry': 0.20}
    for r in results:
        weighted = sum(r['scores'][k] * weights[k] for k in weights)
        r['weighted_score'] = round(float(weighted), 2)

    # 排序(按加权分)
    results.sort(key=lambda x: x['weighted_score'], reverse=True)

    output = {
        'mode': summary.get('mode'),
        'keyword': keyword,
        'analysis_time': str(pd.Timestamp.now()),
        'weights': weights,
        'ranking_by': 'weighted_score',
        'results': results,
    }

    with open(out_dir / 'indicators.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f'[analyze] 分析完成,{len(results)} 只 ETF', file=sys.stderr)
    print(f'[analyze] 输出:{out_dir / "indicators.json"}', file=sys.stderr)


if __name__ == '__main__':
    main()
