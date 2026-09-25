<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { dates, report, saveSnapshot, snapshot, snapshots } from './api.js'
import MarketTimeline from './components/MarketTimeline.vue'
import QualitySummary from './components/QualitySummary.vue'
import CandidatePanel from './components/CandidatePanel.vue'
import ContinuousPanel from './components/ContinuousPanel.vue'
import PatternPanel from './components/PatternPanel.vue'
import ValidationPanel from './components/ValidationPanel.vue'

const params = new URLSearchParams(location.search)
const selectedDay = ref(params.get('date') || '20260922')
const snapshotId = ref(params.get('snapshot') || '')
const dateRows = ref([])
const saved = ref([])
const document = ref(null)
const busy = ref(false)
const error = ref('')
const saving = ref(false)
const saveMessage = ref('')
const savedId = ref('')
const chartReceipts = ref({})
const stateReceipts = ref({})
const loadedDetails = ref({})
const stateWindow = ref(null)
const filters = ref({ search: '', filter: 'all', direction: 'all', sort: 'default' })
const activeTab = ref('review')
const activeStateView = ref(null)
const patternReceipt = ref('')
const patternCodes = ref([])
const patternUI = ref({ tab: 'review' })
const validationReceipt = ref('')
const validationCodes = ref([])
let request = 0

const current = computed(() => document.value?.report?.markets?.at(-1) || null)
const sourceStatus = computed(() => dateRows.value.find(row => row.day === selectedDay.value))
const legacyUrl = computed(() => `${location.port === '5173' ? 'http://127.0.0.1:18762' : ''}/level2-market-scan_20260922.html?${snapshotId.value ? 'snapshot=' + encodeURIComponent(snapshotId.value) : 'date=' + encodeURIComponent(selectedDay.value)}`)
const money = value => value == null ? '未知' : `${(value / 1e8).toFixed(2)} 亿`
const stateLevels = computed(() => Object.fromEntries((activeStateView.value?.stocks || []).map(stock => [stock.code, stock.level])))
watch(activeTab, tab => { patternUI.value = { ...patternUI.value, tab } })

async function load() {
  const id = ++request
  busy.value = true
  error.value = ''
  document.value = null
  try {
    const result = snapshotId.value ? await snapshot(snapshotId.value) : await report(selectedDay.value)
    if (id !== request) return
    document.value = result
    selectedDay.value = result.day
    chartReceipts.value = {}
    stateReceipts.value = {}
    loadedDetails.value = {}
    stateWindow.value = result.mode === 'snapshot' ? result.stateWindow ?? null : null
    activeStateView.value = result.mode === 'snapshot' && result.stateWindow != null ? result.stateViews?.[String(result.stateWindow)] || null : null
    filters.value = { search: '', filter: 'all', direction: 'all', sort: 'default', ...(result.filters || {}) }
    activeTab.value = ['patterns', 'validation'].includes(result.patternUI?.tab) ? result.patternUI.tab : 'review'
    patternUI.value = { ...(result.patternUI || {}), tab: activeTab.value }
    patternReceipt.value = ''
    patternCodes.value = []
    validationReceipt.value = ''
    validationCodes.value = []
    saveMessage.value = ''
    savedId.value = ''
  } catch (cause) {
    if (id === request) error.value = cause.message
  } finally {
    if (id === request) busy.value = false
  }
}

function chooseDay() {
  snapshotId.value = ''
  history.replaceState(null, '', `/?date=${encodeURIComponent(selectedDay.value)}`)
  load()
}

function chooseSnapshot(event) {
  snapshotId.value = event.target.value
  if (!snapshotId.value) return chooseDay()
  history.replaceState(null, '', `/?snapshot=${encodeURIComponent(snapshotId.value)}`)
  load()
}

function captureChart({ key, receipt }) { chartReceipts.value = { ...chartReceipts.value, [key]: receipt } }
function captureState({ window, receipt }) {
  stateReceipts.value = { ...stateReceipts.value, [String(window)]: receipt }
  stateWindow.value = window
}
function captureAppliedState({ window, view }) {
  activeStateView.value = view
  stateWindow.value = view ? window : null
}
function captureDetail(result) { loadedDetails.value = { ...loadedDetails.value, [result.code]: result } }
function capturePattern(receipt) { patternReceipt.value = receipt; patternCodes.value = [] }
function capturePatternDetail(code) { if (!patternCodes.value.includes(code) && patternCodes.value.length < 200) patternCodes.value = [...patternCodes.value, code] }
function capturePatternUI(ui) { patternUI.value = { ...ui, tab: activeTab.value } }
function captureValidation({ receipt }) { validationReceipt.value = receipt; validationCodes.value = [] }
function captureValidationDetail(code) { if (!validationCodes.value.includes(code) && validationCodes.value.length < 50) validationCodes.value = [...validationCodes.value, code] }
async function save() {
  if (!document.value || document.value.mode === 'snapshot' || saving.value) return
  saving.value = true
  saveMessage.value = '正在冻结当前已读取的证据；未加载的图表、深查和窗口不会补算…'
  try {
    // The API payload is JSON; serializing removes Vue's reactive proxies before freezing it.
    const data = JSON.parse(JSON.stringify(document.value.report))
    for (const card of data.cards) {
      const result = loadedDetails.value[card.code]
      if (!result) continue
      for (const key of ['segments', 'parents', 'orders', 'regularCoverage']) card[key] = result[key]
      card.computedDetail = true
      card.detailEvidence = result
    }
    const savedSnapshot = await saveSnapshot({ day: document.value.day, data, charts: chartReceipts.value,
      states: stateReceipts.value, stateWindow: stateWindow.value, filters: filters.value,
      patternReceipt: patternReceipt.value || null, patternCharts: patternCodes.value, patternUI: patternUI.value,
      validationReceipt: validationReceipt.value || null, validationDetails: validationCodes.value })
    savedId.value = savedSnapshot.id
    saveMessage.value = `已保存 ${savedSnapshot.day} 快照：${savedSnapshot.chartCount} 个图表、${Object.keys(loadedDetails.value).length} 只已加载深查、${Object.keys(stateReceipts.value).length} 个连续窗口、${patternReceipt.value ? '形态结果及' + patternCodes.value.length + '张逐根图' : '无形态结果'}、${validationReceipt.value ? '后续研究及' + validationCodes.value.length + '只逐股证据' : '无后续研究'}。`
    try { saved.value = await snapshots() } catch { /* 快照已提交，列表刷新失败不撤销成功状态 */ }
  } catch (cause) { saveMessage.value = `保存失败：${cause.message}` }
  finally { saving.value = false }
}
function openSaved() {
  if (!savedId.value) return
  snapshotId.value = savedId.value
  history.replaceState(null, '', `/?snapshot=${encodeURIComponent(savedId.value)}`)
  load()
}

onMounted(async () => {
  const [dateList, snapshotList] = await Promise.allSettled([dates(), snapshots()])
  if (dateList.status === 'fulfilled') dateRows.value = dateList.value
  if (snapshotList.status === 'fulfilled') saved.value = snapshotList.value
  await load()
})
</script>

<template>
  <main class="shell">
    <header class="hero">
      <div class="hero-copy"><span class="eyebrow">RESEARCH_ONLY · 本地 Level-2</span><h1>连续市场与个股证据</h1><p>同一份 Python 报告数据，分离成可核验的服务接口与交互页面。</p></div>
      <div class="hero-meta"><span>当前证据日</span><strong>{{ document?.day || selectedDay }}</strong><small>{{ snapshotId ? '只读快照 · 不补读最新数据' : '本地报告 · 非实时行情' }}</small></div>
    </header>

    <nav class="toolbar" aria-label="报告选择">
      <label>报告日期<select v-model="selectedDay" :disabled="Boolean(snapshotId)" @change="chooseDay"><option v-if="snapshotId || !dateRows.length" :value="selectedDay">{{ selectedDay }}{{ snapshotId ? ' · 快照证据日' : '' }}</option><option v-if="!snapshotId" v-for="row in dateRows" :key="row.day" :value="row.day">{{ row.day }} · {{ row.status === 'ready' ? '可查看' : row.status === 'stale' ? '待更新' : '待计算' }}</option></select></label>
      <label>历史快照<select :value="snapshotId" @change="chooseSnapshot"><option value="">最新数据</option><option v-for="item in saved" :key="item.id" :value="item.id">{{ item.day }} · {{ new Date(item.savedAt).toLocaleString() }}</option></select></label>
      <a :href="legacyUrl" class="legacy-link">打开完整旧页面 ↗</a>
      <button v-if="document?.mode === 'live'" class="save-button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存当前证据快照' }}</button>
    </nav>
    <p v-if="saveMessage" class="snapshot-message" role="status">{{ saveMessage }} <button v-if="savedId" @click="openSaved">查看快照</button></p>

    <div v-if="busy" class="notice" role="status">正在读取报告数据…</div>
    <div v-else-if="error" class="notice error" role="alert">
      <strong>当前数据不可展示</strong><p>{{ error }}</p><p v-if="sourceStatus">{{ sourceStatus.message }}</p>
      <button @click="load">重试读取</button>
    </div>
    <template v-else-if="document">
      <p class="scope">证据日期 {{ document.day }} · {{ document.mode === 'snapshot' ? '保存时冻结结果' : '来源校验后的本地结果' }} · 非吸筹或交易确认</p>
      <div class="metrics" v-if="current">
        <div class="metric"><span>覆盖 A 股</span><strong>{{ current.stocks?.toLocaleString() ?? '未知' }}</strong></div>
        <div class="metric"><span>成交额</span><strong>{{ money(current.amount) }}</strong></div>
        <div class="metric"><span>主动净额</span><strong :class="current.net == null ? '' : current.net > 0 ? 'positive' : 'negative'">{{ money(current.net) }}</strong></div>
        <div class="metric"><span>上涨 / 下跌</span><strong>{{ current.up ?? '未知' }} / {{ current.down ?? '未知' }}</strong></div>
      </div>
      <nav class="research-tabs" role="tablist" aria-label="研究视图"><button role="tab" :aria-selected="activeTab === 'review'" aria-controls="review-panel" @click="activeTab = 'review'">Level‑2 复盘</button><button role="tab" :aria-selected="activeTab === 'patterns'" aria-controls="patterns-panel" @click="activeTab = 'patterns'">个股形态</button><button role="tab" :aria-selected="activeTab === 'validation'" aria-controls="validation-panel" @click="activeTab = 'validation'">后续验证</button></nav>
      <div id="review-panel" role="tabpanel" v-show="activeTab === 'review'"><QualitySummary :quality="document.report.quality" :gate="document.report.gate" /><MarketTimeline :markets="document.report.markets" /><ContinuousPanel :key="document.mode + document.day" :day="document.day" :cards="document.report.cards" :frozen="document.mode === 'snapshot'" :snapshot-views="document.stateViews || {}" :snapshot-window="document.stateWindow" :snapshot-charts="document.charts || {}" @chart-loaded="captureChart" @state-loaded="captureState" @view-applied="captureAppliedState" /><CandidatePanel :key="document.mode + document.day" :cards="document.report.cards" :day="document.day" :frozen="document.mode === 'snapshot'" :snapshot-charts="document.charts || {}" :initial-filters="filters" :state-view="activeStateView" @chart-loaded="captureChart" @detail-loaded="captureDetail" @filters-change="filters = $event" /></div>
      <div id="patterns-panel" role="tabpanel" v-show="activeTab === 'patterns'"><PatternPanel :key="document.mode + document.day" :day="document.day" :frozen="document.mode === 'snapshot'" :snapshot-patterns="document.patterns || null" :snapshot-charts="document.charts || {}" :initial-ui="document.patternUI || {}" :levels="stateLevels" :state-window="stateWindow" @chart-loaded="captureChart" @pattern-loaded="capturePattern" @detail-loaded="capturePatternDetail" @ui-change="capturePatternUI" /></div>
      <div id="validation-panel" role="tabpanel" v-show="activeTab === 'validation'"><ValidationPanel :key="document.mode + document.day" :day="document.day" :cards="document.report.cards" :frozen="document.mode === 'snapshot'" :saved="document.validation || null" :saved-details="document.validationDetails || {}" @loaded="captureValidation" @detail-loaded="captureValidationDetail" /></div>
      <section class="panel migration-note"><h2>研究边界</h2><p>Vue 已接入日级报告、连续观察、单股深查、22 类形态及事件后续收益描述性研究。收盘后可识别事件的后续收盘收益，不等于可成交收益；盘口队列重建、参数外推及交易授权仍未实现。旧页保留为迁移对照。</p></section>
    </template>
  </main>
</template>
