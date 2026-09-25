"""Date-partitioned report generation and immutable, explicitly bounded snapshots."""
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import hashlib
import json
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


class Workspace:
    def __init__(self,service,base=BASE,calendar=None):
        from level2_state import settings
        self.base,self.root,self.default=Path(base),service.root,service
        self.calendar=Path(calendar) if calendar else Path(settings()['trade_calendar'])
        self.reports=self.base/'.level2_reports'
        self.snapshots=self.base/'level2_snapshots'
        self.receipts=self.base/'.level2_chart_receipts'
        self.services={service.day:service};self.jobs={};self.lock=Lock()
        self.pool=ThreadPoolExecutor(max_workers=1)
        from level2_state import StateService
        self.state=StateService(self)
        self._patterns=None

    @property
    def patterns(self):
        if self._patterns is None:
            from level2_patterns import PatternService
            self._patterns=PatternService(self)
        return self._patterns

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
            'level2_state.py','level2_paths.py','level2_kline.py',
            'level2_kline_ui.html','level2_report_html.py','level2_detail_ui.html'])
        return result

    def dates(self):
        found=set()
        for p in self.root.glob('*.parquet'):
            m=re.fullmatch(r'(?:deal|snapshot|order_raw)_(\d{8})\.parquet',p.name)
            if m:found.add(m[1])
        from level2_intraday import minute_directory
        for p in minute_directory(self.root).glob('*.parquet'):
            if DATE.fullmatch(p.stem):found.add(p.stem)
        rows=[]
        for day in sorted(found,reverse=True):
            try:window=self.window(day)
            except (OSError,ValueError):window=[]
            missing=self.gate(day)
            window_missing=[d for d in window if self.gate(d)]
            ready=(len(window)==7 and window[-1]==day and not window_missing and not missing)
            rows.append({'day':day,'complete':not missing,'missing':missing,'window':window,
                         'windowMissing':window_missing,'canBuild':ready,
                         'minute':(minute_directory(self.root)/f'{day}.parquet').is_file(),
                         **self.status(day)})
        return rows

    def report_path(self,day):
        if not isinstance(day,str) or not DATE.fullmatch(day):raise ValueError('日期格式无效')
        from level2_detail_server import REPORT
        return REPORT if day==self.default.day else self.reports/day/'report.html'

    def status(self,day):
        path=self.report_path(day)
        with self.lock:
            job=self.jobs.get(day)
            if job and job['status'] in ('running','queued','error'):return dict(job)
        if path.is_file():
            meta=path.with_suffix('.provenance.json')
            from level2_paths import PATHS
            if not meta.is_file() and (PATHS['level2']!=Path('/Volumes/Sn850X_4T/data/level2').resolve() or PATHS['stock_basic']!=Path('/Users/m4pro/Documents/claude/quant-platform/data/sync/stock/basic/stock_basic/stock_basic.csv').resolve()):
                return {'status':'stale','message':'数据源已切换，旧报告来源不能确认，请重新计算'}
            if meta.is_file():
                try:
                    if json.loads(meta.read_text())['sourceDigest']!=digest(self.sources(day)):
                        return {'status':'stale','message':'源文件已变化，报告待重新计算'}
                except (ValueError,KeyError):return {'status':'stale','message':'报告指纹无效'}
            return {'status':'ready','message':'报告可查看'+('（旧报告未记录生成时源指纹）' if not meta.is_file() else '')}
        return {'status':'missing','message':'报告待计算'}

    def get_service(self,day):
        from level2_detail_server import Service,read_report
        if self.status(day)['status']!='ready':raise ValueError('所选日期报告未就绪，请先计算')
        with self.lock:
            if day not in self.services:
                self.services[day]=Service(read_report(self.report_path(day)),root=self.root)
            return self.services[day]

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
        target=self.report_path(day)
        target.parent.mkdir(parents=True,exist_ok=True)
        tmp=target.with_suffix('.building.html')
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
            from level2_detail_server import read_report
            data=read_report(tmp)
            if data['markets'][-1]['day']!=day or not data['cards']:raise ValueError('生成结果日期或覆盖无效')
            if digest(initial)!=digest(self.sources(day)):raise ValueError('计算期间源数据变化，未发布结果')
            tmp.replace(target)
            target.with_suffix('.provenance.json').write_text(encoded({'sourceDigest':digest(initial),'sources':initial,'generatedAt':datetime.now(timezone.utc).isoformat()}))
            with self.lock:
                previous=self.services.pop(day,None)
                if previous and previous is not self.default:previous.pool.shutdown(wait=False)
                self.jobs[day]={'status':'ready','message':'全市场报告计算完成'}
        except Exception as exc:
            with self.lock:self.jobs[day]={'status':'error','message':'报告计算失败：'+str(exc)}

    def record_chart(self,result,kind):
        receipt=uuid.uuid4().hex
        self.receipts.mkdir(exist_ok=True)
        sources=[]
        if kind=='minute':
            sources=[fingerprint(result['source']),fingerprint(result['preCloseSource'])]
        else:
            sources=[fingerprint(Path(p)) for p in result['sourceFiles']] if result.get('sourceFiles') else [fingerprint(Path(result['source'])/f'{d}_stk_factor_pro.csv') for d in result['labels']]
        value={'result':result,'kind':kind,'sources':sources,'dataSha256':digest(result)}
        (self.receipts/f'{receipt}.json').write_text(encoded(value))
        return receipt

    def decorate(self,html,context):
        # One canonical toolbar; context precedes all chart/detail scripts.
        html=re.sub(r'<!-- WORKSPACE START -->.*?<!-- WORKSPACE END -->','',html,flags=re.S)
        config='<script>window.L2_CONTEXT='+encoded(context)+';window.L2_CAPTURE={charts:{},states:{}};</script>'
        html=html.replace('<head>','<head>'+config,1)
        state_ui=self.base/'level2_state_ui.html'
        model=self.base/'level2_state_view.js'
        model_script='<script>'+model.read_text()+'</script>' if model.exists() else ''
        pattern_ui=self.base/'level2_patterns_ui.html'
        return html.replace('</body>','<!-- WORKSPACE START -->'+(self.base/'level2_workspace_ui.html').read_text()+model_script+(state_ui.read_text() if state_ui.exists() else '')+(pattern_ui.read_text() if pattern_ui.exists() else '')+'<!-- WORKSPACE END --></body>')

    def page(self,day):
        if self.status(day)['status']!='ready':
            html='''<html><head><meta charset="utf-8"><title>Level-2 报告待计算</title><style>
                body{box-sizing:border-box;margin:0;background:#101820;color:#e7f0fa;font:16px/1.6 system-ui,-apple-system,sans-serif}
                main{max-width:1100px;margin:0 auto;padding:24px}
                h1{font-size:28px;margin:0 0 18px}
                .unavailable{padding:18px 20px;border:1px solid #416781;border-radius:10px;background:#172435;color:#c9d8e7}
                </style></head><body><main><h1>连续市场与个股证据报告</h1><p class="unavailable">当前报告未就绪或来源已变化。请在上方选择日期并计算；完成前不展示旧数据。</p></main></body></html>'''
            return self.decorate(html,{'mode':'live','day':day,'unavailable':True}).encode()
        self.get_service(day)
        return self.decorate(self.report_path(day).read_text(),{'mode':'live','day':day}).encode()

    def snapshot_path(self,identifier):
        if not isinstance(identifier,str) or not ID.fullmatch(identifier):raise ValueError('快照编号无效')
        return self.snapshots/identifier

    def list_snapshots(self):
        result=[]
        for p in self.snapshots.glob('*/bundle.json'):
            if not (p.parent/'COMMITTED').exists():continue
            try:
                b=json.loads(p.read_text());result.append({k:b[k] for k in ['id','day','savedAt','chartCount']})
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
        charts={};receipts={}
        requested=request.get('charts',{})
        if not isinstance(requested,dict) or len(requested)>10418:raise ValueError('图表范围无效')
        for key,token in requested.items():
            if not isinstance(token,str) or not ID.fullmatch(token):raise ValueError('图表凭据无效')
            receipt=json.loads((self.receipts/f'{token}.json').read_text());r=receipt['result']
            if r['day']!=day or r['code'] not in service.cards or key!=receipt['kind']+'/'+r['code']:raise ValueError('快照图表日期或股票不一致')
            charts[key]=r;receipts[key]=receipt
        identifier=uuid.uuid4().hex;saved=datetime.now(timezone.utc).isoformat()
        states=self.state.frozen(request.get('states',{}),day)
        state_window=request.get('stateWindow')
        if state_window is not None and str(state_window) not in states:raise ValueError('选中的观察窗口未冻结')
        # Derive from verified receipts with the identical pure model used by the page.
        views={}
        if states:
            process=subprocess.run(['node','-e',"const m=require(process.argv[1]);let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(Object.fromEntries(Object.entries(JSON.parse(s)).map(([k,v])=>[k,m.derive(v)])))));",str(self.base/'level2_state_view.js')],input=encoded(states),text=True,capture_output=True,timeout=30,check=True)
            views=json.loads(process.stdout)
        context={'mode':'snapshot','day':day,'id':identifier,'savedAt':saved,'charts':charts,'filters':filters,'states':states,'stateWindow':state_window}
        context['stateViews']=views
        pattern_result=None
        if request.get('patternReceipt'):
            verified=self.patterns.receipt(request['patternReceipt'],day)
            codes=request.get('patternCharts',[])
            if not isinstance(codes,list) or len(codes)>200 or any(not isinstance(c,str) or c not in verified['details'] for c in codes):raise ValueError('形态图范围无效，最多200只已查看图')
            pattern_result={'result':verified['result'],'details':{c:verified['details'][c] for c in codes}}
        context['patterns']=pattern_result
        ui=request.get('patternUI',{})
        if not isinstance(ui,dict) or len(encoded(ui))>10000:raise ValueError('形态视图参数无效')
        context['patternUI']=ui
        template=self.report_path(day).read_text()
        marker=re.search(r'const\s+D\s*=\s*',template)
        _,length=json.JSONDecoder().raw_decode(template[marker.end():])
        html=template[:marker.end()]+encoded(data)+template[marker.end()+length:]
        html=self.decorate(html,context)
        provenance=self.report_path(day).with_suffix('.provenance.json')
        bundle={'id':identifier,'day':day,'savedAt':saved,'chartCount':len(charts),'report':data,'filters':filters,
                'stateViews':views,
                'patterns':pattern_result,'patternUI':ui,
                'charts':receipts,'states':states,'stateWindow':state_window,'payloadSha256':digest(data),'htmlSha256':hashlib.sha256(html.encode()).hexdigest(),
                'reportProvenance':json.loads(provenance.read_text()) if provenance.exists() else {'status':'UNKNOWN_GENERATION_LINEAGE'},
                'sourcesObservedAtSave':self.sources(day),
                'scope':'整份当前报告与已加载详情；只冻结本次页面已成功读取的图表；其余明确未保存。历史日期快照不是历史当时可得性证明。'}
        directory=self.snapshot_path(identifier);directory.mkdir(parents=True,exist_ok=False)
        (directory/'bundle.json').write_text(encoded(bundle))
        (directory/'report.html').write_text(html)
        (directory/'COMMITTED').write_text(bundle['htmlSha256'])
        return {'id':identifier,'day':day,'savedAt':saved,'chartCount':len(charts)}

    def frozen_page(self,identifier):
        p=self.snapshot_path(identifier)
        html=(p/'report.html').read_bytes()
        if (p/'COMMITTED').read_text()!=hashlib.sha256(html).hexdigest():raise ValueError('快照文件完整性校验失败')
        return html

    def snapshot_document(self,identifier):
        """Serve only the saved payload; never hydrate a snapshot from live data."""
        p=self.snapshot_path(identifier)
        html=self.frozen_page(identifier).decode('utf-8')
        bundle=json.loads((p/'bundle.json').read_text())
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
        return {'mode':'snapshot','day':bundle['day'],'id':identifier,'savedAt':bundle['savedAt'],
                'researchOnly':True,'provenance':bundle['reportProvenance'],'report':bundle['report'],
                'integrity':{'report':'verified-against-frozen-html','metadata':'legacy-bundle-unverified'},
                'stateViews':frozen_context.get('stateViews',{}),
                'stateWindow':frozen_context.get('stateWindow'),
                'charts':frozen_context.get('charts',{}),
                'patterns':frozen_context.get('patterns'),
                'patternUI':frozen_context.get('patternUI',{}),
                'filters':frozen_context.get('filters',{}),'scope':bundle['scope']}
