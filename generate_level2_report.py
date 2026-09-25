"""Canonical 20260922 Level-2 report. Full-market rows never enter pandas."""
from pathlib import Path
import json, duckdb, pandas as pd, argparse
from level2_paths import PATHS
from level2_contract import native_ticks,KNOWN_NET,UNKNOWN_AMOUNT,COMPLETE_NET,parent_query,window
from level2_state import settings
ROOT=PATHS['level2']
NAMES=PATHS['stock_basic']
DATES=['20260914','20260915','20260916','20260917','20260918','20260921','20260922']; TARGET=DATES[-1]
parser=argparse.ArgumentParser()
parser.add_argument('--date',default=TARGET)
parser.add_argument('--dates',nargs='+')
parser.add_argument('--output',type=Path)
args=parser.parse_args()
TARGET=args.date; OUT=args.output or Path(__file__).parent/'.level2_reports'/TARGET/'report.json'
if OUT.suffix!='.json':raise ValueError('新报告仅生成 JSON；旧 HTML 页面已停止生成')
DATES=window(TARGET,7,settings()['trade_calendar'])
if args.dates and args.dates!=DATES:raise ValueError('报告窗口必须等于交易日历的最近7交易日，不能跳过缺口')
if len(DATES)!=7:raise ValueError('交易日历不足7日')
if not DATES or DATES[-1]!=TARGET or DATES!=sorted(set(DATES)) or any(d>TARGET for d in DATES): raise ValueError('Invalid report window')
PAT=r'^(000|001|002|003|300|301|302|600|601|603|605|688|689)[0-9]{3}\.(SZ|SH)$'
def n(v,d=2): return None if pd.isna(v) else round(float(v),d)
def gate(d):
 a=ROOT/'_conversion_audit'/d
 mp=a/'manifest.json'; m=json.loads(mp.read_text()) if mp.is_file() else {}
 return {'day':d,'files':all((ROOT/f'{k}_{d}.parquet').is_file() for k in ('deal','snapshot','order_raw')),'committed':(a/'COMMITTED').is_file() and m.get('commit_state')=='COMMITTED','manifest':mp.is_file(),'warnings':m.get('warning_count'),'conversionErrors':m.get('conversion_error_count')}
def qday(d):
 dp=ROOT/f'deal_{d}.parquet'; sp=ROOT/f'snapshot_{d}.parquet'
 bid='+'.join(f'COALESCE(TRY_CAST("申买量{i}" AS DOUBLE),0)' for i in range(1,11)); ask='+'.join(f'COALESCE(TRY_CAST("申卖量{i}" AS DOUBLE),0)' for i in range(1,11))
 return f'''WITH ticks AS ({native_ticks(dp,d)}), x AS (SELECT code,SUM(qty) dvol,SUM(price*qty) amount,{COMPLETE_NET} net,{KNOWN_NET} known_net,{UNKNOWN_AMOUNT} unknown_amount,COUNT(*) trades FROM ticks GROUP BY code),
 s AS (SELECT "万得代码" code,TRY_CAST("时间" AS BIGINT) close_time,TRY_CAST("成交价" AS DOUBLE)/10000 close_px,TRY_CAST("前收盘" AS DOUBLE)/10000 pre,TRY_CAST("最高价" AS DOUBLE)/10000 high,TRY_CAST("最低价" AS DOUBLE)/10000 low,TRY_CAST("当日累计成交量" AS DOUBLE) svol,TRY_CAST("当日成交额" AS DOUBLE) samt,ROW_NUMBER()OVER(PARTITION BY "万得代码" ORDER BY TRY_CAST("时间" AS BIGINT) DESC) rn FROM read_parquet('{sp}') WHERE regexp_matches("万得代码",'{PAT}') AND TRY_CAST("成交价" AS DOUBLE)>0),
 b AS (SELECT "万得代码" code,TRY_CAST("时间" AS BIGINT) book_time,{bid} AS bid_depth10,{ask} AS ask_depth10,ROW_NUMBER()OVER(PARTITION BY "万得代码" ORDER BY TRY_CAST("时间" AS BIGINT) DESC) rn FROM read_parquet('{sp}') WHERE regexp_matches("万得代码",'{PAT}') AND TRY_CAST("时间" AS BIGINT)<145700000)
 SELECT '{d}' AS trade_day,x.code,close_px,pre,100*(close_px/pre-1) ret,high,low,amount,net,known_net,unknown_amount,net/NULLIF(amount,0) net_ratio,dvol,svol,samt,(dvol-svol)/NULLIF(svol,0) vgap,(amount-samt)/NULLIF(samt,0) agap,trades,close_time,book_time,bid_depth10,ask_depth10,(bid_depth10-ask_depth10)/NULLIF(bid_depth10+ask_depth10,0) imb FROM x JOIN s ON x.code=s.code AND s.rn=1 LEFT JOIN b ON x.code=b.code AND b.rn=1 WHERE pre>0'''
con=duckdb.connect(); con.execute('PRAGMA threads=4'); con.execute("PRAGMA memory_limit='4GB'")
gates=[gate(d) for d in DATES]
if not all(x['files'] and x['committed'] and x['manifest'] for x in gates): raise RuntimeError(gates)
fs=[]
for d in DATES: print('aggregate',d,flush=True); fs.append(con.execute(qday(d)).df())
names=pd.read_csv(NAMES,usecols=['ts_code','name'],dtype=str).drop_duplicates('ts_code')
daily=pd.concat(fs).merge(names,left_on='code',right_on='ts_code',how='left').drop(columns='ts_code'); daily.name=daily.name.fillna('未匹配名称')
# Regression: numeric time sorting must reproduce the independently checked close series.
bp=daily[daily.code=='301080.SZ'].sort_values('trade_day'); expected=[91.74,90.21,91.91,99.28,109.48,116.20,118.80]
if TARGET=='20260922':
 assert bp.trade_day.tolist()==DATES and all(abs(a-b)<1e-8 for a,b in zip(bp.close_px,expected)),bp[['trade_day','close_px']]
latest=daily[daily.trade_day==TARGET].copy(); liquid=latest[latest.amount>=2e8].copy()
if TARGET=='20260922':
 assert abs(float(latest.loc[latest.code=='600006.SH','close_px'].iloc[0])-5.31)<1e-8
 assert (int((latest.ret>0).sum()),int((latest.ret<0).sum()),int((latest.ret==0).sum()))==(2284,2783,142)
push=liquid[(liquid.ret>0)&(liquid.net>0)].nlargest(8,'net_ratio'); support=liquid[liquid.ret.between(-3,0)&(liquid.net>0)].nlargest(6,'net_ratio'); passive=liquid[liquid.ret.between(-1,3)&(liquid.net<0)].nlargest(6,'ret'); diverge=liquid[(liquid.ret>3)&(liquid.net<0)].nsmallest(6,'net_ratio'); weak=liquid[(liquid.ret<0)&(liquid.net<0)].nsmallest(6,'net_ratio')
codes=list(dict.fromkeys(pd.concat([push.code,support.code,passive.code,diverge.code,weak.code,pd.Series(['301080.SZ'])]).tolist())); cl=','.join(repr(x) for x in codes)
paths='['+','.join(repr(str(ROOT/f'deal_{d}.parquet')) for d in DATES)+']'
segments=[]
for d in DATES:
 con.execute('CREATE OR REPLACE TEMP VIEW ticks AS '+native_ticks(ROOT/f'deal_{d}.parquet',d,codes))
 segments.append(con.execute(f'''SELECT trade_day,code,CASE WHEN t<100000000 THEN '09:30–10:00' WHEN t<103000000 THEN '10:00–10:30' WHEN t<=113000000 THEN '10:30–11:30' WHEN t<140000000 THEN '13:00–14:00' ELSE '14:00–收盘' END segment,SUM(price*qty) amount,{COMPLETE_NET} net,SUM(price*qty)/SUM(qty) vwap FROM ticks WHERE (t BETWEEN 93000000 AND 113000000) OR (t BETWEEN 130000000 AND 150000000) GROUP BY 1,2,3''').df())
seg=pd.concat(segments)
par=con.execute(parent_query()).df()
orders=con.execute(f'''SELECT "万得代码" code,COALESCE(NULLIF(TRIM("委托类型"),''),'空') typ,COALESCE(NULLIF(TRIM("委托代码"),''),'空') side,COUNT(*) row_count,SUM(TRY_CAST("委托数量" AS DOUBLE)) qty FROM read_parquet('{ROOT/f'order_raw_{TARGET}.parquet'}') WHERE "万得代码" IN ({cl}) GROUP BY 1,2,3''').df()
def label(r):
 if pd.isna(r.net):return '方向未知／证据不足'
 if r.ret>0 and r.net>0:return '主动推动候选'
 if -3<=r.ret<=0 and r.net>0:return '下跌中的主动承接候选'
 if -1<=r.ret<=3 and r.net<0:return '被动承接候选（未确认）'
 if r.ret>0 and r.net<0:return '高位分歧风险'
 return '弱势流出/其他'
cards=[]
for code in latest.code.tolist():
 h=daily[daily.code==code].sort_values('trade_day').reset_index(drop=True); r=h.iloc[-1]; sg=seg[(seg.code==code)&(seg.trade_day==TARGET)]
 hist=[]
 byday={z.trade_day:z for _,z in h.iterrows()}
 for i,z in h.iterrows():
  di=DATES.index(z.trade_day); z1=byday.get(DATES[di+1]) if di+1<len(DATES) else None; z3=byday.get(DATES[di+3]) if di+3<len(DATES) else None
  hist.append({'day':z.trade_day,'label':label(z),'ret':n(z.ret),'net':n(z.net,0),'f1':n((z1.close_px/z.close_px-1)*100) if z1 is not None else None,'f3':n((z3.close_px/z.close_px-1)*100) if z3 is not None else None})
 cards.append({'code':code,'name':r['name'],'label':label(r),'detail':code in codes,'ret':n(r.ret),'close':n(r.close_px),'closeTime':int(r.close_time),'vwap':n(r.amount/r.dvol,4),'amount':n(r.amount,0),'regularCoverage':n(sg.amount.sum()/r.amount*100) if len(sg) else None,'net':n(r.net,0),'ratio':n(r.net_ratio*100),'bid':n(r.bid_depth10,0),'ask':n(r.ask_depth10,0),'bookTime':int(r.book_time),'vgap':n(r.vgap*100,5),'agap':n(r.agap*100,5),'segments':[{'s':x.segment,'a':n(x.amount,0),'n':n(x.net,0),'v':n(x.vwap,4)} for x in sg.itertuples()],'parents':[{'b':x.bucket,'n':n(x.net,0),'c':int(x.cnt)} for x in par[par.code==code].itertuples()],'orders':[{'t':x.typ,'s':x.side,'r':int(x.row_count),'q':n(x.qty,0)} for x in orders[orders.code==code].itertuples()],'history':hist})
return_signs = {row.code: (1 if row.ret > 0 else -1 if row.ret < 0 else 0) for row in latest.itertuples()}
for card in cards:
 card['returnSign'] = return_signs[card['code']]
markets=[]
for d,g in daily.groupby('trade_day',sort=True): markets.append({'day':d,'stocks':len(g),'amount':n(g.amount.sum(),0),'net':n(g.net.sum(),0),'up':int((g.ret>0).sum()),'down':int((g.ret<0).sum()),'vp95':n(g.vgap.abs().quantile(.95)*100,5),'ap95':n(g.agap.abs().quantile(.95)*100,5)})
data={'markets':markets,'cards':cards,'gate':gates,'lists':{'主动推动':push.code.tolist(),'主动承接':support.code.tolist(),'被动承接':passive.code.tolist(),'分歧风险':diverge.code.tolist(),'弱势流出':weak.code.tolist()}}
for card in cards:
 row=latest[latest.code==card['code']].iloc[0]
 card.update(knownNet=n(row.known_net,0),unknownAmount=n(row.unknown_amount,0),
             directionStatus='AVAILABLE' if row.unknown_amount==0 else 'UNKNOWN',
             parentIdentityStatus='UNVERIFIED_NO_CHANNEL')
for market in markets:
 g=daily[daily.trade_day==market['day']]
 market.update(knownNet=n(g.known_net.sum(),0),unknownAmount=n(g.unknown_amount.sum(),0),unknownStocks=int(g.net.isna().sum()))
 if market['unknownStocks']:market['net']=None
from level2_quality import quality_report
data['quality']=quality_report(con,ROOT,TARGET,lambda s:print(s,flush=True))
segment_order={'09:30–10:00':0,'10:00–10:30':1,'10:30–11:30':2,'13:00–14:00':3,'14:00–收盘':4}
parent_order={'<5万':0,'5–20万':1,'20–100万':2,'≥100万':3,'关联键未知':4}
for card in cards:
 card['segments'].sort(key=lambda row:segment_order.get(row['s'],99))
 card['parents'].sort(key=lambda row:parent_order.get(row['b'],99))
 card['orders'].sort(key=lambda row:(row['t'],row['s']))
cards.sort(key=lambda card:card['code'])
P=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False)
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(P,encoding='utf-8')
print(OUT); print('days',len(DATES),'stocks',len(latest),'cards',len(cards),'bytes',OUT.stat().st_size)
