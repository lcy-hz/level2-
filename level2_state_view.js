/* Shared, deterministic presentation model. No market or filesystem reads. */
(function(root){
'use strict';
const finite=Number.isFinite;
const usable=r=>!!r&&finite(r.ratio)&&finite(r.amount)&&r.amount>0&&finite(r.net)&&!(r.unknown>0);
function slope(values){if(values.length<2||!values.every(finite))return null;const mid=(values.length-1)/2;return values.reduce((a,v,i)=>a+(i-mid)*v,0)/values.reduce((a,_,i)=>a+(i-mid)**2,0);}
function persistence(values,boundary=0){if(!values.length||!finite(values.at(-1)))return {side:null,days:null,leftCensored:false};const sign=v=>Math.sign(v-boundary),side=sign(values.at(-1));let days=0;for(let i=values.length-1;i>=0;i--){if(!finite(values[i])||sign(values[i])!==side)break;days++;}return {side,days,leftCensored:days===values.length};}
function improvement(values){if(values.length<2||!values.every(finite))return {comparisons:null,leftCensored:false};let comparisons=0;for(let i=values.length-1;i>0;i--){if(values[i]<=values[i-1])break;comparisons++;}return {comparisons,leftCensored:comparisons===values.length-1};}
function marketState(trajectory,window,common){const status=trajectory.length!==window?'INCOMPLETE_WINDOW':!common?'NO_COMMON_COHORT':'AVAILABLE';if(status!=='AVAILABLE')return {status,latestRatio:null,latestBuyShare:null,ratioDeltaPP:null,buyShareDeltaPP:null,ratioSlopePPPerDay:null,buyShareSlopePPPerDay:null,ratioPersistence:persistence([]),breadthPersistence:persistence([]),ratioImprovement:improvement([])};const ratios=trajectory.map(r=>r.ratio),shares=trajectory.map(r=>r.buyShare);return {status,latestRatio:ratios.at(-1),latestBuyShare:shares.at(-1),ratioDeltaPP:ratios.length>1?ratios.at(-1)-ratios.at(-2):null,buyShareDeltaPP:shares.length>1?shares.at(-1)-shares.at(-2):null,ratioSlopePPPerDay:slope(ratios),buyShareSlopePPPerDay:slope(shares),ratioPersistence:persistence(ratios),breadthPersistence:persistence(shares,50),ratioImprovement:improvement(ratios)};}
function priceState(trajectory,window,common){const status=trajectory.length!==window?'INCOMPLETE_WINDOW':!common?'NO_COMMON_PRICE_COHORT':'AVAILABLE',shares=trajectory.map(r=>r.priceUpShare);return {status,latestUpShare:status==='AVAILABLE'?shares.at(-1):null,upShareDeltaPP:status==='AVAILABLE'&&shares.length>1?shares.at(-1)-shares.at(-2):null,upShareSlopePPPerDay:status==='AVAILABLE'?slope(shares):null};}
function derive(result){
 const entries=Object.entries(result.states),dates=[...new Set(entries.flatMap(([,s])=>s.history.map(r=>r.day)))].sort();
 const rows=entries.map(([code,s])=>({code,...s,byDay:Object.fromEntries(s.history.map(r=>[r.day,r]))}));
 const common=rows.filter(s=>dates.length===result.window&&dates.every(d=>usable(s.byDay[d])));
 const priceCommon=rows.filter(s=>dates.length===result.window&&dates.every(d=>finite(s.byDay[d]?.priceDailyReturn)));
 const sources=Object.fromEntries((result.sources||[]).filter(s=>s&&s.day).map(s=>[s.day,s]));
 const trajectory=dates.map(day=>{const amounts=rows.map(s=>s.byDay[day]).filter(r=>r&&finite(r.amount)&&r.amount>0),flow=common.map(s=>s.byDay[day]),den=flow.reduce((a,r)=>a+r.amount,0),net=flow.reduce((a,r)=>a+r.net,0),prices=priceCommon.map(s=>s.byDay[day].priceDailyReturn);return {day,amount:amounts.length?amounts.reduce((a,r)=>a+r.amount,0):null,amountCoverage:amounts.length,directionCoverage:rows.filter(s=>usable(s.byDay[day])).length,commonAmount:flow.length?den:null,commonNet:flow.length?net:null,ratio:den?100*net/den:null,buyShare:flow.length?100*flow.filter(r=>r.ratio>0).length/flow.length:null,priceCoverage:rows.filter(s=>finite(s.byDay[day]?.priceDailyReturn)).length,priceUpShare:prices.length?100*prices.filter(v=>v>0).length/prices.length:null,priceDownShare:prices.length?100*prices.filter(v=>v<0).length/prices.length:null,priceFlatShare:prices.length?100*prices.filter(v=>v===0).length/prices.length:null,sourceStatus:sources[day]?.status||null,sourceFile:sources[day]?.source||null,priceSourceStatus:sources[day]?.priceStatus||null,priceSourceFile:sources[day]?.priceSource||null};});
 trajectory.forEach((row,index)=>{const previous=trajectory[index-1];row.ratioDeltaPP=previous&&finite(row.ratio)&&finite(previous.ratio)?row.ratio-previous.ratio:null;row.buyShareDeltaPP=previous&&finite(row.buyShare)&&finite(previous.buyShare)?row.buyShare-previous.buyShare:null;row.priceUpShareDeltaPP=previous&&finite(row.priceUpShare)&&finite(previous.priceUpShare)?row.priceUpShare-previous.priceUpShare:null;});
 const counts={improve:0,worsen:0,flat:0,unknown:0,toBuy:0,toSell:0};
 const applicable=dates.length>=2&&result.window>1;
 const stocks=rows.map(s=>{const a=s.byDay[dates.at(-2)],b=s.byDay[dates.at(-1)],delta=applicable&&usable(a)&&usable(b)?b.ratio-a.ratio:null,change=delta===null?'unknown':delta>0?'improve':delta<0?'worsen':'flat';if(applicable){counts[change]++;if(delta!==null){if(a.ratio<0&&b.ratio>0)counts.toBuy++;if(a.ratio>0&&b.ratio<0)counts.toSell++;}}const {byDay,...rest}=s;return {...rest,viewDelta:delta,change};}).sort((a,b)=>a.code.localeCompare(b.code));
 return {method:'common-cohort-weighted-flow-and-breadth',eventMethod:result.eventMethod||null,benchmark:result.benchmark||null,day:result.day,window:result.window,dates,total:rows.length,common:common.length,priceCommon:priceCommon.length,trajectory,marketState:marketState(trajectory,result.window,common.length),priceState:priceState(trajectory,result.window,priceCommon.length),applicable,counts,stocks};
}
function matches(s,f={}){
 const sign=(v,k)=>!k||k==='all'||(finite(v)&&(k==='positive'?v>0:k==='negative'?v<0:v===0));
 if(!sign(s.priceReturn,f.price)||!sign(s.level,f.levelSign)||!sign(s.weighted,f.weightedSign)||!sign(s.amountChange,f.volume))return false;
 if(f.coverage==='full'&&s.status!=='AVAILABLE'||f.coverage==='partial'&&s.status==='AVAILABLE'||f.coverage==='unknown'&&finite(s.level))return false;
 const p=f.preset;
 if(p==='relief'&&!(s.level<0&&s.viewDelta>0)||p==='buyStrong'&&!(s.level>0&&s.viewDelta>0)||p==='buyWeak'&&!(s.level>0&&finite(s.viewDelta)&&s.viewDelta<0)||p==='sellStrong'&&!(s.level<0&&finite(s.viewDelta)&&s.viewDelta<0)||p==='upSell'&&!(s.priceReturn>0&&finite(s.weighted)&&s.weighted<0)||p==='downBuy'&&!(finite(s.priceReturn)&&s.priceReturn<0&&s.weighted>0))return false;
 const prev=s.history?.at(-2),last=s.history?.at(-1),pair=usable(prev)&&usable(last);
 if(f.turn&&f.turn!=='all'&&(!pair||!(f.turn==='toBuy'?prev.ratio<0&&last.ratio>0:f.turn==='toSell'?prev.ratio>0&&last.ratio<0:f.turn==='buy'?prev.ratio>0&&last.ratio>0:prev.ratio<0&&last.ratio<0)))return false;
 for(const [key,field,scale] of [['amount','amount',1e8],['level','level',1],['delta','viewDelta',1],['weighted','weighted',1],['price','priceReturn',1]])for(const edge of ['Min','Max']){const bound=f[key+edge];if(bound!==undefined&&(!finite(s[field])||(edge==='Min'?s[field]<bound*scale:s[field]>bound*scale)))return false;}
 for(const [key,field] of [['buyDays','streak'],['sellDays','streak'],['improveTimes','improve'],['worsenTimes','worsen']])if(f[key]!==undefined&&(!finite(s[field])||s[field]<f[key]||(key==='buyDays'&&s.sign!==1)||(key==='sellDays'&&s.sign!==-1)))return false;
 return true;
}
const api={derive,usable,matches};if(typeof module!=='undefined')module.exports=api;else root.L2StateView=api;
})(globalThis);
