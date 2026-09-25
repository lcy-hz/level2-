<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useEvidencePending } from '../evidencePending.js'
import { patternMeta, patternStatus, startPatterns } from '../api.js'
import { defaultPatternFilters, filterPatterns } from '../patternFilters.js'
import KlineTrigger from './KlineTrigger.vue'
import PatternDetail from './PatternDetail.vue'

const props = defineProps({ day: { type: String, required: true }, frozen: { type: Boolean, default: false },
  snapshotPatterns: { type: Object, default: null }, snapshotCharts: { type: Object, default: () => ({}) },
  initialUi: { type: Object, default: () => ({}) }, levels: { type: Object, default: () => ({}) },
  stateWindow: { type: Number, default: null } })
const emit = defineEmits(['chart-loaded', 'pattern-loaded', 'detail-loaded', 'ui-change'])
const result = ref(props.frozen ? props.snapshotPatterns?.result || null : null)
const catalog = ref(result.value?.catalog || [])
const receipt = ref('')
const status = ref(props.frozen ? result.value ? '只读：展示快照内已冻结的形态结果' : '此快照未保存形态扫描，不读取最新数据' : '尚未计算形态；可按需读取本地前复权日 K 与指标')
const pending = ref(false)
const reading = ref(false)
useEvidencePending(computed(() => pending.value || reading.value))
const ui = reactive({ ...defaultPatternFilters, ...props.initialUi, types: [...(props.initialUi.types || [])] })
const selected = ref(null)
const loadedCodes = ref([])
let sequence = 0, timer = null
const groups = computed(() => [...new Set(catalog.value.map(item => item.family))])
const filtered = computed(() => filterPatterns(result.value, ui, props.levels))
const rows = computed(() => filtered.value.rows)
const pages = computed(() => Math.max(1, Math.ceil(rows.value.length / 20)))
const shown = computed(() => rows.value.slice((ui.page - 1) * 20, ui.page * 20))
const fmt = (value, unit = '') => Number.isFinite(value) ? `${value.toFixed(2)}${unit}` : '未知'
const money = value => Number.isFinite(value) ? `${(value / 1e8).toFixed(2)} 亿` : '未知'
const stageName = stage => ({ forming: '○ 形成中', confirmed: '▲ 规则确认', invalidated: '× 已失效' })[stage] || stage
const qualityName = value => ({ anomaly: '数据异常', insufficient: '历史不足', available: '可评估' })[value] || '未知'
function changed() { ui.page = 1 }
function clear() { Object.assign(ui, { ...defaultPatternFilters, types: [] }) }
watch(ui, () => emit('ui-change', JSON.parse(JSON.stringify(ui))), { deep: true })
watch(() => props.initialUi, initial => {
  Object.assign(ui, { ...defaultPatternFilters, ...(initial || {}), types: [...(initial?.types || [])] })
}, { immediate: true })
watch(pages, count => { if (ui.page > count) ui.page = count })
function apply(response, id) {
  if (id !== sequence) return
  if (response.status === 'done') {
    if (!response.result) { poll(id); return }
    if (response.result.day !== props.day) { status.value = '形态结果日期与报告不一致'; pending.value = false; reading.value = false; return }
    result.value = response.result
    catalog.value = response.result.catalog
    receipt.value = response.receipt
    pending.value = false
    reading.value = false
    ui.page = 1
    status.value = `${response.result.stocks.length} 只股票 · ${response.result.dates.length} 个交易日 · 形态计算完成；未经收益校准`
    emit('pattern-loaded', response.receipt)
  } else if (['queued', 'running'].includes(response.status)) {
    status.value = response.message || '形态计算中…'
    timer = setTimeout(() => poll(id), 1500)
  } else {
    pending.value = false
    reading.value = false
    status.value = `${response.message || response.status}；无可用的当前结果`
  }
}
async function poll(id) {
  if (id !== sequence) return
  try { apply(await patternStatus(props.day), id) }
  catch (error) { if (id === sequence) { pending.value = false; reading.value = false; status.value = `读取失败：${error.message}` } }
}
async function start() {
  if (props.frozen || pending.value) return
  clearTimeout(timer)
  const id = ++sequence
  result.value = null
  receipt.value = ''
  pending.value = true
  status.value = '正在提交本地形态扫描…'
  try { apply(await startPatterns(props.day), id) }
  catch (error) { if (id === sequence) { pending.value = false; status.value = `计算失败：${error.message}` } }
}
function open(stock, event) { selected.value = { stock, event } }
function captureDetail(code) {
  if (!loadedCodes.value.includes(code) && loadedCodes.value.length < 200) loadedCodes.value = [...loadedCodes.value, code]
  emit('detail-loaded', code)
}
onMounted(async () => {
  if (props.frozen) return
  reading.value = true
  const id = ++sequence
  try { const meta = await patternMeta(); if (id === sequence) catalog.value = meta.catalog }
  catch (error) { if (id === sequence) status.value = `读取形态规则失败：${error.message}` }
  await poll(id)
})
onBeforeUnmount(() => { sequence++; clearTimeout(timer) })
</script>

<template>
  <section class="panel pattern-panel" aria-labelledby="patterns-title">
    <div class="section-heading"><div><span class="eyebrow">PRICE PATTERN RESEARCH</span><h2 id="patterns-title">个股形态筛选</h2></div><span class="hint">{{ day }} · qfq 前复权日 K · 非交易确认</span></div>
    <p class="footnote">价格形态、技术指标与 Level‑2 资金证据独立观察。22 类固定研究规则尚未经收益校准，不提供胜率或自动买卖点。</p>
    <div class="pattern-toolbar"><button v-if="!frozen" type="button" :disabled="pending" @click="start">{{ pending ? '计算中…' : '计算／刷新形态' }}</button><span role="status">{{ status }}</span></div>
    <template v-if="result">
      <p class="footnote">覆盖 {{ result.stocks.length }} 只 · 缺个股文件 {{ result.missingFiles.length }} 只 · 历史不足 {{ result.stocks.filter(stock => stock.quality === 'insufficient').length }} 只 · 异常 {{ result.stocks.filter(stock => stock.quality === 'anomaly').length }} 只。</p>
      <div class="pattern-filters"><label>名称／代码<input v-model="ui.search" @input="changed" placeholder="搜索股票" /></label><label>阶段<select v-model="ui.stage" @change="changed"><option value="active">形成中＋规则确认</option><option value="all">所有事件（含历史）</option><option value="forming">形成中</option><option value="confirmed">规则确认</option><option value="invalidated">已失效</option></select></label><label>方向<select v-model="ui.direction" @change="changed"><option value="all">全部</option><option value="bull">看涨结构</option><option value="bear">看跌结构</option><option value="neutral">中性整理</option></select></label><label>可评估性<select v-model="ui.quality" @change="changed"><option value="all">有匹配事件</option><option value="available">有可评估形态</option><option value="insufficient">所选形态历史不足</option><option value="anomaly">数据异常</option><option value="none">可评估但未识别</option></select></label><label>排序<select v-model="ui.sort" @change="changed"><option value="detected">最近识别</option><option value="amount">成交额</option><option value="name">代码</option></select></label><button type="button" @click="clear">清空筛选</button></div>
      <details class="pattern-options"><summary>选择形态（默认全部，可多选）</summary><div v-for="family in groups" :key="family"><strong>{{ family }}：</strong><label v-for="item in catalog.filter(row => row.family === family)" :key="item.id"><input v-model="ui.types" type="checkbox" :value="item.id" @change="changed" /> {{ item.name }}</label></div><label>多形态关系<select v-model="ui.combination" @change="changed"><option value="any">任一满足</option><option value="every">全部共存</option></select></label></details>
      <details class="pattern-options"><summary>高级筛选 · 时效／量能／技术指标／资金</summary><div class="pattern-filters"><label>时间字段<select v-model="ui.timeField" @change="changed"><option value="detected">首次识别</option><option value="confirmed">规则确认</option><option value="invalidated">首次失效</option></select></label><label>最近交易日<input v-model="ui.age" type="number" min="0" step="1" placeholder="不限" @input="changed" /></label><label>成交额至少（亿）<input v-model="ui.amount" type="number" min="0" placeholder="不限" @input="changed" /></label><label>量／事前20日均量至少<input v-model="ui.vol" type="number" min="0" placeholder="不限" @input="changed" /></label><label>突破位距离下限（%）<input v-model="ui.distanceMin" type="number" placeholder="不限" @input="changed" /></label><label>突破位距离上限（%）<input v-model="ui.distanceMax" type="number" placeholder="不限" @input="changed" /></label><label>MA20条件<select v-model="ui.ma" @change="changed"><option value="all">不限</option><option value="above">收盘高于 MA20</option><option value="below">收盘低于 MA20</option></select></label><label>MACD柱<select v-model="ui.macd" @change="changed"><option value="all">不限</option><option value="positive">正</option><option value="negative">负</option></select></label><label>Level‑2 当前净额<select v-model="ui.l2" @change="changed"><option value="all">不限</option><option value="positive">正</option><option value="negative">负</option><option value="unknown">未知</option></select></label></div><p class="footnote">Level‑2 仅用当前页面已应用、同截止日的观察窗口；未计算时为未知。不是形态信号当日资金。</p></details>
      <p class="footnote" role="status">{{ filtered.error || `匹配 ${rows.length}/${result.stocks.length} 只 · ${rows.reduce((count, row) => count + row.events.length, 0)} 条事件 · 资金窗口 ${stateWindow ?? '未应用'} · 每页 20 只` }}</p>
      <div class="table-scroll"><table class="pattern-table"><thead><tr><th>股票</th><th>形态／阶段</th><th>识别日</th><th>位置／量能</th><th>指标／资金</th></tr></thead><tbody><tr v-for="row in shown" :key="row.stock.code"><td><strong>{{ row.stock.name }}</strong><br /><KlineTrigger :code="row.stock.code" :name="row.stock.name" :day="day" :frozen="frozen" :snapshot-charts="snapshotCharts" @loaded="emit('chart-loaded', $event)" /></td><td><template v-if="row.events.length"><button v-for="event in row.events.slice(0, 2)" :key="event.eventId" class="pattern-event" @click="open(row.stock, event)">{{ event.name }} · {{ stageName(event.stage) }}{{ event.lifecycleUnknown ? ' · 连续性未知' : !event.active ? ' · 历史' : '' }}</button><button v-if="row.events.length > 2" class="pattern-event" @click="open(row.stock, row.events[0])">＋{{ row.events.length - 2 }} 条</button></template><span v-else>{{ qualityName(row.stock.quality) }} · 未识别</span></td><td>{{ row.events[0]?.detectedDate || '—' }}</td><td>突破位 {{ fmt(row.events[0]?.distance, '%') }}<br />量比 {{ fmt(row.stock.volumeRatio, ' 倍') }}</td><td>RSI6 {{ fmt(row.stock.indicators?.rsi_qfq_6) }}<br />净额比 {{ fmt(levels[row.stock.code], '%') }}</td></tr><tr v-if="!rows.length"><td colspan="5">{{ filtered.error || '无匹配结果；可切换可评估性查看历史不足或异常。' }}</td></tr></tbody></table></div>
      <div class="pagination"><button :disabled="ui.page <= 1" @click="ui.page--">上一页</button><span>{{ ui.page }} / {{ pages }}</span><button :disabled="ui.page >= pages" @click="ui.page++">下一页</button></div>
      <details class="footnote"><summary>规则参数、字段口径与研究边界</summary><pre>{{ JSON.stringify(result.rules, null, 2) }}\n{{ result.indicatorMethod }}\n{{ result.scope }}</pre></details>
    </template>
    <PatternDetail v-if="selected" :key="selected.stock.code" :day="day" :stock="selected.stock" :initial-event="selected.event" :receipt="receipt" :frozen="frozen" :snapshot-details="snapshotPatterns?.details || {}" :indicator-method="result?.indicatorMethod || ''" :level="levels[selected.stock.code]" :state-window="stateWindow" @detail-loaded="captureDetail" @close="selected = null" />
  </section>
</template>
