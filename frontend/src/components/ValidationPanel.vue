<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { startValidation, stateMeta, validationDetail, validationStatus } from '../api.js'
import { cohortName, findStockCode, formatPct, mixedSourceWarning, ruleName, sessionDefaults, sourcePair, sourceStrata, viewRows } from '../validationModel.js'

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
const selectedRule = ref('')
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
const chosenRule = computed(() => rows.value.some(row => row.rule === selectedRule.value) ? selectedRule.value : rows.value[0]?.rule)
const chosenSummary = computed(() => rows.value.find(row => row.rule === chosenRule.value))
const dayBreakdown = computed(() => chosenSummary.value?.signalDayBreakdown)
const sourceBreakdown = computed(() => sourceStrata(result.value, dayBreakdown.value))
const limitStudy = computed(() => result.value?.limitUpStudy)
const limitRows = computed(() => (limitStudy.value?.summary || []).filter(row =>
  row.cohort === selectedCohort.value && row.horizon === selectedHorizon.value))
const limitContrasts = computed(() => (limitStudy.value?.pairedContrasts || []).filter(row =>
  row.cohort === selectedCohort.value && row.horizon === selectedHorizon.value))
const limitCoverage = computed(() => {
  const days = limitStudy.value?.coverage || []
  return { requested: days.length, comparable: days.filter(row => row.studyStatus === 'COMPARABLE').length,
    uRows: days.reduce((total, row) => total + (row.uRows || 0), 0),
    matchedClose: days.reduce((total, row) => total + (row.matchedClose || 0), 0),
    validDirection: days.reduce((total, row) => total + (row.validStockDirection || 0), 0) }
})
const leaveOneDayOutText = computed(() => {
  const audit = chosenSummary.value?.leaveOneDayOutExcess
  if (!audit) return '旧结果未保存逐日剔一敏感性；不读取今日数据补齐。'
  if (audit.comparableDays < 2) return `仅 ${audit.comparableDays} 个可比较事件日，无法逐日剔一。`
  const range = `${formatPct(audit.minPct)} ～ ${formatPct(audit.maxPct)}`
  const crossesZero = audit.minPct <= 0 && audit.maxPct >= 0
  return `${audit.comparableDays} 个可比较日；每次剔除其中一日后的等权超额范围 ${range}。${crossesZero ? '区间含零，方向对单日敏感。' : '单次剔除未改变符号，但不等于显著或可交易。'}`
})
const timingFlagged = computed(() => {
  const audit = result.value?.inputTimingAudit
  if (!audit) return []
  return [...(audit.flow?.days || []).map(row => ({ ...row, type: 'Level‑2 成交' })),
    ...(audit.price?.days || []).map(row => ({ ...row, type: '复权日线' }))]
    .filter(row => !row.present || row.modifiedAfterTradeDay)
    .sort((a, b) => a.day.localeCompare(b.day) || a.type.localeCompare(b.type))
})
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
const point = value => Number.isFinite(value) ? formatPct(value).replace('%', ' pp') : '未知'
const directionName = { IMPROVING: '改善', WEAKENING: '恶化' }
const limitStatusName = { COMPARABLE: '可比较', MISSING_LIMIT_LIST: '涨停名单缺档', MISSING_FLOW: 'Level‑2 缺档',
  SOURCE_NOT_COMPARABLE: '来源不可比', MARKET_UNAVAILABLE_OR_FLAT: '市场未知／持平',
  NO_VALID_U_PRICE: 'U股复权价格不可用', NO_VALID_STOCK_DIRECTION: 'U股资金方向不可用', NO_ELIGIBLE_U: '无合格U股' }
const sensitivityRange = audit => !audit ? '旧结果未保存' : audit.comparableDays < 2
  ? `不足两日（${audit.comparableDays} 日）` : `${point(audit.minPct)} ～ ${point(audit.maxPct)}`
const resultLabel = row => row.status === 'PENDING' ? '未到期' : row.status === 'MISSING_PRICE' ? '价格缺失' : formatPct(row.returnPct)
const entryGateName = { PENDING: '次日未到', MISSING_BAR: '缺日线', MISSING_PRICE: '价缺失', INVALID_OHLC: '价关系异常', UNKNOWN_VOLUME: '量未知', NO_VOLUME: '零成交量', ONE_PRICE_SESSION: '单一价位', PRICE_REFERENCE_ONLY: '仅价格参考' }
const entryCounts = row => row.entryGateCounts ? Object.entries(row.entryGateCounts).map(([key, count]) => `${entryGateName[key] || key} ${count}`).join(' · ') : '旧结果未保存'
const drawdownSummary = row => row.closeDrawdownObserved == null ? '旧结果未保存' : row.closeDrawdownObserved ? `${formatPct(row.medianMaxCloseDrawdownPct)} · ${row.closeDrawdownObserved}/${row.events} 条路径` : `不可计算 · 0/${row.events} 条路径`
const drawdownLabel = row => !row.closeDrawdownStatus ? '旧结果未保存' : row.closeDrawdownStatus === 'PENDING' ? '未到期' : row.closeDrawdownStatus === 'MISSING_PRICE' ? '路径缺价格' : `${formatPct(row.maxCloseDrawdownPct)}${row.drawdownTroughDay ? `（${row.drawdownPeakDay} → ${row.drawdownTroughDay}）` : '（未出现回撤）'}`
const dayPct = (day, key) => day.pending === day.events ? '未到期' : formatPct(day[key])
onBeforeUnmount(() => { sequence++; detailSequence++; clearTimeout(timer) })
</script>

<template>
  <section class="panel validation-panel" aria-labelledby="validation-title">
    <div class="section-heading"><div><span class="eyebrow">OUTCOME STUDY · RESEARCH ONLY</span><h2 id="validation-title">事件后续验证</h2></div><span class="hint">训练／隔离／样本外明确分开</span></div>
    <p class="footnote">固定比较日级主动成交事件触发后 1／3／5 个交易日的收盘到收盘价格变化；训练／样本外仅按交易日期切分，尚非严格 PIT。事件只在触发日数据就绪后可识别。次日日线门槛只检查可观察性及单一价位，不证明排队成交。收盘路径回撤要求沿途价格齐全，不代表盘中或策略回撤。这里不是买点、卖点或可成交收益。</p>
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
      <p v-if="result.signalDaysExcludedSource?.length" class="footnote validation-source-warning">来源不可直接比较：已排除 {{ result.signalDaysExcludedSource.length }} 个事件日（{{ result.signalDaysExcludedSource.map(item => `${item.day} ${sourcePair(result, item.day)}`).join('；') }}）。这些日期未进入下方事件数或后续统计。</p>
      <p v-if="result.signalDaysExcludedSource == null" class="footnote validation-source-warning">旧研究未保存跨来源排除记录；无法核验是否执行当前来源门槛，须重新计算后才能按当前口径比较。</p>
      <p v-if="mixedSourceWarning(result)" class="footnote validation-source-warning">研究窗口同时包含已校准旧格式与正式新格式 Level‑2；即使排除了交界日，训练／隔离／样本外的差异仍可能混有来源与时期效应。</p>
      <p v-if="result.inputTimingAudit" class="footnote validation-source-warning">输入时序：Level‑2 文件 {{ result.inputTimingAudit.flow.present }}/{{ result.inputTimingAudit.flow.requested }} 存在、{{ result.inputTimingAudit.flow.modifiedAfterTradeDay }} 日最后修改晚于交易日；复权日线 {{ result.inputTimingAudit.price.present }}/{{ result.inputTimingAudit.price.requested }} 存在、{{ result.inputTimingAudit.price.modifiedAfterTradeDay }} 日最后修改晚于交易日。修改时间不能证明首次可得时间；严格 PIT 未验收。</p>
      <p v-else class="footnote validation-source-warning">旧研究未保存输入文件时序审计；不能据此认定为严格 PIT 样本外结果。</p>
      <details v-if="result.inputTimingAudit" class="validation-event validation-day-breakdown"><summary>输入时序异常／缺档明细 · {{ timingFlagged.length }} 项</summary><p class="footnote">只列缺档或文件最后修改日期晚于交易日的记录；其余文件也未证明当时可得。复制、回填和保留原时间戳均可改变这种线索的含义。</p><div v-if="timingFlagged.length" class="table-scroll"><table class="validation-table"><thead><tr><th>交易日</th><th>输入</th><th>本地最后修改时间</th><th>线索</th></tr></thead><tbody><tr v-for="row in timingFlagged" :key="row.type + row.day"><th scope="row">{{ row.day }}</th><td>{{ row.type }}</td><td>{{ row.modifiedAtLocal || '无文件' }}</td><td>{{ row.present ? '晚于交易日' : '缺档' }}</td></tr></tbody></table></div><p v-else class="footnote">未发现缺档或晚修改文件；这仍不能证明历史当时可得。</p></details>
      <div class="validation-filters"><label>样本分段<select v-model="selectedCohort"><option v-for="(name, key) in cohortName" :key="key" :value="key">{{ name }}</option></select></label><label>后续交易日<select v-model.number="selectedHorizon"><option v-for="day in horizons" :key="day" :value="day">后 {{ day }} 日</option></select></label><span>{{ cohortName[selectedCohort] }} · 已观察 {{ counts.observed.toLocaleString() }} 条 · 未到期 {{ counts.pending.toLocaleString() }} 条 · 各类最多 {{ counts.days }} 个已观察事件日</span></div>
      <div v-if="rows.length" class="table-scroll"><table class="validation-table"><thead><tr><th>事件</th><th>触发数</th><th>已观察／未到期／缺价格</th><th>次日日线门槛</th><th>已观察／触发日</th><th>平均收益</th><th>收盘路径回撤中位</th><th>同日基准超额</th><th>按事件日等权超额</th><th>基准平均覆盖</th></tr></thead><tbody><tr v-for="row in rows" :key="row.rule"><td>{{ ruleName[row.rule] || row.rule }}</td><td>{{ row.events.toLocaleString() }}</td><td>{{ row.observed.toLocaleString() }} / {{ row.pending.toLocaleString() }} / {{ row.missingPrice.toLocaleString() }}</td><td>{{ entryCounts(row) }}</td><td>{{ row.signalDays }} / {{ row.triggerDays ?? '旧结果未知' }}</td><td>{{ formatPct(row.meanReturnPct) }}</td><td>{{ drawdownSummary(row) }}</td><td>{{ formatPct(row.meanExcessPct) }}</td><td>{{ formatPct(row.equalDayMeanExcessPct) }}</td><td>{{ row.benchmarkPoolMeanN == null ? '未知' : row.benchmarkPoolMeanN.toFixed(0) + ' 只' }}</td></tr></tbody></table></div>
      <p v-else class="footnote">此分段／期限没有已识别事件；不补零，也不推出无效结论。</p>
      <section class="validation-limit-study" aria-label="涨停收盘股专项研究">
        <h3>涨停收盘股 · 市场 × 个股资金变化</h3>
        <p class="footnote">独立母样本：本地 <code>limit_list_d</code> 的 U，排除 ST 与非沪深A股；不按固定涨幅猜板。市场变化取相邻日共同有效股票的成交额加权主动净额比，并排除当日 U 股；个股变化取自身净额比差。正／负变化分四格，平值和未知单列。所有条件均为收盘后证据。</p>
        <template v-if="limitStudy">
          <p class="footnote">事件日 {{ limitCoverage.comparable }}/{{ limitCoverage.requested }} 可比较；源 U {{ limitCoverage.uRows }} 条（含未通过后续核验日）、同日收盘核对及复权价格有效 {{ limitCoverage.matchedClose }} 条、个股资金变化有效 {{ limitCoverage.validDirection }} 条；后两项仅统计实际执行核验的日期。文件／股票缺失不补零。涨停源 {{ limitStudy.sourceTiming?.present ?? '未知' }}/{{ limitStudy.sourceTiming?.requested ?? '未知' }} 文件存在，{{ limitStudy.sourceTiming?.modifiedAfterTradeDay ?? '未知' }} 日最后修改晚于交易日；严格 PIT 未验收。</p>
          <div class="table-scroll"><table class="validation-table"><thead><tr><th>市场净额比变化</th><th>个股净额比变化</th><th>触发／已观察／缺价</th><th>可比较事件日</th><th>后续平均收益</th><th>相对同日U均值 · 按日等权</th><th>剔一日范围</th></tr></thead><tbody><tr v-for="row in limitRows" :key="row.marketDirection + row.stockDirection"><td>{{ directionName[row.marketDirection] }}</td><td>{{ directionName[row.stockDirection] }}</td><td>{{ row.events }} / {{ row.observed }} / {{ row.missingPrice }}</td><td>{{ row.comparableDays }}</td><td>{{ formatPct(row.meanReturnPct) }}</td><td>{{ point(row.equalDayMeanExcessPct) }}</td><td>{{ sensitivityRange(row.leaveOneDayOutExcess) }}</td></tr></tbody></table></div>
          <p class="footnote">同日 U 均值只作价格基准；市场改善／恶化跨日比较混有时期效应。真正可直接配对的是同一事件日的个股改善组与恶化组：</p>
          <div class="table-scroll"><table class="validation-table"><thead><tr><th>当日市场状态</th><th>两组均有后续价的日期</th><th>同日配对收益差 · 改善减恶化</th><th>剔一日范围</th></tr></thead><tbody><tr v-for="row in limitContrasts" :key="row.marketDirection"><td>{{ directionName[row.marketDirection] }}</td><td>{{ row.pairedDays }}</td><td>{{ point(row.equalDayMeanSpreadPct) }}</td><td>{{ sensitivityRange(row.leaveOneDayOutSpread) }}</td></tr></tbody></table></div>
          <details class="validation-event validation-day-breakdown"><summary>涨停专项逐日覆盖 · {{ limitCoverage.requested }} 个事件日</summary><p class="footnote">“可比较”只代表文件、来源、市场变化、至少一只 U 股复权价格和可辨资金方向通过本层门槛；不代表可成交。市场共同样本排除当日 U 股；未运行的价格核对显示“未查”而非零。</p><div class="table-scroll"><table class="validation-table"><thead><tr><th>日期</th><th>状态</th><th>源 U／价格有效／资金有效</th><th>市场共同样本</th><th>市场变化</th><th>缺复权／收盘冲突</th></tr></thead><tbody><tr v-for="day in limitStudy.coverage" :key="day.day"><th scope="row">{{ day.day }}</th><td>{{ limitStatusName[day.studyStatus] || day.studyStatus }}</td><td>{{ day.uRows ?? '未知' }} / {{ day.matchedClose ?? '未查' }} / {{ day.validStockDirection ?? '未查' }}</td><td>{{ day.market?.commonStocks ?? '不可比' }}</td><td>{{ point(day.market?.deltaPP) }}</td><td>{{ day.missingAdjustedClose ?? '未查' }} / {{ day.mismatchedRawClose ?? '未查' }}</td></tr></tbody></table></div></details>
          <p class="footnote">四格与配对差只说明历史分层；收盘后才能观察 U、资金和市场状态，不能解释为收盘买入收益、次日买点或因子显著性。</p>
        </template>
        <p v-else class="footnote">旧研究未保存涨停专项；不读取最新涨停名单补齐。重新计算可按当前口径生成。</p>
      </section>
      <details v-if="rows.length" class="validation-event validation-day-breakdown">
        <summary>逐事件日核对 · {{ cohortName[selectedCohort] }}后 {{ selectedHorizon }} 日</summary>
        <p class="footnote">每行是一个触发日，同日多股不当作独立交易日；期限重叠也不是独立确认。只读保存的逐日摘要，不从最新数据补旧快照。</p>
        <label>事件类型 <select :value="chosenRule" @change="selectedRule = $event.target.value"><option v-for="row in rows" :key="row.rule" :value="row.rule">{{ ruleName[row.rule] || row.rule }}</option></select></label>
        <p v-if="dayBreakdown == null" class="footnote">旧结果未保存逐事件日汇总。</p>
        <div v-else-if="dayBreakdown.length" class="table-scroll"><table class="validation-table"><thead><tr><th>触发日</th><th>前日→当日来源</th><th>触发数</th><th>已观察／未到期／缺价格</th><th>当日事件平均收益</th><th>同日基准</th><th>当日平均超额</th><th>基准覆盖</th></tr></thead><tbody><tr v-for="day in dayBreakdown" :key="day.day"><th scope="row">{{ day.day }}</th><td>{{ sourcePair(result, day.day) }}</td><td>{{ day.events.toLocaleString() }}</td><td>{{ day.observed }} / {{ day.pending }} / {{ day.missingPrice }}</td><td>{{ dayPct(day, 'meanReturnPct') }}</td><td>{{ dayPct(day, 'benchmarkPct') }}</td><td>{{ dayPct(day, 'meanExcessPct') }}</td><td>{{ day.benchmarkN == null ? '未到期' : day.benchmarkN + ' 只' }}</td></tr></tbody></table></div>
        <p v-else class="footnote">所选事件类型没有触发日。</p>
        <p class="footnote">逐日剔一敏感性：{{ leaveOneDayOutText }}</p>
        <template v-if="sourceBreakdown?.length">
          <h4>来源分层 · 仅描述</h4>
          <div class="table-scroll"><table class="validation-table"><thead><tr><th>前日→当日来源</th><th>触发日</th><th>可比较日</th><th>可比较事件</th><th>按日等权超额</th></tr></thead><tbody><tr v-for="source in sourceBreakdown" :key="source.label"><th scope="row">{{ source.label }}</th><td>{{ source.triggerDays }}</td><td>{{ source.comparableDays }}</td><td>{{ source.comparableEvents }}</td><td>{{ formatPct(source.equalDayMeanExcessPct) }}</td></tr></tbody></table></div>
          <p class="footnote">分层均值按各来源组中可比较触发日等权；来源通常与历史时期重合，组间差异不能归因于数据格式。</p>
        </template>
      </details>
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
            <div class="table-scroll"><table><thead><tr><th>期限</th><th>目标交易日</th><th>结果状态</th><th>后续收益</th><th>收盘路径最大回撤</th><th>同日基准</th><th>超额</th></tr></thead><tbody><tr v-for="row in event.rows" :key="row.horizon"><td>后 {{ row.horizon }} 日</td><td>{{ row.targetDay || '日历未覆盖' }}</td><td>{{ row.status === 'OBSERVED' ? '已观察' : row.status === 'PENDING' ? '未到期' : '价格缺失' }}</td><td>{{ resultLabel(row) }}</td><td>{{ drawdownLabel(row) }}</td><td>{{ row.status === 'OBSERVED' ? formatPct(row.benchmarkPct) : '不可比较' }}</td><td>{{ row.status === 'OBSERVED' ? formatPct(row.excessPct) : '不可比较' }}</td></tr></tbody></table></div>
          </details>
        </template>
      </div>
      <details><summary>研究口径与局限</summary><p v-for="item in result.limitations" :key="item" class="footnote">{{ item }}</p><p class="footnote">来源标识 {{ result.sourceIdentity }}。旧快照没有此结果时，不用新数据回填。</p></details>
    </template>
  </section>
</template>
