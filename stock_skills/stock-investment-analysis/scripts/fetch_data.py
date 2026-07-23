"""fetch_data.py — 抓取个股分析所需数据(A股 + 港股)

数据源策略:
- A股日线:ak.stock_zh_a_daily (sina 源,稳定)
- 港股日线:ak.stock_hk_daily (sina 源,稳定)
- A股财务:ak.stock_financial_abstract (eastmoney,接口可用)
- 港股财务:ak.stock_financial_hk_report_em (eastmoney,接口可用)
- 宏观:CPI/PPI/利率 via akshare (best effort,失败不阻塞)
- 行业:best effort,失败不阻塞

所有抓不到的字段在 summary.json 里标 null + reason,不抛异常终止流程。
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import traceback
from pathlib import Path
import pandas as pd
import numpy as np


# ---------- 工具函数 ----------

def safe(fn, *args, **kwargs):
    """调用 akshare 接口,失败时返回 (None, reason_str) 而不是抛"""
    try:
        return fn(*args, **kwargs), None
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:200]}"


def parse_ticker(ticker: str) -> dict:
    """识别市场和标准化代码。返回 {market, raw, sina_symbol}"""
    t = ticker.strip().upper()
    if t.endswith('.HK') or t.endswith('.SS') or t.endswith('.SZ'):
        # 港股 00700.HK
        if t.endswith('.HK'):
            code = t[:-3]
            # 补齐 5 位
            code = code.zfill(5)
            return {'market': 'HK', 'raw': f'{code}.HK', 'sina_symbol': code}
        # A股带后缀(非标准,容错)
        if t.endswith('.SS'):
            code = t[:-3]
            return {'market': 'A', 'raw': code, 'sina_symbol': f'sh{code}'}
        if t.endswith('.SZ'):
            code = t[:-3]
            return {'market': 'A', 'raw': code, 'sina_symbol': f'sz{code}'}
    # 纯数字
    if t.isdigit():
        if len(t) == 6:
            # A股:6开头是 sh,其他 sz
            prefix = 'sh' if t.startswith(('6', '5', '9')) else 'sz'
            return {'market': 'A', 'raw': t, 'sina_symbol': f'{prefix}{t}'}
        if len(t) == 5:
            return {'market': 'HK', 'raw': f'{t}.HK', 'sina_symbol': t}
        if len(t) <= 5:
            return {'market': 'HK', 'raw': f'{t.zfill(5)}.HK', 'sina_symbol': t.zfill(5)}
    raise ValueError(f'无法识别股票代码: {ticker}(期望: A股 6 位数字如 600519,或港股 5 位如 00700 / 00700.HK)')


# ---------- A股数据 ----------

def fetch_a_share_price(sina_symbol: str, years: int = 3) -> tuple[pd.DataFrame | None, str | None]:
    import akshare as ak
    end = pd.Timestamp.now().strftime('%Y%m%d')
    start = (pd.Timestamp.now() - pd.Timedelta(days=365 * years)).strftime('%Y%m%d')
    df, err = safe(ak.stock_zh_a_daily, symbol=sina_symbol, start_date=start, end_date=end, adjust='qfq')
    if err:
        return None, err
    if df is None or df.empty:
        return None, '空数据'
    df = df.rename(columns={'date': 'date', 'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume'})
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    return df, None


def fetch_a_share_financials(code: str) -> tuple[pd.DataFrame | None, str | None]:
    import akshare as ak
    df, err = safe(ak.stock_financial_abstract, symbol=code)
    if err:
        return None, err
    if df is None or df.empty:
        return None, '空数据'
    return df, None


def fetch_a_share_pe_history(code: str) -> tuple[pd.DataFrame | None, str | None]:
    """A股 PE/PB 历史 — akshare 接口版本变动频繁,这里 best-effort"""
    import akshare as ak
    fn = getattr(ak, 'stock_a_indicator_lg', None) or getattr(ak, 'stock_zh_valuation_baidu', None)
    if fn is None:
        return None, 'akshare 已移除该接口(无 stock_a_indicator_lg / stock_zh_valuation_baidu)'
    df, err = safe(fn, symbol=code)
    if err:
        return None, err
    if df is None or df.empty:
        return None, '空数据'
    df['date'] = pd.to_datetime(df.get('date', df.columns[0]))
    return df, None


def fetch_a_share_realtime(code: str) -> tuple[dict | None, str | None]:
    """A股实时估值 — 优先级:雪球 → 东财 → sina,全部 best-effort"""
    import akshare as ak
    # 1. 雪球个股基本信息
    df, err = safe(ak.stock_individual_basic_info_xq, symbol=f'SH{code}' if code.startswith('6') else f'SZ{code}')
    if df is not None and not df.empty and 'item' in df.columns:
        info = dict(zip(df['item'].astype(str), df['value'].astype(str)))
        return info, None
    # 2. 东财个股信息
    df, err2 = safe(ak.stock_individual_info_em, symbol=code)
    if df is not None and not df.empty:
        info = dict(zip(df.iloc[:, 0].astype(str), df.iloc[:, 1].astype(str)))
        return info, None
    return None, f'雪球和东财均失败: {err}; {err2}'


# ---------- 港股数据 ----------

def fetch_hk_share_price(sina_symbol: str, years: int = 3) -> tuple[pd.DataFrame | None, str | None]:
    import akshare as ak
    df, err = safe(ak.stock_hk_daily, symbol=sina_symbol, adjust='qfq')
    if err:
        return None, err
    if df is None or df.empty:
        return None, '空数据'
    df['date'] = pd.to_datetime(df['date'])
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=365 * years)
    df = df[df['date'] >= cutoff].sort_values('date').reset_index(drop=True)
    return df, None


def fetch_hk_share_financials(code: str) -> tuple[dict | None, str | None]:
    import akshare as ak
    out = {}
    for statement, label in [('利润表', 'income'), ('资产负债表', 'balance'), ('现金流量表', 'cashflow')]:
        df, err = safe(ak.stock_financial_hk_report_em, stock=code, symbol=statement, indicator='报告期')
        if df is not None and not df.empty:
            out[label] = df
        else:
            out[label] = None
            out[f'{label}_err'] = err
    return out, None


def fetch_hk_share_basic(code: str) -> tuple[dict | None, str | None]:
    import akshare as ak
    df, err = safe(ak.stock_hk_company_profile_em, symbol=code)
    if df is None or df.empty:
        return None, err
    return df.iloc[0].to_dict() if len(df) > 0 else {}, None


# ---------- 宏观与行业 ----------

def fetch_macro_snapshot() -> dict:
    """抓宏观关键指标,任一失败不影响整体。注意 akshare 的 CPI 数据是倒序(最新在 head)"""
    import akshare as ak
    macro = {}

    # CPI(全国同比) — 数据倒序,head 是最新
    df, err = safe(ak.macro_china_cpi)
    if df is not None and not df.empty:
        try:
            latest = df.iloc[0]
            # 字段名是中文,匹配"同比"列
            yoy_cols = [c for c in df.columns if '同比' in c]
            month = str(latest.get('月份', ''))
            if yoy_cols:
                macro['cpi_latest'] = {'value': float(latest[yoy_cols[0]]), 'month': month}
        except Exception as e:
            macro['cpi_latest'] = {'error': str(e)[:100]}

    # PPI — 数据正序,tail 是最新
    df, err = safe(ak.macro_china_ppi_yearly)
    if df is not None and not df.empty:
        try:
            latest = df.iloc[-1]
            macro['ppi_latest'] = {
                'value': float(latest.get('现值', 0) or 0),
                'date': str(latest.get('日期', '')),
            }
        except Exception as e:
            macro['ppi_latest'] = {'error': str(e)[:100]}

    # LPR — 数据正序
    df, err = safe(ak.macro_china_lpr)
    if df is not None and not df.empty:
        try:
            latest = df.iloc[-1]
            macro['lpr_1y'] = float(latest.get('LPR1Y', 0) or 0)
            macro['lpr_5y'] = float(latest.get('LPR5Y', 0) or 0)
            macro['lpr_date'] = str(latest.get('TRADE_DATE', ''))
        except Exception as e:
            macro['lpr_error'] = str(e)[:100]

    return macro


# ---------- 主流程 ----------

def main():
    parser = argparse.ArgumentParser(description='抓取个股分析所需数据')
    parser.add_argument('--ticker', required=True, help='股票代码(A股 6 位 / 港股 5 位 或 00700.HK)')
    parser.add_argument('--out-dir', default=None, help='输出目录(默认 ./output/<ticker>)')
    parser.add_argument('--years', type=int, default=3, help='价格历史年限(默认 3)')
    args = parser.parse_args()

    info = parse_ticker(args.ticker)
    out_dir = Path(args.out_dir) if args.out_dir else Path('./output') / info['raw']
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        'ticker': info['raw'],
        'market': info['market'],
        'sina_symbol': info['sina_symbol'],
        'fetch_time': pd.Timestamp.now().isoformat(),
        'data_status': {},
        'errors': [],
    }

    # 1. 价格
    if info['market'] == 'A':
        price_df, err = fetch_a_share_price(info['sina_symbol'], args.years)
    else:
        price_df, err = fetch_hk_share_price(info['sina_symbol'], args.years)

    if price_df is not None:
        price_df.to_csv(out_dir / 'price_daily.csv', index=False)
        latest = price_df.iloc[-1]
        summary['data_status']['price'] = 'ok'
        summary['latest_price'] = {
            'date': latest['date'].strftime('%Y-%m-%d'),
            'close': float(latest['close']),
            'volume': float(latest['volume']),
        }
        summary['price_rows'] = len(price_df)
        summary['price_range'] = {
            'start': price_df['date'].iloc[0].strftime('%Y-%m-%d'),
            'end': price_df['date'].iloc[-1].strftime('%Y-%m-%d'),
        }
    else:
        summary['data_status']['price'] = 'failed'
        summary['errors'].append({'field': 'price', 'reason': err})

    # 2. 财务
    if info['market'] == 'A':
        fin_df, err = fetch_a_share_financials(info['raw'])
        if fin_df is not None:
            fin_df.to_csv(out_dir / 'financials.csv', index=False)
            summary['data_status']['financials'] = 'ok'
            summary['financials_shape'] = list(fin_df.shape)
        else:
            summary['data_status']['financials'] = 'failed'
            summary['errors'].append({'field': 'financials', 'reason': err})
        # PE/PB 历史
        pe_df, err2 = fetch_a_share_pe_history(info['raw'])
        if pe_df is not None:
            pe_df.to_csv(out_dir / 'pe_pb_history.csv', index=False)
            summary['data_status']['pe_pb_history'] = 'ok'
            if not pe_df.empty:
                latest_pe = pe_df.iloc[-1]
                summary['latest_pe_pb'] = {
                    'date': str(latest_pe.get('date', '')),
                    'pe_ttm': float(latest_pe.get('pe_ttm', 0) or 0) or None,
                    'pb': float(latest_pe.get('pb', 0) or 0) or None,
                }
        else:
            summary['data_status']['pe_pb_history'] = 'failed'
            summary['errors'].append({'field': 'pe_pb_history', 'reason': err2})
        # 实时估值
        rt, err3 = fetch_a_share_realtime(info['raw'])
        if rt:
            summary['data_status']['realtime'] = 'ok'
            summary['realtime'] = {k: (v if not pd.isna(v) else None) if not isinstance(v, pd.Timestamp) else str(v) for k, v in rt.items()} if isinstance(rt, dict) else None
        else:
            summary['data_status']['realtime'] = 'failed'
            summary['errors'].append({'field': 'realtime', 'reason': err3})
    else:
        # 港股财务
        fin_dict, err = fetch_hk_share_financials(info['sina_symbol'])
        if fin_dict:
            for key, df in fin_dict.items():
                if df is not None and isinstance(df, pd.DataFrame):
                    df.to_csv(out_dir / f'financials_{key}.csv', index=False)
                    summary['data_status'][f'financials_{key}'] = 'ok'
                    summary[f'financials_{key}_shape'] = list(df.shape)
                elif key.endswith('_err'):
                    summary['data_status'][f'financials_{key[:-4]}'] = 'failed'
                    summary['errors'].append({'field': f'financials_{key[:-4]}', 'reason': df})
        # 港股公司基本信息
        basic, err2 = fetch_hk_share_basic(info['sina_symbol'])
        if basic:
            summary['data_status']['company_profile'] = 'ok'
            summary['company_profile'] = {k: str(v) for k, v in basic.items()} if isinstance(basic, dict) else None
        else:
            summary['data_status']['company_profile'] = 'failed'
            summary['errors'].append({'field': 'company_profile', 'reason': err2})

    # 3. 宏观
    try:
        macro = fetch_macro_snapshot()
        summary['macro'] = macro
        summary['data_status']['macro'] = 'ok' if macro else 'empty'
    except Exception as e:
        summary['data_status']['macro'] = 'failed'
        summary['errors'].append({'field': 'macro', 'reason': str(e)})

    # 保存摘要
    with open(out_dir / 'summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    # 打印摘要到 stdout 给 Claude 看
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print(f'\n[fetch_data] 输出目录: {out_dir}', file=sys.stderr)


if __name__ == '__main__':
    main()
