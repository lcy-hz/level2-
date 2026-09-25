<script setup>
import { computed, ref, watch } from 'vue'
import { filterCandidates } from '../candidateFilters.js'
import KlineTrigger from './KlineTrigger.vue'
import DetailEvidence from './DetailEvidence.vue'

const props = defineProps({ cards: { type: Array, required: true }, day: { type: String, required: true },
  frozen: { type: Boolean, default: false }, snapshotCharts: { type: Object, default: () => ({}) },
  initialFilters: { type: Object, default: () => ({}) } })
const emit = defineEmits(['chart-loaded', 'detail-loaded', 'filters-change'])
const query = ref(props.initialFilters.search || '')
const label = ref(props.initialFilters.filter || 'all')
const order = ref(props.initialFilters.sort || 'default')
const direction = ref(props.initialFilters.direction || 'all')
const page = ref(1)
const selected = ref(null)
const labels = computed(() => [...new Set(props.cards.map(card => card.label))].sort())
const matches = computed(() => filterCandidates(props.cards, { query: query.value, label: label.value, direction: direction.value, order: order.value }))
const visible = computed(() => matches.value.slice((page.value - 1) * 24, page.value * 24))
const pages = computed(() => Math.max(1, Math.ceil(matches.value.length / 24)))
const resetPage = () => { page.value = 1 }
const money = value => value == null ? '未知' : Math.abs(value) >= 1e8 ? `${(value / 1e8).toFixed(2)} 亿` : `${(value / 1e4).toFixed(1)} 万`
const percent = value => value == null ? '未知' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
const tone = value => value == null ? '' : value > 0 ? 'positive' : value < 0 ? 'negative' : ''
watch([query, label, direction, order], () => emit('filters-change', { search: query.value, filter: label.value, direction: direction.value, sort: order.value }))
</script>

<template>
  <section class="panel" aria-labelledby="candidates-title">
    <div class="section-heading"><div><span class="eyebrow">CANDIDATE EVIDENCE</span><h2 id="candidates-title">候选形成与变化</h2></div><span class="hint">全库 {{ cards.length.toLocaleString() }} 只 · 非交易建议</span></div>
    <div class="filters">
      <label>名称或代码<input v-model="query" @input="resetPage" placeholder="搜索 000977 / 浪潮" /></label>
      <label>候选类型<select v-model="label" @change="resetPage"><option value="all">全部</option><option v-for="item in labels" :key="item">{{ item }}</option></select></label>
      <label>价格方向<select v-model="direction" @change="resetPage"><option value="all">全部</option><option value="up">上涨</option><option value="down">下跌</option><option value="flat">平盘</option></select></label>
      <label>排序<select v-model="order" @change="resetPage"><option value="default">原报告顺序</option><option value="net">主动净额降序</option><option value="ret">涨跌幅降序</option><option value="amount">成交额降序</option></select></label>
    </div>
    <p class="footnote">筛选结果 {{ matches.length.toLocaleString() }} 只；分页仅改变展示，不改变数据和计算口径。</p>
    <div class="candidate-grid">
      <article v-for="card in visible" :key="card.code" class="candidate-card">
        <span class="badge">{{ card.label }}</span><strong>{{ card.name }} <KlineTrigger :code="card.code" :name="card.name" :day="day" :frozen="frozen" :snapshot-charts="snapshotCharts" @loaded="emit('chart-loaded', $event)" /></strong>
        <span>收盘 {{ card.close ?? '未知' }} · VWAP {{ card.vwap ?? '未知' }}</span>
        <span>涨跌 <b :class="tone(card.ret)">{{ percent(card.ret) }}</b> · 主动净额 <b :class="tone(card.net)">{{ money(card.net) }}</b></span>
        <span class="muted">十档 买 {{ card.bid?.toLocaleString() ?? '未知' }} / 卖 {{ card.ask?.toLocaleString() ?? '未知' }}</span>
        <button type="button" class="card-detail" @click="selected = card">查看证据</button>
      </article>
    </div>
    <div class="pagination"><button :disabled="page <= 1" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page >= pages" @click="page++">下一页</button></div>
    <div v-if="selected" class="dialog-backdrop" @click.self="selected = null">
      <section class="dialog" role="dialog" aria-modal="true" :aria-label="selected.name + '证据详情'">
        <button class="close" @click="selected = null">关闭</button><span class="eyebrow">DAILY EVIDENCE</span><h2>{{ selected.name }} <KlineTrigger :code="selected.code" :name="selected.name" :day="day" :frozen="frozen" :snapshot-charts="snapshotCharts" @loaded="emit('chart-loaded', $event)" /></h2>
        <p>{{ selected.label }} · 涨跌 {{ percent(selected.ret) }} · 主动净额 {{ money(selected.net) }} · 净额比 {{ percent(selected.ratio) }}</p>
        <p>方向状态：{{ selected.directionStatus ?? '未知' }}；未知方向金额：{{ money(selected.unknownAmount) }}；关联单身份：{{ selected.parentIdentityStatus ?? '未验证' }}。</p>
        <DetailEvidence :key="selected.code" :card="selected" :day="day" :frozen="frozen" @loaded="emit('detail-loaded', $event)" />
        <details><summary>逐日历史证据</summary><pre>{{ JSON.stringify(selected.history ?? [], null, 2) }}</pre></details>
        <p class="footnote">K 线悬浮每次读取本地最新文件；快照只展示保存时已加载的图表和深查。研究证据不构成交易确认。</p>
      </section>
    </div>
  </section>
</template>
