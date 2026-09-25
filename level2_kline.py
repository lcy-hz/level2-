"""Local daily candles using source qfq fields without adj_factor dependency.

Chart contract: an in-place stock-code hover preview, daily OHLC in CNY,
last 60 local market sessions <= report date, no invented missing candles.
Red hollow = close >= open; green filled = close < open (A-share convention).
The original Level-2 report's unadjusted prices/returns are not changed.
"""
from pathlib import Path
import json
import re
import pandas as pd

BASE = Path(__file__).parent
from level2_paths import PATHS
SOURCE = PATHS['stk_factor_pro_by_code']
CALENDAR = PATHS['daily']
FIELDS = ['ts_code', 'trade_date', 'open_qfq', 'high_qfq', 'low_qfq', 'close_qfq']


def normalized_candles(frame, codes, dates, target):
    frame = frame[frame.ts_code.isin(codes) & frame.trade_date.isin(dates)].copy()
    frame = frame.drop_duplicates()
    if frame.duplicated(['ts_code', 'trade_date']).any():
        raise ValueError('Conflicting stk_factor_pro rows for the same stock/date')
    for field in FIELDS[2:]:
        frame[field] = pd.to_numeric(frame[field], errors='coerce')
    positions = {day: index for index, day in enumerate(dates)}
    grouped = {code: group for code, group in frame.groupby('ts_code')}
    series = {}
    for code in sorted(codes):
        group = grouped.get(code)
        if group is None:
            series[code] = {'bars': [], 'reason': '缺少qfq价格，未回退为不复权'}
            continue
        bars, rejected = [], 0
        for row in group.sort_values('trade_date').itertuples():
            values = [row.open_qfq, row.high_qfq, row.low_qfq, row.close_qfq]
            if not all(pd.notna(v) and 0 < v < float('inf') for v in values) or not (
                row.low_qfq <= min(row.open_qfq, row.close_qfq) <= max(row.open_qfq, row.close_qfq) <= row.high_qfq
            ):
                rejected += 1
                continue
            prices = [float(v) for v in values]
            bars.append([positions[row.trade_date], *prices])
        series[code] = {'adjustment': 'source_qfq', 'bars': bars, 'rejected': rejected}
    return series


def build_bundle(codes, target, source=SOURCE, calendar=CALENDAR, count=60, include_volume=False):
    if source==SOURCE or any(source.glob('*_??_stk_factor_pro.csv')):
        frames=[];missing=[];files=[]
        for code in sorted(codes):
            p=source/(code.replace('.','_')+'_stk_factor_pro.csv');files.append(str(p))
            if not p.exists():missing.append(code);continue
            f=pd.read_csv(p,usecols=FIELDS+(['vol','amount'] if include_volume else []),dtype={'ts_code':str,'trade_date':str})
            if set(f.ts_code.dropna())!={code}:raise ValueError('个股文件代码不一致：'+str(p))
            frames.append(f[f.trade_date<=target])
        frame=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=FIELDS)
        dates=sorted(set(frame.trade_date)|{p.name[:8] for p in calendar.glob('*_daily.csv') if re.fullmatch(r'\d{8}_daily.csv',p.name) and p.name[:8]<=target})[-count:]
        series=normalized_candles(frame,set(codes),dates,target)
        if include_volume:
            lookup=frame.drop_duplicates().set_index(['ts_code','trade_date'])
            for code,item in series.items():
                for bar in item['bars']:
                    row=lookup.loc[(code,dates[bar[0]])];values=[pd.to_numeric(row[k],errors='coerce') for k in ['vol','amount']]
                    bar.extend([float(v)*scale if pd.notna(v) and 0<=v<float('inf') else None for v,scale in zip(values,[1,1000])])
        for code,item in series.items():item['sourceFiles']=[str(source/(code.replace('.','_')+'_stk_factor_pro.csv'))]
        return {'source':str(source.resolve()),'target':target,'dates':dates,'missingFiles':missing,'method':'本地by_code qfq OHLC直接读取，不依赖adj_factor；沿用来源复权基准；vol手，amount千元转元','series':series}
    files = {p.name[:8]: p for p in source.glob('*_stk_factor_pro.csv')
             if re.fullmatch(r'\d{8}_stk_factor_pro.csv', p.name) and p.name[:8] <= target}
    days = set(files)
    days.update(p.name[:8] for p in calendar.glob('*_daily.csv')
                if re.fullmatch(r'\d{8}_daily.csv', p.name) and p.name[:8] <= target)
    dates = sorted(days)[-count:]
    if not dates:
        raise ValueError('No local factor/calendar dates before report date')
    frames = []
    for day in dates:
        if day not in files:
            continue
        frame = pd.read_csv(files[day], usecols=FIELDS+(['vol','amount'] if include_volume else []), dtype={'ts_code': str, 'trade_date': str})
        if set(frame.trade_date.dropna()) != {day}:
            raise ValueError(f'Partition date mismatch: {files[day]}')
        frames.append(frame[frame.ts_code.isin(codes)])
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=FIELDS)
    series = normalized_candles(frame, set(codes), dates, target)
    if include_volume:
        volumes = frame.drop_duplicates().set_index(['ts_code','trade_date'])
        for code,item in series.items():
            for bar in item['bars']:
                row = volumes.loc[(code,dates[bar[0]])]
                values = [pd.to_numeric(row['vol'],errors='coerce'),pd.to_numeric(row['amount'],errors='coerce')]
                bar.extend([float(v)*scale if pd.notna(v) and 0<=v<float('inf') else None
                            for v,scale in zip(values,[1,1000])])
    return {'source': str(source.resolve()), 'target': target, 'dates': dates,
            'missingFiles': [d for d in dates if d not in files],
            'method': '直接读取stk_factor_pro qfq OHLC，沿用来源复权基准，不依赖adj_factor；元/股；成交量 vol 单位手，不复权；amount 千元转换为元',
            'series': series}


def refresh_kline_ui(html):
    """Refresh interaction without rebuilding or changing the daily data payload."""
    html = minute_availability_note(html)
    payload = re.search(r'<script id="kline-data" type="application/json">(.*?)</script>', html, re.S)
    if not payload:
        raise ValueError('Existing daily chart payload not found')
    feature = (BASE / 'level2_kline_ui.html').read_text(encoding='utf-8').replace('__KLINE_PAYLOAD__', payload[1])
    return re.sub(r'<!-- KLINE START -->.*?<!-- KLINE END -->',
                  lambda _: '<!-- KLINE START -->'+feature+'<!-- KLINE END -->', html, flags=re.S)


def add_kline(html, cards, target, embedded=True):
    # Idempotent: refresh only this feature, retaining verified Level-2 payload.
    html = re.sub(r'<!-- KLINE START -->.*?<!-- KLINE END -->', '', html, flags=re.S)
    html = minute_availability_note(html)
    bundle = build_bundle({c['code'] for c in cards}, target) if embedded else {'target':target,'dates':[],'series':{},'source':str(SOURCE),'method':'悬浮时读取本地文件'}
    payload = json.dumps(bundle, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
    assets = (BASE / 'level2_kline_ui.html').read_text(encoding='utf-8')
    feature = '<!-- KLINE START -->' + assets.replace('__KLINE_PAYLOAD__', payload) + '<!-- KLINE END -->'
    return html.replace('</body>', feature + '</body>'), bundle


def minute_availability_note(html):
    return html.replace('盘中价格曲线、补撤单重建、支撑强度、买卖触发与失效验证尚未完成；',
                        '当日分钟K线可通过代码右侧“分”图标查看；补撤单重建、支撑强度、买卖触发与失效验证尚未完成；')


if __name__ == '__main__':
    path = BASE / 'level2-market-scan_20260922.html'
    html = path.read_text(encoding='utf-8')
    start = re.search(r'const\s+D\s*=\s*', html)
    data, _ = json.JSONDecoder().raw_decode(html[start.end():])
    html, bundle = add_kline(html, data['cards'], data['markets'][-1]['day'])
    path.write_text(html, encoding='utf-8')
    print(json.dumps({'stocks': len(bundle['series']), 'withCandles': sum(bool(x['bars']) for x in bundle['series'].values()),
                      'sessions': len(bundle['dates']), 'missingFiles': bundle['missingFiles'], 'bytes': path.stat().st_size}))
