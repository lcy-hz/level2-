<script setup>
import { computed, onMounted, ref } from 'vue'
import { dates, report, snapshot, snapshots } from './api.js'
import MarketTimeline from './components/MarketTimeline.vue'
import QualitySummary from './components/QualitySummary.vue'
import CandidatePanel from './components/CandidatePanel.vue'
import ContinuousPanel from './components/ContinuousPanel.vue'

const params = new URLSearchParams(location.search)
const selectedDay = ref(params.get('date') || '20260922')
const snapshotId = ref(params.get('snapshot') || '')
const dateRows = ref([])
const saved = ref([])
const document = ref(null)
const busy = ref(false)
const error = ref('')
let request = 0

const current = computed(() => document.value?.report?.markets?.at(-1) || null)
const sourceStatus = computed(() => dateRows.value.find(row => row.day === selectedDay.value))
const legacyUrl = computed(() => `${location.port === '5173' ? 'http://127.0.0.1:18762' : ''}/level2-market-scan_20260922.html?${snapshotId.value ? 'snapshot=' + encodeURIComponent(snapshotId.value) : 'date=' + encodeURIComponent(selectedDay.value)}`)
const money = value => value == null ? '未知' : `${(value / 1e8).toFixed(2)} 亿`

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
    </nav>

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
      <QualitySummary :quality="document.report.quality" :gate="document.report.gate" />
      <MarketTimeline :markets="document.report.markets" />
      <ContinuousPanel :key="document.mode + document.day" :day="document.day" :cards="document.report.cards" :frozen="document.mode === 'snapshot'" :snapshot-views="document.stateViews || {}" :snapshot-window="document.stateWindow" />
      <CandidatePanel :cards="document.report.cards" />
      <section class="panel migration-note"><h2>迁移范围</h2><p>当前 Vue 页面已接入报告、来源状态、质量证据、市场轨迹、连续观察、全库候选筛选和只读快照读取。形态扫描、悬浮 K 线、按需深查与快照保存暂保留在旧页面，迁移前不伪装成已实现。</p></section>
    </template>
  </main>
</template>
