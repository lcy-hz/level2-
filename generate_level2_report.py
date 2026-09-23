"""Canonical 20260922 Level-2 report. Full-market rows never enter pandas."""
from pathlib import Path
import json, duckdb, pandas as pd, argparse
from level2_paths import PATHS
ROOT=PATHS['level2']; OUT=Path(__file__).parent/'level2-market-scan_20260922.html'
NAMES=PATHS['stock_basic']
DATES=['20260914','20260915','20260916','20260917','20260918','20260921','20260922']; TARGET=DATES[-1]
parser=argparse.ArgumentParser()
parser.add_argument('--date',default=TARGET)
parser.add_argument('--dates',nargs='+')
parser.add_argument('--output',type=Path,default=OUT)
args=parser.parse_args()
TARGET=args.date; OUT=args.output
if args.dates: DATES=args.dates
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
 return f'''WITH x AS (SELECT "万得代码" code,SUM(TRY_CAST("成交数量" AS DOUBLE)) FILTER(WHERE TRY_CAST("成交价格" AS DOUBLE)>0) dvol,SUM(TRY_CAST("成交价格" AS DOUBLE)*TRY_CAST("成交数量" AS DOUBLE)/10000) FILTER(WHERE TRY_CAST("成交价格" AS DOUBLE)>0) amount,SUM(CASE WHEN "BS标志"='B' THEN TRY_CAST("成交价格" AS DOUBLE)*TRY_CAST("成交数量" AS DOUBLE)/10000 WHEN "BS标志"='S' THEN -TRY_CAST("成交价格" AS DOUBLE)*TRY_CAST("成交数量" AS DOUBLE)/10000 ELSE 0 END) net,COUNT(*) FILTER(WHERE TRY_CAST("成交价格" AS DOUBLE)>0) trades FROM read_parquet('{dp}') WHERE regexp_matches("万得代码",'{PAT}') GROUP BY 1),
 s AS (SELECT "万得代码" code,TRY_CAST("时间" AS BIGINT) close_time,TRY_CAST("成交价" AS DOUBLE)/10000 close_px,TRY_CAST("前收盘" AS DOUBLE)/10000 pre,TRY_CAST("最高价" AS DOUBLE)/10000 high,TRY_CAST("最低价" AS DOUBLE)/10000 low,TRY_CAST("当日累计成交量" AS DOUBLE) svol,TRY_CAST("当日成交额" AS DOUBLE) samt,ROW_NUMBER()OVER(PARTITION BY "万得代码" ORDER BY TRY_CAST("时间" AS BIGINT) DESC) rn FROM read_parquet('{sp}') WHERE regexp_matches("万得代码",'{PAT}') AND TRY_CAST("成交价" AS DOUBLE)>0),
 b AS (SELECT "万得代码" code,TRY_CAST("时间" AS BIGINT) book_time,{bid} AS bid_depth10,{ask} AS ask_depth10,ROW_NUMBER()OVER(PARTITION BY "万得代码" ORDER BY TRY_CAST("时间" AS BIGINT) DESC) rn FROM read_parquet('{sp}') WHERE regexp_matches("万得代码",'{PAT}') AND TRY_CAST("时间" AS BIGINT)<145700000)
 SELECT '{d}' AS trade_day,x.code,close_px,pre,100*(close_px/pre-1) ret,high,low,amount,net,net/NULLIF(amount,0) net_ratio,dvol,svol,samt,(dvol-svol)/NULLIF(svol,0) vgap,(amount-samt)/NULLIF(samt,0) agap,trades,close_time,book_time,bid_depth10,ask_depth10,(bid_depth10-ask_depth10)/NULLIF(bid_depth10+ask_depth10,0) imb FROM x JOIN s ON x.code=s.code AND s.rn=1 LEFT JOIN b ON x.code=b.code AND b.rn=1 WHERE pre>0'''
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
seg=con.execute(f'''SELECT "自然日" AS trade_day,"万得代码" code,CASE WHEN TRY_CAST("时间" AS BIGINT)<100000000 THEN '09:30–10:00' WHEN TRY_CAST("时间" AS BIGINT)<103000000 THEN '10:00–10:30' WHEN TRY_CAST("时间" AS BIGINT)<=113000000 THEN '10:30–11:30' WHEN TRY_CAST("时间" AS BIGINT)<140000000 THEN '13:00–14:00' ELSE '14:00–收盘' END segment,SUM(TRY_CAST("成交价格" AS DOUBLE)*TRY_CAST("成交数量" AS DOUBLE)/10000) amount,SUM(CASE WHEN "BS标志"='B' THEN TRY_CAST("成交价格" AS DOUBLE)*TRY_CAST("成交数量" AS DOUBLE)/10000 WHEN "BS标志"='S' THEN -TRY_CAST("成交价格" AS DOUBLE)*TRY_CAST("成交数量" AS DOUBLE)/10000 ELSE 0 END) net,SUM(TRY_CAST("成交价格" AS DOUBLE)*TRY_CAST("成交数量" AS DOUBLE)/10000)/SUM(TRY_CAST("成交数量" AS DOUBLE)) vwap FROM read_parquet({paths},union_by_name=true) WHERE "万得代码" IN ({cl}) AND TRY_CAST("成交价格" AS DOUBLE)>0 AND ((TRY_CAST("时间" AS BIGINT)>=93000000 AND TRY_CAST("时间" AS BIGINT)<=113000000) OR (TRY_CAST("时间" AS BIGINT)>=130000000 AND TRY_CAST("时间" AS BIGINT)<=150000000)) GROUP BY 1,2,3''').df()
par=con.execute(f'''WITH p AS(SELECT "万得代码" code,"BS标志" side,CASE WHEN "BS标志"='B' THEN "叫买序号" ELSE "叫卖序号" END pid,SUM(TRY_CAST("成交价格" AS DOUBLE)*TRY_CAST("成交数量" AS DOUBLE)/10000) amt FROM read_parquet('{ROOT/f'deal_{TARGET}.parquet'}') WHERE "万得代码" IN ({cl}) AND TRY_CAST("成交价格" AS DOUBLE)>0 AND "BS标志" IN('B','S') GROUP BY 1,2,3) SELECT code,CASE WHEN amt<50000 THEN '<5万' WHEN amt<200000 THEN '5–20万' WHEN amt<1000000 THEN '20–100万' ELSE '≥100万' END bucket,SUM(CASE WHEN side='B' THEN amt ELSE -amt END) net,COUNT(*) cnt FROM p GROUP BY 1,2''').df()
orders=con.execute(f'''SELECT "万得代码" code,COALESCE(NULLIF(TRIM("委托类型"),''),'空') typ,COALESCE(NULLIF(TRIM("委托代码"),''),'空') side,COUNT(*) row_count,SUM(TRY_CAST("委托数量" AS DOUBLE)) qty FROM read_parquet('{ROOT/f'order_raw_{TARGET}.parquet'}') WHERE "万得代码" IN ({cl}) GROUP BY 1,2,3''').df()
def label(r):
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
P=json.dumps(data,ensure_ascii=False,separators=(',',':'))
HTML='''<!doctype html><html lang=zh-CN><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>2026-09-22 Level-2 连续证据报告</title><style>:root{--b:#07111e;--p:#0e1b2d;--l:#27415c;--t:#e7f0fa;--m:#8fa7c1;--g:#55dda1;--r:#ff7d8a}*{box-sizing:border-box}body{margin:0;background:var(--b);color:var(--t);font:14px/1.55 -apple-system,"PingFang SC",sans-serif}.w{max-width:1400px;margin:auto;padding:25px 18px 60px}h1{margin:4px 0}h2{border-left:3px solid #53d4ff;padding-left:9px;margin-top:28px}.muted{color:var(--m)}.warn{padding:12px;background:#241e13;border:1px solid #785e29;border-radius:9px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.p,.card{background:var(--p);border:1px solid var(--l);border-radius:10px;padding:13px}.metric b{display:block;font-size:20px}.pos{color:var(--g)}.neg{color:var(--r)}table{width:100%;border-collapse:collapse}th,td{padding:7px;border-bottom:1px solid var(--l);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}.scroll{overflow:auto}.controls{display:flex;gap:8px;margin:12px 0;flex-wrap:wrap}input,select,button{background:#10253b;color:var(--t);border:1px solid var(--l);padding:8px;border-radius:7px}.card{cursor:pointer}.card:hover{border-color:#53d4ff}.tag{color:#bdeaff}dialog{width:min(1000px,94vw);max-height:90vh;overflow:auto;background:#09182a;color:var(--t);border:1px solid #3b6080;border-radius:12px}.two{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:800px){.grid,.two{grid-template-columns:1fr 1fr}}@media(max-width:550px){.grid,.two{grid-template-columns:1fr}}</style></head><body><main class=w><div class=muted>RESEARCH_ONLY · 本地原生 Level-2 · 证据日 2026-09-22</div><h1>连续市场与个股证据报告</h1><p class=warn><b>纠错：</b>旧报告把叫买/叫卖总量误作十档，并曾把字符串时间倒序的09:59:57误作收盘。本报告收盘取数值时间≤15:00最后正价；盘口取&lt;14:57连续竞价末档，逐列加总实际申买量1–10/申卖量1–10。主动净额不是持仓或资本流出；上涨且净卖出仅是分歧风险，不确认派发。</p><h2>数据门槛与口径</h2><div class=two><div class=p><b>7/7 发布门槛通过</b><p>尾部7个交易日三类文件、manifest、COMMITTED齐。发布成功不等于原始市场数据无缺；转换 warnings 保留在 manifest。本地只有9个证据日，20日不足，不替换日期。</p></div><div class=p><b>单位与方向</b><p>价格原始1/10000元，数量股，金额元。B/S为有效成交方向；C零价格记录不混入成交。对账展示逐股量额误差95分位。</p></div></div><h2>最近7交易日市场轨迹</h2><div id=metrics class=grid></div><div class="p scroll"><table><thead><tr><th>日期</th><th>股票</th><th>成交额</th><th>主动净额</th><th>上涨/下跌</th><th>量差P95</th><th>额差P95</th></tr></thead><tbody id=market></tbody></table></div><h2>候选形成与变化</h2><p>成交额≥2亿元后，以主动净额比45%+涨跌幅30%+成交额15%+连续竞价末档十档不平衡10%横截面排序。后验1/3日只用于历史验证，不回填当时信号。</p><div class=controls><input id=search placeholder="搜索代码/名称"><select id=filter><option value=全部>全部</option><option>主动推动候选</option><option>下跌中的主动承接候选</option><option>高位分歧风险</option><option>弱势流出/其他</option></select><select id=sort><option value=default>默认顺序</option><option value=net>主动净额</option><option value=ret>涨跌幅</option><option value=amount>成交额</option></select></div><div id=cards class=grid></div><h2>证据、反证与未知</h2><div class=two><div class=p><b>已实做</b><p>全市场7日日级轨迹；重点候选盘中价格/VWAP、五时段主动成交、主动成交关联单金额组、真实十档、状态迁移与独立后验。</p></div><div class=p><b>UNKNOWN</b><p>order_raw 已真实读取并展示类型/方向覆盖，但类型码、撤单—成交关联与深沪一致性尚未完成可靠验证，不能计算补单率/撤单率。委托序号是关联键，不是机构母单身份。</p></div></div><p class=muted>盘中深查仅覆盖页面重点候选；全市场部分为日级聚合。盘后15:30快照不作15:00可执行盘口。本报告不构成交易授权。</p></main><dialog id=dlg><button onclick="dlg.close()">关闭</button><div id=detail></div></dialog><script>const D='''+P+''';const M=v=>{let a=Math.abs(v),s=v<0?'-':'';return a>=1e8?s+(a/1e8).toFixed(2)+'亿':s+(a/1e4).toFixed(1)+'万'},P=v=>v==null?'未知':(v>=0?'+':'')+v.toFixed(2)+'%',C=v=>v>=0?'pos':'neg';market.innerHTML=D.markets.map(x=>`<tr><td>${x.day}</td><td>${x.stocks}</td><td>${M(x.amount)}</td><td class=${C(x.net)}>${M(x.net)}</td><td>${x.up}/${x.down}</td><td>${x.vp95}%</td><td>${x.ap95}%</td></tr>`).join('');let z=D.markets.at(-1);metrics.innerHTML=`<div class="p metric"><b>${z.stocks}</b>纳入A股</div><div class="p metric"><b>${M(z.amount)}</b>成交额</div><div class="p metric"><b class=${C(z.net)}>${M(z.net)}</b>主动净额</div><div class="p metric"><b>${z.up}/${z.down}</b>上涨/下跌</div>`;function table(h,r){return `<div class=scroll><table><thead><tr>${h.map(x=>'<th>'+x+'</th>').join('')}</tr></thead><tbody>${r.join('')}</tbody></table></div>`}function render(){let q=search.value.toLowerCase(),f=filter.value,a=D.cards.filter(x=>(f==='全部'||x.label===f)&&(!q||x.code.toLowerCase().includes(q)||x.name.toLowerCase().includes(q)));if(sort.value!=='default')a.sort((x,y)=>y[sort.value]-x[sort.value]);cards.innerHTML=a.map(x=>`<article class=card onclick="openCard('${x.code}')"><span class=tag>${x.label}</span><h3>${x.name} <span class=muted>${x.code}</span></h3><div>收盘 ${x.close} · VWAP ${x.vwap}</div><div>涨跌 <b class=${C(x.ret)}>${P(x.ret)}</b> · 净额 <b class=${C(x.net)}>${M(x.net)}</b></div><div>十档 买 ${x.bid.toLocaleString()} / 卖 ${x.ask.toLocaleString()}</div></article>`).join('')}search.oninput=filter.onchange=sort.onchange=render;function openCard(c){let x=D.cards.find(y=>y.code===c);detail.innerHTML=`<h2>${x.name} ${x.code}</h2><p>${x.label} · 收盘 ${x.close} · VWAP ${x.vwap} · 净额比 ${P(x.ratio)}</p><p>连续竞价盘口时点 ${x.bookTime}；量/额对账误差 ${x.vgap}% / ${x.agap}%</p><h3>盘中主动成交</h3>${table(['时段','成交额','净额','VWAP'],x.segments.map(y=>`<tr><td>${y.s}</td><td>${M(y.a)}</td><td class=${C(y.n)}>${M(y.n)}</td><td>${y.v}</td></tr>`))}<h3>主动成交关联单分组</h3>${table(['金额组','净额','组数'],x.parents.map(y=>`<tr><td>${y.b}</td><td class=${C(y.n)}>${M(y.n)}</td><td>${y.c}</td></tr>`))}<h3>order_raw覆盖（非撤单结论）</h3>${table(['类型原值','方向','行数','数量'],x.orders.map(y=>`<tr><td>${y.t}</td><td>${y.s}</td><td>${y.r.toLocaleString()}</td><td>${y.q.toLocaleString()}</td></tr>`))}<h3>信号轨迹/独立后验</h3>${table(['信号日','当时标签','当日','净额','后1日','后3日'],x.history.map(y=>`<tr><td>${y.day}</td><td>${y.label}</td><td>${P(y.ret)}</td><td class=${C(y.net)}>${M(y.net)}</td><td>${P(y.f1)}</td><td>${P(y.f3)}</td></tr>`))}`;dlg.showModal()}render();</script></body></html>'''
HTML=HTML.replace('本报告收盘取数值时间≤15:00最后正价；盘口取&lt;14:57连续竞价末档','本报告日终收盘取数值时间最后正价（可能为延迟发布的闭市结果，不解释为可交易时点）；盘口取&lt;14:57连续竞价末档')
HTML=HTML.replace('<b>7/7 发布门槛通过</b>','<b>7/7 发布门槛通过</b><p>'+('；'.join(x['day']+' warnings='+str(x['warnings']) for x in gates))+'</p>')
HTML=HTML.replace('本地只有9个证据日，20日不足，不替换日期。','本报告分析窗口为尾部7个交易日；20日窗口未计算，不用其他日期替换。各日转换 warning 数已嵌入数据门槛。')
HTML=HTML.replace('以主动净额比45%+涨跌幅30%+成交额15%+连续竞价末档十档不平衡10%横截面排序。','按透明的主动净额比横截面排序；涨跌幅、成交额与真实十档作为并列事实，不合成未经校准的概率分。')
HTML=HTML.replace('<option>高位分歧风险</option>','<option>被动承接候选（未确认）</option><option>高位分歧风险</option>')
HTML=HTML.replace('重点候选盘中价格/VWAP、五时段主动成交','重点候选收盘/VWAP、五时段主动成交')
HTML=HTML.replace("a=D.cards.filter(x=>(f==='全部'||x.label===f)&&(!q||x.code.toLowerCase().includes(q)||x.name.toLowerCase().includes(q)))","a=D.cards.filter(x=>(q||f!=='全部'||x.detail)&&(f==='全部'||x.label===f)&&(!q||x.code.toLowerCase().includes(q)||x.name.toLowerCase().includes(q)))")
HTML=HTML.replace("detail.innerHTML=`<h2>${x.name}","detail.innerHTML=`<h2>${x.name}")
HTML=HTML.replace("<h3>盘中主动成交</h3>${table(","${x.detail?'<h3>重点深查</h3>':'<p class=warn>该股仅有全市场日级轨迹；盘中分段、关联单和 order_raw 深查未计算。</p>'}<h3>盘中主动成交</h3>${table(")
HTML=HTML.replace('连续竞价盘口时点 ${x.bookTime}；量/额对账误差','日终证据发布时点 ${x.closeTime}（非可交易时点）；连续竞价盘口时点 ${x.bookTime}；常规时段五段成交额覆盖全天 ${x.regularCoverage==null?\'未计算\':x.regularCoverage+\'%\'}，其余含竞价或时钟异常记录；量/额对账误差')
HTML=HTML.replace('按透明的主动净额比横截面排序；涨跌幅、成交额与真实十档作为并列事实，不合成未经校准的概率分。','分池后透明排序：主动推动/主动承接按净额比降序，分歧/弱势按净额比升序，被动承接按涨跌幅降序；池间可能重叠，标签按页面优先级互斥；不合成未经校准的概率分。')
HTML=HTML.replace('后验1/3日只用于历史验证，不回填当时信号。','后1/3日只展示历史原始收盘变化，不回填当时信号；未复权且存在目标日存续样本选择偏差，不是无偏回测或信号有效性验证。')
HTML=HTML.replace('信号轨迹/独立后验','信号轨迹/历史原始收盘变化（未复权、非策略回测）')
HTML=HTML.replace('状态迁移与独立后验','标签历史与原始收盘后续变化')
HTML=HTML.replace('x.segments.map(', '[...x.segments].sort((a,b)=>a.s.localeCompare(b.s)).map(')
HTML=HTML.replace('x.parents.map(', "[...x.parents].sort((a,b)=>['<5万','5–20万','20–100万','≥100万'].indexOf(a.b)-['<5万','5–20万','20–100万','≥100万'].indexOf(b.b)).map(")
HTML=HTML.replace('<option value=全部>全部</option>', '<option value=全部>全部类型（默认重点股）</option>')
HTML=HTML.replace('<div id=cards class=grid></div>', '<p class=muted>默认显示33只重点深查股；输入代码或名称可搜索5,209只股票。深查并不等于买入推荐。</p><div id=cards class=grid></div>')
HTML=HTML.replace('本报告不构成交易授权。', '盘中价格曲线、补撤单重建、支撑强度、买卖触发与失效验证尚未完成；这些状态为未验证，并非没有信号。本报告不构成交易授权。')
HTML=HTML.replace('<select id=sort>', '<select id=direction aria-label="涨跌方向"><option value=all>全部涨跌</option><option value=up>↑ 上涨</option><option value=down>↓ 下跌</option><option value=flat>— 平盘</option></select><select id=sort>')
HTML=HTML.replace("(q||f!=='全部'||x.detail)", "(q||f!=='全部'||direction.value!=='all'||x.detail)")
HTML=HTML.replace("(f==='全部'||x.label===f)&&", "(f==='全部'||x.label===f)&&(direction.value==='all'||(direction.value==='up'&&x.ret>0)||(direction.value==='down'&&x.ret<0)||(direction.value==='flat'&&x.ret===0))&&")
HTML=HTML.replace('<span class=tag>${x.label}</span>', '<span class=tag>${x.label}</span> · <b class="${x.ret>0?\'pos\':x.ret<0?\'neg\':\'muted\'}">${x.ret>0?\'↑ 上涨\':x.ret<0?\'↓ 下跌\':\'— 平盘\'}</b>')
HTML=HTML.replace('search.oninput=filter.onchange=sort.onchange=render;', 'search.oninput=filter.onchange=direction.onchange=sort.onchange=render;')
HTML=HTML.replace('输入代码或名称可搜索5,209只股票。', '输入代码或名称可搜索5,209只股票；选择涨跌方向可筛选全库，并可与候选类型组合。')
HTML=HTML.replace('x.ret>0', 'x.returnSign>0').replace('x.ret<0', 'x.returnSign<0').replace('x.ret===0', 'x.returnSign===0')
HTML=HTML.replace('<select id=sort>', '<select id=sort aria-label="排序指标">')
HTML=HTML.replace('<option value=amount>成交额</option></select>', '<option value=amount>成交额</option></select><select id=sortOrder aria-label="排序方向" disabled><option value=desc>倒序（大 → 小）</option><option value=asc>正序（小 → 大）</option></select>')
HTML=HTML.replace("function render(){", "function render(){sortOrder.disabled=sort.value==='default';")
HTML=HTML.replace('a.sort((x,y)=>y[sort.value]-x[sort.value])', "a.sort((x,y)=>(sortOrder.value==='asc'?1:-1)*(x[sort.value]-y[sort.value]))")
HTML=HTML.replace('direction.onchange=sort.onchange=render;', 'direction.onchange=sort.onchange=sortOrder.onchange=render;')
from level2_kline import add_kline
HTML, kline_bundle = add_kline(HTML, cards, TARGET, embedded=False)
from level2_detail_server import add_detail_controls
HTML = add_detail_controls(HTML)
HTML=HTML.replace('2026-09-22',f'{TARGET[:4]}-{TARGET[4:6]}-{TARGET[6:]}')
HTML=HTML.replace('33只',str(len(codes))+'只').replace('5,209只',f'{len(cards):,}只')
OUT.write_text(HTML,encoding='utf-8'); print(OUT); print('days',len(DATES),'stocks',len(latest),'cards',len(cards),'bytes',OUT.stat().st_size)
