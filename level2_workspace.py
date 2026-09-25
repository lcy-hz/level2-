"""Date-partitioned report generation and immutable, explicitly bounded snapshots."""
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import hashlib
import json
import math
import re
import subprocess
import sys
import uuid

BASE=Path(__file__).resolve().parent
DATE=re.compile(r'\d{8}')
ID=re.compile(r'[0-9a-f]{32}')


def encoded(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('<','\\u003c')


def fingerprint(path):
    path=Path(path)
    if not path.is_file(): return {'path':str(path),'missing':True}
    s=path.stat()
    return {'path':str(path.resolve()),'bytes':s.st_size,'mtimeNs':s.st_mtime_ns}


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def chart_sources(result,kind):
    if kind=='minute':
        return [fingerprint(result['source']),fingerprint(result['preCloseSource'])]
    if kind=='day':
        files=result.get('sourceFiles') or [Path(result['source'])/f'{day}_stk_factor_pro.csv' for day in result['labels']]
        return [fingerprint(path) for path in files]
    raise ValueError('图表类型无效')


def validate_continuous_ui(value):
    """Freeze presentation controls, never accept them as computed market evidence."""
    if not isinstance(value,dict) or len(encoded(value))>5000:raise ValueError('连续筛选参数无效')
    choices={
        'change':{'all','improve','worsen','flat','unknown'},
        'continuity':{'all','known','unknown'},
        'coverage':{'all','full','partial','unknown'},
        'sort':{'code','level','delta','weighted','slope','streak','improve','amount','amountRelative','sizePeer','liquidityPeer','price','drawdown','minuteDrawdown','relative'},
        'direction':{'asc','desc'},
    }
    if set(value)-{'search','change','continuity','coverage','sort','direction','advanced','page'}:
        raise ValueError('连续筛选参数无效')
    if 'search' in value and (not isinstance(value['search'],str) or len(value['search'])>200):raise ValueError('连续搜索无效')
    if any(key in value and (not isinstance(value[key],str) or value[key] not in allowed) for key,allowed in choices.items()):
        raise ValueError('连续筛选选项无效')
    if 'page' in value and (type(value['page']) is not int or not 1<=value['page']<=10000):raise ValueError('连续分页无效')
    advanced=value.get('advanced',{})
    if not isinstance(advanced,dict):raise ValueError('连续高级筛选无效')
    selects={'preset':{'all','relief','buyStrong','buyWeak','sellStrong','upSell','downBuy'},
             'price':{'all','positive','negative','zero'},
             'levelSign':{'all','positive','negative','zero'},'weightedSign':{'all','positive','negative','zero'},
             'turn':{'all','toBuy','toSell','buy','sell'},'volume':{'all','positive','negative','zero'}}
    ranges={key+edge for key in ('amount','level','delta','weighted','price') for edge in ('Min','Max')}
    durations={'buyDays','sellDays','improveTimes','worsenTimes'}
    if set(advanced)-set(selects)-ranges-durations:raise ValueError('连续高级筛选字段无效')
    parsed={}
    for key,item in advanced.items():
        if not isinstance(item,str) or len(item)>40:raise ValueError('连续高级筛选值无效')
        if key in selects:
            if item not in selects[key]:raise ValueError('连续高级筛选选项无效')
        elif item:
            try:number=float(item)
            except ValueError:raise ValueError('连续数值筛选无效') from None
            if not math.isfinite(number) or (key.startswith('amount') and number<0) or (key in durations and (not number.is_integer() or number<1)):
                raise ValueError('连续数值筛选无效')
            parsed[key]=number
    for key in ('amount','level','delta','weighted','price'):
        if key+'Min' in parsed and key+'Max' in parsed and parsed[key+'Min']>parsed[key+'Max']:
            raise ValueError('连续筛选上下限无效')
    return value


def report_sources_match(recorded, current):
    """Ignore only the state calculator's implementation; calendar path/data remain gated."""
    if (not isinstance(recorded, dict) or not isinstance(recorded.get('sources'), list)
            or not all(isinstance(item, dict) for item in recorded['sources'])
            or not all(isinstance(item, dict) for item in current)):
        return False
    if digest(recorded['sources']) != recorded.get('sourceDigest'):
        return False
    ignored = str(BASE/'level2_state.py')
    trim = lambda items: [item for item in items if item.get('path') != ignored]
    return digest(trim(recorded['sources'])) == digest(trim(current))


class Workspace:
    def __init__(self,service=None,base=BASE,calendar=None,root=None):
        from level2_state import settings
        from level2_paths import PATHS
        self.base=Path(base)
        self.root=Path(root) if root is not None else service.root if service is not None else PATHS['level2']
        self.calendar=Path(calendar) if calendar else Path(settings()['trade_calendar'])
        self.reports=self.base/'.level2_reports'
        self.snapshots=self.base/'level2_snapshots'
        self.receipts=self.base/'.level2_chart_receipts'
        self.services={service.day:service} if service is not None else {}
        self.minute_services={}
        self.jobs={};self.lock=Lock()
        self.pool=ThreadPoolExecutor(max_workers=1)
        from level2_state import StateService
        self.state=StateService(self)
        self._patterns=None
        self._validation=None

    @property
    def patterns(self):
        if self._patterns is None:
            from level2_patterns import PatternService
            self._patterns=PatternService(self)
        return self._patterns

    @property
    def validation(self):
        if self._validation is None:
            from level2_validation import ValidationService
            self._validation=ValidationService(self.base)
        return self._validation

    def window(self,day):
        from level2_contract import window
        return window(day,7,self.calendar)

    def gate(self,day):
        audit=self.root/'_conversion_audit'/day
        missing=[k for k in ['deal','snapshot','order_raw'] if not (self.root/f'{k}_{day}.parquet').is_file()]
        try:
            m=json.loads((audit/'manifest.json').read_text())
            if not (audit/'COMMITTED').is_file() or m.get('commit_state')!='COMMITTED':missing.append('COMMITTED')
        except (OSError,ValueError):missing.append('manifest')
        return missing

    def sources(self,day):
        result=[fingerprint(self.calendar)]
        for d in self.window(day):
            result.extend(fingerprint(self.root/f'{k}_{d}.parquet') for k in ['deal','snapshot','order_raw'])
            manifest=self.root/'_conversion_audit'/d/'manifest.json'
            item=fingerprint(manifest)
            if manifest.is_file():item['sha256']=hashlib.sha256(manifest.read_bytes()).hexdigest()
            result.append(item)
        from level2_paths import CONFIG,PATHS
        result.append(fingerprint(CONFIG))
        result.append(fingerprint(PATHS['stock_basic']))
        # Only report-generation inputs invalidate the generated report. UI/API
        # changes do not, while name data and imported calculators do.
        result.extend(fingerprint(self.base/p) for p in [
            'generate_level2_report.py','level2_contract.py','level2_quality.py',
            'level2_paths.py'])
        return result

    def dates(self):
        found=set()
        for p in self.root.glob('*.parquet'):
            m=re.fullmatch(r'(?:deal|snapshot|order_raw)_(\d{8})\.parquet',p.name)
            if m:found.add(m[1])
        from level2_intraday import minute_directory
        minute_root=minute_directory(self.root)
        for p in minute_root.glob('*.parquet'):
            if DATE.fullmatch(p.stem):found.add(p.stem)
        # A manifest can be large; a date may occur in several overlapping
        # windows. Share its gate result only within this request so the next
        # request still observes changed files or publication markers.
        gate_results={}
        def checked_gate(day):
            if day not in gate_results:gate_results[day]=self.gate(day)
            return gate_results[day]
        rows=[]
        for day in sorted(found,reverse=True):
            try:window=self.window(day)
            except (OSError,ValueError):window=[]
            missing=checked_gate(day)
            window_missing=[d for d in window if checked_gate(d)]
            ready=(len(window)==7 and window[-1]==day and not window_missing and not missing)
            rows.append({'day':day,'complete':not missing,'missing':missing,'window':window,
                         'windowMissing':window_missing,'canBuild':ready,
                         'minute':(minute_root/f'{day}.parquet').is_file(),
                         **self.status(day)})
        return rows

    def report_path(self,day):
        if not isinstance(day,str) or not DATE.fullmatch(day):raise ValueError('日期格式无效')
        return self.reports/day/'report.json'

    def status(self,day):
        path=self.report_path(day)
        with self.lock:
            job=self.jobs.get(day)
            if job and job['status'] in ('running','queued','error'):return dict(job)
        if path.is_file():
            meta=path.with_suffix('.provenance.json')
            if not meta.is_file():
                return {'status':'stale','message':'报告缺少来源凭据，不能作为实时报告；请重新计算'}
            try:
                from level2_detail_service import read_report
                window=self.window(day)
                if len(window)!=7 or window[-1]!=day or any(self.gate(d) for d in window):
                    return {'status':'stale','message':'最近7交易日正式来源不完整，请核对后重新计算'}
                recorded=json.loads(meta.read_text())
                if not report_sources_match(recorded,self.sources(day)):
                    return {'status':'stale','message':'源文件已变化，报告待重新计算'}
                report=read_report(path,day)
                if not report['cards']:
                    return {'status':'stale','message':'报告股票覆盖为空，请重新计算'}
                checksum=recorded.get('reportSha256')
                if checksum is not None and checksum!=hashlib.sha256(path.read_bytes()).hexdigest():
                    return {'status':'stale','message':'报告内容与发布凭据不一致，请重新计算'}
            except (OSError,ValueError,KeyError,TypeError):
                return {'status':'stale','message':'报告或来源凭据无效，请重新计算'}
            return {'status':'ready','message':'报告可查看'+('（旧报告未记录内容哈希；仅核验来源与结构）' if checksum is None else '')}
        return {'status':'missing','message':'报告待计算'}

    def get_service(self,day):
        from level2_detail_service import Service,read_report
        if self.status(day)['status']!='ready':raise ValueError('所选日期报告未就绪，请先计算')
        path=self.report_path(day)
        stamp=fingerprint(path)
        with self.lock:
            previous=self.services.get(day)
            if previous is not None and (not hasattr(previous,'_report_stamp') or previous._report_stamp==stamp):
                return previous
            report=read_report(path,day)
            if stamp!=fingerprint(path):raise ValueError('读取期间报告发生变化，请重试')
            if previous is not None:previous.pool.shutdown(wait=False,cancel_futures=True)
            old_minute=self.minute_services.pop(day,None)
            if old_minute:old_minute.pool.shutdown(wait=False,cancel_futures=True)
            current=Service(report,root=self.root)
            current._report_stamp=stamp
            self.services[day]=current
            return self.services[day]

    def get_minute_service(self,day):
        from level2_detail_service import Service
        from level2_intraday import calculate_intraday, minute_identity
        report_service=self.get_service(day)
        with self.lock:
            if day not in self.minute_services:
                self.minute_services[day]=Service(report_service.report,root=self.root,
                    cache=self.base/'.level2_minute_cache',calculator=calculate_intraday,identity=minute_identity,
                    verify_report_totals=False)
            return self.minute_services[day]

    def close(self):
        for service in [*self.services.values(),*self.minute_services.values()]:
            service.pool.shutdown(wait=False,cancel_futures=True)
        self.pool.shutdown(wait=False,cancel_futures=True)
        self.state.pool.shutdown(wait=False,cancel_futures=True)
        if self._patterns:self._patterns.pool.shutdown(wait=False,cancel_futures=True)
        if self._validation:self._validation.pool.shutdown(wait=False,cancel_futures=True)

    def report_document(self,day):
        """Read-only, source-gated payload shared by the HTML and future clients."""
        service=self.get_service(day)
        provenance=self.report_path(day).with_suffix('.provenance.json')
        lineage=json.loads(provenance.read_text()) if provenance.is_file() else {'status':'UNKNOWN_GENERATION_LINEAGE'}
        return {'mode':'live','day':day,'researchOnly':True,'provenance':lineage,'report':service.report}

    def build(self,day):
        rows={r['day']:r for r in self.dates()}
        if day not in rows or not rows[day]['canBuild']:raise ValueError('该日期或最近7交易日数据不完整，不能用其他日期替换')
        with self.lock:
            if self.jobs.get(day,{}).get('status') in ('queued','running'):return self.jobs[day]
            if any(j['status'] in ('queued','running') for j in self.jobs.values()):raise ValueError('已有报告正在计算，请等待完成')
            self.jobs[day]={'status':'queued','message':'已排队，准备全市场计算'}
            self.pool.submit(self._build,day,rows[day]['window'])
        return {'status':'queued','message':'已提交全市场报告计算'}

    def _build(self,day,window):
        target=self.reports/day/'report.json'
        target.parent.mkdir(parents=True,exist_ok=True)
        tmp=target.with_suffix('.building.json')
        initial=self.sources(day)
        try:
            with self.lock:self.jobs[day]={'status':'running','message':'正在扫描原始 Level-2 全市场数据…'}
            cmd=[sys.executable,str(self.base/'generate_level2_report.py'),'--date',day,'--dates',*window,'--output',str(tmp)]
            process=subprocess.Popen(cmd,cwd=self.base,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            tail=[]
            for line in process.stdout:
                tail.append(line.rstrip());tail=tail[-12:]
                if line.startswith('aggregate'):
                    with self.lock:self.jobs[day]={'status':'running','message':'正在汇总 '+line.strip().split()[-1]+'；随后计算候选详情'}
            if process.wait()!=0:raise ValueError('\n'.join(tail)[-1800:])
            from level2_detail_service import read_report
            data=read_report(tmp,day)
            if data['markets'][-1]['day']!=day or not data['cards']:raise ValueError('生成结果日期或覆盖无效')
            if digest(initial)!=digest(self.sources(day)):raise ValueError('计算期间源数据变化，未发布结果')
            meta=target.with_suffix('.provenance.json')
            meta_tmp=meta.with_suffix('.building.json')
            meta_tmp.write_text(encoded({'sourceDigest':digest(initial),'sources':initial,
                'reportSha256':hashlib.sha256(tmp.read_bytes()).hexdigest(),
                'generatedAt':datetime.now(timezone.utc).isoformat()}))
            # Publish the new checksum first: an interrupted swap cannot make a
            # new report look ready under an old, checksum-free provenance file.
            meta_tmp.replace(meta)
            tmp.replace(target)
            with self.lock:
                previous=self.services.pop(day,None)
                old_minute=self.minute_services.pop(day,None)
                if previous:previous.pool.shutdown(wait=False,cancel_futures=True)
                if old_minute:old_minute.pool.shutdown(wait=False,cancel_futures=True)
                self.jobs[day]={'status':'ready','message':'全市场报告计算完成'}
        except Exception as exc:
            with self.lock:self.jobs[day]={'status':'error','message':'报告计算失败：'+str(exc)}

    def record_chart(self,result,kind):
        receipt=uuid.uuid4().hex
        self.receipts.mkdir(exist_ok=True)
        sources=chart_sources(result,kind)
        value={'result':result,'kind':kind,'sources':sources,'dataSha256':digest(result)}
        (self.receipts/f'{receipt}.json').write_text(encoded(value))
        return receipt

    def snapshot_path(self,identifier):
        if not isinstance(identifier,str) or not ID.fullmatch(identifier):raise ValueError('快照编号无效')
        return self.snapshots/identifier

    def list_snapshots(self):
        result=[]
        for p in self.snapshots.glob('*/bundle.json'):
            if not (p.parent/'COMMITTED').exists():continue
            try:
                raw=p.read_bytes();b=json.loads(raw)
                if b.get('format')=='vue-json' and (p.parent/'COMMITTED').read_text()!=hashlib.sha256(raw).hexdigest():continue
                result.append({k:b[k] for k in ['id','day','savedAt','chartCount']})
            except (OSError,ValueError,KeyError):continue
        return sorted(result,key=lambda b:b['savedAt'],reverse=True)

    def save(self,request):
        day=request.get('day');service=self.get_service(day)
        data=request.get('data');filters=request.get('filters',{})
        if not isinstance(data,dict) or data.get('markets')!=service.report['markets']:raise ValueError('报告日期或统计不匹配')
        if data.get('quality')!=service.report.get('quality'):raise ValueError('数据质量证据与服务端不一致')
        cards=data.get('cards',[])
        if len(cards)!=len(service.cards) or {c.get('code') for c in cards}!=set(service.cards):raise ValueError('报告股票覆盖不一致')
        mutable={'segments','parents','orders','regularCoverage','computedDetail','detailEvidence'}
        for card in cards:
            original=service.cards[card['code']]
            if {k:v for k,v in card.items() if k not in mutable}!={k:v for k,v in original.items() if k not in mutable}:
                raise ValueError('报告基础字段与服务端不一致，请重新加载')
            if card.get('computedDetail'):
                status=service.status(card['code'])
                if status.get('status')!='done':raise ValueError('该股深查未通过当前来源身份核验')
                detail=status['result']
                if any(card.get(key)!=detail.get(key) for key in ['segments','parents','orders','regularCoverage']):
                    raise ValueError('该股深查字段与服务端不一致')
                if 'detailEvidence' in card and card['detailEvidence']!=detail:
                    raise ValueError('该股完整深查证据与服务端不一致')
            elif 'detailEvidence' in card:
                raise ValueError('未标记深查完成却附带深查证据')
        # Freeze the actual viewed report, including loaded detail tables. No background completion.
        if not isinstance(filters,dict) or any(not isinstance(v,str) or len(v)>200 for v in filters.values()):raise ValueError('筛选条件无效')
        continuous_ui=validate_continuous_ui(request.get('continuousUI',{}))
        charts={};receipts={}
        requested=request.get('charts',{})
        if not isinstance(requested,dict) or len(requested)>10418:raise ValueError('图表范围无效')
        for key,token in requested.items():
            if not isinstance(token,str) or not ID.fullmatch(token):raise ValueError('图表凭据无效')
            receipt=json.loads((self.receipts/f'{token}.json').read_text());r=receipt['result']
            if r['day']!=day or r['code'] not in service.cards or key!=receipt['kind']+'/'+r['code']:raise ValueError('快照图表日期或股票不一致')
            if receipt.get('dataSha256')!=digest(r):raise ValueError('图表凭据内容校验失败，请重新悬浮读取')
            if receipt.get('sources')!=chart_sources(r,receipt['kind']):raise ValueError('图表来源已变化，请重新悬浮读取')
            charts[key]=r;receipts[key]=receipt
        identifier=uuid.uuid4().hex;saved=datetime.now(timezone.utc).isoformat()
        states=self.state.frozen(request.get('states',{}),day)
        state_window=request.get('stateWindow')
        if state_window is not None and str(state_window) not in states:raise ValueError('选中的观察窗口未冻结')
        # API and frozen snapshots use one Python presentation calculation.
        from level2_state_view import derive
        views={key:derive(value) for key,value in states.items()}
        context={'mode':'snapshot','day':day,'id':identifier,'savedAt':saved,'charts':charts,'filters':filters,'continuousUI':continuous_ui,'states':states,'stateWindow':state_window}
        context['stateViews']=views
        pattern_result=None
        if request.get('patternReceipt'):
            verified=self.patterns.receipt(request['patternReceipt'],day)
            codes=request.get('patternCharts',[])
            if not isinstance(codes,list) or len(codes)>200 or any(not isinstance(c,str) or c not in verified['details'] for c in codes):raise ValueError('形态图范围无效，最多200只已查看图')
            pattern_result={'result':verified['result'],'details':{c:verified['details'][c] for c in codes}}
        context['patterns']=pattern_result
        validation_result=None
        validation_details={}
        if request.get('validationReceipt'):
            validation_result=self.validation.frozen(request['validationReceipt'])
            codes=request.get('validationDetails',[])
            if not isinstance(codes,list) or len(codes)>50:raise ValueError('后续研究逐股范围无效')
            if codes:
                if any(code not in service.cards for code in codes):raise ValueError('后续研究逐股代码不属于当前报告')
                validation_details=self.validation.details(request['validationReceipt'],codes)
        elif request.get('validationDetails'):
            raise ValueError('未保存后续研究却附带逐股证据')
        context['validation']=validation_result
        context['validationDetails']=validation_details
        ui=request.get('patternUI',{})
        if not isinstance(ui,dict) or len(encoded(ui))>10000:raise ValueError('形态视图参数无效')
        context['patternUI']=ui
        provenance=self.report_path(day).with_suffix('.provenance.json')
        bundle={'format':'vue-json','id':identifier,'day':day,'savedAt':saved,'chartCount':len(charts),'report':data,'filters':filters,'continuousUI':continuous_ui,
                'stateViews':views,
                'patterns':pattern_result,'patternUI':ui,'validation':validation_result,
                'validationDetails':validation_details,
                'charts':charts,'chartReceipts':receipts,'states':states,'stateWindow':state_window,'payloadSha256':digest(data),
                'reportProvenance':json.loads(provenance.read_text()) if provenance.exists() else {'status':'UNKNOWN_GENERATION_LINEAGE'},
                'sourcesObservedAtSave':self.sources(day),
                'scope':'整份当前报告与已加载详情；只冻结本次页面已成功读取的图表、观察窗口、形态、后续研究摘要及已查看逐股证据；其余明确未保存。历史日期快照不是历史当时可得性证明。'}
        directory=self.snapshot_path(identifier);directory.mkdir(parents=True,exist_ok=False)
        payload=encoded(bundle).encode('utf-8')
        (directory/'bundle.json').write_bytes(payload)
        (directory/'COMMITTED').write_text(hashlib.sha256(payload).hexdigest())
        return {'id':identifier,'day':day,'savedAt':saved,'chartCount':len(charts)}

    def frozen_page(self,identifier):
        p=self.snapshot_path(identifier)
        html=(p/'report.html').read_bytes()
        if (p/'COMMITTED').read_text()!=hashlib.sha256(html).hexdigest():raise ValueError('快照文件完整性校验失败')
        return html

    def snapshot_document(self,identifier):
        """Serve only the saved payload; never hydrate a snapshot from live data."""
        p=self.snapshot_path(identifier)
        raw=(p/'bundle.json').read_bytes();bundle=json.loads(raw)
        if bundle.get('format')=='vue-json':
            if ((p/'COMMITTED').read_text()!=hashlib.sha256(raw).hexdigest()
                    or bundle.get('id')!=identifier or digest(bundle.get('report'))!=bundle.get('payloadSha256')):
                raise ValueError('快照数据完整性校验失败')
            frozen_context=bundle
            integrity={'report':'verified-json-bundle','metadata':'verified-json-bundle'}
        else:
            # Existing immutable snapshots retain their original HTML checksum.
            # It is parsed only for read compatibility, never served as a page.
            html=self.frozen_page(identifier).decode('utf-8')
            marker=re.search(r'const\s+D\s*=\s*',html)
            if not marker:raise ValueError('快照报告缺少数据载荷')
            frozen_report=json.JSONDecoder().raw_decode(html[marker.end():])[0]
            context_marker=re.search(r'window\.L2_CONTEXT\s*=\s*',html)
            if not context_marker:raise ValueError('快照缺少冻结上下文')
            frozen_context=json.JSONDecoder().raw_decode(html[context_marker.end():])[0]
            if (bundle.get('id')!=identifier or digest(bundle.get('report'))!=bundle.get('payloadSha256')
                    or digest(frozen_report)!=digest(bundle.get('report'))
                    or frozen_context.get('id')!=identifier or frozen_context.get('day')!=bundle.get('day')):
                raise ValueError('快照数据完整性校验失败')
            integrity={'report':'verified-against-frozen-html','metadata':'legacy-bundle-unverified'}
        return {'mode':'snapshot','day':bundle['day'],'id':identifier,'savedAt':bundle['savedAt'],
                'researchOnly':True,'provenance':bundle['reportProvenance'],'report':bundle['report'],
                'integrity':integrity,
                'stateViews':frozen_context.get('stateViews',{}),
                'stateWindow':frozen_context.get('stateWindow'),
                'charts':frozen_context.get('charts',{}),
                'patterns':frozen_context.get('patterns'),
                'validation':frozen_context.get('validation'),
                'validationDetails':frozen_context.get('validationDetails',{}),
                'patternUI':frozen_context.get('patternUI',{}),
                'filters':frozen_context.get('filters',{}),'continuousUI':frozen_context.get('continuousUI',{}),'scope':bundle['scope']}
