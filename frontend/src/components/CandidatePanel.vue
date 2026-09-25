<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { filterCandidates, futureCloseChange, priceDirection, stateNarrative, summarizeCandidatePools } from '../candidateFilters.js'
import KlineTrigger from './KlineTrigger.vue'
import DetailEvidence from './DetailEvidence.vue'

const props = defineProps({ cards: { type: Array, required: true }, day: { type: String, required: true },
  lists: { type: Object, default: () => ({}) },
  frozen: { type: Boolean, default: false }, snapshotCharts: { type: Object, default: () => ({}) },
  initialFilters: { type: Object, default: () => ({}) }, stateView: { type: Object, default: null } })
const emit = defineEmits(['chart-loaded', 'detail-loaded', 'filters-change'])
const query = ref(props.initialFilters.search || '')
const label = ref(props.initialFilters.filter || 'all')
const order = ref(props.initialFilters.sort || 'default')
const direction = ref(props.initialFilters.direction || 'all')
const orderDirection = ref(props.initialFilters.sortDirection || 'desc')
const stateChange = ref(props.initialFilters.stateChange || 'all')
const stateContinuity = ref(props.initialFilters.stateContinuity || 'all')
const page = ref(1)
const selected = ref(null)
const detailDialog = ref(null)
const labels = computed(() => [...new Set(props.cards.map(card => card.label))].sort())
const poolSummary = computed(() => summarizeCandidatePools(props.lists, props.cards))
const linkedView = computed(() => props.stateView?.day === props.day ? props.stateView : null)
const states = computed(() => new Map((linkedView.value?.stocks || []).map(stock => [stock.code, stock])))
const selectedState = computed(() => selected.value ? states.value.get(selected.value.code) || null : null)
const effectiveOrder = computed(() => (
  (!linkedView.value && order.value.startsWith('state')) ||
  (!linkedView.value?.applicable && ['stateSlope', 'stateImprove'].includes(order.value))
) ? 'default' : order.value)
const focusOnly = computed(() => !query.value.trim() && label.value === 'all' && direction.value === 'all' &&
  stateChange.value === 'all' && stateContinuity.value === 'all')
const matches = computed(() => filterCandidates(props.cards, { query: query.value, label: label.value,
  direction: direction.value, order: effectiveOrder.value, orderDirection: orderDirection.value,
  stateChange: linkedView.value?.applicable ? stateChange.value : 'all',
  stateContinuity: linkedView.value ? stateContinuity.value : 'all', stateView: linkedView.value,
  focusOnly: focusOnly.value }))
const visible = computed(() => matches.value.slice((page.value - 1) * 24, page.value * 24))
const pages = computed(() => Math.max(1, Math.ceil(matches.value.length / 24)))
const resetPage = () => { page.value = 1 }
function openFromCard(event, card) {
  // The card body is a pointer shortcut; nested K-line and detail buttons
  // keep their own action, while the explicit detail button stays keyboardable.
  if (event.target instanceof Element && event.target.closest('button, a, input, select, textarea')) return
  selected.value = card
}
function closeDetail() {
  detailDialog.value?.close()
  selected.value = null
}
function closeOnBackdrop(event) {
  const dialog = detailDialog.value
  if (!dialog || event.target !== dialog) return
  const bounds = dialog.getBoundingClientRect()
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closeDetail()
}
watch(selected, async card => {
  if (!card) return
  await nextTick()
  if (selected.value === card && detailDialog.value && !detailDialog.value.open) detailDialog.value.showModal()
})
const finite = value => typeof value === 'number' && Number.isFinite(value)
const money = value => !finite(value) ? '未知' : Math.abs(value) >= 1e8 ? `${(value / 1e8).toFixed(2)} 亿` : `${(value / 1e4).toFixed(1)} 万`
const percent = value => !finite(value) ? '未知' : `${value > 0 ? '+' : ''}${value !== 0 && Math.abs(value) < .005 ? value.toExponential(2) : value.toFixed(2)}%`
const pp = value => !finite(value) ? '未知' : `${value > 0 ? '+' : ''}${value !== 0 && Math.abs(value) < .005 ? value.toExponential(2) : value.toFixed(2)} pp`
const tone = value => !finite(value) ? '' : value > 0 ? 'positive' : value < 0 ? 'negative' : ''
const delta = stock => linkedView.value?.applicable ? stock?.viewDelta : stock?.delta
const streak = stock => !finite(stock?.streak) ? '未知' : `${stock.leftCensored ? '至少 ' : ''}${stock.streak} 日`
const improvement = stock => !stock || stock.expected <= 1 ? '不适用' : !finite(stock.improve) ? '未知' : `${stock.improveCensored ? '至少 ' : ''}${stock.improve} 次`
const coverage = stock => stock ? `${stock.valid}/${stock.expected} 日${stock.status === 'AVAILABLE' ? '' : ' · 不完整'}` : '未计算'
watch(linkedView, () => { page.value = 1 })
watch([query, label, direction, order, orderDirection, stateChange, stateContinuity], () => {
  page.value = 1
  emit('filters-change', { search: query.value, filter: label.value, direction: direction.value,
    sort: order.value, sortDirection: orderDirection.value, stateChange: stateChange.value,
    stateContinuity: stateContinuity.value })
})
watch(pages, count => { if (page.value > count) page.value = count })
</script>

<template>
  <section class="panel" aria-labelledby="candidates-title">
    <div class="section-heading"><div><span class="eyebrow">CANDIDATE EVIDENCE</span><h2 id="candidates-title">候选形成与变化</h2></div><span class="hint">全库 {{ cards.length.toLocaleString() }} 只 · 非交易建议</span></div>
    <p class="footnote" v-if="poolSummary">重点名单按报告内冻结的重点池展示：{{ poolSummary.pools.map(pool => `${pool.name} ${pool.count} 只`).join(' · ') }}{{ poolSummary.extra.length ? `；另单独关注 ${poolSummary.extra.join('、')}` : '' }}。池间可重叠；默认重点名单与全库互斥标签不是同一个筛选口径。</p>
    <p class="footnote" v-else>此报告未保存重点池名单；仅按已冻结的卡片标记展示默认重点股，不反推名单形成门槛。</p>
    <details class="candidate-method"><summary>候选标签与历史收益口径</summary><p>当前生成器的重点池先要求目标日成交额 ≥ 2 亿元，池内按各自指标排序；实际成员以上述冻结名单为准。全库标签按顺序互斥归类：方向未知单列；上涨且净买入为主动推动；跌幅 0% 至 3% 且净买入为下跌承接；涨跌幅 -1% 至 +3% 且净卖出为被动承接候选；其余上涨且净卖出为高位分歧；剩余为弱势／其他。这些是描述标签，不是吸筹、派发或买卖确认。</p><p>逐日历史中的后 1／3 日仅为未复权的原始收盘变化，且只覆盖目标日仍存续的股票；不能作为无偏样本外收益验证。</p></details>
    <div class="filters">
      <label>名称或代码<input v-model="query" @input="resetPage" placeholder="搜索 000977 / 浪潮" /></label>
      <label>候选类型<select v-model="label" @change="resetPage"><option value="all">全部</option><option v-for="item in labels" :key="item">{{ item }}</option></select></label>
      <label>价格方向<select v-model="direction" @change="resetPage"><option value="all">全部</option><option value="up">上涨</option><option value="down">下跌</option><option value="flat">平盘</option></select></label>
      <label>排序指标<select v-model="order" @change="resetPage"><option value="default">报告记录顺序</option><option value="net">主动净额</option><option value="ret">涨跌幅</option><option value="amount">成交额</option><option value="stateLevel" :disabled="!linkedView">当前净额比 %</option><option value="stateDelta" :disabled="!linkedView">较前日变化 pp</option><option value="stateWeighted" :disabled="!linkedView">窗口加权净额比 %</option><option value="stateSlope" :disabled="!linkedView?.applicable">窗口斜率 pp/日</option><option value="stateStreak" :disabled="!linkedView">可观察同向日数</option><option value="stateImprove" :disabled="!linkedView?.applicable">连续改善次数</option></select></label>
      <label>资金变化<select v-model="stateChange" :disabled="!linkedView?.applicable"><option value="all">全部</option><option value="improve">改善</option><option value="worsen">恶化</option><option value="flat">持平</option><option value="unknown">未知</option></select></label>
      <label>连续性<select v-model="stateContinuity" :disabled="!linkedView"><option value="all">全部</option><option value="known">可判定</option><option value="unknown">未知</option></select></label>
      <label>排序方向<select v-model="orderDirection" :disabled="effectiveOrder === 'default'"><option value="desc">倒序 · 大→小</option><option value="asc">正序 · 小→大</option></select></label>
    </div>
    <p class="footnote">{{ focusOnly ? `默认显示 ${matches.length.toLocaleString()} 只重点深查股；输入名称／代码或选择条件可筛选 ${cards.length.toLocaleString()} 只全库股票。` : `筛选结果 ${matches.length.toLocaleString()} / ${cards.length.toLocaleString()} 只。` }}{{ linkedView ? `连续指标采用已应用 ${linkedView.window} 交易日（${linkedView.dates[0]}—${linkedView.dates.at(-1)}）${!linkedView.applicable ? '；窗口内变化筛选与趋势排序暂停' : ''}` : frozen ? '此快照未保存当前连续窗口，连续筛选／排序暂停且不补读' : '连续指标须先应用同日报告的观察窗口；连续筛选／排序暂不生效' }}。报告记录顺序：新报告按代码固定排序，历史快照保持保存时的原顺序；未知排序值始终排最后，筛选与分页不改变原报告事实。</p>
    <div class="candidate-grid">
      <article v-for="card in visible" :key="card.code" class="candidate-card" @click="openFromCard($event, card)">
        <div class="candidate-tags"><span class="badge">{{ card.label }}</span><span class="price-direction" :class="priceDirection(card.returnSign).tone">{{ priceDirection(card.returnSign).text }}</span></div><strong>{{ card.name }} <KlineTrigger :code="card.code" :name="card.name" :day="day" :frozen="frozen" :snapshot-charts="snapshotCharts" @loaded="emit('chart-loaded', $event)" /></strong>
        <span>收盘 {{ card.close ?? '未知' }} · VWAP {{ card.vwap ?? '未知' }}</span>
        <span>涨跌 <b :class="tone(card.ret)">{{ percent(card.ret) }}</b> · 主动净额 <b :class="tone(card.net)">{{ money(card.net) }}</b></span>
        <span class="muted">十档 买 {{ card.bid?.toLocaleString() ?? '未知' }} / 卖 {{ card.ask?.toLocaleString() ?? '未知' }}</span>
        <template v-if="linkedView"><span>净额比 <b :class="tone(states.get(card.code)?.level)">{{ percent(states.get(card.code)?.level) }}</b> · 较前日 {{ pp(delta(states.get(card.code))) }}</span><span class="muted">同向 {{ streak(states.get(card.code)) }} · 连续改善 {{ improvement(states.get(card.code)) }} · 有效 {{ coverage(states.get(card.code)) }}</span></template>
        <button type="button" class="card-detail" @click.stop="selected = card">查看证据</button>
      </article>
    </div>
    <div class="pagination"><button :disabled="page <= 1" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page >= pages" @click="page++">下一页</button></div>
    <dialog v-if="selected" ref="detailDialog" class="dialog" :aria-label="selected.name + '证据详情'" @close="selected = null" @click="closeOnBackdrop">
        <button class="close" @click="closeDetail">关闭</button><span class="eyebrow">DAILY EVIDENCE</span><h2>{{ selected.name }} <KlineTrigger :code="selected.code" :name="selected.name" :day="day" :frozen="frozen" :snapshot-charts="snapshotCharts" @loaded="emit('chart-loaded', $event)" /></h2>
        <p>{{ selected.label }} · 涨跌 {{ percent(selected.ret) }} · 主动净额 {{ money(selected.net) }} · 净额比 {{ percent(selected.ratio) }}</p>
        <p>方向状态：{{ selected.directionStatus ?? '未知' }}；未知方向金额：{{ money(selected.unknownAmount) }}；关联单身份：{{ selected.parentIdentityStatus ?? '未验证' }}。</p>
        <section v-if="linkedView" class="candidate-state-evidence" aria-label="连续状态证据"><p class="footnote">已应用 {{ linkedView.window }} 交易日（{{ linkedView.dates[0] }}—{{ linkedView.dates.at(-1) }}）{{ linkedView.applicable ? '' : '；较前日比较使用窗口外上一交易日有效数据，结构变化统计仍不适用' }}。</p><p>{{ stateNarrative(selected, selectedState, linkedView.applicable) }}</p><div class="table-scroll"><table class="candidate-state-table"><thead><tr><th>指标</th><th>当前水平</th><th>较前日变化</th><th>窗口趋势</th><th>持续性</th><th>质量</th></tr></thead><tbody><tr><th>主动净额比</th><td data-label="当前水平">{{ percent(selectedState?.level) }}</td><td data-label="较前日变化">{{ pp(delta(selectedState)) }}</td><td data-label="窗口趋势">加权 {{ percent(selectedState?.weighted) }} · 斜率 {{ linkedView.applicable ? pp(selectedState?.slope) + '/日' : '不适用' }}</td><td data-label="持续性">同向 {{ streak(selectedState) }} · 改善 {{ improvement(selectedState) }}</td><td data-label="质量">方向 {{ coverage(selectedState) }}</td></tr><tr><th>成交额</th><td data-label="当前水平">{{ money(selectedState?.amount) }}</td><td data-label="较前日变化">{{ percent(selectedState?.amountChange) }}</td><td data-label="窗口趋势">均值 {{ money(selectedState?.meanAmount) }}</td><td data-label="持续性">未定义</td><td data-label="质量">成交额 {{ selectedState ? `${selectedState.amountValid}/${selectedState.expected} 日` : '未计算' }}</td></tr><tr><th>价格</th><td data-label="当前水平">报告收盘 {{ selected.close ?? '未知' }}</td><td data-label="较前日变化">{{ percent(selected.ret) }}</td><td data-label="窗口趋势">区间 {{ percent(selectedState?.priceReturn) }}</td><td data-label="持续性">未定义</td><td data-label="质量">{{ selectedState?.priceReturn == null ? '复权价格覆盖不足' : '复权价格比值可用' }}</td></tr></tbody></table></div><details><summary>连续窗口逐日证据与反证</summary><p v-for="row in selectedState?.history || []" :key="row.day">{{ row.day }} · 成交额 {{ money(row.amount) }} · 净额比 {{ percent(row.ratio) }} · {{ row.reason || '方向记录可用' }}</p><p>当前连续指标仅为日级描述；十档末档与关联单身份不能单独证明盘中补单或被动吸筹。</p></details></section>
        <DetailEvidence :key="selected.code" :card="selected" :day="day" :frozen="frozen" @loaded="emit('detail-loaded', $event)" />
        <details><summary>信号轨迹／历史原始收盘变化</summary><p class="footnote">后 1／3 日从该行信号日原始收盘算至相应后续交易日原始收盘；未复权、未控制目标日存续样本选择，不是买卖点或无偏回测。</p><div v-if="selected.history?.length" class="table-scroll"><table class="history-table"><thead><tr><th>信号日</th><th>当时标签</th><th>当日涨跌</th><th>主动净额</th><th>后 1 日</th><th>后 3 日</th></tr></thead><tbody><tr v-for="row in selected.history" :key="row.day"><td data-label="信号日">{{ row.day }}</td><td data-label="当时标签">{{ row.label || '未知' }}</td><td data-label="当日涨跌" :class="tone(row.ret)">{{ percent(row.ret) }}</td><td data-label="主动净额" :class="tone(row.net)">{{ money(row.net) }}</td><td data-label="后 1 日" :class="tone(row.f1)">{{ futureCloseChange(row.f1) }}</td><td data-label="后 3 日" :class="tone(row.f3)">{{ futureCloseChange(row.f3) }}</td></tr></tbody></table></div><p v-else class="footnote">此报告未保存逐日历史证据，不读取当前数据补齐。</p></details>
        <p class="footnote">K 线悬浮每次读取本地最新文件；快照只展示保存时已加载的图表和深查。研究证据不构成交易确认。</p>
    </dialog>
  </section>
</template>

<style scoped>
.dialog { width: min(760px, calc(100% - 32px)); margin: auto; color: #e7f0fa; }
.dialog::backdrop { background: #000b; }
@media (max-width: 620px) {
  .history-table thead { display: none; }
  .history-table tbody tr { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border-bottom: 1px solid #30475d; }
  .history-table tbody td { display: grid; gap: 3px; padding: 7px; border: 0; text-align: left; white-space: normal; overflow-wrap: anywhere; }
  .history-table tbody td::before { content: attr(data-label); color: #9db5c8; font-size: 11px; }
}
</style>
