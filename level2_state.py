"""Daily continuous observations. Unknown legacy direction never becomes zero flow."""
import csv
import hashlib
import json
import math
import re
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import duckdb
from level2_contract import calendar
from level2_events import observe

BASE=Path(__file__).resolve().parent
CONFIG=BASE/'level2_research.json'
# Validated only for this supplier/root; never infer all numeric Side schemas agree.
CALIBRATED_LEGACY_ROOT=Path('/Volumes/990pro/data/level2')
PAT=r'^(000|001|002|003|300|301|302|600|601|603|605|688|689)[0-9]{3}\.(SZ|SH)$'

def dump(x):return json.dumps(x,ensure_ascii=False,allow_nan=False,separators=(',',':'))
def sha(x):return hashlib.sha256(dump(x).encode()).hexdigest()
def stamp(p):
    p=Path(p)
    return [str(p.resolve()),p.stat().st_size,p.stat().st_mtime_ns] if p.is_file() else [str(p),'missing']

def settings():
    from level2_paths import PATHS
    defaults={'history_roots':[], 'trade_calendar':str(PATHS['stock_basic'].parent.parent/'trade_cal'/'trade_cal.csv'),'default_window':5,'max_window':60,'benchmark':None}
    if CONFIG.exists():defaults.update(json.loads(CONFIG.read_text()))
    for p in [defaults['trade_calendar'],*defaults['history_roots']]:
        if not isinstance(p,str) or not Path(p).is_absolute():raise ValueError('研究数据路径必须为绝对路径')
    if type(defaults['max_window']) is not int or not 1<=defaults['max_window']<=250:raise ValueError('max_window 必须为1至250的整数')
    if type(defaults['default_window']) is not int or not 1<=defaults['default_window']<=defaults['max_window']:raise ValueError('default_window 必须在最大窗口范围内')
    benchmark=defaults['benchmark']
    if benchmark is not None:
        if not isinstance(benchmark,dict) or set(benchmark)!={'code','name','path'}:
            raise ValueError('benchmark 需要 code、name、path 三个字段')
        if not isinstance(benchmark['code'],str) or not re.fullmatch(r'\d{6}\.(SH|SZ)',benchmark['code']):
            raise ValueError('benchmark.code 必须为交易所指数代码')
        if not isinstance(benchmark['name'],str) or not benchmark['name'].strip() or len(benchmark['name'])>80:
            raise ValueError('benchmark.name 无效')
        if not isinstance(benchmark['path'],str) or not Path(benchmark['path']).is_absolute() or Path(benchmark['path']).suffix.lower()!='.csv':
            raise ValueError('benchmark.path 必须是绝对 CSV 路径')
    return defaults

def benchmark_evidence(config,dates,window):
    """Price-index close comparison, never filled from a neighboring session."""
    method='价格指数收盘点位比值；不含分红再投资；不同规模股票仅作描述性比较'
    if config is None:
        return {'status':'NOT_CONFIGURED','code':None,'name':None,'source':None,'method':method,
                'baselineDay':None,'endDay':dates[-1] if dates else None,'missing':list(dates),'returnPct':None}
    source=Path(config['path'])
    result={'status':'MISSING_FILE' if not source.is_file() else 'INCOMPLETE_WINDOW' if len(dates)!=window+1 else 'INCOMPLETE_PRICES',
            'code':config['code'],'name':config['name'],'source':str(source),'method':method,
            'baselineDay':dates[0] if len(dates)==window+1 else None,
            'endDay':dates[-1] if dates else None,'missing':list(dates),'returnPct':None}
    if result['status']!='INCOMPLETE_PRICES':return result
    required=set(dates);prices={}
    try:
        with source.open(newline='') as f:
            reader=csv.DictReader(f)
            if not {'ts_code','trade_date','close'}.issubset(reader.fieldnames or []):
                result['status']='INVALID_SCHEMA';return result
            for row in reader:
                d=row['trade_date']
                if row['ts_code']!=config['code'] or d not in required:continue
                if d in prices:
                    result.update(status='DUPLICATE_DATE',missing=[d]);return result
                try:value=float(row['close'])
                except (TypeError,ValueError):value=None
                prices[d]=value if value is not None and math.isfinite(value) and value>0 else None
    except (OSError,UnicodeError):
        result['status']='READ_ERROR';return result
    result['missing']=[d for d in dates if prices.get(d) is None]
    if not result['missing']:
        result['status']='AVAILABLE'
        result['returnPct']=100*(prices[dates[-1]]/prices[dates[0]]-1)
    return result

def compute(rows, days, day, window, benchmark_return=None):
    """rows keyed by day; extra preceding observation is allowed for delta only."""
    dates=[d for d in days if d<=day][-window:]
    series=[rows.get(d) for d in dates]
    usable=lambda r:r is not None and r.get('ratio') is not None and r.get('unknown',0)==0
    flows=[r for r in series if usable(r)]
    amounts=[r for r in series if r and r.get('amount',0)>0]
    latest=rows.get(day);previous=rows.get(days[days.index(day)-1]) if day in days and days.index(day)>0 else None
    level=latest.get('ratio') if usable(latest) else None
    delta=level-previous['ratio'] if level is not None and usable(previous) else None
    full=len(dates)==window and len(flows)==window
    complete_amount=len(dates)==window and len(amounts)==window
    values=[r['ratio'] for r in flows]
    slope=None
    if full and window>1:
        mid=(window-1)/2
        slope=sum((i-mid)*v for i,v in enumerate(values))/sum((i-mid)**2 for i in range(window))
    sign=lambda v:1 if v>0 else -1 if v<0 else 0
    streak=None;improve=None;worsen=None;left=False
    if level is not None:
        streak=0;improve=0;worsen=0
        for r in reversed(series):
            if not usable(r) or sign(r['ratio'])!=sign(level):break
            streak+=1
        left=streak==len(series)
        for a,b in zip(reversed(series[:-1]),reversed(series[1:])):
            if not usable(a) or not usable(b) or b['ratio']<=a['ratio']:break
            improve+=1
        for a,b in zip(reversed(series[:-1]),reversed(series[1:])):
            if not usable(a) or not usable(b) or b['ratio']>=a['ratio']:break
            worsen+=1
    change_amount=(latest['amount']/previous['amount']-1)*100 if latest and latest.get('amount',0)>0 and previous and previous.get('amount',0)>0 else None
    # Compare the latest session only with earlier sessions inside the applied window.
    # A one-day or incomplete window cannot supply a valid historical denominator.
    prior_amounts=[r['amount'] for r in series[:-1] if r and r.get('amount',0)>0]
    prior_amount_mean=(sum(prior_amounts)/(window-1)
                       if window>1 and len(dates)==window and len(prior_amounts)==window-1 else None)
    amount_relative=(100*(latest['amount']/prior_amount_mean-1)
                     if prior_amount_mean is not None and latest and latest.get('amount',0)>0 else None)
    baseidx=days.index(dates[0])-1 if dates else -1
    baseline=rows.get(days[baseidx]) if baseidx>=0 else None
    prices=[baseline,*series]
    price_ok=len(dates)==window and all(r and r.get('adjusted',0)>0 for r in prices)
    price_return=100*(prices[-1]['adjusted']/prices[0]['adjusted']-1) if price_ok else None
    drawdown=None;drawdown_peak=None;drawdown_trough=None
    if price_ok:
        peak=prices[0]['adjusted'];peak_day=days[baseidx]
        drawdown=0.0
        for d,r in zip(dates,series):
            value=r['adjusted']
            if value>peak:
                peak=value;peak_day=d
            current=100*(value/peak-1)
            if current<drawdown:
                drawdown=current;drawdown_peak=peak_day;drawdown_trough=d
    history=[]
    for index,(d,r) in enumerate(zip(dates,series)):
        earlier,now=prices[index:index+2]
        price_daily=(100*(now['adjusted']/earlier['adjusted']-1)
                     if earlier and now and earlier.get('adjusted',0)>0 and now.get('adjusted',0)>0 else None)
        history.append({'day':d,**(r or {}),'priceDailyReturn':price_daily,
                        'reason':(r or {}).get('reason') or ('方向记录可用' if usable(r) else '缺成交记录或方向未知／停牌未核实')})
    return {'level':level,'delta':delta,'weighted':100*sum(r['net'] for r in flows)/sum(r['amount'] for r in flows) if full else None,
            'slope':slope,'sign':sign(level) if level is not None else None,'streak':streak,'leftCensored':left,
            'improve':improve,'worsen':worsen,'improveCensored':improve is not None and len(series)>1 and improve==len(series)-1,
            'worsenCensored':worsen is not None and len(series)>1 and worsen==len(series)-1,
            'positiveDays':sum(r['ratio']>0 for r in flows),'expected':window,'valid':len(flows),
            'amountValid':len(amounts),'missing':[d for d,r in zip(dates,series) if not usable(r)],
            'status':'AVAILABLE' if full else 'INCOMPLETE','amount':latest.get('amount') if latest else None,
            'amountChange':change_amount,'meanAmount':sum(r['amount'] for r in amounts)/window if complete_amount else None,
            'amountPriorMean':prior_amount_mean,'amountRelativePct':amount_relative,
            'priceReturn':price_return,
            'relativeReturn':price_return-benchmark_return if price_return is not None and benchmark_return is not None else None,
            'maxCloseDrawdown':drawdown,'drawdownPeakDay':drawdown_peak,'drawdownTroughDay':drawdown_trough,
            'start':dates[0] if dates else None,'end':day,
            'history':history,'events':observe(history)}

class StateService:
    def __init__(self,workspace):
        self.workspace=workspace;self.base=workspace.base;self.jobs={};self.lock=Lock()
        self.pool=ThreadPoolExecutor(max_workers=1);self.cache=self.base/'.level2_state_cache'
        self.receipts=self.base/'.level2_state_receipts'

    def metadata(self):
        cfg=settings();days,last=calendar(cfg['trade_calendar'])
        return {'days':days,'calendarThrough':last,'defaultWindow':cfg['default_window'],'maxWindow':cfg['max_window'],
                'historyRoots':cfg['history_roots'],'benchmark':cfg['benchmark'],
                'legacyDirection':'SOURCE_SCOPED_0_BUY_1_SELL_WITH_ID_GUARD'}

    def validate(self,day,window):
        if type(window) is not int or not 1<=window<=settings()['max_window']:raise ValueError('回看天数须为范围内的正整数')
        days,_=calendar(settings()['trade_calendar'])
        if day not in days:raise ValueError('截止日不在已核验交易日历内')
        return days

    def source(self,day):
        roots=[self.workspace.root,*map(Path,settings()['history_roots'])]
        for root in roots:
            p=root/f'deal_{day}.parquet'
            if p.exists():return p
        return None

    def identity(self,day,window):
        from level2_paths import PATHS
        days=self.validate(day,window);dates=[d for d in days if d<=day][-window-1:]
        cfg=settings()
        items=[stamp(cfg['trade_calendar']),stamp(CONFIG),stamp(Path(__file__)),stamp(BASE/'level2_contract.py'),stamp(BASE/'level2_events.py'),cfg]
        if cfg['benchmark']:items.append(stamp(cfg['benchmark']['path']))
        for d in dates:
            p=self.source(d)
            items.extend([stamp(p) if p else [d,'missing'],stamp(PATHS['stk_factor_pro']/f'{d}_stk_factor_pro.csv')])
            if p:items.extend([stamp(p.parent/'_conversion_audit'/d/'manifest.json'),stamp(p.parent/'_conversion_audit'/d/'COMMITTED')])
        return sha(items)

    def facts(self,day):
        p=self.source(day)
        if p is None:return {},{'day':day,'status':'MISSING','source':None}
        import pyarrow.parquet as pq
        names=pq.ParquetFile(p).schema_arrow.names
        native='万得代码' in names
        calibrated=(not native and p.parent.resolve()==CALIBRATED_LEGACY_ROOT.resolve()
                    and {'BuyID','SellID'}.issubset(names))
        if not native and not {'SecuCode','Price','Volume','Side','TradingDay'}.issubset(names):
            return {},{'day':day,'status':'UNKNOWN_SCHEMA','source':str(p)}
        audit=p.parent/'_conversion_audit'/day
        if native:
            try:committed=(audit/'COMMITTED').is_file() and json.loads((audit/'manifest.json').read_text()).get('commit_state')=='COMMITTED'
            except (OSError,ValueError):committed=False
            if not committed:return {},{'day':day,'status':'UNCOMMITTED','source':str(p)}
        source_status='NATIVE' if native else 'LEGACY_CALIBRATED_ROW_GUARD' if calibrated else 'LEGACY_DIRECTION_UNKNOWN'
        key=sha([stamp(p),stamp(Path(__file__)),stamp(audit/'manifest.json'),stamp(audit/'COMMITTED')])
        self.cache.mkdir(exist_ok=True);dest=self.cache/f'{day}-{key}.json'
        if dest.exists():return json.loads(dest.read_text()),{'day':day,'status':source_status,'source':str(p)}
        if native:
            projection='''"万得代码" AS code,TRY_CAST("自然日" AS BIGINT) AS trade_day,TRY_CAST("成交价格" AS DOUBLE)/10000 AS price,TRY_CAST("成交数量" AS DOUBLE) AS volume,CAST("BS标志" AS VARCHAR) AS side'''
            excluded="side='C'"
        else:
            direction="""CASE WHEN Side=0 AND BuyID>SellID AND SellID>0 THEN 'B'
                WHEN Side=1 AND SellID>BuyID AND BuyID>0 THEN 'S' ELSE 'UNKNOWN' END""" if calibrated else "'UNKNOWN'"
            projection=f'''LPAD(CAST(TRY_CAST(SecuCode AS BIGINT) AS VARCHAR),6,'0') || CASE WHEN TRY_CAST(SecuCode AS BIGINT)>=600000 THEN '.SH' ELSE '.SZ' END AS code,TRY_CAST(TradingDay AS BIGINT) AS trade_day,TRY_CAST(Price AS DOUBLE)/100 AS price,TRY_CAST(Volume AS DOUBLE) AS volume,{direction} AS side,CAST(Side AS VARCHAR) AS raw_side'''
            excluded="raw_side IN ('-1','-11')"
        net="CASE WHEN side='B' THEN price*volume WHEN side='S' THEN -price*volume ELSE 0 END"
        unknown="CASE WHEN side IN ('B','S') THEN 0 ELSE price*volume END"
        con=duckdb.connect();con.execute("SET memory_limit='2GB'");con.execute('SET threads=4')
        try:
            result=con.execute(f'''WITH x AS (SELECT {projection} FROM read_parquet(?))
                SELECT code,SUM(price*volume),SUM({net}),SUM({unknown}),COUNT(*) FROM x
                WHERE trade_day=? AND price>0 AND volume>0 AND isfinite(price) AND isfinite(volume)
                AND NOT COALESCE({excluded},false) AND regexp_matches(code,?) GROUP BY code''',[str(p),int(day),PAT]).fetchall()
        finally:con.close()
        recognized=native or calibrated
        rows={c:{'amount':a,'net':n if recognized else None,'unknown':u,'ratio':100*n/a if recognized and a else None,
                 'reason':('方向或买卖编号冲突／未知成交存在' if u else '旧格式已校准：0买1卖，逐条编号一致') if calibrated
                          else ('方向未知成交存在' if u else None) if native else '旧格式来源未校准',
                 'trades':count,'directionMethod':source_status} for c,a,n,u,count in result}
        tmp=dest.with_suffix('.tmp');tmp.write_text(dump(rows));tmp.replace(dest)
        return rows,{'day':day,'status':source_status,'source':str(p)}

    def prices(self,day):
        from level2_paths import PATHS
        p=PATHS['stk_factor_pro']/f'{day}_stk_factor_pro.csv'
        if not p.exists():return {}
        result={}
        with p.open(newline='') as f:
            for row in csv.DictReader(f):
                if row.get('trade_date')!=day:continue
                try:v=float(row['close'])*float(row['adj_factor'])
                except (ValueError,KeyError):continue
                if math.isfinite(v) and v>0:
                    code=row['ts_code']
                    if code in result:raise ValueError('价格表股票日期重复：'+code)
                    result[code]=v
        return result

    def price_source(self,day):
        from level2_paths import PATHS
        return PATHS['stk_factor_pro']/f'{day}_stk_factor_pro.csv'

    def start(self,day,window):
        self.validate(day,window);self.workspace.get_service(day)
        key=(day,window);identity=self.identity(day,window)
        with self.lock:
            old=self.jobs.get(key)
            if old and old.get('identity')==identity and old['status'] in ('queued','running','done'):return dict(old)
            if any(j['status'] in ('queued','running') for j in self.jobs.values()):raise ValueError('连续状态已有计算任务，请稍后再试')
            self.jobs[key]={'status':'queued','message':'等待逐日聚合','identity':identity}
            self.pool.submit(self.run,day,window,identity)
        return {'status':'queued','message':'已提交连续状态计算'}

    def status(self,day,window):
        self.validate(day,window)
        with self.lock:r=dict(self.jobs.get((day,window),{'status':'missing','message':'尚未计算'}))
        if r['status']=='done' and r['identity']!=self.identity(day,window):return {'status':'stale','message':'来源已变化，请重新计算'}
        return r

    def run(self,day,window,identity):
        key=(day,window)
        try:
            service=self.workspace.get_service(day);days=self.validate(day,window)
            dates=[d for d in days if d<=day][-window-1:];allrows={};sources=[]
            for d in dates:
                with self.lock:self.jobs[key]={'status':'running','message':'连续状态：正在聚合 '+d,'identity':identity}
                rows,source=self.facts(d);prices=self.prices(d)
                price_file=self.price_source(d)
                source['priceStatus']='FILE_PRESENT' if price_file.is_file() else 'MISSING'
                source['priceSource']=str(price_file) if price_file.is_file() else None
                # Price evidence is independent of missing Level-2 flow evidence.
                for code,value in prices.items():rows.setdefault(code,{})['adjusted']=value
                allrows[d]=rows;sources.append(source)
            benchmark=benchmark_evidence(settings()['benchmark'],dates,window)
            states={code:compute({d:rows[code] for d,rows in allrows.items() if code in rows},days,day,window,
                                 benchmark['returnPct']) for code in service.cards}
            if identity!=self.identity(day,window):raise ValueError('计算期间来源变化，结果未发布')
            result={'day':day,'window':window,'states':states,'sources':sources,'benchmark':benchmark,'identity':identity,
                    'eventMethod':'相邻交易日日级主动净额比严格变号或负值变化；状态仅随窗口内后续有效观测更新；未知不跨越',
                    'priceMethod':'本地 close×adj_factor 比值；N日收益使用窗口前一交易日为基点；历史当时可得性未验证',
                    'scope':'日级价格／成交额／已识别主动方向。已校准旧来源0买1卖，逐条买卖编号复核；未校准来源及冲突记录未知。无自动吸筹、支撑或买卖触发。'}
            token=uuid.uuid4().hex;self.receipts.mkdir(exist_ok=True)
            (self.receipts/f'{token}.json').write_text(dump(result))
            with self.lock:self.jobs[key]={'status':'done','message':'连续状态计算完成','identity':identity,'receipt':token,'result':result}
        except Exception as e:
            with self.lock:self.jobs[key]={'status':'error','message':str(e),'identity':identity}

    def frozen(self,tokens,day):
        if not isinstance(tokens,dict) or len(tokens)>60:raise ValueError('连续状态凭据范围无效')
        result={}
        for window,token in tokens.items():
            if not isinstance(token,str) or not re.fullmatch('[0-9a-f]{32}',token):raise ValueError('连续状态凭据无效')
            r=json.loads((self.receipts/f'{token}.json').read_text())
            if r['day']!=day or str(r['window'])!=window or r['identity']!=self.identity(day,r['window']):raise ValueError('连续状态日期、参数或来源不匹配')
            result[window]=r
        return result
