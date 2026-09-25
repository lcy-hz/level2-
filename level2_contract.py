"""Shared calendar and native成交 contracts. SQL builders are used by report and detail."""
import csv
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

PAT=r'^(000|001|002|003|300|301|302|600|601|603|605|688|689)[0-9]{3}\.(SZ|SH)$'

@lru_cache(maxsize=8)
def _calendar(path, size, mtime):
    with open(path,newline='') as f: rows=[r for r in csv.DictReader(f) if r.get('exchange')=='SSE']
    if not rows:raise ValueError('交易日历缺少 SSE')
    values={}
    for r in rows:
        d=r['cal_date'];datetime.strptime(d,'%Y%m%d')
        if r.get('is_open') not in ('0','1'):raise ValueError('交易日历开市标记无效：'+d)
        if d in values:raise ValueError('交易日历日期重复：'+d)
        values[d]=r['is_open']
    ordered=sorted(values)
    first=datetime.strptime(ordered[0],'%Y%m%d');last=datetime.strptime(ordered[-1],'%Y%m%d')
    if (last-first).days+1!=len(ordered):raise ValueError('交易日历存在自然日缺口，不能证明连续交易日')
    return tuple(d for d in ordered if values[d]=='1'),ordered[-1]

def calendar(path):
    p=Path(path);s=p.stat();days,last=_calendar(str(p.resolve()),s.st_size,s.st_mtime_ns)
    return list(days),last

def window(day, length, path):
    days,_=calendar(path)
    if day not in days:raise ValueError('截止日不在已核验交易日历内')
    return [d for d in days if d<=day][-length:]

def native_ticks(path, day, codes=None):
    """Valid traded amount: date exact, positive finite price/qty, explicit C excluded.

    Unknown direction remains valid amount, but never a complete directional net.
    Time quality is measured separately; daily amount is not silently intraday-filtered.
    """
    escaped=str(path).replace("'","''")
    code_filter="" if codes is None else ' AND "万得代码" IN ('+','.join("'"+c.replace("'","''")+"'" for c in codes)+')'
    return f'''SELECT "万得代码" code,CAST("自然日" AS VARCHAR) trade_day,
       TRY_CAST("时间" AS BIGINT) t,TRY_CAST("成交价格" AS DOUBLE)/10000 price,
       TRY_CAST("成交数量" AS DOUBLE) qty,CAST("BS标志" AS VARCHAR) side,
       TRY_CAST(CASE WHEN "BS标志"='B' THEN "叫买序号" WHEN "BS标志"='S' THEN "叫卖序号" END AS BIGINT) pid
       FROM read_parquet('{escaped}') WHERE regexp_matches("万得代码",'{PAT}')
       AND TRY_CAST("自然日" AS BIGINT)={int(day)}
       AND TRY_CAST("成交价格" AS DOUBLE)>0 AND isfinite(TRY_CAST("成交价格" AS DOUBLE))
       AND TRY_CAST("成交数量" AS DOUBLE)>0 AND isfinite(TRY_CAST("成交数量" AS DOUBLE))
       AND COALESCE("BS标志",'')<>'C' {code_filter}'''

KNOWN_NET="SUM(CASE WHEN side='B' THEN price*qty WHEN side='S' THEN -price*qty ELSE 0 END)"
UNKNOWN_AMOUNT="SUM(CASE WHEN side IN ('B','S') THEN 0 ELSE price*qty END)"
COMPLETE_NET=f'CASE WHEN {UNKNOWN_AMOUNT}=0 THEN {KNOWN_NET} ELSE NULL END'

def parent_query(relation='ticks'):
    # Invalid keys are never aggregated into artificial large orders.
    # Date, security and side are part of the key; channel is absent in native schema.
    return f'''WITH g AS (
      SELECT trade_day,code,side,pid,SUM(price*qty) amt FROM {relation}
      WHERE side IN ('B','S') AND pid>0 GROUP BY 1,2,3,4
    ), b AS (
      SELECT code,CASE WHEN amt<50000 THEN '<5万' WHEN amt<200000 THEN '5–20万'
        WHEN amt<1000000 THEN '20–100万' ELSE '≥100万' END bucket,
        CASE WHEN side='B' THEN amt ELSE -amt END net,1 cnt FROM g
      UNION ALL
      SELECT code,'关联键未知',CASE WHEN side='B' THEN price*qty ELSE -price*qty END,1
        FROM {relation} WHERE side IN ('B','S') AND (pid IS NULL OR pid<=0)
    ) SELECT code,bucket,SUM(net) net,SUM(cnt) cnt FROM b GROUP BY 1,2'''
