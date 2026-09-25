<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { startValidation, stateMeta, validationStatus } from '../api.js'
import { cohortName, formatPct, ruleName, sessionDefaults, viewRows } from '../validationModel.js'

const props = defineProps({ day: { type: String, required: true }, frozen: { type: Boolean, default: false },
  saved: { type: Object, default: null } })
const emit = defineEmits(['loaded'])
const fields = ref({ start: '', split: '', end: '', asof: props.day })
const horizons = [1, 3, 5]
const result = ref(props.frozen ? props.saved : null)
const receipt = ref('')
const pending = ref(false)
const status = ref(props.frozen ? props.saved ? '只读：展示保存时的描述性研究' : '此快照未保存事件后续收益；不会读取最新数据补齐' : '确认观察日期后手动计算；参数改变不会自动覆盖已展示结果')
const selectedCohort = ref('OUT_OF_SAMPLE')
const selectedHorizon = ref(1)
const rows = computed(() => viewRows(result.value, selectedCohort.value, selectedHorizon.value))
const counts = computed(() => {
  const values = rows.value
  return { observed: values.reduce((total, row) => total + row.observed, 0),
    pending: values.reduce((total, row) => total + row.pending, 0),
    days: Math.max(0, ...values.map(row => row.signalDays)) }
})
let sequence = 0
let timer

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
onBeforeUnmount(() => { sequence++; clearTimeout(timer) })
</script>

<template>
  <section class="panel validation-panel" aria-labelledby="validation-title">
    <div class="section-heading"><div><span class="eyebrow">OUTCOME STUDY · RESEARCH ONLY</span><h2 id="validation-title">事件后续验证</h2></div><span class="hint">训练／隔离／样本外明确分开</span></div>
    <p class="footnote">固定比较日级主动成交事件触发后 1／3／5 个交易日的收盘到收盘价格变化；事件只在触发日数据就绪后可识别。这里不是买点、卖点或可成交收益。</p>
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
      <div v-if="rows.length" class="table-scroll"><table class="validation-table"><thead><tr><th>事件</th><th>触发数</th><th>已观察／未到期／缺价格</th><th>事件日</th><th>平均收益</th><th>同日基准超额</th><th>按事件日等权超额</th><th>基准平均覆盖</th></tr></thead><tbody><tr v-for="row in rows" :key="row.rule"><td>{{ ruleName[row.rule] || row.rule }}</td><td>{{ row.events.toLocaleString() }}</td><td>{{ row.observed.toLocaleString() }} / {{ row.pending.toLocaleString() }} / {{ row.missingPrice.toLocaleString() }}</td><td>{{ row.signalDays }}</td><td>{{ formatPct(row.meanReturnPct) }}</td><td>{{ formatPct(row.meanExcessPct) }}</td><td>{{ formatPct(row.equalDayMeanExcessPct) }}</td><td>{{ row.benchmarkPoolMeanN == null ? '未知' : row.benchmarkPoolMeanN.toFixed(0) + ' 只' }}</td></tr></tbody></table></div>
      <p v-else class="footnote">此分段／期限没有已识别事件；不补零，也不推出无效结论。</p>
      <details><summary>研究口径与局限</summary><p v-for="item in result.limitations" :key="item" class="footnote">{{ item }}</p><p class="footnote">来源标识 {{ result.sourceIdentity }}。旧快照没有此结果时，不用新数据回填。</p></details>
    </template>
  </section>
</template>
