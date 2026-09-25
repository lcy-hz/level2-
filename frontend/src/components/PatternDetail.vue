<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { patternDetail } from '../api.js'
import { buildPatternChart } from '../patternChartModel.js'

const props = defineProps({ day: { type: String, required: true }, stock: { type: Object, required: true },
  initialEvent: { type: Object, required: true }, receipt: { type: String, default: '' },
  frozen: { type: Boolean, default: false }, snapshotDetails: { type: Object, default: () => ({}) },
  indicatorMethod: { type: String, default: '' }, level: { type: Number, default: null }, stateWindow: { type: Number, default: null } })
const emit = defineEmits(['close', 'detail-loaded'])
const detail = ref(null)
const error = ref('正在读取形态逐根证据…')
const selectedEventId = ref(props.initialEvent.eventId)
const indicator = ref('MACD')
const showMA = ref(true)
const showSignals = ref(true)
const selectedIndex = ref(null)
let request = 0
const selectedEvent = computed(() => props.stock.events.find(event => event.eventId === selectedEventId.value) || props.initialEvent)
const model = computed(() => buildPatternChart(detail.value, selectedEvent.value, { indicator: indicator.value, showMA: showMA.value, showSignals: showSignals.value }))
const candle = computed(() => selectedIndex.value == null ? null : detail.value?.bars[selectedIndex.value])
const date = computed(() => selectedIndex.value == null ? '未知' : detail.value?.dates[selectedIndex.value] || '未知')
const indicators = computed(() => selectedIndex.value == null ? {} : detail.value?.indicators[selectedIndex.value] || {})
const fmt = (value, unit = '') => Number.isFinite(value) ? `${value.toFixed(2)}${unit}` : '未知'
const stageName = stage => ({ forming: '○ 形成中', confirmed: '▲ 规则确认', invalidated: '× 已失效' })[stage] || stage
function inspect(index) { if (model.value) selectedIndex.value = Math.max(model.value.begin, Math.min(model.value.end, index)) }
async function load() {
  const id = ++request
  try {
    const value = props.frozen ? props.snapshotDetails[props.stock.code] : await patternDetail(props.day, props.stock.code, props.receipt)
    if (id !== request) return
    if (!value) throw new Error('此形态逐根图未保存到快照；不读取最新数据')
    if (value.code !== props.stock.code || value.day !== props.day) throw new Error('形态证据股票或日期与报告不一致')
    detail.value = value
    selectedIndex.value = value.dates.length - 1
    error.value = ''
    if (!props.frozen) emit('detail-loaded', value.code)
  } catch (cause) { if (id === request) error.value = cause.message }
}
onMounted(load)
onBeforeUnmount(() => { request++ })
</script>

<template>
  <div class="dialog-backdrop pattern-backdrop" @click.self="emit('close')">
    <section class="dialog pattern-dialog" role="dialog" aria-modal="true" :aria-label="`${stock.name}形态证据`" @keydown.esc="emit('close')">
      <button class="close" @click="emit('close')">关闭</button>
      <span class="eyebrow">PATTERN EVIDENCE · {{ day }}</span><h2>{{ stock.name }} {{ stock.code }}</h2>
      <p class="footnote">{{ frozen ? '只读快照 · 仅展示已保存的逐根图' : '本地前复权日 K · 截止报告日' }} · 价格形态不是买卖或 Level‑2 吸筹确认。</p>
      <p v-if="error" class="notice" role="status">{{ error }}</p>
      <template v-if="detail">
        <div class="pattern-actions"><label>形态事件<select v-model="selectedEventId"><option v-for="event in stock.events" :key="event.eventId" :value="event.eventId">{{ event.name }} · {{ stageName(event.stage) }} · {{ event.detectedDate }}</option></select></label><label>副图<select v-model="indicator"><option>MACD</option><option>RSI6</option><option>KDJ</option></select></label><label><input v-model="showMA" type="checkbox" /> MA5／20</label><label><input v-model="showSignals" type="checkbox" /> 形态标注</label></div>
        <p class="pattern-readout" aria-live="polite" v-if="candle">{{ date }} · qfq 开 {{ fmt(candle[0]) }} / 高 {{ fmt(candle[1]) }} / 低 {{ fmt(candle[2]) }} / 收 {{ fmt(candle[3]) }} · 量 {{ fmt(candle[4]) }} 手 · 额 {{ candle[5] == null ? '未知' : fmt(candle[5] / 100000, ' 亿') }}</p>
        <p class="pattern-readout" v-else>{{ date }} · qfq 数据缺失或异常，不补值。</p>
        <svg v-if="model" viewBox="0 0 600 360" class="pattern-svg" tabindex="0" role="img" :aria-label="`${stock.name}前复权K线、成交量及${indicator}；左右方向键查看逐日证据`" @keydown.left.prevent="inspect(selectedIndex - 1)" @keydown.right.prevent="inspect(selectedIndex + 1)">
          <g v-for="(tick, index) in model.ticks" :key="index"><line x1="50" x2="585" :y1="tick.y" :y2="tick.y" stroke="#2b4057" /><text x="46" :y="tick.y + 4" text-anchor="end" fill="#a9bfd5" font-size="10">{{ fmt(tick.price) }}</text></g>
          <g v-for="bar in model.bars" :key="bar.index" @pointerenter="inspect(bar.index)">
            <rect v-if="bar.missing" :x="bar.x - bar.width / 2" y="25" :width="bar.width" height="175" fill="#8994a5" opacity=".22"><title>{{ detail.dates[bar.index] }} 缺失，不补值</title></rect>
            <template v-else><line :x1="bar.x" :x2="bar.x" :y1="bar.highY" :y2="bar.lowY" :stroke="bar.color" /><rect :x="bar.x - bar.width / 2" :y="bar.bodyY" :width="bar.width" :height="bar.bodyHeight" :fill="bar.rising ? '#102034' : bar.color" :stroke="bar.color" /><rect v-if="bar.volumeY != null" :x="bar.x - bar.width / 2" :y="bar.volumeY" :width="bar.width" :height="bar.volumeHeight" :fill="bar.color" /></template>
            <rect :x="bar.x - Math.max(bar.width, 2) / 2" y="22" :width="Math.max(bar.width, 2)" height="310" fill="transparent" />
          </g>
          <template v-for="ma in model.mas" :key="ma.field"><polyline v-for="(line, index) in ma.lines" :key="index" :points="line" fill="none" :stroke="ma.color" stroke-width="1" /></template>
          <g v-for="signal in model.signals" :key="signal.label"><line x1="55" x2="585" :y1="signal.y" :y2="signal.y" stroke="#d5cfa0" stroke-dasharray="4 3" /><text x="580" :y="signal.y - 4" text-anchor="end" fill="#d5cfa0" font-size="10">{{ signal.label }} {{ fmt(signal.value) }}</text></g>
          <circle v-for="anchor in model.anchors" :key="anchor.index" :cx="anchor.x" :cy="anchor.y" r="3" fill="#b8ddf5" />
          <text v-for="transition in model.transitions" :key="transition.index + transition.stage" :x="transition.x" :y="transition.y" text-anchor="middle" fill="#f3d98b" font-size="14">{{ transition.stage === 'forming' ? '○' : transition.stage === 'confirmed' ? '▲' : '×' }}<title>{{ transition.stage }} {{ detail.dates[transition.index] }}</title></text>
          <template v-for="line in model.indicators" :key="line.field"><polyline v-for="(points, index) in line.lines" :key="index" :points="points" fill="none" :stroke="line.color" stroke-width="1" /></template>
          <line v-if="selectedIndex != null" :x1="model.x(selectedIndex)" :x2="model.x(selectedIndex)" y1="22" y2="333" stroke="#accbe5" stroke-dasharray="3 3" pointer-events="none" />
          <text x="5" y="225" fill="#a9bfd5" font-size="10">量(手)</text><text x="6" y="286" fill="#a9bfd5" font-size="10">{{ indicator }}</text><text x="55" y="350" fill="#a9bfd5" font-size="10">{{ detail.dates[model.begin] }}</text><text x="585" y="350" text-anchor="end" fill="#a9bfd5" font-size="10">{{ detail.dates[model.end] }}</text>
        </svg>
        <p v-else class="footnote">没有可绘制的 K 线；不造缺失价格。</p>
        <p class="pattern-readout">当日指标：{{ Object.entries(indicators).filter(([, value]) => Number.isFinite(value)).map(([key, value]) => `${key} ${fmt(value)}`).join(' · ') || '未知' }}</p>
        <div class="pattern-explanation"><strong>{{ selectedEvent.name }} · {{ stageName(selectedEvent.stage) }} · {{ selectedEvent.direction > 0 ? '看涨结构' : selectedEvent.direction < 0 ? '看跌结构' : '中性整理' }}</strong><p>起始 {{ selectedEvent.startDate }} · 识别 {{ selectedEvent.detectedDate }} · 确认 {{ selectedEvent.confirmedDate || '未发生' }} · 失效 {{ selectedEvent.invalidatedDate || '未发生' }}</p><p>规则依据：{{ selectedEvent.evidence }}</p><p>关键位 {{ fmt(selectedEvent.key) }} · 失效位 {{ fmt(selectedEvent.stop) }} · 当前距离 {{ fmt(selectedEvent.distance, '%') }}；断档后生命周期{{ selectedEvent.lifecycleUnknown ? '未知' : '按规则跟踪' }}。</p><p>报告日 Level‑2 净额比 {{ fmt(level, '%') }} · 资金窗口 {{ stateWindow ?? '未应用' }} 日。不是信号当日资金，不回填历史。</p></div>
        <details class="footnote"><summary>指标与来源口径</summary><p>{{ indicatorMethod }}</p><p>来源身份：{{ detail.identity }}；qfq 价格直接读取，成交量不复权，灰带为缺失。</p></details>
      </template>
    </section>
  </div>
</template>
