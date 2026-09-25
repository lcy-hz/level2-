<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { startState, stateView } from '../api.js'
import { filterContinuousStocks } from '../continuousFilters.js'
import KlineTrigger from './KlineTrigger.vue'
import StateEventPanel from './StateEventPanel.vue'

const props = defineProps({
  day: { type: String, required: true }, cards: { type: Array, required: true },
  frozen: { type: Boolean, default: false }, snapshotViews: { type: Object, default: () => ({}) },
  snapshotWindow: { type: Number, default: null },
  snapshotCharts: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['chart-loaded', 'state-loaded', 'view-applied'])
const windowDays = ref(props.snapshotWindow || 3)
const document = ref(props.frozen ? props.snapshotViews[String(windowDays.value)] || null : null)
const status = ref(props.frozen ? document.value ? '只读：展示保存时的连续状态' : '此快照未保存所选窗口的连续状态' : '选择交易日窗口后计算；不自动扫描原始 Level-2')
const pending = ref(false)
const query = ref('')
const change = ref('all')
const continuity = ref('all')
const coverage = ref('all')
const sort = ref('code')
const sortDirection = ref('asc')
const page = ref(1)
let sequence = 0
let timer = null
const view = computed(() => document.value?.view || document.value)
const names = computed(() => Object.fromEntries(props.cards.map(card => [card.code, card.name])))
const filtered = computed(() => filterContinuousStocks(view.value?.stocks || [], names.value, {
  query: query.value, change: change.value, continuity: continuity.value, coverage: coverage.value,
  sort: sort.value, direction: sortDirection.value,
}))
const shown = computed(() => filtered.value.slice((page.value - 1) * 20, page.value * 20))
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / 20)))
watch([query, change, continuity, coverage, sort, sortDirection], () => { page.value = 1 })
watch(pages, count => { if (page.value > count) page.value = count })
watch(view, current => {
  if (!current?.applicable) {
    change.value = 'all'
    if (['slope', 'improve'].includes(sort.value)) sort.value = 'code'
  }
})
const number = (value, unit = '%') => Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value !== 0 && Math.abs(value) < .005 ? value.toExponential(2) : value.toFixed(2)}${unit}` : '未知'
const money = value => Number.isFinite(value) ? `${(value / 1e8).toFixed(2)} 亿` : '未知'
const tone = value => !Number.isFinite(value) ? '' : value > 0 ? 'positive' : value < 0 ? 'negative' : ''
const label = { improve: '↑ 改善', worsen: '↓ 恶化', flat: '→ 持平', unknown: '— 未知' }
function resetFilter(value) { change.value = value; page.value = 1 }
const persistence = stock => stock.streak == null ? '未知' : `${stock.leftCensored ? '至少 ' : ''}${stock.streak} 日`
const improvement = stock => stock.expected <= 1 ? '不适用' : stock.improve == null ? '未知' : `${stock.improveCensored ? '至少 ' : ''}${stock.improve} 次`
const dailyDelta = stock => view.value?.applicable ? stock.viewDelta : stock.delta

async function apply() {
  const days = Number(windowDays.value)
  if (!Number.isInteger(days) || days < 1 || days > 60) { status.value = '窗口必须是 1 至 60 个交易日'; return }
  if (props.frozen) {
    document.value = props.snapshotViews[String(days)] || null
    status.value = document.value ? '只读：展示保存时的连续状态' : '此快照未保存该窗口；不读取最新数据补齐'
    emit('view-applied', { window: days, view: document.value?.view || document.value || null })
    return
  }
  const id = ++sequence
  clearTimeout(timer)
  pending.value = true
  status.value = `正在计算 ${days} 个交易日；${view.value ? '仍展示上次结果' : '暂无结果'}`
  try {
    await startState(props.day, days)
    await poll(id, days)
  } catch (error) {
    if (id === sequence) { pending.value = false; status.value = `计算失败：${error.message}；${view.value ? '仍展示上次结果' : '暂无结果'}` }
  }
}
async function poll(id, days) {
  if (id !== sequence) return
  const response = await stateView(props.day, days)
  if (id !== sequence) return
  if (response.status === 'done') {
    document.value = response
    pending.value = false
    page.value = 1
    status.value = `已计算 ${days} 个交易日；共同方向样本 ${response.view.common}/${response.view.total} 只`
    if (response.receipt) emit('state-loaded', { window: days, receipt: response.receipt })
    emit('view-applied', { window: days, view: response.view })
  } else if (response.status === 'queued' || response.status === 'running') {
    status.value = `${response.message}；${view.value ? '仍展示上次结果' : '暂无结果'}`
    timer = setTimeout(() => poll(id, days).catch(error => {
      if (id === sequence) { pending.value = false; status.value = `读取失败：${error.message}；仍保留上次结果` }
    }), 1500)
  } else {
    pending.value = false
    status.value = `${response.message || response.status}；${view.value ? '仍展示上次结果' : '暂无结果'}`
  }
}
onBeforeUnmount(() => { sequence++; clearTimeout(timer) })
</script>

<template>
  <section class="panel" aria-labelledby="continuous-title">
    <div class="section-heading"><div><span class="eyebrow">DAILY EVIDENCE</span><h2 id="continuous-title">连续观察</h2></div><span class="hint">水平、变化、持续性分开观察</span></div>
    <div class="state-controls"><label>回看交易日<input v-model.number="windowDays" type="number" min="1" max="60" step="1" /></label><button v-for="quick in [3,5,20]" :key="quick" @click="windowDays = quick">{{ quick }} 日</button><button class="primary" :disabled="pending" @click="apply">{{ frozen ? '查看已保存窗口' : pending ? '计算中…' : '应用观察窗口' }}</button></div>
    <p class="footnote" role="status">{{ status }}</p>
    <template v-if="view">
      <p class="footnote">{{ view.dates[0] || '未知' }} — {{ view.dates.at(-1) || '未知' }}；共同方向样本 {{ view.common }} / {{ view.total }} 只。重叠窗口不是独立确认，未知不补零。</p>
      <div class="state-days"><article v-for="day in view.trajectory" :key="day.day" class="subpanel"><strong>{{ day.day }}</strong><p>加权主动净额比 <b :class="tone(day.ratio)">{{ number(day.ratio) }}</b></p><p>净买入占比 {{ number(day.buyShare) }} · 成交额 {{ money(day.amount) }}</p><small>共同方向样本 {{ view.common }} 只 · 成交额覆盖 {{ day.amountCoverage }} 只</small></article></div>
      <div class="section-heading state-subheading"><div><h3>结构变化统计</h3><p class="footnote">{{ view.applicable ? view.dates.at(-2) + ' → ' + view.dates.at(-1) : '单日窗口无前一交易日' }}；有效比较 {{ view.applicable ? view.total - view.counts.unknown : 0 }} / {{ view.total }} 只。</p></div></div>
      <div v-if="view.applicable" class="state-counts"><button v-for="key in ['improve','worsen','flat','unknown']" :key="key" :class="{ active: change === key }" @click="resetFilter(key)"><span>{{ label[key] }}</span><strong>{{ view.counts[key].toLocaleString() }}</strong></button></div>
      <p v-if="view.applicable" class="footnote">净卖出转净买入 {{ view.counts.toBuy }} 只；净买入转净卖出 {{ view.counts.toSell }} 只。价格方向与资金变化独立判断。</p>
      <StateEventPanel :view="view" :names="names" :frozen="frozen" />
      <div class="state-list-head"><h3>个股逐日证据</h3><div class="state-stock-filters"><label>搜索<input v-model="query" placeholder="代码或名称" aria-label="连续状态股票搜索" /></label><label>资金变化<select v-model="change" :disabled="!view.applicable" aria-label="资金变化筛选"><option value="all">全部变化</option><option v-for="key in ['improve','worsen','flat','unknown']" :key="key" :value="key">{{ label[key] }}</option></select></label><label>连续性<select v-model="continuity" aria-label="连续性覆盖筛选"><option value="all">全部</option><option value="known">可判定</option><option value="unknown">未知</option></select></label><label>方向覆盖<select v-model="coverage" aria-label="方向覆盖筛选"><option value="all">全部</option><option value="full">窗口完整</option><option value="partial">部分或缺失</option></select></label><label>排序指标<select v-model="sort" aria-label="连续状态排序指标"><option value="code">股票代码</option><option value="level">当前净额比 %</option><option value="delta">较前日变化 pp</option><option value="weighted">窗口加权净额比 %</option><option value="slope" :disabled="!view.applicable">窗口斜率 pp/日</option><option value="streak">可观察同向日数</option><option value="improve" :disabled="!view.applicable">连续改善次数</option><option value="amount">最新成交额 元</option><option value="price">区间涨跌幅 %</option></select></label><label>方向<select v-model="sortDirection" aria-label="连续状态排序方向"><option value="asc">正序 · 小→大</option><option value="desc">倒序 · 大→小</option></select></label></div></div>
      <p class="footnote">已应用 {{ view.window }} 交易日（{{ view.dates[0] }}—{{ view.dates.at(-1) }}）· 匹配 {{ filtered.length }} 只 · 每页 20 只。排序只改变展示，未知始终排最后、同值按代码升序；左截断天数为可观察下界。极端净额比还需核对成交额与流动性，不是交易确认。</p>
      <div class="state-stocks"><article v-for="stock in shown" :key="stock.code" class="subpanel"><div class="state-stock-title"><strong>{{ names[stock.code] || '名称未知' }} <KlineTrigger :code="stock.code" :name="names[stock.code] || ''" :day="day" :frozen="frozen" :snapshot-charts="snapshotCharts" @loaded="emit('chart-loaded', $event)" /></strong><span>{{ view.applicable ? label[stock.change] : '单日观察' }}</span></div><p>区间价格 {{ number(stock.priceReturn) }} · 当前净额比 <b :class="tone(stock.level)">{{ number(stock.level) }}</b></p><p>{{ view.applicable ? '日变化' : '较窗口外前日' }} {{ number(dailyDelta(stock), ' pp') }} · 窗口加权 {{ number(stock.weighted) }}</p><p>窗口斜率 {{ view.window > 1 ? number(stock.slope, ' pp/日') : '不适用' }} · 连续改善 {{ improvement(stock) }}</p><small>方向有效 {{ stock.valid }}/{{ stock.expected }} 日 · 可观察同向 {{ persistence(stock) }}</small><details><summary>逐日证据</summary><p v-for="row in stock.history" :key="row.day">{{ row.day }} · 成交额 {{ money(row.amount) }} · 净额比 {{ number(row.ratio) }} · {{ row.reason || '方向记录可用' }}</p></details></article></div>
      <p v-if="!filtered.length" class="footnote">当前组合无匹配股票；可放宽筛选，未知值不会按 0 纳入排序。</p>
      <div class="pagination"><button :disabled="page <= 1" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page >= pages" @click="page++">下一页</button></div>
    </template>
  </section>
</template>
