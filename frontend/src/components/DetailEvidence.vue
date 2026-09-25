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
const weightedTenPct = row => row.medianWeightedTenImbalancePct === undefined ? '未保存' : bookPct(row.medianWeightedTenImbalancePct)
const microBp = row => row.medianMicropricePremiumBps === undefined ? '未保存' : spreadBps(row.medianMicropricePremiumBps)
const displayedRise = row => !row || row.sameBidComparable == null ? '未保存' : row.sameBidComparable ? `${row.sameBidDisplayedRise} / ${row.sameBidComparable}` : '无可比同价快照'
const recoveryCounts = item => !item ? '未保存' : item.status === 'INVALID_CLOCK' ? '时钟异常' : item.status !== 'OBSERVED' ? '无同价可比快照' : `${item.declines} / ${item.recovered} / ${item.censored}`
const recoveryTime = item => !item ? '未保存' : item.status !== 'OBSERVED' ? '不可比较' : item.declines === 0 ? '无降量事件' : Number.isFinite(item.medianObservedSeconds) ? `${item.medianObservedSeconds.toFixed(2)} 秒` : '无完整恢复'
const recoveryPairs = item => !item ? '未保存' : item.samePricePairs == null ? '不可比较' : item.samePricePairs.toLocaleString()
const auditCount = value => Number.isFinite(value) ? value.toLocaleString() : '未知'
const auditStatus = { MISSING_FIELD: '源字段缺失', NO_VALID_KEYS: '无有效正编号', AVAILABLE: '候选关联可统计' }
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
      <details v-if="evidence.quotePath?.segments?.length" class="book-observations"><summary>盘口结构 · 价差、微价格与一／十档显示量</summary><div class="table-scroll"><table><thead><tr><th>时段</th><th>价差中位数</th><th>微价格－中间价</th><th>一档量差</th><th>十档量差</th><th>距离加权十档量差</th><th>完整十档 / 有效报价</th><th>同价买一显示量上升 / 可比对</th><th>有效一档量 / 报价</th></tr></thead><tbody><tr v-for="row in evidence.quotePath.segments" :key="row.s"><td>{{ row.s }}</td><td>{{ spreadBps(row.medianSpreadBps) }}</td><td>{{ microBp(row) }}</td><td>{{ bookPct(row.medianTopImbalancePct) }}</td><td>{{ tenPct(row) }}</td><td>{{ weightedTenPct(row) }}</td><td>{{ row.tenLevelValid == null ? '未保存' : `${row.tenLevelValid} / ${row.valid}` }}</td><td>{{ displayedRise(row) }}</td><td>{{ row.depthValid == null ? '未保存' : `${row.depthValid} / ${row.valid}` }}</td></tr></tbody></table></div><p class="footnote">微价格以买卖一档价量交叉加权，减中间价后以 bp 表示；正值表示当前显示量偏向买一。十档距离权重为 1/(1+离最优价距离/尺度)，尺度取当前价差，锁定盘口取最近档位价差；完整十档覆盖与原十档量差相同。它们只是相关的静态显示量描述，不等于可成交深度或独立确认。同价显示量上升也不等于补单、吸筹或队列增加；缺失不补零。</p></details>
      <details v-if="evidence.quotePath?.segments?.length" class="book-observations"><summary>同价一档显示量恢复 · 非补单识别</summary><div class="table-scroll"><table><thead><tr><th>时段</th><th>买一下降 / 恢复 / 删失</th><th>买一中位耗时</th><th>买一同价可比对</th><th>卖一下降 / 恢复 / 删失</th><th>卖一中位耗时</th><th>卖一同价可比对</th></tr></thead><tbody><tr v-for="row in evidence.quotePath.segments" :key="row.s"><td>{{ row.s }}</td><td>{{ recoveryCounts(row.bidDisplayedRecovery) }}</td><td>{{ recoveryTime(row.bidDisplayedRecovery) }}</td><td>{{ recoveryPairs(row.bidDisplayedRecovery) }}</td><td>{{ recoveryCounts(row.askDisplayedRecovery) }}</td><td>{{ recoveryTime(row.askDisplayedRecovery) }}</td><td>{{ recoveryPairs(row.askDisplayedRecovery) }}</td></tr></tbody></table></div><p class="footnote">仅在最优报价不变、该侧价量连续有效且显示量为正时，记录下降及首次观测回到下降前数量；价格变化、零／缺量或时段结束均记为删失。中位耗时只对已观测到恢复的事件计算，不能代表所有降量事件或实际补单速度。成交、撤单与新增委托未逐条匹配，不推断订单来源或吸筹意图。</p></details>
      <details v-if="evidence.quotePath?.source"><summary>盘口快照来源</summary><code>{{ evidence.quotePath.source }}</code></details>
      <h4>主动成交关联委托</h4>
      <div class="table-scroll"><table><thead><tr><th>分档</th><th>净额</th><th>关联键数</th></tr></thead><tbody><tr v-for="row in evidence.parents || []" :key="row.b"><td>{{ row.b }}</td><td>{{ money(row.n) }}</td><td>{{ row.c?.toLocaleString() ?? '未知' }}</td></tr></tbody></table></div>
      <details><summary>order_raw 原始委托类型与代码</summary><div class="table-scroll"><table><thead><tr><th>委托类型</th><th>委托代码</th><th>行数</th><th>数量</th></tr></thead><tbody><tr v-for="(row, index) in evidence.orders || []" :key="index"><td>{{ row.t }}</td><td>{{ row.s }}</td><td>{{ row.r?.toLocaleString() ?? '未知' }}</td><td>{{ row.q?.toLocaleString() ?? '未知' }}</td></tr></tbody></table></div></details>
      <details class="book-observations"><summary>候选委托编号关联审计 · 非订单身份</summary><template v-if="evidence.orderLinkAudit?.length"><div class="table-scroll"><table><thead><tr><th>原始字段</th><th>状态</th><th>有效委托行 / 原始行</th><th>候选键 / 重复键组 / 多代码键组</th><th>字段交集成交 / 有效成交</th><th>委托代码同字母</th><th>单条键且同字母</th><th>重复键涉及成交</th></tr></thead><tbody><tr v-for="row in evidence.orderLinkAudit" :key="row.field"><td>{{ row.field }}</td><td>{{ auditStatus[row.status] || '不可比较' }}</td><td>{{ auditCount(row.validOrderRows) }} / {{ auditCount(row.orderRows) }}</td><td>{{ auditCount(row.candidateKeys) }} / {{ auditCount(row.repeatedKeyGroups) }} / {{ auditCount(row.multiCodeKeyGroups) }}</td><td>{{ auditCount(row.matchedTrades) }} / {{ auditCount(row.eligibleTrades) }}</td><td>{{ auditCount(row.sameCodeMatches) }}</td><td>{{ auditCount(row.singleRowSameCodeMatches) }}</td><td>{{ auditCount(row.repeatedKeyMatchedTrades) }}</td></tr></tbody></table></div><p class="footnote">逐笔成交按主动方向选取叫买／叫卖序号，与两种原始委托编号分别做正编号字段交集；“同字母”仅比较 B/S 字段字符。重复键、多代码键会扩大歧义；即使单条键也未验证频道、事件顺序及订单生命周期，不能据此认定新增、撤单、补单、被动吸筹或母单身份。</p></template><p v-else class="footnote">此结果未保存编号关联审计；只读快照不补读最新原始数据。</p></details>
      <p class="footnote">{{ evidence.note || '关联分组不是已验证经济母单；委托类型未解码为补撤单。' }}</p>
    </template>
  </section>
</template>
