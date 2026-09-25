"""Pure, deterministic continuous-state presentation model for API clients."""
import math


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def usable(row):
    return (isinstance(row,dict) and finite(row.get('ratio')) and
            finite(row.get('amount')) and row['amount']>0 and
            finite(row.get('net')) and not (finite(row.get('unknown')) and row['unknown']>0))


def derive(result):
    entries=list(result.get('states',{}).items())
    dates=sorted({row['day'] for _,state in entries for row in state.get('history',[])})
    rows=[(code,state,{row['day']:row for row in state.get('history',[])}) for code,state in entries]
    common=[item for item in rows if len(dates)==result['window'] and all(usable(item[2].get(day)) for day in dates)]
    trajectory=[]
    for day in dates:
        amounts=[row[day]['amount'] for _,_,row in rows if isinstance(row.get(day),dict) and finite(row[day].get('amount')) and row[day]['amount']>0]
        flow=[row[day] for _,_,row in common]
        denominator=sum(row['amount'] for row in flow)
        trajectory.append({'day':day,'amount':sum(amounts) if amounts else None,'amountCoverage':len(amounts),
                           'ratio':100*sum(row['net'] for row in flow)/denominator if denominator else None,
                           'buyShare':100*sum(row['ratio']>0 for row in flow)/len(flow) if flow else None})
    counts={'improve':0,'worsen':0,'flat':0,'unknown':0,'toBuy':0,'toSell':0}
    applicable=len(dates)>=2 and result['window']>1
    stocks=[]
    for code,state,by_day in rows:
        previous=by_day.get(dates[-2]) if applicable else None
        latest=by_day.get(dates[-1]) if applicable else None
        delta=latest['ratio']-previous['ratio'] if applicable and usable(previous) and usable(latest) else None
        change='unknown' if delta is None else 'improve' if delta>0 else 'worsen' if delta<0 else 'flat'
        if applicable:
            counts[change]+=1
            if delta is not None:
                if previous['ratio']<0<latest['ratio']:counts['toBuy']+=1
                if previous['ratio']>0>latest['ratio']:counts['toSell']+=1
        stocks.append({'code':code,**state,'viewDelta':delta,'change':change})
    stocks.sort(key=lambda row:row['code'])
    return {'method':'continuous-common-cohort-20260923','eventMethod':result.get('eventMethod'),'day':result.get('day'),'window':result['window'],
            'dates':dates,'total':len(rows),'common':len(common),'trajectory':trajectory,
            'applicable':applicable,'counts':counts,'stocks':stocks}
