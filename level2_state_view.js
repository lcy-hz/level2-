/* Shared, deterministic presentation model. No market or filesystem reads. */
(function(root){
'use strict';
const finite=Number.isFinite;
const usable=r=>!!r&&finite(r.ratio)&&finite(r.amount)&&r.amount>0&&finite(r.net)&&!(r.unknown>0);
function derive(result){
 const entries=Object.entries(result.states),dates=[...new Set(entries.flatMap(([,s])=>s.history.map(r=>r.day)))].sort();
 const rows=entries.map(([code,s])=>({code,...s,byDay:Object.fromEntries(s.history.map(r=>[r.day,r]))}));
 const common=rows.filter(s=>dates.length===result.window&&dates.every(d=>usable(s.byDay[d])));
 const trajectory=dates.map(day=>{const amounts=rows.map(s=>s.byDay[day]).filter(r=>r&&finite(r.amount)&&r.amount>0),flow=common.map(s=>s.byDay[day]),den=flow.reduce((a,r)=>a+r.amount,0);return {day,amount:amounts.length?amounts.reduce((a,r)=>a+r.amount,0):null,amountCoverage:amounts.length,ratio:den?100*flow.reduce((a,r)=>a+r.net,0)/den:null,buyShare:flow.length?100*flow.filter(r=>r.ratio>0).length/flow.length:null};});
 const counts={improve:0,worsen:0,flat:0,unknown:0,toBuy:0,toSell:0};
 const applicable=dates.length>=2&&result.window>1;
 const stocks=rows.map(s=>{const a=s.byDay[dates.at(-2)],b=s.byDay[dates.at(-1)],delta=applicable&&usable(a)&&usable(b)?b.ratio-a.ratio:null,change=delta===null?'unknown':delta>0?'improve':delta<0?'worsen':'flat';if(applicable){counts[change]++;if(delta!==null){if(a.ratio<0&&b.ratio>0)counts.toBuy++;if(a.ratio>0&&b.ratio<0)counts.toSell++;}}const {byDay,...rest}=s;return {...rest,viewDelta:delta,change};}).sort((a,b)=>a.code.localeCompare(b.code));
 return {method:'continuous-common-cohort-20260923',day:result.day,window:result.window,dates,total:rows.length,common:common.length,trajectory,applicable,counts,stocks};
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
