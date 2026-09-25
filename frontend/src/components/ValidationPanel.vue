<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { startValidation, stateMeta, validationDetail, validationStatus } from '../api.js'
import { cohortName, findStockCode, formatPct, ruleName, sessionDefaults, viewRows } from '../validationModel.js'

const props = defineProps({ day: { type: String, required: true }, frozen: { type: Boolean, default: false },
  cards: { type: Array, required: true }, saved: { type: Object, default: null },
  savedDetails: { type: Object, default: () => ({}) } })
const emit = defineEmits(['loaded', 'detail-loaded'])
const fields = ref({ start: '', split: '', end: '', asof: props.day })
const horizons = [1, 3, 5]
const result = ref(props.frozen ? props.saved : null)
const receipt = ref('')
const pending = ref(false)
const status = ref(props.frozen ? props.saved ? '只读：展示保存时的描述性研究' : '此快照未保存事件后续收益；不会读取最新数据补齐' : '确认观察日期后手动计算；参数改变不会自动覆盖已展示结果')
const selectedCohort = ref('OUT_OF_SAMPLE')
const selectedHorizon = ref(1)
const lookup = ref('')
const selectedCode = ref('')
const detailByCode = ref(props.frozen ? props.savedDetails : {})
const detailBusy = ref(false)
const detailStatus = ref(props.frozen ? Object.keys(props.savedDetails).length ? '仅可查看快照已保存的个股' : '此快照未保存逐股后续证据' : '搜索代码或名称，按需读取该股的事件与后续结果')
const names = computed(() => Object.fromEntries(props.cards.map(card => [card.code, card.name])))
const matches = computed(() => {
  const query = lookup.value.trim().toLowerCase()
  if (!query) return []
  const cards = props.frozen ? props.cards.filter(card => props.savedDetails[card.code]) : props.cards
  return cards.filter(card => card.code?.toLowerCase().includes(query) || card.name?.toLowerCase().includes(query)).slice(0, 8)
})
const selectedDetail = computed(() => detailByCode.value[selectedCode.value] || null)
const evidenceDays = computed(() => {
  const grouped = new Map()
  for (const row of selectedDetail.value?.observations || []) {
    if (!grouped.has(row.day)) grouped.set(row.day, [])
    grouped.get(row.day).push(row)
  }
  return [...grouped].map(([day, rows]) => ({ day, rows: rows.sort((a, b) => a.horizon - b.horizon) }))
})
const rows = computed(() => viewRows(result.value, selectedCohort.value, selectedHorizon.value))
const counts = computed(() => {
  const values = rows.value
  return { observed: values.reduce((total, row) => total + row.observed, 0),
    pending: values.reduce((total, row) => total + row.pending, 0),
    days: Math.max(0, ...values.map(row => row.signalDays)) }
})
let sequence = 0
let timer
let detailSequence = 0

onMounted(async () => {
  if (props.frozen) return
  try {
    const meta = await stateMeta()
    const preset = sessionDefaults(meta.days, props.day)
    if (preset) fields.value = preset
  } catch { status.value = '未能读取交易日历，请手动填写 YYYYMMDD 日期' }
})

async function calculate() {
  if (props.frozen || pending.value) return
  const id = ++sequence
  clearTimeout(timer)
  pending.value = true
  status.value = `正在计算；${result.value ? '下方仍为上次参数的结果' : '暂无结果'}`
  try {
    const job = await startValidation({ ...fields.value, horizons })
    await poll(id, job.id)
  } catch (error) {
    if (id === sequence) { pending.value = false; status.value = `计算失败：${error.message}；${result.value ? '保留上次结果' : '暂无结果'}` }
  }
}

async function poll(sequenceId, jobId) {
  if (sequenceId !== sequence) return
  const response = await validationStatus(jobId)
  if (sequenceId !== sequence) return
  if (response.status === 'done') {
    result.value = response.result
    receipt.value = response.receipt
    detailSequence++
    detailByCode.value = {}
    selectedCode.value = ''
    detailStatus.value = '新研究已应用；逐股证据需按需读取'
    pending.value = false
    status.value = '已完成；收盘后可识别事件的描述性后续收益，非可交易回测'
    emit('loaded', { receipt: receipt.value, result: result.value })
  } else if (response.status === 'running' || response.status === 'queued') {
    status.value = `${response.message}；${result.value ? '下方仍为上次参数的结果' : '暂无结果'}`
    timer = setTimeout(() => poll(sequenceId, jobId).catch(error => {
      if (sequenceId === sequence) { pending.value = false; status.value = `读取失败：${error.message}；可重新提交研究` }
    }), 1500)
  } else {
    pending.value = false
    status.value = `${response.message || response.status}；${result.value ? '保留上次结果' : '暂无结果'}`
  }
}
async function loadDetail(code = null) {
  const selected = code || findStockCode(props.cards, lookup.value)
  if (!selected) { detailStatus.value = '代码或名称不唯一／不存在，请从匹配列表选择'; return }
  if (!result.value) { detailStatus.value = '请先完成后续收益研究'; return }
  if (props.frozen) {
    selectedCode.value = selected
    detailStatus.value = props.savedDetails[selected] ? '只读：仅展示保存时的逐股证据' : '此快照未保存该股证据；不读取最新数据'
    return
  }
  if (detailByCode.value[selected]) {
    selectedCode.value = selected
    detailStatus.value = '展示本次已加载的逐股证据'
    return
  }
  const id = ++detailSequence
  detailBusy.value = true
  detailStatus.value = `正在读取 ${selected} 的逐股事件，不重新扫描原始 Level‑2…`
  try {
    const detail = await validationDetail(receipt.value, selected)
    if (id !== detailSequence) return
    if (detail.sourceIdentity !== result.value.sourceIdentity) throw new Error('研究来源与当前结果不一致')
    detailByCode.value = { ...detailByCode.value, [selected]: detail }
    selectedCode.value = selected
    detailStatus.value = detail.status === 'NO_EVENT' ? '该股在所选事件窗口内没有满足规则的事件' : '已加载；后续收益与触发日证据分开显示'
    emit('detail-loaded', selected)
  } catch (error) {
    if (id === detailSequence) detailStatus.value = `逐股读取失败：${error.message}`
  } finally { if (id === detailSequence) detailBusy.value = false }
}
const point = value => Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(2)} pp` : '未知'
const resultLabel = row => row.status === 'PENDING' ? '未到期' : row.status === 'MISSING_PRICE' ? '价格缺失' : formatPct(row.returnPct)
const entryGateName = { PENDING: '次日未到', MISSING_BAR: '缺日线', MISSING_PRICE: '价缺失', INVALID_OHLC: '价关系异常', UNKNOWN_VOLUME: '量未知', NO_VOLUME: '零成交量', ONE_PRICE_SESSION: '单一价位', PRICE_REFERENCE_ONLY: '仅价格参考' }
const entryCounts = row => row.entryGateCounts ? Object.entries(row.entryGateCounts).map(([key, count]) => `${entryGateName[key] || key} ${count}`).join(' · ') : '旧结果未保存'
onBeforeUnmount(() => { sequence++; detailSequence++; clearTimeout(timer) })
</script>

<template>
  <section class="panel validation-panel" aria-labelledby="validation-title">
    <div class="section-heading"><div><span class="eyebrow">OUTCOME STUDY · RESEARCH ONLY</span><h2 id="validation-title">事件后续验证</h2></div><span class="hint">训练／隔离／样本外明确分开</span></div>
    <p class="footnote">固定比较日级主动成交事件触发后 1／3／5 个交易日的收盘到收盘价格变化；事件只在触发日数据就绪后可识别。次日日线门槛只检查可观察性及单一价位，不证明排队成交。这里不是买点、卖点或可成交收益。</p>
    <div v-if="!frozen" class="validation-controls">
      <label>事件起点<input v-model.trim="fields.start" inputmode="numeric" maxlength="8" aria-label="事件起点 YYYYMMDD" /></label>
      <label>训练截止<input v-model.trim="fields.split" inputmode="numeric" maxlength="8" aria-label="训练截止 YYYYMMDD" /></label>
      <label>事件终点<input v-model.trim="fields.end" inputmode="numeric" maxlength="8" aria-label="事件终点 YYYYMMDD" /></label>
      <label>数据截止<input v-model.trim="fields.asof" inputmode="numeric" maxlength="8" aria-label="数据截止 YYYYMMDD" /></label>
      <button class="primary" :disabled="pending" @click="calculate">{{ pending ? '研究中…' : '计算后续结果' }}</button>
    </div>
    <p class="footnote" role="status">{{ status }}</p>
    <template v-if="result">
      <div class="validation-context"><span>事件 {{ result.start }} — {{ result.end }}</span><span>训练截止 {{ result.split }}</span><span>数据截止 {{ result.asof }}</span><span>最长预测期限隔离 {{ result.embargoSessions }} 个交易日</span></div>
      <p class="footnote">请求 {{ result.signalDaysRequested }} 个事件日；Level‑2 缺档 {{ result.signalDaysMissingFlow.length }} 日；累计事件×期限 {{ result.observationCount?.toLocaleString() ?? '旧结果未记录' }} 条。{{ frozen ? '此结果只使用快照保存时的来源。' : '调整上方日期后，只有重新计算才更新下方结果。' }}</p>
      <p v-if="result.signalDaysMissingFlow.length" class="footnote">缺档日期：{{ result.signalDaysMissingFlow.map(item => item.day).join('、') }}；缺档不跨越形成事件。</p>
      <div class="validation-filters"><label>样本分段<select v-model="selectedCohort"><option v-for="(name, key) in cohortName" :key="key" :value="key">{{ name }}</option></select></label><label>后续交易日<select v-model.number="selectedHorizon"><option v-for="day in horizons" :key="day" :value="day">后 {{ day }} 日</option></select></label><span>{{ cohortName[selectedCohort] }} · 已观察 {{ counts.observed.toLocaleString() }} 条 · 未到期 {{ counts.pending.toLocaleString() }} 条 · 各类最多 {{ counts.days }} 个事件日</span></div>
      <div v-if="rows.length" class="table-scroll"><table class="validation-table"><thead><tr><th>事件</th><th>触发数</th><th>已观察／未到期／缺价格</th><th>次日日线门槛</th><th>事件日</th><th>平均收益</th><th>同日基准超额</th><th>按事件日等权超额</th><th>基准平均覆盖</th></tr></thead><tbody><tr v-for="row in rows" :key="row.rule"><td>{{ ruleName[row.rule] || row.rule }}</td><td>{{ row.events.toLocaleString() }}</td><td>{{ row.observed.toLocaleString() }} / {{ row.pending.toLocaleString() }} / {{ row.missingPrice.toLocaleString() }}</td><td>{{ entryCounts(row) }}</td><td>{{ row.signalDays }}</td><td>{{ formatPct(row.meanReturnPct) }}</td><td>{{ formatPct(row.meanExcessPct) }}</td><td>{{ formatPct(row.equalDayMeanExcessPct) }}</td><td>{{ row.benchmarkPoolMeanN == null ? '未知' : row.benchmarkPoolMeanN.toFixed(0) + ' 只' }}</td></tr></tbody></table></div>
      <p v-else class="footnote">此分段／期限没有已识别事件；不补零，也不推出无效结论。</p>
      <div class="validation-stock">
        <h3>个股事件与后续结果</h3>
        <p class="footnote">仅查询所选研究窗口中的触发事件；不把后续涨跌写回触发日判断。快照只保留实际打开过的个股。</p>
        <div class="validation-stock-controls"><input v-model.trim="lookup" aria-label="个股后续证据搜索" placeholder="代码或唯一名称，例如 301080.SZ" @keyup.enter="loadDetail()" /><button :disabled="detailBusy || (frozen && !Object.keys(savedDetails).length)" @click="loadDetail()">{{ detailBusy ? '读取中…' : '查看逐股证据' }}</button></div>
        <div v-if="matches.length" class="validation-suggestions"><button v-for="card in matches" :key="card.code" @click="lookup = card.code; loadDetail(card.code)">{{ card.name }} {{ card.code }}</button></div>
        <div v-if="frozen && Object.keys(savedDetails).length && !lookup" class="validation-suggestions"><button v-for="code in Object.keys(savedDetails)" :key="code" @click="lookup = code; loadDetail(code)">{{ names[code] || '名称未知' }} {{ code }}</button></div>
        <p class="footnote" role="status">{{ detailStatus }}</p>
        <template v-if="selectedDetail">
          <h4>{{ names[selectedCode] || '名称未知' }} {{ selectedCode }} · {{ evidenceDays.length ? evidenceDays.length + ' 个触发日' : '无已识别事件' }}</h4>
          <p v-if="selectedDetail.status === 'NO_EVENT'" class="footnote">没有识别到这四类事件，不代表该股没有其他价格或盘口结构。</p>
          <details v-for="(event, index) in evidenceDays" :key="event.day" :open="index === 0" class="validation-event">
            <summary>{{ event.day }} · {{ ruleName[event.rows[0].rule] || event.rows[0].rule }} · {{ cohortName[event.rows[0].cohort] }}</summary>
            <p>前日净额比 {{ formatPct(event.rows[0].previousRatio) }} → 触发日 {{ formatPct(event.rows[0].currentRatio) }}；变化 {{ point(event.rows[0].deltaPP) }}。次日 {{ event.rows[0].entryDay || '未覆盖' }} 日线门槛：{{ entryGateName[event.rows[0].entryGate] || '旧结果未保存' }}；通过也不等于成交。收益以 close×adj_factor 的比值计算；该绝对值不是可成交价格。</p>
            <div class="table-scroll"><table><thead><tr><th>期限</th><th>目标交易日</th><th>结果状态</th><th>后续收益</th><th>同日基准</th><th>超额</th></tr></thead><tbody><tr v-for="row in event.rows" :key="row.horizon"><td>后 {{ row.horizon }} 日</td><td>{{ row.targetDay || '日历未覆盖' }}</td><td>{{ row.status === 'OBSERVED' ? '已观察' : row.status === 'PENDING' ? '未到期' : '价格缺失' }}</td><td>{{ resultLabel(row) }}</td><td>{{ row.status === 'OBSERVED' ? formatPct(row.benchmarkPct) : '不可比较' }}</td><td>{{ row.status === 'OBSERVED' ? formatPct(row.excessPct) : '不可比较' }}</td></tr></tbody></table></div>
          </details>
        </template>
      </div>
      <details><summary>研究口径与局限</summary><p v-for="item in result.limitations" :key="item" class="footnote">{{ item }}</p><p class="footnote">来源标识 {{ result.sourceIdentity }}。旧快照没有此结果时，不用新数据回填。</p></details>
    </template>
  </section>
</template>
