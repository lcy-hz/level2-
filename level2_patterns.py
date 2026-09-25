"""Causal, explicitly parameterized research patterns from local daily factors.

No outcome probabilities, trade authority, or Level-2 inference. Gaps are retained.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import hashlib
import json
import math
import uuid
import numpy as np
import pandas as pd
from level2_contract import window
from level2_paths import PATHS

CATALOG = {
 'soldiers':('红三兵','K线组合',1,8), 'crows':('三只乌鸦','K线组合',-1,8),
 'morning':('早晨之星','K线组合',1,8), 'evening':('黄昏之星','K线组合',-1,8),
 'bull_engulf':('看涨吞没','K线组合',1,8), 'bear_engulf':('看跌吞没','K线组合',-1,8),
 'hammer':('锤头线','单根K线',1,8), 'shooting':('流星线','单根K线',-1,8),
 'double_bottom':('双底','反转结构',1,60), 'double_top':('双顶','反转结构',-1,60),
 'head_bottom':('头肩底','反转结构',1,90), 'head_top':('头肩顶','反转结构',-1,90),
 'round':('圆弧底','反转结构',1,60), 'cup':('杯柄','整理结构',1,90),
 'breakout':('平台突破','趋势结构',1,21), 'retest':('突破回踩','趋势结构',1,21),
 'pullback':('上升趋势回调','趋势结构',1,40), 'box_support':('箱体下沿企稳','趋势结构',1,21),
 'triangle':('三角收敛','整理结构',0,40), 'flag':('旗形整理','整理结构',1,40),
 'failed':('突破失败','风险结构',-1,21), 'breakdown':('支撑跌破','风险结构',-1,21)}
RULES = {
 'history':180,'eventScan':60,'activeSessions':20,'pivotRadius':2,
 'bodyRangeMin':0.5,'smallBodyRatio':0.35,'shadowBody':2.0,'upperBodyMax':0.5,
 'extremaTolerance':0.04,'minSwing':0.05,'breakBuffer':0.005,'volumeMultiple':1.2,
 'boxWidth':0.15,'retestTolerance':0.03,'headDepth':0.03,
 'note':'固定研究规则，未经收益校准。结构必须完整连续；完成型K线无形成中。有效观察20交易日，届满只归历史，不自动判失效。'}
FIELDS=['ts_code','trade_date','open','high','low','close','adj_factor','vol','amount','open_qfq','high_qfq','low_qfq','close_qfq',
        'ma_qfq_5','ma_qfq_10','ma_qfq_20','ma_qfq_60','macd_qfq','macd_dif_qfq','macd_dea_qfq','rsi_qfq_6','kdj_k_qfq','kdj_d_qfq','kdj_qfq']

def clean(x):
    try:
        v=float(x);return v if math.isfinite(v) else None
    except (TypeError,ValueError):return None

def normalize_qfq(row,anchor=None):
    """Read provider qfq fields directly; no adjustment-factor dependency."""
    q=[clean(row.get(k+'_qfq')) for k in ['open','high','low','close']]
    if any(v is None or v<=0 for v in q):return None,{}
    prices=q
    if not prices[2]<=min(prices[0],prices[3])<=max(prices[0],prices[3])<=prices[1]:return None,{}
    vol=clean(row.get('vol'));amount=clean(row.get('amount'))
    indicators={}
    for name in FIELDS[13:]:
        indicators[name]=clean(row.get(name))
    return prices+[vol if vol is not None and vol>=0 else None,amount if amount is not None and amount>=0 else None],indicators

def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def stamp(p):
    p=Path(p)
    if not p.exists():return [str(p),None]
    s=p.stat();return [str(p),s.st_size,s.st_mtime_ns]

def read_factor_files(codes, dates, root, progress=None, workers=8):
    """Bound concurrent CSV reads; return deterministic, date-filtered frames."""
    ordered=sorted(codes)
    workers=max(1,min(8,int(workers)))
    def read(code):
        p=Path(root)/(code.replace('.','_')+'_stk_factor_pro.csv')
        if not p.exists():return code,None
        f=pd.read_csv(p,usecols=lambda c:c in FIELDS,dtype={'ts_code':str,'trade_date':str})
        if set(f.ts_code.dropna())!={code}:raise ValueError('因子个股文件代码不一致：'+code)
        return code,f[f.trade_date.isin(dates)]
    frames=[];missing=[]
    with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='factor-read') as pool:
        for done,(code,frame) in enumerate(pool.map(read,ordered),1):
            if frame is None:missing.append(code)
            else:frames.append(frame)
            if progress:progress(done,len(ordered),workers)
    return frames,missing

def recognize(bars,dates):
    """Input is aligned to authoritative sessions; None resets continuity.
    Prices may use a common adjustment scale: all rules are scale invariant.
    """
    n=len(bars);events=[];keys=set();run=0
    def emit(kind,start,t,key,stop,evidence,anchors=(),forming=False):
        identity=(kind,start)
        if identity in keys:return
        keys.add(identity)
        sign=CATALOG[kind][2]
        if forming and sign and key is not None and vr is not None and vr>=1.2 and (c>key*1.005 if sign>0 else c<key*.995):forming=False
        events.append(dict(eventId=digest([kind,dates[start]])[:16],pattern=kind,name=CATALOG[kind][0],direction=CATALOG[kind][2],
            start=start,detected=t,confirmed=None if forming else t,invalidated=None,key=key,stop=stop,
            stage='forming' if forming else 'confirmed',evidence=evidence,anchors=list(anchors),transitions=[{'index':t,'stage':'forming' if forming else 'confirmed'}]))
    for t,b in enumerate(bars):
        if b is None:run=0;continue
        run+=1;o,h,l,c=b[:4];v=b[4]
        previous=bars[t-20:t] if t>=20 else []
        vr=v/(sum(x[4] for x in previous)/20) if len(previous)==20 and all(x is not None and x[4] is not None for x in previous) and v is not None and sum(x[4] for x in previous)>0 else None
        for e in events:
            if e['stage']=='invalidated' or t-e['detected']>RULES['activeSessions']:continue
            # A gap after detection makes subsequent lifecycle unavailable, not confirmed by inference.
            if any(x is None for x in bars[e['detected']:t+1]):e['lifecycleUnknown']=True;continue
            sign=e['direction'];failed=sign and (c<e['stop'] if sign>0 else c>e['stop'])
            if failed:e['stage']='invalidated';e['invalidated']=t;e['transitions'].append({'index':t,'stage':'invalidated'})
            elif e['stage']=='forming' and sign and (c>e['key']*1.005 if sign>0 else c<e['key']*.995) and vr is not None and vr>=1.2:
                e['stage']='confirmed';e['confirmed']=t;e['transitions'].append({'index':t,'stage':'confirmed'})
        # Evaluate causally from the available history start; never slide detection
        # start with the report date and then backdate events.
        if run>=8:
            a,z=bars[t-2],bars[t-1];body=abs(c-o);rng=h-l
            prior_down=bars[t-3][3]<bars[t-7][3];prior_up=bars[t-3][3]>bars[t-7][3]
            trio=[a,z,b];bull=all(x[3]>x[0] and x[1]>x[2] and (x[3]-x[0])/(x[1]-x[2])>=.5 for x in trio)
            bear=all(x[3]<x[0] and x[1]>x[2] and (x[0]-x[3])/(x[1]-x[2])>=.5 for x in trio)
            if bull and prior_down and a[3]<z[3]<c and a[0]<=z[0]<=a[3] and z[0]<=o<=z[3]:emit('soldiers',t-2,t,None,min(x[2] for x in trio),'三阳实体≥振幅50%；收盘递升、开盘在前实体内；前置4日下行')
            if bear and prior_up and a[3]>z[3]>c and a[3]<=z[0]<=a[0] and z[3]<=o<=z[0]:emit('crows',t-2,t,None,max(x[1] for x in trio),'三阴实体≥振幅50%；收盘递降、开盘在前实体内；前置4日上行')
            if prior_down and a[3]<a[0] and abs(z[3]-z[0])<=abs(a[3]-a[0])*.35 and c>o and c>(a[0]+a[3])/2 and max(z[0],z[3])<=a[3]:emit('morning',t-2,t,None,min(x[2] for x in trio),'首阴、中间小实体且在首根收盘下方、末阳收回首实体一半')
            if prior_up and a[3]>a[0] and abs(z[3]-z[0])<=abs(a[3]-a[0])*.35 and c<o and c<(a[0]+a[3])/2 and min(z[0],z[3])>=a[3]:emit('evening',t-2,t,None,max(x[1] for x in trio),'首阳、中间小实体且在首根收盘上方、末阴回落首实体一半')
            if z[3]<z[0] and c>o and o<=z[3] and c>=z[0] and body>abs(z[3]-z[0]) and prior_down:emit('bull_engulf',t-1,t,None,min(l,z[2]),'阳实体严格更大且包覆前阴实体，前置下行')
            if z[3]>z[0] and c<o and o>=z[3] and c<=z[0] and body>abs(z[3]-z[0]) and prior_up:emit('bear_engulf',t-1,t,None,max(h,z[1]),'阴实体严格更大且包覆前阳实体，前置上行')
            if body>0 and rng>0 and body/rng<=.35:
                if min(o,c)-l>=2*body and h-max(o,c)<=.5*body and prior_down:emit('hammer',t,t,None,l,'下影≥2倍实体，上影≤0.5倍实体，前置下行')
                if h-max(o,c)>=2*body and min(o,c)-l<=.5*body and prior_up:emit('shooting',t,t,None,h,'上影≥2倍实体，下影≤0.5倍实体，前置上行')
        if run>=21:
            segment=bars[t-20:t];hi=max(x[1] for x in segment);lo=min(x[2] for x in segment)
            if hi/lo-1<=.15:
                if c>hi*1.005 and vr is not None and vr>=1.2:emit('breakout',t-20,t,hi,lo,'此前20日区间≤15%；收盘突破上沿0.5%；量/事前20日均量≥1.2',[(t-20,hi),(t-1,hi)])
                if c<lo*.995:emit('breakdown',t-20,t,lo,hi,'此前20日区间≤15%；收盘跌破下沿0.5%',[(t-20,lo),(t-1,lo)])
                touches=sum(x[2]<=lo*1.03 for x in segment)
                if touches>=2 and l<=lo*1.03 and c>=lo and c>o:emit('box_support',t-20,t,hi,lo*.995,'20日箱体≤15%；至少2日接近下沿3%；当日阳线守下沿',[(t-20,lo),(t,lo)],True)
            for e in list(events):
                if e['pattern']=='breakout' and 1<=t-e['detected']<=10 and not any(x is None for x in bars[e['detected']:t+1]):
                    if e['stage']=='confirmed' and abs(l/e['key']-1)<=.03 and c>=e['key'] and vr is not None and vr<1:emit('retest',e['start'],t,e['key'],e['stop'],'突破后10日内回踩上沿±3%，收盘守住，量低于事前20日均量',e['anchors'])
                    if c<e['key']*.995:emit('failed',e['start'],t,e['key'],max(x[1] for x in bars[e['detected']:t+1]),'此前量价突破，10日内收回原平台上沿下0.5%',e['anchors'])
        if run>=40:
            a=bars[t-39:t+1];cl=np.array([x[3] for x in a]);ma20=float(cl[-20:].mean());old20=float(cl[-40:-20].mean())
            if ma20>old20*1.02 and c>ma20 and c<max(cl[-10:])*.97 and vr is not None and vr<1:emit('pullback',t-39,t,max(cl[-10:]),min(x[2] for x in a[-20:]),'MA20较前20日均价抬升>2%；距10日高点回落>3%；仍在MA20上且缩量',forming=True)
            hi1=max(x[1] for x in a[-20:-10]);hi2=max(x[1] for x in a[-10:]);lo1=min(x[2] for x in a[-20:-10]);lo2=min(x[2] for x in a[-10:])
            if hi2<hi1*.99 and lo2>lo1*1.01 and (hi2-lo2)<(hi1-lo1)*.8:emit('triangle',t-19,t,hi2,lo2,'两个10日区间：上沿下降≥1%，下沿抬升≥1%，宽度收敛≥20%；仅区间收敛候选',[(t-19,hi1),(t,hi2),(t-19,lo1),(t,lo2)],True)
            if cl[29]/cl[19]-1>=.15 and -.1<=cl[-1]/cl[29]-1<=0 and vr is not None and vr<1:emit('flag',t-20,t,max(x[1] for x in a[-10:]),min(x[2] for x in a[-10:]),'前10日上涨≥15%，后10日回落0–10%且缩量；旗形规则候选',forming=True)
        if run<60:continue
        start=t-min(run,90)+1;a=bars[start:t+1];low=np.array([x[2] for x in a]);high=np.array([x[1] for x in a]);m=len(a)
        # Pivots require two right-hand bars already observed by t.
        lows=[i for i in range(2,m-2) if low[i]<min(low[i-2:i]) and low[i]<=min(low[i+1:i+3])]
        highs=[i for i in range(2,m-2) if high[i]>max(high[i-2:i]) and high[i]>=max(high[i+1:i+3])]
        for kind,points,values,other,sign in [('double_bottom',lows,low,high,1),('double_top',highs,high,low,-1)]:
            if len(points)<2:continue
            p,q=points[-2:]
            if 5<=q-p<=40 and m-1-q<=15 and abs(values[p]/values[q]-1)<=.04:
                key=float(max(other[p:q+1]) if sign>0 else min(other[p:q+1]));stop=float(min(values[p],values[q])*.995 if sign>0 else max(values[p],values[q])*1.005)
                swing=key/min(values[p],values[q])-1 if sign>0 else max(values[p],values[q])/key-1
                if swing>=.05:emit(kind,start+p,t,key,stop,'两侧已确认拐点相隔5–40日、价差≤4%、颈线幅度≥5%；右拐点最近15日',[(start+p,float(values[p])),(start+q,float(values[q]))],True)
        if run>=90:
            for kind,points,values,other,sign in [('head_bottom',lows,low,high,1),('head_top',highs,high,low,-1)]:
                if len(points)<3:continue
                p,q,r=points[-3:]
                deep=values[q]<min(values[p],values[r])*.97 if sign>0 else values[q]>max(values[p],values[r])*1.03
                if 5<=q-p<=30 and 5<=r-q<=30 and abs(values[p]/values[r]-1)<=.04 and deep and m-1-r<=15:
                    key=float(max(other[p:r+1]) if sign>0 else min(other[p:r+1]));stop=float(values[q]* (.995 if sign>0 else 1.005))
                    emit(kind,start+p,t,key,stop,'三确认拐点；肩差≤4%，头部深≥3%，相邻5–30日；水平颈线取两肩间极值',[(start+i,float(values[i])) for i in [p,q,r]],True)
        close=np.array([x[3] for x in a[-60:]]);bottom=int(close.argmin());left=float(close[:10].mean());right=float(close[-10:].mean());depth=1-float(close.min())/max(left,right)
        means=[float(x.mean()) for x in np.array_split(close,6)]
        if 18<=bottom<=42 and .08<=depth<=.35 and abs(left/right-1)<=.05 and means[0]>means[1]>means[2] and means[3]<means[4]<means[5]:emit('round',t-59,t,max(left,right),float(close.min())*.995,'60日六段均价先降后升；谷在中间40%；深8–35%；两端均价差≤5%',[(t-59,left),(t-59+bottom,float(close.min())),(t,right)],True)
        if run>=90:
            cup=np.array([x[3] for x in a[-70:-10]]);handle=np.array([x[3] for x in a[-10:]]);p=int(cup.argmin());rim=float(max(cup[:10].mean(),cup[-10:].mean()));dep=1-float(cup.min())/rim;parts=[float(x.mean()) for x in np.array_split(cup,6)]
            if 18<=p<=42 and .12<=dep<=.35 and abs(cup[:10].mean()/cup[-10:].mean()-1)<=.05 and parts[0]>parts[1]>parts[2] and parts[3]<parts[4]<parts[5] and handle.min()>=rim*.9 and handle.min()>rim*(1-dep/2) and handle[-1]<rim and vr is not None and vr<1:
                emit('cup',t-69,t,rim,float(handle.min())*.995,'60日杯＋10日柄；杯深12–35%、杯沿差≤5%；柄深≤10%且高于杯半深；缩量',[(t-69,float(cup[0])),(t-69+p,float(cup.min())),(t-10,float(cup[-1])),(t,float(handle[-1]))],True)
    for e in events:
        e['active']=n-1-e['detected']<=20 and not e.get('lifecycleUnknown',False)
        e['distance']=100*(bars[-1][3]/e['key']-1) if bars[-1] and e['key'] else None
        for field in ['start','detected','confirmed','invalidated']:e[field+'Date']=dates[e[field]] if e[field] is not None else None
    # Keep the full history for causal detection, return only a bounded event
    # ledger. This is explicitly a recent-events screen, not all-history search.
    return [e for e in events if max(e['detected'],e['confirmed'] or -1,e['invalidated'] or -1)>=n-RULES['eventScan']]

class PatternService:
    def __init__(self,workspace):
        self.w=workspace;self.pool=ThreadPoolExecutor(max_workers=1);self.lock=Lock();self.jobs={};self.results={}
        self.cache=workspace.base/'.level2_patterns';self.cache.mkdir(exist_ok=True)
    def dates(self,day):return window(day,RULES['history'],self.w.calendar)
    def identity(self,day):
        return digest([RULES,stamp(__file__),stamp(self.w.calendar),stamp(self.w.report_path(day)),*[stamp(PATHS['stk_factor_pro_by_code']/(c.replace('.','_')+'_stk_factor_pro.csv')) for c in sorted(self.w.get_service(day).cards)]])
    def metadata(self):return {'catalog':[{'id':k,'name':v[0],'family':v[1],'direction':v[2],'required':v[3],'implemented':True} for k,v in CATALOG.items()],'rules':RULES}
    def start(self,day):
        self.w.get_service(day);identity=self.identity(day)
        with self.lock:
            old=self.jobs.get(day)
            if old and old.get('identity')==identity and old['status'] in ['queued','running','done']:return {k:v for k,v in old.items() if k!='result'}
            if any(v['status'] in ['queued','running'] for v in self.jobs.values()):raise ValueError('已有形态任务运行中')
            self.jobs[day]={'status':'queued','identity':identity,'message':'准备读取本地日K与指标'}
        self.pool.submit(self.run,day,identity);return self.jobs[day]
    def status(self,day):
        self.dates(day);r=self.jobs.get(day,{'status':'missing','message':'尚未计算形态'})
        if r['status']=='done' and r['identity']!=self.identity(day):return {'status':'stale','message':'行情已更新，形态待重算'}
        return r
    def run(self,day,identity):
        try:
            dates=self.dates(day);service=self.w.get_service(day);codes=set(service.cards)
            def progress(done,total,workers):
                self.jobs[day]={'status':'running','identity':identity,'message':f'多线程读取by_code指标 {done}/{total}（{workers}线程）'}
            progress(0,len(codes),8)
            frames,missing=read_factor_files(codes,dates,PATHS['stk_factor_pro_by_code'],progress)
            if not frames:raise ValueError('没有可用因子文件')
            frame=pd.concat(frames,ignore_index=True).drop_duplicates()
            if frame.duplicated(['ts_code','trade_date']).any():raise ValueError('因子同股同日存在冲突行')
            groups={c:g.set_index('trade_date') for c,g in frame.groupby('ts_code')};stocks=[];details={}
            for num,code in enumerate(sorted(codes)):
                if num%100==0:self.jobs[day]={'status':'running','identity':identity,'message':f'识别形态 {num}/{len(codes)}'}
                group=groups.get(code);rows={} if group is None else group.to_dict('index');anchor=clean(rows.get(day,{}).get('adj_factor'));bars=[];indicators=[];invalid=[]
                for d in dates:
                    r=rows.get(d,{});bar,ind=normalize_qfq(r,anchor)
                    if bar is None:
                        bars.append(None);indicators.append({});
                        if r:invalid.append(d)
                        continue
                    bars.append(bar)
                    indicators.append(ind)
                events=recognize(bars,dates);run=0
                for b in reversed(bars):
                    if b is None:break
                    run+=1
                for e in events:e['eventId']=digest([code,e['pattern'],e['startDate']])[:20]
                latest=bars[-1];vols=[x[4] for x in bars[-21:-1] if x and x[4] is not None];vr=latest[4]/(sum(vols)/20) if latest and latest[4] is not None and len(vols)==20 and sum(vols)>0 else None
                stock={'code':code,'name':service.cards[code]['name'],'events':events,'close':latest[3] if latest else None,'valid':sum(x is not None for x in bars),'expected':len(dates),'consecutive':run,'amount':latest[5]*1000 if latest and latest[5] is not None else None,'volumeRatio':vr,'indicators':indicators[-1],
                       'quality':'anomaly' if invalid else 'insufficient' if run<8 else 'available','coverage':{k:run>=v[3] for k,v in CATALOG.items()}}
                stocks.append(stock);details[code]={'code':code,'name':stock['name'],'dates':dates,'bars':bars,'indicators':indicators,'events':events,'invalidDates':invalid,'anchor':anchor,'identity':identity,'day':day}
            if self.identity(day)!=identity:raise ValueError('计算期间来源变化，未发布')
            token=uuid.uuid4().hex;result={'day':day,'identity':identity,'dates':dates,'stocks':stocks,'missingFiles':missing,**self.metadata(),'indicatorMethod':'直接读取本地qfq OHLC/MA/MACD/RSI/KDJ字段，不依赖adj_factor；沿用来源复权基准，不额外缩放或宣称报告日基准，跨分区复权基准一致性未独立核验。供应商指标平滑参数未独立复算，不参与形态确认。','scope':'当前报告股票集合、最近180交易日的回溯研究；历史左边界截断，不是全历史或无偏回测。无胜率/交易确认。'}
            (self.cache/f'{token}.json').write_text(json.dumps({'result':result,'details':details},ensure_ascii=False,allow_nan=False))
            self.results[token]={'result':result,'details':details};self.jobs[day]={'status':'done','message':'形态计算完成','identity':identity,'receipt':token,'result':result}
        except Exception as e:self.jobs[day]={'status':'error','identity':identity,'message':str(e)}
    def receipt(self,token,day):
        import re
        if not isinstance(token,str) or not re.fullmatch('[0-9a-f]{32}',token):raise ValueError('形态凭据无效')
        r=self.results.get(token)
        if r is None:r=json.loads((self.cache/f'{token}.json').read_text())
        if r['result']['day']!=day or r['result']['identity']!=self.identity(day):raise ValueError('行情或规则已更新，形态待重算')
        return r
    def detail(self,day,code,token):
        r=self.receipt(token,day)
        if code not in r['details']:raise ValueError('代码不在当前形态结果内')
        return r['details'][code]
