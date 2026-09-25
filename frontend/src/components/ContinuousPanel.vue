<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { startState, stateView } from '../api.js'
import { filterContinuousStocks, parseAdvancedFilters } from '../continuousFilters.js'
import { flowNarrative, observedTransitions } from '../continuousEvidence.js'
import { requestGeneration } from '../interactionIdentity.js'
import { useEvidencePending } from '../evidencePending.js'
import KlineTrigger from './KlineTrigger.vue'
import StateEventPanel from './StateEventPanel.vue'

const props = defineProps({
  day: { type: String, required: true }, cards: { type: Array, required: true },
  frozen: { type: Boolean, default: false }, snapshotViews: { type: Object, default: () => ({}) },
  snapshotWindow: { type: Number, default: null },
  initialWindow: { type: Number, default: 3 }, maxWindow: { type: Number, default: 60 },
  snapshotCharts: { type: Object, default: () => ({}) },
  previousDay: { type: String, default: null }, nextDay: { type: String, default: null },
  initialUi: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['chart-loaded', 'state-loaded', 'view-applied', 'navigate-day', 'window-staged', 'ui-change'])
const windowDays = ref(props.snapshotWindow || props.initialWindow)
const document = ref(props.frozen ? props.snapshotViews[String(windowDays.value)] || null : null)
const status = ref(props.frozen ? document.value ? '只读：展示保存时的连续状态' : '此快照未保存所选窗口的连续状态' : '选择交易日窗口后计算；不自动扫描原始 Level-2')
const pending = ref(false)
const reading = ref(false)
useEvidencePending(computed(() => pending.value || reading.value))
const query = ref(props.initialUi.search || '')
const change = ref(props.initialUi.change || 'all')
const continuity = ref(props.initialUi.continuity || 'all')
const coverage = ref(props.initialUi.coverage || 'all')
const sort = ref(props.initialUi.sort || 'code')
const sortDirection = ref(props.initialUi.direction || 'asc')
const defaultAdvanced = () => ({ preset: 'all', price: 'all', amountMin: '', amountMax: '',
  levelSign: 'all', weightedSign: 'all', turn: 'all', volume: 'all',
  levelMin: '', levelMax: '', deltaMin: '', deltaMax: '', weightedMin: '', weightedMax: '',
  priceMin: '', priceMax: '', buyDays: '', sellDays: '', improveTimes: '', worsenTimes: '' })
const advancedRaw = ref({ ...defaultAdvanced(), ...(props.initialUi.advanced || {}) })
const advanced = computed(() => parseAdvancedFilters(advancedRaw.value))
const page = ref(props.initialUi.page || 1)
const requests = requestGeneration()
let timer = null
const view = computed(() => document.value?.view || document.value)
const names = computed(() => Object.fromEntries(props.cards.map(card => [card.code, card.name])))
const directionComplete = computed(() => (view.value?.stocks || []).filter(stock => stock.valid === stock.expected).length)
const filtered = computed(() => advanced.value.error ? [] : filterContinuousStocks(view.value?.stocks || [], names.value, {
  query: query.value, change: change.value, continuity: continuity.value, coverage: coverage.value,
  sort: sort.value, direction: sortDirection.value, advanced: advanced.value.filters,
}))
const shown = computed(() => filtered.value.slice((page.value - 1) * 20, page.value * 20))
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / 20)))
watch([query, change, continuity, coverage, sort, sortDirection, advancedRaw], () => { page.value = 1 }, { deep: true })
watch([query, change, continuity, coverage, sort, sortDirection, advancedRaw, page], () => {
  emit('ui-change', { search: query.value, change: change.value, continuity: continuity.value,
    coverage: coverage.value, sort: sort.value, direction: sortDirection.value,
    advanced: { ...advancedRaw.value }, page: page.value })
}, { deep: true })
watch(pages, count => { if (page.value > count) page.value = count })
watch(view, current => {
  if (!current?.applicable) {
    change.value = 'all'
    if (['slope', 'improve'].includes(sort.value)) sort.value = 'code'
  }
  if (sort.value === 'amountRelative' && (!current?.stocks?.some(stock => stock.amountRelativePct !== undefined) || current.window <= 1)) sort.value = 'code'
  if (['sizePeer', 'liquidityPeer'].includes(sort.value) && !current?.peers) sort.value = 'code'
})
const number = (value, unit = '%') => Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value !== 0 && Math.abs(value) < .005 ? value.toExponential(2) : value.toFixed(2)}${unit}` : '未知'
const share = value => Number.isFinite(value) ? `${value.toFixed(2)}%` : '不可比较'
const money = value => Number.isFinite(value) ? `${(value / 1e8).toFixed(2)} 亿` : '未知'
const tone = value => !Number.isFinite(value) ? '' : value > 0 ? 'positive' : value < 0 ? 'negative' : ''
const sourceLabel = { NATIVE: '原生已提交', LEGACY_CALIBRATED_ROW_GUARD: '旧来源逐条校准', LEGACY_DIRECTION_UNKNOWN: '旧来源方向未校准' }
const benchmarkStatus = { NOT_CONFIGURED: '未配置基准', MISSING_FILE: '基准文件缺失', INCOMPLETE_WINDOW: '交易日窗口不完整', INCOMPLETE_PRICES: '基准收盘数据不完整', INVALID_SCHEMA: '基准文件字段不符', DUPLICATE_DATE: '基准交易日重复', READ_ERROR: '基准文件读取失败' }
const peerStatus = { NOT_CONFIGURED: '未配置当日市值来源', MISSING_FILE: '当日市值文件缺失', INVALID_SCHEMA: '市值文件字段不符', INVALID_DATE: '市值文件混入其他日期', DUPLICATE_CODE: '市值文件代码重复', READ_ERROR: '市值文件读取失败' }
const persistenceText = (record, type) => record?.days == null ? '未知' : `${type === 'flow' ? record.side > 0 ? '净买入' : record.side < 0 ? '净卖出' : '净额为零' : record.side > 0 ? '过半' : record.side < 0 ? '不足半数' : '正好半数'} ${record.leftCensored ? '至少 ' : ''}${record.days} 日`
const improvementText = record => record?.comparisons == null ? '不适用' : `${record.leftCensored ? '至少 ' : ''}${record.comparisons} 次`
const label = { improve: '↑ 改善', worsen: '↓ 恶化', flat: '→ 持平', unknown: '— 未知' }
function resetFilter(value) { change.value = value; page.value = 1 }
function stageWindow(value) {
  // A staged window supersedes any in-flight read or calculation. The server job may
  // finish, but its response must never become the applied view for this selection.
  requests.invalidate()
  clearTimeout(timer)
  pending.value = false
  reading.value = false
  windowDays.value = value
  emit('window-staged', value)
  status.value = `待应用 ${value} 个交易日；${view.value ? `当前仍展示 ${view.value.window} 日结果` : '尚无已应用结果'}`
}
function clearFilters() {
  query.value = ''; change.value = 'all'; continuity.value = 'all'; coverage.value = 'all'
  advancedRaw.value = defaultAdvanced()
}
const persistence = stock => stock.streak == null ? '未知' : `${stock.leftCensored ? '至少 ' : ''}${stock.streak} 日`
const improvement = stock => stock.expected <= 1 ? '不适用' : stock.improve == null ? '未知' : `${stock.improveCensored ? '至少 ' : ''}${stock.improve} 次`
const dailyDelta = stock => view.value?.applicable ? stock.viewDelta : stock.delta
const relative = stock => !view.value?.benchmark ? '未保存' : view.value.benchmark.status !== 'AVAILABLE' ? '不可比较' : stock.relativeReturn === undefined ? '未保存' : number(stock.relativeReturn, ' pp')
const amountActivity = stock => stock.amountRelativePct === undefined ? '未保存' : stock.expected <= 1 ? '单日不适用' : stock.amountRelativePct === null ? '覆盖不足' : number(stock.amountRelativePct)
const minuteWindow = stock => {
  const item = stock.observedMinuteCloseDrawdown
  if (!item) return '未保存'
  if (item.status === 'MISSING_BASELINE') return '窗口前收盘缺失'
  if (item.status === 'INCOMPLETE_WINDOW') return '交易日窗口不足'
  if (item.status !== 'OBSERVED') return `证据不足${item.missingDays?.length ? `（缺 ${item.missingDays.join('、')}）` : ''}`
  const times = item.peakTime && item.troughTime ? `（${item.peakTime} → ${item.troughTime}）` : ''
  return `${number(item.valuePct)}${times} · 成交分钟 ${item.tradedMinutes}/${item.expectedMinutes}`
}
const peerText = (stock, prefix) => stock[`${prefix}Group`] === undefined ? '未保存' : stock[`${prefix}Group`] == null ? '无可比组' : `${stock[`${prefix}Group`]} / ${stock[`${prefix}GroupCount`]} 组 · 净额比组内百分位 ${share(stock[`${prefix}FlowPercentile`])}（有效 ${stock[`${prefix}PeerCount`]} 只）`

async function apply() {
  const days = Number(windowDays.value)
  if (!Number.isInteger(days) || days < 1 || days > props.maxWindow) { status.value = `窗口必须是 1 至 ${props.maxWindow} 个交易日`; return }
  if (props.frozen) {
    const saved = props.snapshotViews[String(days)]
    if (!saved) {
      status.value = `此快照未保存 ${days} 日窗口；${view.value ? `仍展示此前已应用的 ${view.value.window} 日结果` : '暂无可展示结果'}，不读取最新数据补齐`
      return
    }
    document.value = saved
    status.value = '只读：展示保存时的连续状态'
    emit('view-applied', { window: days, view: saved.view || saved })
    return
  }
  const id = requests.begin()
  clearTimeout(timer)
  pending.value = true
  status.value = `正在计算 ${days} 个交易日；${view.value ? '仍展示上次结果' : '暂无结果'}`
  try {
    await startState(props.day, days)
    await poll(id, days)
  } catch (error) {
    if (requests.accepts(id)) { pending.value = false; status.value = `计算失败：${error.message}；${view.value ? '仍展示上次结果' : '暂无结果'}` }
  }
}
async function poll(id, days) {
  if (!requests.accepts(id)) return
  const response = await stateView(props.day, days)
  if (!requests.accepts(id)) return
  if (response.status === 'done') {
    document.value = response
    pending.value = false
    reading.value = false
    page.value = 1
    status.value = `已计算 ${days} 个交易日；共同方向样本 ${response.view.common}/${response.view.total} 只`
    if (response.receipt) emit('state-loaded', { window: days, receipt: response.receipt })
    emit('view-applied', { window: days, view: response.view })
  } else if (response.status === 'queued' || response.status === 'running') {
    status.value = `${response.message}；${view.value ? '仍展示上次结果' : '暂无结果'}`
    timer = setTimeout(() => poll(id, days).catch(error => {
      if (requests.accepts(id)) { pending.value = false; reading.value = false; status.value = `读取失败：${error.message}；仍保留上次结果` }
    }), 1500)
  } else {
    pending.value = false
    reading.value = false
    status.value = `${response.message || response.status}；${view.value ? '仍展示上次结果' : '暂无结果'}`
  }
}
onMounted(() => {
  if (props.frozen) return
  // Reuse an already-calculated default window without starting a raw-data scan.
  status.value = `正在读取已有的 ${windowDays.value} 日连续状态；不会自动发起原始 Level-2 计算`
  reading.value = true
  const id = requests.begin()
  poll(id, Number(windowDays.value)).catch(error => {
    if (!requests.accepts(id)) return
    reading.value = false
    status.value = `已有状态读取失败：${error.message}；可手动应用观察窗口重试`
  })
})
onBeforeUnmount(() => { requests.invalidate(); clearTimeout(timer) })
</script>

<template>
  <section class="panel" aria-labelledby="continuous-title">
    <div class="section-heading"><div><span class="eyebrow">DAILY EVIDENCE</span><h2 id="continuous-title">连续观察</h2></div><span class="hint">水平、变化、持续性分开观察</span></div>
    <div class="state-controls"><button :disabled="frozen || !previousDay" :title="previousDay || '无前一交易日'" @click="emit('navigate-day', -1)">前一交易日</button><span>截止 {{ day }}</span><button :disabled="frozen || !nextDay" :title="nextDay || '无后一交易日'" @click="emit('navigate-day', 1)">后一交易日</button><label>回看交易日<input v-model.number="windowDays" type="number" min="1" :max="maxWindow" step="1" @input="stageWindow(windowDays)" /></label><button aria-label="减少一个交易日" :disabled="windowDays <= 1" @click="stageWindow(Math.max(1, Number(windowDays || 1) - 1))">−1</button><button aria-label="增加一个交易日" :disabled="windowDays >= maxWindow" @click="stageWindow(Math.min(maxWindow, Number(windowDays || 1) + 1))">+1</button><button v-for="quick in [3,5,20]" :key="quick" :disabled="quick > maxWindow" @click="stageWindow(quick)">{{ quick }} 日</button><button class="primary" :disabled="pending" @click="apply">{{ frozen ? '查看已保存窗口' : pending ? '计算中…' : '应用观察窗口' }}</button></div>
    <p class="footnote" role="status">{{ status }}</p>
    <template v-if="view">
      <p class="footnote">{{ view.dates[0] || '未知' }} — {{ view.dates.at(-1) || '未知' }}；共同方向样本 {{ view.common }} / {{ view.total }} 只。重叠窗口不是独立确认，未知不补零。</p>
      <div class="section-heading state-subheading"><div><h3>共同样本市场资金状态</h3><p class="footnote">仅描述主动方向与净买入股票占比，不等同于市场强弱或价格宽度。</p></div></div>
      <div v-if="view.marketState?.status === 'AVAILABLE'" class="market-state-strip"><article class="subpanel"><span>最新净额比</span><strong :class="tone(view.marketState.latestRatio)">{{ number(view.marketState.latestRatio) }}</strong><small>较前日 {{ view.window > 1 ? number(view.marketState.ratioDeltaPP, ' pp') : '窗口内不适用' }}</small></article><article class="subpanel"><span>净买入股票占比</span><strong>{{ share(view.marketState.latestBuyShare) }}</strong><small>较前日 {{ view.window > 1 ? number(view.marketState.buyShareDeltaPP, ' pp') : '窗口内不适用' }}</small></article><article class="subpanel"><span>窗口趋势</span><strong>{{ view.window > 1 ? number(view.marketState.ratioSlopePPPerDay, ' pp/日') : '不适用' }}</strong><small>净买入占比斜率 {{ view.window > 1 ? number(view.marketState.buyShareSlopePPPerDay, ' pp/日') : '不适用' }}</small></article><article class="subpanel"><span>可观察持续性</span><strong>{{ persistenceText(view.marketState.ratioPersistence, 'flow') }}</strong><small>净买入过半：{{ persistenceText(view.marketState.breadthPersistence, 'breadth') }} · 净额比连续改善 {{ improvementText(view.marketState.ratioImprovement) }}</small></article></div>
      <p v-else class="footnote">{{ !view.marketState ? frozen ? '此快照未保存市场状态向量；不以最新口径回填。' : '当前结果未包含市场状态向量，请重新计算。' : view.marketState.status === 'INCOMPLETE_WINDOW' ? '交易日窗口不完整，市场趋势不可比较。' : '没有全窗口方向有效的共同股票样本；市场资金状态不可比较。' }}</p>
      <div class="state-days"><article v-for="(day, index) in view.trajectory" :key="day.day" class="subpanel"><strong>{{ day.day }}</strong><p>共同样本加权净额比 <b :class="tone(day.ratio)">{{ number(day.ratio) }}</b><small> · {{ !index ? '窗口首日' : day.ratioDeltaPP === undefined ? '未保存' : number(day.ratioDeltaPP, ' pp') }}</small></p><p>净买入占比 {{ share(day.buyShare) }}<small> · {{ !index ? '窗口首日' : day.buyShareDeltaPP === undefined ? '未保存' : number(day.buyShareDeltaPP, ' pp') }}</small></p><p>共同样本净额 {{ day.commonNet === undefined ? '未保存' : money(day.commonNet) }} / 成交额 {{ day.commonAmount === undefined ? '未保存' : money(day.commonAmount) }}</p><small>全市场成交额 {{ money(day.amount) }} · 成交额覆盖 {{ day.amountCoverage }} 只 · 每日方向有效 {{ day.directionCoverage ?? '未保存' }} / {{ view.total }} 只 · 共同资金样本 {{ view.common }} 只</small><p v-if="view.priceState" class="price-breadth-line">共同价格样本：上涨 {{ share(day.priceUpShare) }} · 下跌 {{ share(day.priceDownShare) }} · 平盘 {{ share(day.priceFlatShare) }}<small> · 上涨较前日 {{ !index ? '窗口首日' : number(day.priceUpShareDeltaPP, ' pp') }}</small></p><small v-if="view.priceState">当日价格有效 {{ day.priceCoverage }} / {{ view.total }} 只 · 共同价格样本 {{ view.priceCommon }} 只</small><small class="market-source">成交来源：{{ sourceLabel[day.sourceStatus] || '来源状态未保存' }}<template v-if="view.priceState"> · 价格来源：{{ day.priceSourceStatus === 'FILE_PRESENT' ? '文件存在' : '文件缺失' }}</template></small><details class="market-source-detail"><summary>源文件</summary><small>逐笔成交</small><code>{{ day.sourceFile || '保存时未记录' }}</code><template v-if="view.priceState"><small>价格因子</small><code>{{ day.priceSourceFile || '文件缺失' }}</code></template></details></article></div>
      <p class="footnote">净额比的分子与分母仅来自窗口共同方向样本；全市场成交额按每天独立覆盖。原报告的全市场主动净额若因方向未知而不可计算，这里的共同样本净额不能替代它。每日方向有效数变化是覆盖变化，不自动解释为资金转向；不同来源校准口径也不能混用。</p>
      <div class="section-heading state-subheading"><div><h3>价格上涨宽度</h3><p class="footnote">与资金方向分开计算；价格样本须在窗口内每日都有可核对的前收盘基点。</p></div></div>
      <div v-if="view.priceState?.status === 'AVAILABLE'" class="market-state-strip price-state-strip"><article class="subpanel"><span>最新上涨占比</span><strong>{{ share(view.priceState.latestUpShare) }}</strong><small>较前日 {{ view.window > 1 ? number(view.priceState.upShareDeltaPP, ' pp') : '窗口内不适用' }}</small></article><article class="subpanel"><span>窗口上涨宽度斜率</span><strong>{{ view.window > 1 ? number(view.priceState.upShareSlopePPPerDay, ' pp/日') : '不适用' }}</strong><small>交易日位置线性斜率，非收益预测</small></article><article class="subpanel"><span>共同价格样本</span><strong>{{ view.priceCommon }} / {{ view.total }}</strong><small>独立于共同资金方向样本</small></article></div>
      <p v-else class="footnote">{{ !view.priceState ? frozen ? '此快照未保存价格宽度；不读取最新数据回填。' : '当前结果未包含价格宽度，请重新计算。' : view.priceState.status === 'INCOMPLETE_WINDOW' ? '交易日窗口不完整，价格宽度不可比较。' : '无全窗口价格有效的共同股票样本；价格宽度不可比较。' }}</p>
      <p class="footnote">价格日涨跌按本地 close×adj_factor 与前一交易日之比计算；最大收盘回撤从窗口前一交易日收盘起，沿窗口逐日收盘的历史峰值计算，0% 表示观察到的收盘价没有回撤，不含盘中低点。因子历史当时可得性尚未验证。上涨占比只在共同价格样本内计算，不是指数收益；与资金共同样本的分母可能不同，也不作吸筹或买卖确认。</p>
      <p class="footnote">窗口分钟收盘观察：{{ view.minuteSources ? `${view.minuteSources.filter(source => source.status === 'READY').length}/${view.window} 日来源就绪；${view.minuteObserved}/${view.total} 只具备逐日分钟证据` : '此快照未保存，不读取最新分钟文件' }}。仅按有成交分钟收盘价和复权因子计算；缺日不跨越，缺档可能低估实际盘中回撤，不等于可成交路径。</p>
      <div class="benchmark-evidence subpanel"><div><strong>相对基准 · {{ view.benchmark?.name || '未保存' }} <small>{{ view.benchmark?.code || '' }}</small></strong><p v-if="view.benchmark?.status === 'AVAILABLE'">{{ view.benchmark.baselineDay }} → {{ view.benchmark.endDay }} · 指数收盘收益 {{ number(view.benchmark.returnPct) }}；个股相对收益＝个股复权收盘收益－指数价格收益，单位 pp。</p><p v-else>{{ !view.benchmark ? frozen ? '此快照未保存基准比较；不读取最新数据回填。' : '当前结果未包含基准比较，请重新计算。' : benchmarkStatus[view.benchmark.status] || '基准不可比较' }}<template v-if="view.benchmark?.missing?.length"> · 缺失 {{ view.benchmark.missing.join('、') }}</template></p><small>{{ view.benchmark?.name || '所选基准' }}是可配置的价格指数比较尺，不是全市场统一适配基准；指数不含分红再投资，股票复权因子历史当时可得性未验证。</small></div><details v-if="view.benchmark?.source" class="market-source-detail"><summary>基准来源与口径</summary><code>{{ view.benchmark.source }}</code><small>{{ view.benchmark.method }}</small></details></div>
      <div class="benchmark-evidence subpanel"><div><strong>同日可比组 · 收盘后横截面</strong><p v-if="view.peers">市值组：{{ view.peers.status === 'AVAILABLE' ? `市值有效 ${view.peers.sizeCoverage} / ${view.peers.stockCount} 只` : peerStatus[view.peers.status] || '市值不可比较' }}；成交额组：有效 {{ view.peers.liquidityCoverage }} / {{ view.peers.stockCount }} 只。</p><p v-else>{{ frozen ? '此快照未保存同日可比组；不读取最新数据回填。' : '当前结果未包含同日可比组，请重新计算。' }}</p><small>按当日总市值和 Level-2 成交额分别等数量分组，组内仅对方向可靠股票排名；每组方向有效不足 20 只不出百分位。同日成交额分组受当日交易影响，指标只供收盘后描述，不能解释为行业中性、盘中信号或预测收益。</small></div><details v-if="view.peers?.source" class="market-source-detail"><summary>市值来源与口径</summary><code>{{ view.peers.source }}</code><small>{{ view.peers.scope }}；{{ view.peers.metric }}</small></details></div>
      <div class="section-heading state-subheading"><div><h3>结构变化统计</h3><p class="footnote">{{ view.applicable ? view.dates.at(-2) + ' → ' + view.dates.at(-1) : '单日窗口无前一交易日' }}；有效比较 {{ view.applicable ? view.total - view.counts.unknown : 0 }} / {{ view.total }} 只。</p></div></div>
      <div v-if="view.applicable" class="state-counts"><button v-for="key in ['improve','worsen','flat','unknown']" :key="key" :class="{ active: change === key }" @click="resetFilter(key)"><span>{{ label[key] }}</span><strong>{{ view.counts[key].toLocaleString() }}</strong></button></div>
      <p v-if="view.applicable" class="footnote">净卖出转净买入 {{ view.counts.toBuy }} 只；净买入转净卖出 {{ view.counts.toSell }} 只。价格方向与资金变化独立判断。</p>
      <StateEventPanel :view="view" :names="names" :frozen="frozen" />
      <div class="state-list-head"><h3>个股逐日证据</h3><div class="state-stock-filters"><label>搜索<input v-model="query" placeholder="代码或名称" aria-label="连续状态股票搜索" /></label><label>资金变化<select v-model="change" :disabled="!view.applicable" aria-label="资金变化筛选"><option value="all">全部变化</option><option v-for="key in ['improve','worsen','flat','unknown']" :key="key" :value="key">{{ label[key] }}</option></select></label><label>连续性<select v-model="continuity" aria-label="连续性覆盖筛选"><option value="all">全部</option><option value="known">可判定</option><option value="unknown">未知</option></select></label><label>方向覆盖<select v-model="coverage" aria-label="方向覆盖筛选"><option value="all">全部</option><option value="full">窗口完整</option><option value="partial">部分或缺失</option><option value="unknown">当前方向未知</option></select></label><label>排序指标<select v-model="sort" aria-label="连续状态排序指标"><option value="code">股票代码</option><option value="level">当前净额比 %</option><option value="delta">较前日变化 pp</option><option value="weighted">窗口加权净额比 %</option><option value="slope" :disabled="!view.applicable">窗口斜率 pp/日</option><option value="streak">可观察同向日数</option><option value="improve" :disabled="!view.applicable">连续改善次数</option><option value="amount">最新成交额 元</option><option value="amountRelative" :disabled="view.window <= 1 || !view.stocks?.some(stock => stock.amountRelativePct !== undefined)">最新成交额相对窗口前段 %</option><option value="sizePeer" :disabled="!view.peers || view.peers.status !== 'AVAILABLE'">市值组净额比分位</option><option value="liquidityPeer" :disabled="!view.peers">成交额组净额比分位</option><option value="price">区间涨跌幅 %</option><option value="drawdown">窗口最大收盘回撤 %</option><option value="minuteDrawdown" :disabled="!view.minuteObserved">窗口已观测分钟收盘回撤 %</option><option value="relative" :disabled="view.benchmark?.status !== 'AVAILABLE'">相对基准收益 pp</option></select></label><label>方向<select v-model="sortDirection" aria-label="连续状态排序方向"><option value="asc">正序 · 小→大</option><option value="desc">倒序 · 大→小</option></select></label></div></div>
      <div class="advanced-filters subpanel"><div class="state-stock-filters"><label>组合预设<select v-model="advancedRaw.preset"><option value="all">不限</option><option value="relief">卖压减轻</option><option value="buyStrong">买方增强</option><option value="buyWeak">买方减弱</option><option value="sellStrong">卖方增强</option><option value="upSell">价涨 · 窗口净卖出</option><option value="downBuy">价跌 · 窗口净买入</option></select></label><label>区间价格方向<select v-model="advancedRaw.price"><option value="all">不限</option><option value="positive">上涨</option><option value="negative">下跌</option><option value="zero">平盘</option></select></label><label>当日成交额下限（亿）<input v-model="advancedRaw.amountMin" type="number" min="0" step="any" placeholder="不限" /></label><label>当日成交额上限（亿）<input v-model="advancedRaw.amountMax" type="number" min="0" step="any" placeholder="不限" /></label></div><details><summary>高级筛选 · 资金范围与持续性</summary><div class="state-stock-filters"><label>当前主动方向<select v-model="advancedRaw.levelSign"><option value="all">不限</option><option value="positive">净买入</option><option value="negative">净卖出</option><option value="zero">净额为零</option></select></label><label>窗口加权方向<select v-model="advancedRaw.weightedSign"><option value="all">不限</option><option value="positive">净买入</option><option value="negative">净卖出</option><option value="zero">净额为零</option></select></label><label>相邻两日方向转换<select v-model="advancedRaw.turn" :disabled="!view.applicable"><option value="all">不限</option><option value="toBuy">卖转买</option><option value="toSell">买转卖</option><option value="buy">持续买</option><option value="sell">持续卖</option></select></label><label>成交额较前日<select v-model="advancedRaw.volume"><option value="all">不限</option><option value="positive">放量</option><option value="negative">缩量</option><option value="zero">持平</option></select></label><template v-for="field in [['level','当前净额比（%）'],['delta','日变化（百分点）'],['weighted','窗口加权净额比（%）'],['price','区间涨跌幅（%）']]" :key="field[0]"><label>{{ field[1] }}下限<input v-model="advancedRaw[`${field[0]}Min`]" type="number" step="any" placeholder="不限" /></label><label>{{ field[1] }}上限<input v-model="advancedRaw[`${field[0]}Max`]" type="number" step="any" placeholder="不限" /></label></template><label>连续净买入至少几日<input v-model="advancedRaw.buyDays" type="number" min="1" step="1" placeholder="不限" /></label><label>连续净卖出至少几日<input v-model="advancedRaw.sellDays" type="number" min="1" step="1" placeholder="不限" /></label><label>连续改善至少几次<input v-model="advancedRaw.improveTimes" type="number" min="1" step="1" placeholder="不限" /></label><label>连续恶化至少几次<input v-model="advancedRaw.worsenTimes" type="number" min="1" step="1" placeholder="不限" /></label></div></details><p class="footnote" role="status">{{ advanced.error || '条件同时满足；未知值不通过数值筛选。' }}</p><button type="button" @click="clearFilters">清空全部筛选</button></div>
      <p class="footnote">已应用 {{ view.window }} 交易日（{{ view.dates[0] }}—{{ view.dates.at(-1) }}）· 匹配 {{ filtered.length }} 只 · 每页 20 只。成交活跃度＝最新日成交额 ÷ 窗口内此前 {{ Math.max(0, view.window - 1) }} 个交易日平均成交额－1；此前任一天缺成交额即不可比较。排序只改变展示，未知始终排最后、同值按代码升序；左截断天数为可观察下界。极端净额比还需核对成交额与流动性，不是交易确认。</p>
      <div class="state-stocks"><article v-for="stock in shown" :key="stock.code" class="subpanel"><div class="state-stock-title"><strong>{{ names[stock.code] || '名称未知' }} <KlineTrigger :code="stock.code" :name="names[stock.code] || ''" :day="day" :frozen="frozen" :snapshot-charts="snapshotCharts" @loaded="emit('chart-loaded', $event)" /></strong><span>{{ view.applicable ? label[stock.change] : '单日观察' }}</span></div><p>区间价格 {{ number(stock.priceReturn) }} · 最大收盘回撤 {{ stock.maxCloseDrawdown === undefined ? "未保存" : number(stock.maxCloseDrawdown) }}<small v-if="stock.drawdownPeakDay && stock.drawdownTroughDay">（{{ stock.drawdownPeakDay }} → {{ stock.drawdownTroughDay }}）</small></p><p>窗口分钟收盘回撤 {{ minuteWindow(stock) }}</p><p>相对{{ view.benchmark?.name || '基准' }} {{ relative(stock) }}</p><p>当前净额比 <b :class="tone(stock.level)">{{ number(stock.level) }}</b></p><p>{{ view.applicable ? '日变化' : '较窗口外前日' }} {{ number(dailyDelta(stock), ' pp') }} · 窗口加权 {{ number(stock.weighted) }}</p><p class="footnote">{{ flowNarrative(stock, view.applicable) }}</p><p>成交活跃度 {{ amountActivity(stock) }}<small v-if="stock.amountPriorMean != null"> · 前 {{ stock.expected - 1 }} 日均 {{ money(stock.amountPriorMean) }}</small><small v-else-if="stock.amountValid !== undefined"> · 成交额有效 {{ stock.amountValid }}/{{ stock.expected }} 日</small></p><p>市值 {{ stock.totalMv === undefined ? '未保存' : stock.totalMv == null ? '未知' : `${(stock.totalMv / 10000).toFixed(2)} 亿` }} · 市值组 {{ peerText(stock, 'size') }}</p><p>成交额组 {{ peerText(stock, 'liquidity') }}</p><p>窗口斜率 {{ view.window > 1 ? number(stock.slope, ' pp/日') : '不适用' }} · {{ observedTransitions(stock) }}</p><small>方向有效 {{ stock.valid }}/{{ stock.expected }} 日 · 成交额有效 {{ stock.amountValid ?? '未知' }}/{{ stock.expected }} 日 · 可观察同向 {{ persistence(stock) }}</small><details><summary>逐日证据</summary><p v-for="row in stock.history" :key="row.day">{{ row.day }} · 日涨跌 {{ view.priceState ? number(row.priceDailyReturn) : '未保存' }} · 成交额 {{ money(row.amount) }} · 净额比 {{ number(row.ratio) }} · {{ row.reason || '方向记录可用' }}</p></details></article></div>
      <p v-if="!filtered.length" class="footnote">当前组合无匹配股票；可放宽筛选，未知值不会按 0 纳入排序。</p>
      <div class="pagination"><button :disabled="page <= 1" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page >= pages" @click="page++">下一页</button></div>
      <p class="footnote">覆盖说明：{{ view.total }} 只股票中，方向窗口完整 {{ directionComplete }} 只；其余 {{ view.total - directionComplete }} 只不足或方向未知。价格和成交额按各自覆盖独立展示。</p>
      <details class="market-source-detail"><summary>详细计算口径与来源</summary><p>净额比＝共同方向样本主动净额合计 ÷ 同样本成交额合计；{{ view.method || '此结果未保存方法标识' }}。相邻日变化按原始精度比较，极小值不补零；持续次数被窗口左边界截断时显示“至少”。股票缺日、方向未知与价格缺失分别保留。</p><p>逐日源文件和方向校准状态见上方“市场资金状态”的源文件；价格取前复权收盘，历史当时可得性未验证。</p><p v-if="!document?.sources?.length">此结果未保存完整来源清单；不从当前文件回填。</p><p v-for="source in document?.sources || []" :key="`${source.day}-${source.source}`">{{ source.day }} · {{ sourceLabel[source.status] || source.status || '状态未知' }} · 成交 {{ source.source || '路径未知' }} · 价格 {{ source.priceSource || '路径未知' }}</p></details>
    </template>
  </section>
</template>
