"""Pure, deterministic continuous-state presentation model for API clients."""
import math


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def usable(row):
    return (isinstance(row,dict) and finite(row.get('ratio')) and
            finite(row.get('amount')) and row['amount']>0 and
            finite(row.get('net')) and not (finite(row.get('unknown')) and row['unknown']>0))


def slope(values):
    if len(values)<2 or not all(finite(value) for value in values):
        return None
    midpoint=(len(values)-1)/2
    return sum((index-midpoint)*value for index,value in enumerate(values))/sum((index-midpoint)**2 for index in range(len(values)))


def persistence(values, boundary=0):
    if not values or not finite(values[-1]):
        return {'side':None,'days':None,'leftCensored':False}
    side=(values[-1]>boundary)-(values[-1]<boundary)
    days=0
    for value in reversed(values):
        if not finite(value) or (value>boundary)-(value<boundary)!=side:
            break
        days+=1
    return {'side':side,'days':days,'leftCensored':days==len(values)}


def improvement(values):
    if len(values)<2 or not all(finite(value) for value in values):
        return {'comparisons':None,'leftCensored':False}
    comparisons=0
    for previous,current in reversed(list(zip(values[:-1],values[1:]))):
        if current<=previous:
            break
        comparisons+=1
    return {'comparisons':comparisons,'leftCensored':comparisons==len(values)-1}


def market_state(trajectory,window,common):
    status='INCOMPLETE_WINDOW' if len(trajectory)!=window else 'NO_COMMON_COHORT' if not common else 'AVAILABLE'
    if status!='AVAILABLE':
        return {'status':status,'latestRatio':None,'latestBuyShare':None,'ratioDeltaPP':None,'buyShareDeltaPP':None,
                'ratioSlopePPPerDay':None,'buyShareSlopePPPerDay':None,'ratioPersistence':persistence([]),
                'breadthPersistence':persistence([]),'ratioImprovement':improvement([])}
    ratios=[row['ratio'] for row in trajectory]
    shares=[row['buyShare'] for row in trajectory]
    return {'status':status,'latestRatio':ratios[-1],'latestBuyShare':shares[-1],
            'ratioDeltaPP':ratios[-1]-ratios[-2] if len(ratios)>1 else None,
            'buyShareDeltaPP':shares[-1]-shares[-2] if len(shares)>1 else None,
            'ratioSlopePPPerDay':slope(ratios),'buyShareSlopePPPerDay':slope(shares),
            'ratioPersistence':persistence(ratios),'breadthPersistence':persistence(shares,50),
            'ratioImprovement':improvement(ratios)}


def price_state(trajectory,window,common):
    status='INCOMPLETE_WINDOW' if len(trajectory)!=window else 'NO_COMMON_PRICE_COHORT' if not common else 'AVAILABLE'
    shares=[row['priceUpShare'] for row in trajectory]
    return {'status':status,'latestUpShare':shares[-1] if status=='AVAILABLE' else None,
            'upShareDeltaPP':shares[-1]-shares[-2] if status=='AVAILABLE' and len(shares)>1 else None,
            'upShareSlopePPPerDay':slope(shares) if status=='AVAILABLE' else None}


def derive(result):
    entries=list(result.get('states',{}).items())
    dates=sorted({row['day'] for _,state in entries for row in state.get('history',[])})
    rows=[(code,state,{row['day']:row for row in state.get('history',[])}) for code,state in entries]
    common=[item for item in rows if len(dates)==result['window'] and all(usable(item[2].get(day)) for day in dates)]
    price_common=[item for item in rows if len(dates)==result['window'] and
                  all(finite(item[2].get(day,{}).get('priceDailyReturn')) for day in dates)]
    sources={source['day']:source for source in result.get('sources',[]) if isinstance(source,dict) and 'day' in source}
    trajectory=[]
    for day in dates:
        amounts=[row[day]['amount'] for _,_,row in rows if isinstance(row.get(day),dict) and finite(row[day].get('amount')) and row[day]['amount']>0]
        flow=[row[day] for _,_,row in common]
        denominator=sum(row['amount'] for row in flow)
        numerator=sum(row['net'] for row in flow)
        price_values=[row[day]['priceDailyReturn'] for _,_,row in price_common]
        price_coverage=sum(finite(row.get(day,{}).get('priceDailyReturn')) for _,_,row in rows)
        trajectory.append({'day':day,'amount':sum(amounts) if amounts else None,'amountCoverage':len(amounts),
                           'directionCoverage':sum(usable(row.get(day)) for _,_,row in rows),
                           'commonAmount':denominator if flow else None,'commonNet':numerator if flow else None,
                           'ratio':100*numerator/denominator if denominator else None,
                           'buyShare':100*sum(row['ratio']>0 for row in flow)/len(flow) if flow else None,
                           'priceCoverage':price_coverage,
                           'priceUpShare':100*sum(value>0 for value in price_values)/len(price_values) if price_values else None,
                           'priceDownShare':100*sum(value<0 for value in price_values)/len(price_values) if price_values else None,
                           'priceFlatShare':100*sum(value==0 for value in price_values)/len(price_values) if price_values else None,
                           'sourceStatus':sources.get(day,{}).get('status'),'sourceFile':sources.get(day,{}).get('source'),
                           'priceSourceStatus':sources.get(day,{}).get('priceStatus'),
                           'priceSourceFile':sources.get(day,{}).get('priceSource')})
    for index,row in enumerate(trajectory):
        previous=trajectory[index-1] if index else None
        row['ratioDeltaPP']=row['ratio']-previous['ratio'] if previous and finite(row['ratio']) and finite(previous['ratio']) else None
        row['buyShareDeltaPP']=row['buyShare']-previous['buyShare'] if previous and finite(row['buyShare']) and finite(previous['buyShare']) else None
        row['priceUpShareDeltaPP']=row['priceUpShare']-previous['priceUpShare'] if previous and finite(row['priceUpShare']) and finite(previous['priceUpShare']) else None
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
    return {'method':'common-cohort-weighted-flow-and-breadth','eventMethod':result.get('eventMethod'),
            'benchmark':result.get('benchmark'),'peers':result.get('peers'),'day':result.get('day'),'window':result['window'],
            'dates':dates,'total':len(rows),'common':len(common),'priceCommon':len(price_common),'trajectory':trajectory,
            'marketState':market_state(trajectory,result['window'],len(common)),
            'priceState':price_state(trajectory,result['window'],len(price_common)),
            'applicable':applicable,'counts':counts,'stocks':stocks}
