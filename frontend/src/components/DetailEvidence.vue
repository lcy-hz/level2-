<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { detailStatus, startDetail } from '../api.js'

const props = defineProps({ card: { type: Object, required: true }, day: { type: String, required: true }, frozen: { type: Boolean, default: false } })
const emit = defineEmits(['loaded'])
const state = ref(props.frozen ? { status: props.card.computedDetail ? 'done' : 'unavailable', message: props.card.computedDetail ? '快照内已保存该股深查' : '快照未保存该股深查；不补算' } : { status: 'idle', message: '尚未查询本地缓存' })
const result = ref(null)
let sequence = 0
let timer = null
const evidence = computed(() => result.value || (props.card.computedDetail ? props.card.detailEvidence || props.card : null))
const busy = computed(() => ['queued', 'running'].includes(state.value.status))
const money = value => !Number.isFinite(value) ? '未知' : Math.abs(value) >= 1e8 ? `${(value / 1e8).toFixed(2)} 亿` : `${(value / 1e4).toFixed(1)} 万`
const ratio = value => Number.isFinite(value) ? `${value.toFixed(2)}%` : '未知'

function accept(response, id) {
  if (id !== sequence) return
  state.value = response
  if (response.status === 'done') {
    if (response.result?.code !== props.card.code || response.result?.day !== props.day) {
      state.value = { status: 'error', message: '深查结果股票或日期与报告不一致' }
      return
    }
    result.value = response.result
    if (!props.frozen) emit('loaded', response.result)
  } else if (busy.value) {
    timer = setTimeout(() => poll(id), 1500)
  }
}
async function poll(id) {
  if (id !== sequence) return
  try { accept(await detailStatus(props.card.code, props.day), id) }
  catch (error) { if (id === sequence) state.value = { status: 'error', message: error.message } }
}
async function calculate() {
  if (props.frozen) return
  clearTimeout(timer)
  const id = ++sequence
  state.value = { status: 'running', message: '正在提交当前报告日的单股深查…' }
  try { accept(await startDetail(props.card.code, props.day), id) }
  catch (error) { if (id === sequence) state.value = { status: 'error', message: error.message } }
}
onMounted(() => { if (!props.frozen) poll(++sequence) })
onBeforeUnmount(() => { sequence++; clearTimeout(timer) })
</script>

<template>
  <section class="detail-evidence" aria-label="按需 Level-2 深查">
    <div class="detail-heading"><h3>盘中与关联单深查</h3><button v-if="!frozen && !evidence" type="button" :disabled="busy" @click="calculate">{{ busy ? '计算中…' : state.status === 'error' ? '重试计算' : '点击计算' }}</button></div>
    <p class="footnote" role="status">{{ state.message }}。{{ frozen ? '只读快照，不读取最新数据。' : '仅计算本股、当前报告日；结果缓存于本机。' }}</p>
    <template v-if="evidence">
      <p class="footnote">成交 {{ evidence.tradeRows?.toLocaleString() ?? '未知' }} 条 · 有效时段成交额覆盖 {{ ratio(evidence.regularCoverage) }} · 主动净额 {{ money(evidence.net) }} · 未知方向金额 {{ money(evidence.unknownAmount) }}</p>
      <h4>盘中五时段</h4>
      <div class="table-scroll"><table><thead><tr><th>时段</th><th>成交额</th><th>主动净额</th><th>VWAP</th></tr></thead><tbody><tr v-for="row in evidence.segments || []" :key="row.s"><td>{{ row.s }}</td><td>{{ money(row.a) }}</td><td>{{ money(row.n) }}</td><td>{{ row.v ?? '未知' }}</td></tr></tbody></table></div>
      <h4>主动成交关联委托</h4>
      <div class="table-scroll"><table><thead><tr><th>分档</th><th>净额</th><th>关联键数</th></tr></thead><tbody><tr v-for="row in evidence.parents || []" :key="row.b"><td>{{ row.b }}</td><td>{{ money(row.n) }}</td><td>{{ row.c?.toLocaleString() ?? '未知' }}</td></tr></tbody></table></div>
      <details><summary>order_raw 原始委托类型与代码</summary><div class="table-scroll"><table><thead><tr><th>委托类型</th><th>委托代码</th><th>行数</th><th>数量</th></tr></thead><tbody><tr v-for="(row, index) in evidence.orders || []" :key="index"><td>{{ row.t }}</td><td>{{ row.s }}</td><td>{{ row.r?.toLocaleString() ?? '未知' }}</td><td>{{ row.q?.toLocaleString() ?? '未知' }}</td></tr></tbody></table></div></details>
      <p class="footnote">{{ evidence.note || '关联分组不是已验证经济母单；委托类型未解码为补撤单。' }}</p>
    </template>
  </section>
</template>
