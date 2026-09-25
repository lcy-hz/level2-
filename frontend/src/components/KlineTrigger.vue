<script setup>
import { computed, nextTick, onBeforeUnmount, ref, useId } from 'vue'
import { chart } from '../api.js'
import { buildChartModel, minuteDrawdownText } from '../chartModel.js'

const props = defineProps({
  code: { type: String, required: true }, name: { type: String, default: '' }, day: { type: String, required: true },
  frozen: { type: Boolean, default: false }, snapshotCharts: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['loaded'])
const previewId = useId()
const open = ref(false)
const pinned = ref(false)
const kind = ref('day')
const result = ref(null)
const status = ref('')
const selected = ref(0)
const position = ref({ left: '12px', top: '12px', maxHeight: 'calc(100vh - 24px)' })
let active = null
let sequence = 0
let controller = null
let hideTimer = null
let departed = false
const model = computed(() => buildChartModel(result.value, kind.value))
const selectedBar = computed(() => result.value?.bars?.[selected.value] || null)
const selectedDate = computed(() => selectedBar.value ? result.value.labels[selectedBar.value[0]] : null)
const money = value => Number.isFinite(value) ? `${(value / 1e8).toFixed(2)} 亿` : '未知'
const dayLabel = value => /^\d{8}$/.test(value || '') ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : value || '未知'
const fmt = value => Number.isFinite(value) ? value.toFixed(2) : '未知'
const minuteDrawdown = computed(() => minuteDrawdownText(result.value))

async function place(element) {
  await nextTick()
  if (!open.value || !element?.isConnected) return
  const bounds = element.getBoundingClientRect()
  const width = Math.min(500, innerWidth - 24)
  const height = Math.min(415, innerHeight - 24)
  const below = innerHeight - bounds.bottom - 12
  const top = below >= height || below >= bounds.top ? bounds.bottom + 8 : Math.max(12, bounds.top - height - 8)
  position.value = { left: `${Math.max(12, Math.min(bounds.left, innerWidth - width - 12))}px`, top: `${top}px`, maxHeight: `${Math.max(90, innerHeight - top - 12)}px` }
}

function close() {
  sequence++
  controller?.abort()
  controller = null
  clearTimeout(hideTimer)
  open.value = false
  pinned.value = false
  active = null
  departed = false
}
function later() {
  clearTimeout(hideTimer)
  departed = true
  if (!pinned.value) hideTimer = setTimeout(close, 180)
}
function cancelHide() { clearTimeout(hideTimer); departed = false }
async function show(nextKind, event, pin = false) {
  clearTimeout(hideTimer)
  if (pinned.value && !pin) return
  const element = event.currentTarget
  if (pin && open.value && pinned.value && active === element) { close(); return }
  if (open.value && active === element && kind.value === nextKind && !departed) {
    if (pin) pinned.value = true
    return
  }
  departed = false
  controller?.abort()
  const id = ++sequence
  active = element
  kind.value = nextKind
  pinned.value = pin
  result.value = null
  status.value = props.frozen ? '读取快照内已保存图表…' : '正在重新读取本地文件…'
  open.value = true
  await place(element)
  try {
    let data
    if (props.frozen) {
      data = props.snapshotCharts[`${nextKind}/${props.code}`]
      if (!data) throw new Error('此图表未保存到快照；不会读取最新文件')
    } else {
      controller = new AbortController()
      const response = await chart(nextKind, props.code, props.day, controller.signal)
      if (response.status !== 'done') throw new Error(response.message || '图表读取失败')
      data = response.result
    }
    if (id !== sequence) return
    if (data.code !== props.code || data.day !== props.day) throw new Error('图表股票或日期与当前报告不一致')
    result.value = data
    selected.value = Math.max(0, (data.bars?.length || 0) - 1)
    status.value = data.bars?.length ? '' : data.reason || '本地无可用 K 线；缺失不补值'
    if (!props.frozen && data.receipt) emit('loaded', { key: `${nextKind}/${props.code}`, receipt: data.receipt })
    await place(element)
  } catch (error) {
    if (id !== sequence || error.name === 'AbortError') return
    status.value = error.message
    await place(element)
  }
}
function hover(nextKind, event) { if (event.pointerType !== 'touch') show(nextKind, event) }
function inspect(step) { selected.value = Math.max(0, Math.min((result.value?.bars?.length || 1) - 1, selected.value + step)) }
function onKey(event) {
  if (event.key === 'Escape') close()
}
onBeforeUnmount(close)
</script>

<template>
  <span class="chart-trigger-group" @pointerleave="later" @focusout="later">
    <button type="button" class="chart-code" :aria-controls="previewId" :aria-label="`${name} ${code} 前复权日 K 线`" title="悬浮查看前复权日 K；点击固定" @pointerenter="hover('day', $event)" @focus="show('day', $event)" @click.stop="show('day', $event, true)" @keydown="onKey">{{ code }}</button>
    <button type="button" class="minute-trigger" :aria-controls="previewId" :aria-label="`${name} ${code} 当日分钟 K 线`" title="悬浮查看当日分钟 K；点击固定" @pointerenter="hover('minute', $event)" @focus="show('minute', $event)" @click.stop="show('minute', $event, true)" @keydown="onKey">分</button>
    <Teleport to="body">
      <section v-if="open" :id="previewId" class="chart-preview" :style="position" role="region" :aria-label="`${name} ${code} ${kind === 'minute' ? '分钟' : '日'} K 线预览`" @pointerenter="cancelHide" @pointerleave="later" @keydown.esc="close">
        <header><div><strong>{{ name }} {{ code }} · {{ kind === 'minute' ? '当日 1 分钟 K' : '前复权日 K' }}</strong><small>{{ dayLabel(day) }} · {{ frozen ? '只读快照' : '每次悬浮重新读取本地文件' }}</small></div><button type="button" @click="close">关闭</button></header>
        <p v-if="status" class="chart-status" role="status">{{ status }}</p>
        <template v-if="result && model.bars.length">
          <p class="chart-values" aria-live="polite">{{ dayLabel(selectedDate) }} · 开 {{ fmt(selectedBar[1]) }} 高 {{ fmt(selectedBar[2]) }} 低 {{ fmt(selectedBar[3]) }} 收 {{ fmt(selectedBar[4]) }} · 量 {{ selectedBar[5]?.toLocaleString() ?? '未知' }} 手 · 额 {{ money(selectedBar[6]) }}</p>
          <svg viewBox="0 0 530 290" class="chart-svg" tabindex="0" role="img" :aria-label="`${kind === 'minute' ? '分钟' : '日'} K 线与成交量；左右方向键查看数据`" @keydown.left.prevent="inspect(-1)" @keydown.right.prevent="inspect(1)">
            <g v-for="(tick, index) in model.ticks" :key="index"><line x1="52" x2="480" :y1="tick.y" :y2="tick.y" stroke="#30485b" /><text x="45" :y="tick.y + 4" text-anchor="end" fill="#a9bfd0" font-size="11">{{ fmt(tick.price) }}</text></g>
            <g v-for="gap in model.gaps" :key="gap.index"><rect :x="gap.x" y="14" :width="gap.width" height="182" fill="#899aa5" opacity=".12"><title>{{ gap.label }} 缺失，不补值</title></rect></g>
            <line v-if="model.zero != null" x1="52" x2="480" :y1="model.zero" :y2="model.zero" stroke="#e7d6a2" stroke-width="1.4" stroke-dasharray="6 4" /><text v-if="model.zero != null" x="488" :y="model.zero + 4" fill="#e7d6a2" font-size="11">0.00%</text>
            <g v-for="bar in model.bars" :key="bar.index" @pointerenter="selected = bar.index">
              <line :x1="bar.x" :x2="bar.x" :y1="bar.highY" :y2="bar.lowY" :stroke="bar.color" />
              <rect :x="bar.x - bar.width / 2" :y="bar.bodyY" :width="bar.width" :height="bar.bodyHeight" :stroke="bar.color" :fill="bar.rising ? '#0b1929' : bar.color" />
              <rect v-if="bar.volumeY != null" :x="bar.x - bar.width / 2" :y="bar.volumeY" :width="bar.width" :height="bar.volumeHeight" :fill="bar.color" />
              <rect :x="bar.x - Math.max(bar.width, 2) / 2" y="12" :width="Math.max(bar.width, 2)" height="258" fill="transparent" />
            </g>
            <line v-if="model.bars[selected]" :x1="model.bars[selected].x" :x2="model.bars[selected].x" y1="12" y2="270" stroke="#d8e6f0" stroke-dasharray="3 3" pointer-events="none" />
            <text x="45" y="228" text-anchor="end" fill="#a9bfd0" font-size="10">量(手)</text>
            <text x="52" y="285" fill="#a9bfd0" font-size="11">{{ kind === 'minute' ? '09:31' : dayLabel(model.labels[0]) }}</text><text x="480" y="285" text-anchor="end" fill="#a9bfd0" font-size="11">{{ kind === 'minute' ? '15:00' : dayLabel(model.labels.at(-1)) }}</text>
          </svg>
          <p class="chart-note">红色空心＝收≥开，绿色实心＝收&lt;开；下方为成交量。{{ kind === 'minute' ? model.zero == null ? '昨收缺失，0 轴未知。' : `0 轴为昨收 ${fmt(result.preClose)}，垂直居中。` : '前复权价格与原始成交量分别展示。' }}缺失 {{ model.gaps.length }} {{ kind === 'minute' ? '分钟' : '交易日' }}，不插值。</p>
          <p v-if="kind === 'minute'" class="chart-note">{{ minuteDrawdown }}。仅比较有成交分钟的收盘价与此前峰值（含昨收），不包含分钟内高低点；缺档可能低估实际盘中回撤。</p>
        </template>
        <details v-if="result" class="chart-note"><summary>来源与质量口径</summary><p>{{ result.source }} · {{ result.method }}</p><p v-if="result.quality">{{ result.quality }}</p><p v-if="result.rejected">排除 {{ result.rejected }} 条异常 OHLC。</p><p>读取时间：{{ result.readAt || '快照未记录' }}。本地最新不等于交易所实时行情。</p></details>
      </section>
    </Teleport>
  </span>
</template>
