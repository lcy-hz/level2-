<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({ view: { type: Object, required: true }, names: { type: Object, required: true }, frozen: { type: Boolean, default: false } })
const scope = ref('latest')
const kind = ref('all')
const query = ref('')
const page = ref(1)
const kinds = [['SELL_EASING', '负值收敛'], ['SELL_WORSENING', '负值扩大'],
  ['SELL_TO_BUY', '净卖转净买'], ['BUY_TO_SELL', '净买转净卖']]
const currentDay = computed(() => props.view.dates.at(-1))
const all = computed(() => props.view.stocks.flatMap(stock => (stock.events || []).map(event => ({ ...event, code: stock.code }))))
const latest = computed(() => all.value.filter(event => event.triggerDay === currentDay.value))
const counts = computed(() => Object.fromEntries(kinds.map(([key]) => [key, latest.value.filter(event => event.kind === key).length])))
const filtered = computed(() => all.value.filter(event =>
  (scope.value === 'all' || event.triggerDay === currentDay.value) &&
  (kind.value === 'all' || event.kind === kind.value) &&
  (!query.value || `${event.code} ${props.names[event.code] || ''}`.toLowerCase().includes(query.value.trim().toLowerCase()))
).sort((a, b) => b.triggerDay.localeCompare(a.triggerDay) || a.code.localeCompare(b.code) || a.kind.localeCompare(b.kind)))
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / 20)))
const shown = computed(() => filtered.value.slice((page.value - 1) * 20, page.value * 20))
const precise = value => `${value > 0 ? '+' : ''}${value !== 0 && Math.abs(value) < .0005 ? value.toExponential(2) : value.toFixed(3)}`
const number = value => Number.isFinite(value) ? `${precise(value)} pp` : '未知'
const percent = value => Number.isFinite(value) ? `${precise(value)}%` : '未知'
const status = { ACTIVE: '仍满足延续条件', INVALIDATED: '已失效', RESOLVED: '已结束', UNKNOWN: '后续连续性未知' }
watch([scope, kind, query], () => { page.value = 1 })
watch(pages, count => { if (page.value > count) page.value = count })
</script>

<template>
  <section class="state-events" aria-labelledby="state-events-title">
    <div class="section-heading state-subheading"><div><span class="eyebrow">DAILY EVENT LOG</span><h3 id="state-events-title">日级事件观察</h3></div><span class="hint">{{ currentDay }} · 仅收盘后数据就绪可识别</span></div>
    <p v-if="!view.eventMethod" class="footnote">{{ frozen ? '此快照未保存日级事件层；不读取最新数据补齐。' : '当前窗口尚无事件层；请重新计算。' }}</p>
    <template v-else>
      <p class="footnote">{{ view.eventMethod }}。事件是事实记录，不是吸筹、支撑或买卖确认；单日窗口无窗口内相邻日，不触发事件。</p>
      <div class="event-counts"><button v-for="[key, title] in kinds" :key="key" :class="{active:kind === key}" @click="kind = kind === key ? 'all' : key"><span>{{ title }}</span><strong>{{ counts[key].toLocaleString() }}</strong></button></div>
      <div class="event-controls"><label>范围<select v-model="scope"><option value="latest">仅截止日触发</option><option value="all">窗口内全部事件</option></select></label><label>搜索<input v-model="query" placeholder="代码或名称" /></label><span>{{ filtered.length.toLocaleString() }} 条 · 每页 20 条</span></div>
      <div class="event-list"><article v-for="event in shown" :key="event.code + event.id" class="subpanel"><strong>{{ names[event.code] || '名称未知' }} {{ event.code }}</strong><span>{{ event.name }} · {{ event.triggerDay }}</span><p>前日 {{ event.previousDay }} → 触发日 {{ event.triggerDay }} · 净额比变化 {{ number(event.evidence.deltaPP) }}</p><details><summary>触发、失效与证据</summary><p>最早可识别：{{ event.firstRecognizableAt }}；{{ event.rule }}。</p><p>前日净额比 {{ percent(event.evidence.previousRatio) }}；触发日 {{ percent(event.evidence.currentRatio) }}。{{ event.invalidation }}。</p><p>截至 {{ event.statusAsOf }}：{{ status[event.status] || '未知' }}{{ event.endDay ? `（${event.endDay}）` : '' }}。{{ event.source }}。</p></details></article><p v-if="!shown.length" class="footnote">此范围无可识别事件；缺失或方向未知不会被补零成事件。</p></div>
      <div class="pagination"><button :disabled="page <= 1" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page >= pages" @click="page++">下一页</button></div>
    </template>
  </section>
</template>
