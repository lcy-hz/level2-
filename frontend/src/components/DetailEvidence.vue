<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { detailStatus, startDetail } from '../api.js'

const props = defineProps({ card: { type: Object, required: true }, day: { type: String, required: true }, frozen: { type: Boolean, default: false } })
const emit = defineEmits(['loaded'])
const state = ref(props.frozen ? { status: props.card.computedDetail ? 'done' : 'unavailable', message: props.card.computedDetail ? '快照内已保存该股深查' : '快照未保存该股深查；不补算' } : { status: 'idle', message: '尚未查询本地缓存' })
const result = ref(null)
let sequence = 0
let timer = null
const evidence = computed(() => result.value || (props.card.computedDetail ? props.card.detailEvidence || props.card : null))
const quoteBySegment = computed(() => Object.fromEntries((evidence.value?.quotePath?.segments || []).map(row => [row.s, row])))
const busy = computed(() => ['queued', 'running'].includes(state.value.status))
const money = value => !Number.isFinite(value) ? '未知' : Math.abs(value) >= 1e8 ? `${(value / 1e8).toFixed(2)} 亿` : `${(value / 1e4).toFixed(1)} 万`
const ratio = value => Number.isFinite(value) ? `${value.toFixed(2)}%` : '未知'
const quotePrice = value => Number.isFinite(value) ? value.toFixed(4) : evidence.value?.quotePath ? '不可比较' : '未保存'
const quotePct = value => Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%` : evidence.value?.quotePath ? '不可比较' : '未保存'
const spreadBps = value => Number.isFinite(value) ? `${value.toFixed(2)} bp` : evidence.value?.quotePath ? '不可比较' : '未保存'
const bookPct = value => Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%` : evidence.value?.quotePath ? '不可比较' : '未保存'
const tenPct = row => row.tenLevelValid == null ? '未保存' : bookPct(row.medianTenLevelImbalancePct)
const displayedRise = row => !row || row.sameBidComparable == null ? '未保存' : row.sameBidComparable ? `${row.sameBidDisplayedRise} / ${row.sameBidComparable}` : '无可比同价快照'
const quoteStatus = { INVALID_DATE: '快照日期异常，未计算', DUPLICATE_TIME: '连续竞价时间戳重复，未任意选样', NO_COMPARABLE_QUOTES: '无可比较的有效一档快照' }
const tradeStatus = { MISSING_SEQUENCE: '缺少成交编号', INVALID_SEQUENCE: '成交编号缺失或重复', INVALID_TIME_ORDER: '编号与时间顺序冲突', INVALID_PRINT: '成交价或数量异常', NO_REGULAR_PRINTS: '连续竞价无有效成交' }
const tradeDrawdown = computed(() => {
  const item = evidence.value?.tradePrintDrawdown
  if (!item) return '此结果未保存；不读取最新逐笔数据回填'
  if (item.status !== 'OBSERVED') return tradeStatus[item.status] || '逐笔路径不可比较'
  return `${ratio(item.valuePct)}（${item.peakTime} → ${item.troughTime}） · ${item.printCount.toLocaleString()} 笔`
})

function accept(response, id) {
  if (id !== sequence) return
  state.value = response
  if (response.status === 'done') {
    if (response.result?.code !== props.card.code || response.result?.day !== props.day) {
      state.value = { status: 'error', message: '深查结果股票或日期与报告不一致' }
      return
    }
    result.value = response.result
    if (!props.frozen) emit('loaded', response.result)
  } else if (busy.value) {
    timer = setTimeout(() => poll(id), 1500)
  }
}
async function poll(id) {
  if (id !== sequence) return
  try { accept(await detailStatus(props.card.code, props.day), id) }
  catch (error) { if (id === sequence) state.value = { status: 'error', message: error.message } }
}
async function calculate() {
  if (props.frozen) return
  clearTimeout(timer)
  const id = ++sequence
  state.value = { status: 'running', message: '正在提交当前报告日的单股深查…' }
  try { accept(await startDetail(props.card.code, props.day), id) }
  catch (error) { if (id === sequence) state.value = { status: 'error', message: error.message } }
}
onMounted(() => { if (!props.frozen) poll(++sequence) })
onBeforeUnmount(() => { sequence++; clearTimeout(timer) })
</script>

<template>
  <section class="detail-evidence" aria-label="按需 Level-2 深查">
    <div class="detail-heading"><h3>盘中与关联单深查</h3><button v-if="!frozen && !evidence" type="button" :disabled="busy" @click="calculate">{{ busy ? '计算中…' : state.status === 'error' ? '重试计算' : '点击计算' }}</button></div>
    <p class="footnote" role="status">{{ state.message }}。{{ frozen ? '只读快照，不读取最新数据。' : '仅计算本股、当前报告日；结果缓存于本机。' }}</p>
    <template v-if="evidence">
      <p class="footnote">成交 {{ evidence.tradeRows?.toLocaleString() ?? '未知' }} 条 · 有效时段成交额覆盖 {{ ratio(evidence.regularCoverage) }} · 主动净额 {{ money(evidence.net) }} · 未知方向金额 {{ money(evidence.unknownAmount) }}</p>
      <p class="footnote">连续竞价逐笔成交价已观测回撤：{{ tradeDrawdown }}。仅用与报告成交额相同的正价正量有效成交；成交编号唯一且时间非降时按编号排序。不含集合竞价或无成交价位，也不代表可成交退出或含滑点收益。</p>
      <h4>盘中五时段</h4>
      <div class="table-scroll"><table><thead><tr><th>时段</th><th>成交额</th><th>主动净额</th><th>VWAP</th><th>一档中间价 首→末</th><th>中间价变化</th><th>低点至末值恢复</th></tr></thead><tbody><tr v-for="row in evidence.segments || []" :key="row.s"><td>{{ row.s }}</td><td>{{ money(row.a) }}</td><td>{{ money(row.n) }}</td><td>{{ row.v ?? '未知' }}</td><td>{{ quotePrice(quoteBySegment[row.s]?.firstMid) }} → {{ quotePrice(quoteBySegment[row.s]?.lastMid) }}<small v-if="quoteBySegment[row.s]" class="quote-coverage">{{ quoteBySegment[row.s].valid }}/{{ quoteBySegment[row.s].observed }} 条有效快照</small></td><td>{{ quotePct(quoteBySegment[row.s]?.midChangePct) }}</td><td>{{ quotePct(quoteBySegment[row.s]?.recoveryPct) }}</td></tr></tbody></table></div>
      <p class="footnote">盘口中间价：{{ evidence.quotePath ? evidence.quotePath.status === 'AVAILABLE' ? evidence.quotePath.method : quoteStatus[evidence.quotePath.status] || '盘口路径不可比较' : '此结果未保存盘口路径，不读取最新数据回填' }}；与主动净额并列仅供观察，不把价稳自动解释为被动承接或补单。</p>
      <details v-if="evidence.quotePath?.segments?.length" class="book-observations"><summary>盘口结构 · 价差与一／十档显示量</summary><div class="table-scroll"><table><thead><tr><th>时段</th><th>价差中位数</th><th>一档量差</th><th>十档量差</th><th>完整十档 / 有效报价</th><th>同价买一显示量上升 / 可比对</th><th>有效一档量 / 报价</th></tr></thead><tbody><tr v-for="row in evidence.quotePath.segments" :key="row.s"><td>{{ row.s }}</td><td>{{ spreadBps(row.medianSpreadBps) }}</td><td>{{ bookPct(row.medianTopImbalancePct) }}</td><td>{{ tenPct(row) }}</td><td>{{ row.tenLevelValid == null ? '未保存' : `${row.tenLevelValid} / ${row.valid}` }}</td><td>{{ displayedRise(row) }}</td><td>{{ row.depthValid == null ? '未保存' : `${row.depthValid} / ${row.valid}` }}</td></tr></tbody></table></div><p class="footnote">价差＝(卖一－买一)÷中间价，以 bp 计；量差＝(买量－卖量)÷两侧总量。十档仅纳入价位有序且价量完整的快照，取各档显示量总和；它与一档量差相关，不能当成独立确认。同价显示量上升仅是相邻有效快照的可见变化，不等于补单、吸筹或可成交队列增加。缺失量不补零。</p></details>
      <details v-if="evidence.quotePath?.source"><summary>盘口快照来源</summary><code>{{ evidence.quotePath.source }}</code></details>
      <h4>主动成交关联委托</h4>
      <div class="table-scroll"><table><thead><tr><th>分档</th><th>净额</th><th>关联键数</th></tr></thead><tbody><tr v-for="row in evidence.parents || []" :key="row.b"><td>{{ row.b }}</td><td>{{ money(row.n) }}</td><td>{{ row.c?.toLocaleString() ?? '未知' }}</td></tr></tbody></table></div>
      <details><summary>order_raw 原始委托类型与代码</summary><div class="table-scroll"><table><thead><tr><th>委托类型</th><th>委托代码</th><th>行数</th><th>数量</th></tr></thead><tbody><tr v-for="(row, index) in evidence.orders || []" :key="index"><td>{{ row.t }}</td><td>{{ row.s }}</td><td>{{ row.r?.toLocaleString() ?? '未知' }}</td><td>{{ row.q?.toLocaleString() ?? '未知' }}</td></tr></tbody></table></div></details>
      <p class="footnote">{{ evidence.note || '关联分组不是已验证经济母单；委托类型未解码为补撤单。' }}</p>
    </template>
  </section>
</template>
