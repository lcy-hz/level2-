"""Native three-table quality evidence. No raw data mutation or automatic deduplication."""
from pathlib import Path
import json
from level2_contract import PAT, native_ticks, UNKNOWN_AMOUNT, KNOWN_NET

def quality_report(con,root,day,progress=print):
    import hashlib
    from level2_contract import __file__ as contract_file
    def identity():
        files=[Path(root)/f'{k}_{day}.parquet' for k in ['deal','snapshot','order_raw']]+[Path(__file__),Path(contract_file)]
        return hashlib.sha256(json.dumps([(str(p.resolve()),p.stat().st_size,p.stat().st_mtime_ns) for p in files]).encode()).hexdigest()
    before=identity();folder=Path(__file__).parent/'.level2_quality_cache';folder.mkdir(exist_ok=True)
    path=folder/f'{day}-{before}.json'
    if path.exists():return json.loads(path.read_text())
    result=inspect_day(con,root,day,progress)
    if identity()!=before:raise ValueError('质量核验期间来源变化，不发布')
    result['sourceIdentity']=before
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False));tmp.replace(path)
    return result

def inspect_day(con, root, day, progress=print):
    root=Path(root);profiles={};sets={}
    for kind in ['deal','snapshot','order_raw']:
        progress('quality '+day+' '+kind)
        path=root/f'{kind}_{day}.parquet'
        rows=con.execute(f'''WITH x AS (
          SELECT "万得代码" code,TRY_CAST("自然日" AS BIGINT) d,TRY_CAST("时间" AS BIGINT) t
          FROM read_parquet(?) WHERE regexp_matches("万得代码",'{PAT}')
        ) SELECT code,count(*) nrows,
          count(*) FILTER (WHERE d IS NULL OR d<>?) bad_date,
          count(*) FILTER (WHERE t IS NULL OR t<0 OR t>=240000000 OR (t//100000)%100>=60 OR (t//1000)%100>=60) bad_clock,
          count(*) FILTER (WHERE t=0) zero_clock,
          count(*) FILTER (WHERE t>150000000) after_close,
          min(t),max(t) FROM x GROUP BY code''',[str(path),int(day)]).fetchall()
        sets[kind]={r[0] for r in rows}
        totals=[sum(r[i] for r in rows) for i in range(1,6)]
        count=totals[0]
        profiles[kind]={'file':str(path),'stocks':len(rows),'rows':count,
            **dict(zip(['badDate','invalidClock','zeroClock','afterClose'],totals[1:])),
            'invalidClockRate':totals[2]/count if count else None,
            'affectedStocks':sum(any(r[i] for i in range(2,5)) for r in rows),
            'minTime':min((r[6] for r in rows if r[6] is not None),default=None),
            'maxTime':max((r[7] for r in rows if r[7] is not None),default=None)}
    con.execute('CREATE OR REPLACE TEMP VIEW quality_ticks AS '+native_ticks(root/f'deal_{day}.parquet',day))
    progress('quality '+day+' direction')
    n,amount,known,unknown,badkeys=con.execute(f'''SELECT count(*),sum(price*qty),{KNOWN_NET},{UNKNOWN_AMOUNT},
        count(*) FILTER(WHERE side IN ('B','S') AND (pid IS NULL OR pid<=0)) FROM quality_ticks''').fetchone()
    progress('quality '+day+' candidate duplicate keys')
    # ID is a candidate key only: no Channel in native schema, so collisions are not auto-deleted.
    dup=con.execute(f'''WITH g AS (
      SELECT "万得代码", "自然日", "成交编号",count(*) n
      FROM read_parquet(?) WHERE regexp_matches("万得代码",'{PAT}')
      AND TRY_CAST("成交编号" AS BIGINT)>0 GROUP BY 1,2,3 HAVING count(*)>1
    ) SELECT count(*),COALESCE(sum(n),0),COALESCE(sum(n-1),0) FROM g''',[str(root/f'deal_{day}.parquet')]).fetchone()
    progress('quality '+day+' order linkage')
    # Inspect both native candidate key fields, never select one merely for best fit.
    linkage={}
    for field in ['委托编号','交易所委托号']:
        a=[0,0,0,0];codes=sorted(sets['deal'])
        for offset in range(0,len(codes),200):
            selected=','.join("'"+s+"'" for s in codes[offset:offset+200])
            con.execute(f'''CREATE OR REPLACE TEMP TABLE quality_orders AS
              SELECT "万得代码" code,TRY_CAST("{field}" AS BIGINT) pid,
                count(*) nrows,count(DISTINCT "委托代码") sides
              FROM read_parquet(?) WHERE "自然日"=? AND "万得代码" IN ({selected})
              AND TRY_CAST("{field}" AS BIGINT)>0 GROUP BY 1,2''',[str(root/f'order_raw_{day}.parquet'),day])
            batch=con.execute(f'''SELECT count(*),count(*) FILTER(WHERE o.pid IS NOT NULL),
              count(*) FILTER(WHERE o.nrows>1),count(*) FILTER(WHERE o.sides>1)
              FROM quality_ticks t LEFT JOIN quality_orders o USING(code,pid)
              WHERE t.side IN ('B','S') AND t.pid>0 AND t.code IN ({selected})''').fetchone()
            a=[x+y for x,y in zip(a,batch)]
            con.execute('DROP TABLE quality_orders')
        linkage[field]={'eligibleTrades':a[0],'matchedTrades':a[1],'repeatedKeyTrades':a[2],
            'multiSideKeyTrades':a[3],'matchRate':a[1]/a[0] if a[0] else None}
    intersection=set.intersection(*sets.values());union=set.union(*sets.values())
    return {'day':day,'scope':'目标日沪深A股原生三表；分母为各表A股行数，不含ETF/转债',
      'tables':profiles,'coverage':{'union':len(union),'intersection':len(intersection),
          'missingByTable':{k:sorted(union-v) for k,v in sets.items()}},
      'direction':{'validTrades':n,'amount':amount,'knownNet':known,'unknownAmount':unknown,
          'unknownRate':unknown/amount if amount else None,'invalidLinkedKeyTrades':badkeys},
      'candidateDuplicateKey':{'groups':dup[0],'affectedRows':dup[1],'excessRows':dup[2],
          'rate':dup[1]/profiles['deal']['rows'] if profiles['deal']['rows'] else None},
      'linkage':linkage,'limits':['成交候选键为股票/日期/成交编号；无频道，不将候选键重复直接判定为重复成交，不自动去重。',
          '两种委托键仅做匹配审计，匹配不证明经济订单身份；重复键可能含撤单等多事件，不自动认定错误。',
          '零时钟、盘后记录单列：可能是状态或延迟发布，不直接称为非法交易。',
          '未完成逐字段完全重复行、时间乱序、订单事件语义与盘口重建验证；不是完整性认证。']}

def render_quality(q):
    from html import escape
    def f(v):return f'{v:,}' if isinstance(v,int) else '未知' if v is None else str(v)
    d=q['direction'];c=q['coverage'];du=q['candidateDuplicateKey']
    unknown='未知' if d['unknownRate'] is None else f"{d['unknownRate']*100:.6f}%"
    html=f'''<section id="data-quality"><h2>数据质量与关联键核验</h2>
      <p>目标日 {q['day']}：三表共同覆盖 {c['intersection']:,} 只，并集 {c['union']:,} 只；有效成交未知方向金额占比 {unknown}。
      文件发布通过不等于行情无异常；以下是诊断计数，不是吸筹或交易确认。</p>
      <p>{escape(q['scope'])}。非法时钟指无法解析或时分秒越界；零时钟与15:00之后记录独立统计，不混为错误。</p>
      <div class="scroll"><table><thead><tr><th>表</th><th>证券数</th><th>行数</th><th>日期异常</th><th>非法时钟</th><th>零时钟</th><th>盘后行</th></tr></thead><tbody>'''
    for k,v in q['tables'].items():
        html+='<tr>'+''.join('<td>'+f(x)+'</td>' for x in [k,v['stocks'],v['rows'],v['badDate'],v['invalidClock'],v['zeroClock'],v['afterClose']])+'</tr>'
    html+='</tbody></table></div>'
    html+=f"<p>成交候选键重复：{du['groups']:,}组，涉及{du['affectedRows']:,}行；有效已识别方向成交中无效关联编号：{d['invalidLinkedKeyTrades']:,}条。无效编号不会拼成大单。</p>"
    html+='<h3>候选委托字段匹配，不代表已确认订单身份</h3><div class="scroll"><table><thead><tr><th>候选字段</th><th>有效编号成交</th><th>匹配成交</th><th>重复键涉及成交</th><th>多方向键涉及成交</th></tr></thead><tbody>'
    for k,v in q['linkage'].items():
        html+='<tr>'+''.join('<td>'+f(x)+'</td>' for x in [k,v['eligibleTrades'],v['matchedTrades'],v['repeatedKeyTrades'],v['multiSideKeyTrades']])+'</tr>'
    html+='</tbody></table></div><p>高匹配率不能证明编号全局唯一；频道未提供，关联分组仅为描述性统计，不作为机构母单或已验证大单因子。</p>'
    html+='<details><summary>覆盖差异、来源与未完成检查</summary>'
    for k,v in c['missingByTable'].items():html+='<p>'+escape(k+'缺少（相对三表并集）：'+('、'.join(v) or '无'))+'</p>'
    for v in q['tables'].values():html+='<p>'+escape(v['file'])+'</p>'
    for s in q['limits']:html+='<p>'+escape(s)+'</p>'
    return html+'</details></section>'
