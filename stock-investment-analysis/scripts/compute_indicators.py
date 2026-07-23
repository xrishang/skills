"""compute_indicators.py — 计算技术指标、财务指标、估值指标

输入: fetch_data.py 生成的 output/<ticker>/ 目录
输出: output/<ticker>/indicators.json

所有计算都基于已有 CSV 数据,不再联网。指标带"信号解读"字段,但 Claude 需自己判断。
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
import pandas as pd
import numpy as np


# ---------- 技术指标 ----------

def ema(values: pd.Series, period: int) -> pd.Series:
    return values.ewm(span=period, adjust=False).mean()


def compute_technical(price_df: pd.DataFrame) -> dict:
    df = price_df.sort_values('date').reset_index(drop=True).copy()
    close = df['close'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    vol = df['volume'].astype(float)

    out = {}
    # 均线
    for p in [5, 10, 20, 60, 120, 250]:
        if len(df) >= p:
            out[f'MA{p}'] = round(float(close.rolling(p).mean().iloc[-1]), 4)
            out[f'price_vs_MA{p}'] = '上方' if close.iloc[-1] > out[f'MA{p}'] else '下方'

    # 多头排列判断(收盘 > MA5 > MA10 > MA20 > MA60)
    if all(f'MA{p}' in out for p in [5, 10, 20, 60]):
        ma_seq = [out[f'MA{p}'] for p in [5, 10, 20, 60]]
        out['trend'] = '多头排列(强趋势)' if all(ma_seq[i] > ma_seq[i+1] for i in range(len(ma_seq)-1)) else \
                       '空头排列(弱趋势)' if all(ma_seq[i] < ma_seq[i+1] for i in range(len(ma_seq)-1)) else \
                       '震荡(无明确趋势)'

    # MACD
    if len(df) >= 35:
        ema12 = ema(close, 12)
        ema26 = ema(close, 26)
        dif = ema12 - ema26
        dea = ema(dif, 9)
        macd_hist = (dif - dea) * 2
        out['MACD_DIF'] = round(float(dif.iloc[-1]), 4)
        out['MACD_DEA'] = round(float(dea.iloc[-1]), 4)
        out['MACD_Hist'] = round(float(macd_hist.iloc[-1]), 4)
        out['MACD_signal'] = '金叉(看多)' if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2] else \
                             '死叉(看空)' if dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2] else \
                             '多头运行(DIF>DEA)' if dif.iloc[-1] > dea.iloc[-1] else \
                             '空头运行(DIF<DEA)'

    # RSI(14)
    if len(df) >= 14:
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        out['RSI14'] = round(float(rsi.iloc[-1]), 2)
        out['RSI_signal'] = '超买(>70,短期可能回调)' if out['RSI14'] > 70 else \
                            '超卖(<30,短期可能反弹)' if out['RSI14'] < 30 else \
                            '中性'

    # KDJ
    if len(df) >= 9:
        low_9 = low.rolling(9).min()
        high_9 = high.rolling(9).max()
        rsv = (close - low_9) / (high_9 - low_9).replace(0, np.nan) * 100
        k = rsv.ewm(alpha=1/3, adjust=False).mean()
        d = k.ewm(alpha=1/3, adjust=False).mean()
        j = 3 * k - 2 * d
        out['KDJ_K'] = round(float(k.iloc[-1]), 2)
        out['KDJ_D'] = round(float(d.iloc[-1]), 2)
        out['KDJ_J'] = round(float(j.iloc[-1]), 2)
        out['KDJ_signal'] = '金叉(看多)' if k.iloc[-1] > d.iloc[-1] and k.iloc[-2] <= d.iloc[-2] else \
                            '死叉(看空)' if k.iloc[-1] < d.iloc[-1] and k.iloc[-2] >= d.iloc[-2] else \
                            '多头' if k.iloc[-1] > d.iloc[-1] else '空头'

    # 量价
    if len(df) >= 20:
        up_days = df[df['close'] > df['close'].shift(1)]
        down_days = df[df['close'] < df['close'].shift(1)]
        if len(up_days) > 0 and len(down_days) > 0:
            avg_up_vol = up_days['volume'].mean()
            avg_down_vol = down_days['volume'].mean()
            out['volume_ratio_up_down'] = round(float(avg_up_vol / avg_down_vol), 3) if avg_down_vol > 0 else None
            out['volume_signal'] = '上涨放量(健康)' if avg_up_vol > avg_down_vol * 1.1 else \
                                   '下跌放量(警惕)' if avg_down_vol > avg_up_vol * 1.1 else \
                                   '量价均衡'

    # 支撑压力位
    recent = df.tail(250) if len(df) >= 250 else df
    out['high_52w'] = round(float(recent['high'].max()), 4)
    out['low_52w'] = round(float(recent['low'].min()), 4)
    out['price_position_52w'] = round(float((close.iloc[-1] - recent['low'].min()) / (recent['high'].max() - recent['low'].min()) * 100), 2) if recent['high'].max() > recent['low'].min() else None

    return out


# ---------- A股财报解析 ----------

def parse_a_share_financials(csv_path: Path) -> dict:
    """A股财报宽格式:行=指标,列=季度。转置为 dict[date_str -> dict[指标 -> value]]"""
    df = pd.read_csv(csv_path, encoding='utf-8')
    # 筛选"选项"列为"全部指标"的行(去掉衍生指标行)
    # 实际财报数据是"选项"列=全部指标,衍生指标行是另一种"选项"
    if '选项' not in df.columns or '指标' not in df.columns:
        return {'error': '财报列名不匹配'}

    # 提取日期列(列名是 YYYYMMDD 格式 8 位数字)
    date_cols = [c for c in df.columns if str(c).isdigit() and len(str(c)) == 8]

    result = {}
    for _, row in df.iterrows():
        metric = str(row['指标']).strip()
        for col in date_cols:
            if col not in result:
                result[col] = {}
            val = row[col]
            if pd.notna(val) and val != 0:
                try:
                    result[col][metric] = float(val)
                except (ValueError, TypeError):
                    pass
    return {'by_date': result, 'date_cols': sorted(date_cols, reverse=True)}


def compute_a_share_financials(fin_path: Path) -> dict:
    parsed = parse_a_share_financials(fin_path)
    if 'error' in parsed:
        return parsed
    by_date = parsed['by_date']
    date_cols = parsed['date_cols']  # 倒序,最新在前

    out = {'quarters_available': len(date_cols), 'latest_quarter': date_cols[0] if date_cols else None, 'series': {}}

    # 关键指标提取(按 A股财报"指标"列中文匹配)
    key_metrics = {
        '净资产收益率(ROE)': 'ROE',
        '毛利率': '毛利率',
        '净利润利率': '净利率',
        '资产负债率': '资产负债率',
        '归母净利润': '归母净利润',
        '营业总收入': '营业总收入',
        '营业成本': '营业成本',
        '净利润': '净利润',
        '扣非净利润': '扣非净利润',
        '经营现金流量净额': '经营现金流',
        '总资产': '总资产',
        '股东权益合计(归属于母公司)': '归母股东权益',
    }

    series = {label: [] for label in key_metrics.values()}
    dates_used = []
    for col in date_cols[:12]:  # 取最近 12 个季度
        d = by_date.get(col, {})
        dates_used.append(col)
        for cn, label in key_metrics.items():
            # 模糊匹配:cn 可能在 d 里精确出现
            val = d.get(cn)
            if val is None:
                # 尝试 starts with
                for k in d:
                    if str(k).strip() == cn:
                        val = d[k]
                        break
            series[label].append(val)
    out['dates'] = dates_used
    out['series'] = series

    # 衍生指标
    if series['ROE'] and series['ROE'][0] is not None:
        out['ROE_latest'] = round(series['ROE'][0], 4)
        out['ROE_trend'] = '上升' if len(series['ROE']) >= 2 and series['ROE'][0] > (series['ROE'][1] or 0) else '下降' if len(series['ROE']) >= 2 else '未知'

    if series['毛利率'] and series['毛利率'][0] is not None:
        out['毛利率_latest'] = round(series['毛利率'][0], 4)

    if series['净利率'] and series['净利率'][0] is not None:
        out['净利率_latest'] = round(series['净利率'][0], 4)

    if series['资产负债率'] and series['资产负债率'][0] is not None:
        out['资产负债率_latest'] = round(series['资产负债率'][0], 4)

    # 营收增速(同比)— 简单实现:用最新季度 vs 4 个季度前
    if len(series['营业总收入']) >= 5 and series['营业总收入'][0] and series['营业总收入'][4]:
        try:
            yoy = (series['营业总收入'][0] - series['营业总收入'][4]) / abs(series['营业总收入'][4]) * 100
            out['营收同比增速'] = round(float(yoy), 2)
        except Exception:
            pass

    if len(series['归母净利润']) >= 5 and series['归母净利润'][0] and series['归母净利润'][4]:
        try:
            yoy = (series['归母净利润'][0] - series['归母净利润'][4]) / abs(series['归母净利润'][4]) * 100
            out['净利润同比增速'] = round(float(yoy), 2)
        except Exception:
            pass

    # 现金流/净利润匹配度
    if series['经营现金流'] and series['净利润'] and series['净利润'][0] and series['净利润'][0] != 0:
        out['现金流净利润比'] = round(float(series['经营现金流'][0] / series['净利润'][0]), 3)

    return out


# ---------- 港股财报解析 ----------

def compute_hk_share_financials(fin_dir: Path) -> dict:
    """港股财报长格式,3 个 CSV:income / balance / cashflow。用港式会计术语"""
    out = {}
    # 利润表
    inc_path = fin_dir / 'financials_income.csv'
    if inc_path.exists():
        df = pd.read_csv(inc_path, encoding='utf-8')
        if 'STD_ITEM_NAME' in df.columns and 'AMOUNT' in df.columns and 'REPORT_DATE' in df.columns:
            # 港式术语映射
            key_map = {
                '营业额': 'revenue',
                '毛利': 'gross_profit',
                '经营溢利': 'operating_profit',
                '除税前溢利': 'pretax_profit',
                '除税后溢利': 'net_profit',
                '股东应占溢利': 'net_profit_attributable',
                '每股基本盈利': 'eps',
            }
            for cn, label in key_map.items():
                rows = df[df['STD_ITEM_NAME'].astype(str).str.strip() == cn]
                if not rows.empty:
                    rows = rows.sort_values('REPORT_DATE', ascending=False)
                    out[label] = {
                        'latest_date': str(rows.iloc[0]['REPORT_DATE']),
                        'latest_value': float(rows.iloc[0]['AMOUNT']),
                        'history': [(str(r['REPORT_DATE']), float(r['AMOUNT'])) for _, r in rows.head(8).iterrows() if pd.notna(r['AMOUNT'])],
                    }
            # 计算毛利率
            if 'revenue' in out and 'gross_profit' in out and out['revenue']['latest_value']:
                out['毛利率_latest'] = round(float(out['gross_profit']['latest_value'] / out['revenue']['latest_value'] * 100), 2)
            if 'revenue' in out and 'net_profit_attributable' in out and out['revenue']['latest_value']:
                out['净利率_latest'] = round(float(out['net_profit_attributable']['latest_value'] / out['revenue']['latest_value'] * 100), 2)

    # 资产负债表
    bal_path = fin_dir / 'financials_balance.csv'
    if bal_path.exists():
        df = pd.read_csv(bal_path, encoding='utf-8')
        if 'STD_ITEM_NAME' in df.columns:
            key_map = {
                '总资产': 'total_assets',
                '股东权益': 'equity_attributable',  # 港股财报用"股东权益"作为归母权益
                '总负债': 'total_liabilities',
                '净资产': 'net_assets',
            }
            for cn, label in key_map.items():
                rows = df[df['STD_ITEM_NAME'].astype(str).str.strip() == cn]
                if not rows.empty:
                    rows = rows.sort_values('REPORT_DATE', ascending=False)
                    out[label] = {
                        'latest_date': str(rows.iloc[0]['REPORT_DATE']),
                        'latest_value': float(rows.iloc[0]['AMOUNT']),
                    }
            if 'total_assets' in out and 'total_liabilities' in out and out['total_assets']['latest_value']:
                out['资产负债率_latest'] = round(float(out['total_liabilities']['latest_value'] / out['total_assets']['latest_value'] * 100), 2)
    # 现金流表
    cf_path = fin_dir / 'financials_cashflow.csv'
    if cf_path.exists():
        df = pd.read_csv(cf_path, encoding='utf-8')
        if 'STD_ITEM_NAME' in df.columns:
            # 港股现金流项名称多变,用模糊匹配
            candidates = ['经营活动所得现金流量净额', '经营活动产生的现金流量净额', '经营业务所得之现金流入净额', '经营活动之现金流量净额']
            mask = df['STD_ITEM_NAME'].astype(str).str.strip().isin(candidates)
            rows = df[mask]
            if not rows.empty:
                rows = rows.sort_values('REPORT_DATE', ascending=False)
                out['operating_cashflow'] = {
                    'latest_date': str(rows.iloc[0]['REPORT_DATE']),
                    'latest_value': float(rows.iloc[0]['AMOUNT']),
                }

    # 衍生指标
    if 'net_profit_attributable' in out and 'equity_attributable' in out and out['equity_attributable']['latest_value']:
        out['ROE_latest'] = round(float(out['net_profit_attributable']['latest_value'] / out['equity_attributable']['latest_value'] * 100), 2)

    # 现金流/净利润匹配度
    if 'operating_cashflow' in out and 'net_profit_attributable' in out and out['net_profit_attributable']['latest_value']:
        ratio = out['operating_cashflow']['latest_value'] / abs(out['net_profit_attributable']['latest_value'])
        out['现金流净利润比'] = round(float(ratio), 3)

    # 营收同比增速
    if 'revenue' in out and len(out['revenue'].get('history', [])) >= 5:
        try:
            latest = out['revenue']['history'][0][1]
            prev = out['revenue']['history'][4][1]
            if prev:
                out['营收同比增速'] = round(float((latest - prev) / abs(prev) * 100), 2)
        except Exception:
            pass

    # 净利润同比增速
    if 'net_profit_attributable' in out and len(out['net_profit_attributable'].get('history', [])) >= 5:
        try:
            latest = out['net_profit_attributable']['history'][0][1]
            prev = out['net_profit_attributable']['history'][4][1]
            if prev:
                out['净利润同比增速'] = round(float((latest - prev) / abs(prev) * 100), 2)
        except Exception:
            pass

    return out


# ---------- 估值指标 ----------

def compute_valuation(price_df: pd.DataFrame, financials_summary: dict, market: str) -> dict:
    """用最近收盘价 × 总股本 / 净利润 TTM 估算 PE。数据不足时返回部分指标"""
    out = {}
    latest_close = float(price_df['close'].iloc[-1])

    # 总股本 — A股财报里有"摊薄每股总股本_期末数",港股从公司基本信息里取(简化:不取)
    # 这里简化:只算 A股的 PE/PB;港股财报没股本数据就标 null
    if market == 'A':
        # 从 A股财报取每股净资产、每股收益(摊薄)
        # financials_summary 是 compute_a_share_financials 的输出
        series = financials_summary.get('series', {})
        eps_list = series.get('每股收益') or series.get('基本每股收益_期末', [])
        bvps_list = series.get('每股净资产') or []
        # 实际财报"指标"列里有"基本每股收益_期末"和"每股净资产"
        # 这里尝试匹配
        return out  # A股 PE/PB 需要 PE 历史接口;此处省略,在 fetch 时已记录 latest_pe_pb

    # 港股估值:从财报算
    if market == 'HK':
        # 没有 total_shares 数据,无法直接算市值
        out['note'] = '港股需用户提供总股本或市值才能算 PE/PB;报告里用相对估值(历史 PB 分位)'
        return out
    return out


# ---------- 估值历史分位 ----------

def compute_valuation_percentile(price_df: pd.DataFrame) -> dict:
    """用价格自身做历史分位(代理估值分位,因为没法直接拿 PE 历史)"""
    close = price_df['close'].astype(float)
    out = {}
    latest = close.iloc[-1]
    for window in [250, 750, 1250]:  # 1 年 / 3 年 / 5 年
        if len(close) >= window:
            window_close = close.tail(window)
            pct = (window_close < latest).sum() / len(window_close) * 100
            out[f'price_percentile_{window}d'] = round(float(pct), 2)
            out[f'price_high_{window}d'] = round(float(window_close.max()), 4)
            out[f'price_low_{window}d'] = round(float(window_close.min()), 4)
    return out


# ---------- 主流程 ----------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticker', required=True)
    parser.add_argument('--out-dir', default=None)
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else Path('./output') / args.ticker
    summary_path = out_dir / 'summary.json'

    if not summary_path.exists():
        print(f'错误: 找不到 {summary_path},请先运行 fetch_data.py', file=sys.stderr)
        sys.exit(1)

    with open(summary_path, 'r', encoding='utf-8') as f:
        summary = json.load(f)

    market = summary.get('market')
    indicators = {'ticker': args.ticker, 'market': market, 'compute_time': pd.Timestamp.now().isoformat()}

    # 1. 技术指标
    price_path = out_dir / 'price_daily.csv'
    if price_path.exists():
        price_df = pd.read_csv(price_path, encoding='utf-8')
        price_df['date'] = pd.to_datetime(price_df['date'])
        indicators['technical'] = compute_technical(price_df)
        indicators['valuation_percentile'] = compute_valuation_percentile(price_df)
    else:
        indicators['technical'] = {'error': 'price_daily.csv 不存在'}

    # 2. 财务指标
    if market == 'A':
        fin_path = out_dir / 'financials.csv'
        if fin_path.exists():
            indicators['financials'] = compute_a_share_financials(fin_path)
        else:
            indicators['financials'] = {'error': 'financials.csv 不存在'}
    elif market == 'HK':
        indicators['financials'] = compute_hk_share_financials(out_dir)

    # 3. 宏观(直接复制 summary)
    if 'macro' in summary:
        indicators['macro'] = summary['macro']

    # 4. 估值(PE/PB 历史 — 如果 fetch 阶段拿到了)
    if 'latest_pe_pb' in summary:
        indicators['latest_pe_pb'] = summary['latest_pe_pb']

    # 保存
    with open(out_dir / 'indicators.json', 'w', encoding='utf-8') as f:
        json.dump(indicators, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps(indicators, ensure_ascii=False, indent=2, default=str))
    print(f'\n[compute_indicators] 输出: {out_dir / "indicators.json"}', file=sys.stderr)


if __name__ == '__main__':
    main()
