const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('level2_patterns_ui.html', 'utf8');
const code = source.slice(source.indexOf('function chart('), source.indexOf('async function open('));
const nodes = [];
function node(tag, text = '') {
  const n = {tag, textContent:text, style:{}, attrs:{}, listeners:{},
    setAttribute(k,v){this.attrs[k]=v;}, addEventListener(k,v){this.listeners[k]=v;},
    getBoundingClientRect(){return {left:0,width:600};}};
  nodes.push(n); return n;
}
const scope = {Number, Math, Object, make:(tag,parent,text)=>node(tag,text),
  svgNode:(parent,tag,attrs,text)=>{const n=node(tag,text); n.attrs={...attrs}; return n;},
  fmt:(v,s='')=>Number.isFinite(v)?v.toFixed(2)+s:'未知',stageNames:{confirmed:'确认'}};
vm.createContext(scope);vm.runInContext(code,scope);
const data={name:'测试',dates:['20260918','20260921','20260922'],
  bars:[[10,12,9,11,100,10000],null,[12,14,11,13,200,20000]],
  indicators:[{ma_qfq_5:10},{},{ma_qfq_5:12,rsi_qfq_6:60}]};
scope.chart({},data,{name:'红三兵',start:0,key:null,stop:null,anchors:[],transitions:[]},'RSI6',true,true);
const svg=nodes.find(n=>n.tag==='svg'), readout=nodes.find(n=>n.className==='pattern-hover-detail');
svg.listeners.pointermove({clientX:55+530/6});
assert(readout.textContent.includes('20260918 · qfq 开 10.00'));
assert(readout.textContent.includes('成交量 100.00手'));
svg.listeners.pointermove({clientX:55+530/2});
assert(readout.textContent.includes('qfq数据缺失或异常'));
svg.listeners.keydown({key:'ArrowRight',preventDefault(){}});
assert(readout.textContent.includes('20260922'));
assert(readout.textContent.includes('较前交易日 未知'));
assert(readout.textContent.includes('rsi_qfq_6 60.00'));
console.log('Pattern chart pointer / keyboard / missing day / qfq indicators PASS');
