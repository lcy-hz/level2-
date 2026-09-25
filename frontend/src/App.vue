<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { dates, report, reportStatus, saveSnapshot, snapshot, snapshots, startReportBuild, stateMeta } from './api.js'
import { adjacentTradingDay, initialReportDay } from './tradingDays.js'
import { normalizeCandidateFilters } from './candidateFilters.js'
import MarketTimeline from './components/MarketTimeline.vue'
import QualitySummary from './components/QualitySummary.vue'
import CandidatePanel from './components/CandidatePanel.vue'
import ContinuousPanel from './components/ContinuousPanel.vue'
import PatternPanel from './components/PatternPanel.vue'
import ValidationPanel from './components/ValidationPanel.vue'

const params = new URLSearchParams(location.search)
const selectedDay = ref(params.get('date') || '')
const targetDay = ref(selectedDay.value)
const snapshotId = ref(params.get('snapshot') || '')
const dateRows = ref([])
const tradingDays = ref([])
const saved = ref([])
const document = ref(null)
const busy = ref(false)
const error = ref('')
const saving = ref(false)
const saveMessage = ref('')
const savedId = ref('')
const buildBusy = ref(false)
const buildMessage = ref('')
const chartReceipts = ref({})
const stateReceipts = ref({})
const loadedDetails = ref({})
const stateWindow = ref(null)
const continuousUI = ref({})
const filters = ref({ search: '', filter: 'all', direction: 'all', sort: 'default' })
const activeTab = ref('review')
const activeStateView = ref(null)
const patternReceipt = ref('')
const patternCodes = ref([])
const patternUI = ref({ tab: 'review' })
const validationReceipt = ref('')
const validationCodes = ref([])
let request = 0
let buildRequest = 0
let buildTimer = null
let failedLoad = null

const current = computed(() => document.value?.report?.markets?.at(-1) || null)
// Key on the document that has finished loading, not the requested selection.
// Otherwise a same-day snapshot switch can retain the previous filters/dialogs.
const panelKey = computed(() => document.value?.id || `${document.value?.mode}:${document.value?.day}`)
const sourceStatus = computed(() => dateRows.value.find(row => row.day === targetDay.value))
const previousDay = computed(() => adjacentTradingDay(tradingDays.value, document.value?.day, -1))
const nextDay = computed(() => adjacentTradingDay(tradingDays.value, document.value?.day, 1))
const money = value => value == null ? '未知' : `${(value / 1e8).toFixed(2)} 亿`
const stateLevels = computed(() => Object.fromEntries((activeStateView.value?.stocks || []).map(stock => [stock.code, stock.level])))
watch(activeTab, tab => { patternUI.value = { ...patternUI.value, tab } })

async function load({ day = selectedDay.value, key = snapshotId.value } = {}) {
  const id = ++request
  busy.value = true
  error.value = ''
  try {
    const result = key ? await snapshot(key) : await report(day)
    if (id !== request) return
    document.value = result
    snapshotId.value = key
    selectedDay.value = result.day
    targetDay.value = result.day
    history.replaceState(null, '', key ? `/?snapshot=${encodeURIComponent(key)}` : `/?date=${encodeURIComponent(result.day)}`)
    failedLoad = null
    chartReceipts.value = {}
    stateReceipts.value = {}
    loadedDetails.value = {}
    stateWindow.value = result.mode === 'snapshot' ? result.stateWindow ?? null : null
    continuousUI.value = result.continuousUI || {}
    activeStateView.value = result.mode === 'snapshot' && result.stateWindow != null ? result.stateViews?.[String(result.stateWindow)] || null : null
    filters.value = normalizeCandidateFilters(result.filters)
    activeTab.value = ['patterns', 'validation'].includes(result.patternUI?.tab) ? result.patternUI.tab : 'review'
    patternUI.value = { ...(result.patternUI || {}), tab: activeTab.value }
    patternReceipt.value = ''
    patternCodes.value = []
    validationReceipt.value = ''
    validationCodes.value = []
    saveMessage.value = ''
    savedId.value = ''
  } catch (cause) {
    if (id === request) {
      error.value = `${key ? '目标快照' : `报告 ${day}`} 读取失败：${cause.message}`
      failedLoad = { day, key }
    }
  } finally {
    if (id === request) busy.value = false
  }
}
function retryLoad() { return load(failedLoad || { day: selectedDay.value, key: snapshotId.value }) }

function chooseDay() {
  if (sourceStatus.value?.status !== 'ready') {
    buildMessage.value = sourceStatus.value?.message || '此日期报告尚未就绪；请先计算报告。'
    return
  }
  buildMessage.value = ''
  load({ day: targetDay.value, key: '' })
}

function moveTradingDay(offset) {
  if (snapshotId.value || !document.value) return
  const day = adjacentTradingDay(tradingDays.value, document.value.day, offset)
  if (!day) return
  targetDay.value = day
  if (dateRows.value.some(row => row.day === day && row.status === 'ready')) chooseDay()
  else buildMessage.value = `${day} 是相邻交易日，但报告尚未就绪；当前仍显示 ${document.value.day}。请核对来源后计算所选日期。`
}

function chooseSnapshot(event) {
  const key = event.target.value
  // Keep the selector aligned with the evidence that is actually displayed.
  event.target.value = snapshotId.value
  if (!key) return returnLive()
  load({ key })
}

function returnLive() {
  if (!snapshotId.value) return
  const ready = dateRows.value.find(row => row.day === document.value?.day && row.status === 'ready') || dateRows.value.find(row => row.status === 'ready')
  if (!ready) { buildMessage.value = '没有可查看的最新报告；当前快照保持只读。'; return }
  targetDay.value = ready.day
  chooseDay()
}

async function buildSelectedDay() {
  const day = targetDay.value
  if (!sourceStatus.value?.canBuild || snapshotId.value || buildBusy.value) return
  const id = ++buildRequest
  buildBusy.value = true
  buildMessage.value = `${day}：正在提交计算；当前页面保留。`
  try {
    await startReportBuild(day)
    const poll = async () => {
      if (id !== buildRequest) return
      try {
        const state = await reportStatus(day)
        if (id !== buildRequest) return
        buildMessage.value = `${day}：${state.message}`
        if (['queued', 'running'].includes(state.status)) {
          buildTimer = setTimeout(poll, 2000)
          return
        }
        buildBusy.value = false
        dateRows.value = await dates()
        if (state.status === 'ready') {
          targetDay.value = day
          chooseDay()
        }
      } catch (cause) {
        if (id === buildRequest) { buildBusy.value = false; buildMessage.value = `${day}：状态读取失败：${cause.message}。可重试查询或重新计算。` }
      }
    }
    await poll()
  } catch (cause) {
    if (id === buildRequest) { buildBusy.value = false; buildMessage.value = `${day}：计算提交失败：${cause.message}` }
  }
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
function captureContinuousUI(ui) { continuousUI.value = ui }
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
      continuousUI: continuousUI.value,
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
  load({ key: savedId.value })
}

onMounted(async () => {
  const [dateList, snapshotList, calendar] = await Promise.allSettled([dates(), snapshots(), stateMeta()])
  if (dateList.status === 'fulfilled') dateRows.value = dateList.value
  if (snapshotList.status === 'fulfilled') saved.value = snapshotList.value
  if (calendar.status === 'fulfilled') tradingDays.value = calendar.value.days || []
  if (!snapshotId.value && !params.has('date')) {
    selectedDay.value = initialReportDay(dateRows.value)
    targetDay.value = selectedDay.value
  }
  if (snapshotId.value || selectedDay.value) await load()
  else error.value = dateList.status === 'rejected'
    ? `本地日期读取失败：${dateList.reason?.message || '请检查服务和数据路径'}`
    : '本地尚无可识别的 Level-2 日期；请检查数据路径与正式文件。'
})
onBeforeUnmount(() => { buildRequest++; clearTimeout(buildTimer) })
</script>

<template>
  <main class="shell">
    <header class="hero">
      <div class="hero-copy"><span class="eyebrow">RESEARCH_ONLY · 本地 Level-2</span><h1>连续市场与个股证据</h1><p>同一份 Python 报告数据，分离成可核验的服务接口与交互页面。</p></div>
      <div class="hero-meta"><span>当前证据日</span><strong>{{ document?.day || selectedDay || '未选择' }}</strong><small>{{ snapshotId ? '只读快照 · 不补读最新数据' : '本地报告 · 非实时行情' }}</small></div>
    </header>

    <nav class="toolbar" aria-label="报告选择">
      <label>报告日期<select v-model="targetDay" :disabled="Boolean(snapshotId) || buildBusy" @change="buildMessage = ''"><option v-if="snapshotId || !dateRows.some(row => row.day === targetDay)" :value="targetDay">{{ targetDay }}{{ snapshotId ? ' · 快照证据日' : ' · 来源未列出' }}</option><option v-if="!snapshotId" v-for="row in dateRows" :key="row.day" :value="row.day">{{ row.day }} · {{ row.status === 'ready' ? '可查看' : row.status === 'stale' ? '待更新' : '待计算' }}</option></select></label>
      <button v-if="!snapshotId" class="save-button" :disabled="buildBusy || sourceStatus?.status !== 'ready' || targetDay === document?.day" @click="chooseDay">查看所选日期</button>
      <button v-if="!snapshotId" class="save-button secondary" :disabled="buildBusy || !sourceStatus?.canBuild || sourceStatus?.status === 'ready'" @click="buildSelectedDay">{{ buildBusy ? '计算中…' : '计算所选日期' }}</button>
      <label>历史快照<select :value="snapshotId" @change="chooseSnapshot"><option value="">最新数据</option><option v-for="item in saved" :key="item.id" :value="item.id">{{ item.day }} · {{ new Date(item.savedAt).toLocaleString() }}</option></select></label>
      <button v-if="snapshotId" class="save-button secondary" :disabled="busy" @click="returnLive">返回最新数据</button>
      <button v-if="document?.mode === 'live'" class="save-button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存当前证据快照' }}</button>
    </nav>
    <p v-if="sourceStatus && !snapshotId" class="scope">所选 {{ targetDay }}：{{ sourceStatus.message }}{{ !sourceStatus.canBuild ? '；最近 7 交易日的正式文件或日历不足，暂不可计算' : '' }}{{ !sourceStatus.minute ? '；当日分钟文件缺失' : '' }}</p>
    <p v-if="buildMessage" class="snapshot-message" role="status">{{ buildMessage }}</p>
    <p v-if="saveMessage" class="snapshot-message" role="status">{{ saveMessage }} <button v-if="savedId" @click="openSaved">查看快照</button></p>

    <div v-if="busy" class="notice" role="status">正在读取报告数据…</div>
    <div v-if="error" class="notice error" role="alert">
      <strong>{{ document ? '切换失败，仍显示此前证据' : '当前数据不可展示' }}</strong><p>{{ error }}</p><p v-if="sourceStatus">{{ sourceStatus.message }}</p>
      <button @click="retryLoad">{{ document ? '重试切换' : '重试读取' }}</button>
    </div>
    <template v-if="document">
      <p class="scope">证据日期 {{ document.day }} · {{ document.mode === 'snapshot' ? '保存时冻结结果' : '来源校验后的本地结果' }} · 非吸筹或交易确认</p>
      <aside class="method-alert" aria-label="关键计算口径"><strong>口径提醒</strong><span>报告收盘价取数值时钟最后正价快照；同刻重复仍需质量核验，闭市值不解释为可交易时点。十档买／卖是 14:57 前连续竞价末档逐列显示量合计，缺档可能低估，不代表全日承接。主动净额不是持仓变化；上涨伴净卖出不直接确认派发。</span></aside>
      <div class="metrics" v-if="current">
        <div class="metric"><span>覆盖 A 股</span><strong>{{ current.stocks?.toLocaleString() ?? '未知' }}</strong></div>
        <div class="metric"><span>成交额</span><strong>{{ money(current.amount) }}</strong></div>
        <div class="metric"><span>主动净额</span><strong :class="current.net == null ? '' : current.net > 0 ? 'positive' : 'negative'">{{ money(current.net) }}</strong></div>
        <div class="metric"><span>上涨 / 下跌</span><strong>{{ current.up ?? '未知' }} / {{ current.down ?? '未知' }}</strong></div>
      </div>
      <nav class="research-tabs" role="tablist" aria-label="研究视图"><button role="tab" :aria-selected="activeTab === 'review'" aria-controls="review-panel" @click="activeTab = 'review'">Level‑2 复盘</button><button role="tab" :aria-selected="activeTab === 'patterns'" aria-controls="patterns-panel" @click="activeTab = 'patterns'">个股形态</button><button role="tab" :aria-selected="activeTab === 'validation'" aria-controls="validation-panel" @click="activeTab = 'validation'">后续验证</button></nav>
      <div id="review-panel" role="tabpanel" v-show="activeTab === 'review'"><QualitySummary :quality="document.report.quality" :gate="document.report.gate" /><MarketTimeline :markets="document.report.markets" :quality-available="Boolean(document.report.quality)" /><ContinuousPanel :key="panelKey" :day="document.day" :cards="document.report.cards" :frozen="document.mode === 'snapshot'" :previous-day="previousDay" :next-day="nextDay" :snapshot-views="document.stateViews || {}" :snapshot-window="document.stateWindow" :snapshot-charts="document.charts || {}" :initial-ui="continuousUI" @navigate-day="moveTradingDay" @chart-loaded="captureChart" @state-loaded="captureState" @view-applied="captureAppliedState" @ui-change="captureContinuousUI" /><CandidatePanel :key="panelKey" :cards="document.report.cards" :lists="document.report.lists || {}" :day="document.day" :frozen="document.mode === 'snapshot'" :snapshot-charts="document.charts || {}" :initial-filters="filters" :state-view="activeStateView" @chart-loaded="captureChart" @detail-loaded="captureDetail" @filters-change="filters = $event" /></div>
      <div id="patterns-panel" role="tabpanel" v-show="activeTab === 'patterns'"><PatternPanel :key="panelKey" :day="document.day" :frozen="document.mode === 'snapshot'" :snapshot-patterns="document.patterns || null" :snapshot-charts="document.charts || {}" :initial-ui="document.patternUI || {}" :levels="stateLevels" :state-window="stateWindow" @chart-loaded="captureChart" @pattern-loaded="capturePattern" @detail-loaded="capturePatternDetail" @ui-change="capturePatternUI" /></div>
      <div id="validation-panel" role="tabpanel" v-show="activeTab === 'validation'"><ValidationPanel :key="panelKey" :day="document.day" :cards="document.report.cards" :frozen="document.mode === 'snapshot'" :saved="document.validation || null" :saved-details="document.validationDetails || {}" @loaded="captureValidation" @detail-loaded="captureValidationDetail" /></div>
      <section class="panel migration-note" aria-labelledby="boundary-title"><div class="section-heading"><div><span class="eyebrow">EVIDENCE BOUNDARY</span><h2 id="boundary-title">证据、反证与未知</h2></div></div><div class="quality-grid"><div class="subpanel"><strong>已展示的证据</strong><p>7 交易日日级轨迹、目标日质量报告与全库候选；已计算的连续窗口、单股盘中／盘口深查、图表、形态和后续观察按各自来源与覆盖展示。快照只读取保存时冻结的结果。</p></div><div class="subpanel"><strong>仍不能确认</strong><p>委托类型码、撤补单与成交队列身份、主动成交的因果价格冲击、可执行支撑及吸筹／派发意图。价格与资金背离是待核验现象，不是单独的买卖触发。</p></div></div><p>收盘后可识别事件的后续收盘收益，不等于可成交、成本后的策略收益；参数外推、排队成交和交易授权仍未验收。</p></section>
    </template>
  </main>
</template>

<style scoped>
.method-alert { display: flex; gap: 10px; align-items: baseline; padding: 10px 13px; margin: 0 0 12px; border: 1px solid #67515d; border-left: 3px solid #db9ca8; border-radius: 9px; background: #241d29; color: #d8c9d2; font-size: 12px; line-height: 1.6; }
.method-alert strong { flex: none; color: #ffd1d5; }
@media (max-width: 620px) { .method-alert { display: block; } .method-alert strong { display: block; margin-bottom: 2px; } }
</style>
