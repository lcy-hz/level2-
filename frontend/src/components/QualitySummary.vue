<script setup>
defineProps({ quality: { type: Object, default: null }, gate: { type: Array, default: () => [] } })
const count = value => value == null ? '未知' : value.toLocaleString()
</script>

<template>
  <section class="panel" aria-labelledby="quality-title">
    <div class="section-heading"><div><span class="eyebrow">DATA INTEGRITY</span><h2 id="quality-title">数据门槛与口径</h2></div><span class="hint">发布通过 ≠ 原始行情无异常</span></div>
    <div class="quality-grid">
      <div class="subpanel"><strong>发布门槛</strong><p>{{ gate.length }} 个交易日记录；逐日源文件、manifest 与提交标识以原报告口径核验。</p></div>
      <div class="subpanel"><strong>共同证券覆盖</strong><p>{{ count(quality?.coverage?.intersection) }} / {{ count(quality?.coverage?.union) }} 只；交并集按目标日三表统计。</p></div>
      <div class="subpanel"><strong>未知方向成交金额</strong><p>{{ quality?.direction?.unknownAmount == null ? '未知' : (quality.direction.unknownAmount / 1e8).toFixed(4) + ' 亿' }}；比例 {{ quality?.direction?.unknownRate == null ? '未知' : (quality.direction.unknownRate * 100).toFixed(6) + '%' }}。</p></div>
      <div class="subpanel"><strong>重复候选关联键</strong><p>{{ count(quality?.candidateDuplicateKey?.groups) }} 组，涉及 {{ count(quality?.candidateDuplicateKey?.affectedRows) }} 行；不能直接当作母单身份。</p></div>
    </div>
    <div v-if="quality?.tables" class="table-scroll"><table><thead><tr><th>原始表</th><th>证券数</th><th>行数</th><th>日期异常</th><th>非法时钟</th><th>零时钟</th><th>盘后记录</th></tr></thead><tbody><tr v-for="(row, key) in quality.tables" :key="key"><th scope="row">{{ key }}</th><td>{{ count(row.stocks) }}</td><td>{{ count(row.rows) }}</td><td>{{ count(row.badDate) }}</td><td>{{ count(row.invalidClock) }}</td><td>{{ count(row.zeroClock) }}</td><td>{{ count(row.afterClose) }}</td></tr></tbody></table></div>
    <p class="footnote">连续竞价同股同时间快照：<template v-if="quality?.snapshotTimestampDuplicates">{{ count(quality.snapshotTimestampDuplicates.groups) }} 组，涉及 {{ count(quality.snapshotTimestampDuplicates.affectedStocks) }} 只、{{ count(quality.snapshotTimestampDuplicates.affectedRows) }} 行；检查范围 {{ count(quality.snapshotTimestampDuplicates.eligibleRows) }} 行。</template><template v-else>未核验；旧报告不按零处理。</template>重复时间不自动去重，相关盘口路径拒绝任意选样。</p>
    <p class="footnote">快照全字段完全重复：<template v-if="quality?.snapshotExactDuplicates">{{ count(quality.snapshotExactDuplicates.groups) }} 组、{{ count(quality.snapshotExactDuplicates.affectedRows) }} 行；先查 {{ count(quality.snapshotExactDuplicates.candidateKeyGroups) }} 组同股同日期同时间候选，再逐字段比较。</template><template v-else>未核验。</template> Parquet 物理行时钟回退：<template v-if="quality?.snapshotPhysicalTimeRegressions">{{ count(quality.snapshotPhysicalTimeRegressions.regressions) }} / {{ count(quality.snapshotPhysicalTimeRegressions.comparablePairs) }} 对，涉及 {{ count(quality.snapshotPhysicalTimeRegressions.affectedStocks) }} 只。</template><template v-else>未核验。</template>文件顺序不等于交易所事件顺序；成交与原始委托未做全字段重复审计。</p>
    <details v-if="quality"><summary>完整质量证据与来源</summary><pre>{{ JSON.stringify(quality, null, 2) }}</pre></details>
  </section>
</template>
