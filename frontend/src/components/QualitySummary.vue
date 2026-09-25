<script setup>
defineProps({ quality: { type: Object, default: null }, gate: { type: Array, default: () => [] } })
const count = value => value == null ? '未知' : value.toLocaleString()
const rate = row => row?.eligibleRows > 0 ? `${(row.affectedRows / row.eligibleRows * 100).toFixed(6)}%` : '不可计算'
</script>

<template>
  <section class="panel" aria-labelledby="quality-title">
    <div class="section-heading"><div><span class="eyebrow">DATA INTEGRITY</span><h2 id="quality-title">数据门槛与口径</h2></div><span class="hint">发布通过 ≠ 原始行情无异常</span></div>
    <div class="quality-grid" :class="{ single: !quality }">
      <div class="subpanel"><strong>发布门槛</strong><p>{{ gate.filter(row => row.files && row.manifest && row.committed).length }} / {{ gate.length }} 个交易日三表、manifest 与提交标识齐备；转换警告仍须逐日查看。</p></div>
      <div v-if="quality" class="subpanel"><strong>共同证券覆盖</strong><p>{{ count(quality.coverage?.intersection) }} / {{ count(quality.coverage?.union) }} 只；交并集按目标日三表统计。</p></div>
      <div v-if="quality" class="subpanel"><strong>未知方向成交金额</strong><p>{{ quality.direction?.unknownAmount == null ? '未知' : (quality.direction.unknownAmount / 1e8).toFixed(4) + ' 亿' }}；比例 {{ quality.direction?.unknownRate == null ? '未知' : (quality.direction.unknownRate * 100).toFixed(6) + '%' }}。</p></div>
      <div v-if="quality" class="subpanel"><strong>重复候选关联键</strong><p>{{ count(quality.candidateDuplicateKey?.groups) }} 组，涉及 {{ count(quality.candidateDuplicateKey?.affectedRows) }} 行；不能直接当作母单身份。</p></div>
    </div>
    <p v-if="!quality" class="footnote">此报告未保存目标日原始三表质量报告；只能查看已冻结的发布门槛，不把缺少的覆盖、时钟和关联键核验写成零，也不读取最新文件补齐。</p>
    <template v-if="quality">
    <p class="footnote">{{ quality?.scope || '统计范围未保存' }}。非法时钟指无法解析或时分秒越界；零时钟与 15:00 后记录独立统计，不混为错误。</p>
    <div v-if="quality?.tables" class="table-scroll"><table><thead><tr><th>原始表</th><th>证券数</th><th>行数</th><th>日期异常</th><th>非法时钟</th><th>零时钟</th><th>盘后记录</th></tr></thead><tbody><tr v-for="(row, key) in quality.tables" :key="key"><th scope="row">{{ key }}</th><td>{{ count(row.stocks) }}</td><td>{{ count(row.rows) }}</td><td>{{ count(row.badDate) }}</td><td>{{ count(row.invalidClock) }}</td><td>{{ count(row.zeroClock) }}</td><td>{{ count(row.afterClose) }}</td></tr></tbody></table></div>
    <p class="footnote">有效已识别方向成交中无效关联编号：{{ count(quality?.direction?.invalidLinkedKeyTrades) }} 条；无效编号不并入大额关联编号分组。</p>
    <p class="footnote">连续竞价同股同时间快照：<template v-if="quality?.snapshotTimestampDuplicates">{{ count(quality.snapshotTimestampDuplicates.groups) }} 组，涉及 {{ count(quality.snapshotTimestampDuplicates.affectedStocks) }} 只、{{ count(quality.snapshotTimestampDuplicates.affectedRows) }} 行；检查范围 {{ count(quality.snapshotTimestampDuplicates.eligibleRows) }} 行。</template><template v-else>未核验；旧报告不按零处理。</template>重复时间不自动去重，相关盘口路径拒绝任意选样。</p>
    <p class="footnote">快照全字段完全重复：<template v-if="quality?.snapshotExactDuplicates">{{ count(quality.snapshotExactDuplicates.groups) }} 组、{{ count(quality.snapshotExactDuplicates.affectedRows) }} 行；先查 {{ count(quality.snapshotExactDuplicates.candidateKeyGroups) }} 组同股同日期同时间候选，再逐字段比较。</template><template v-else>未核验。</template> Parquet 物理行时钟回退：<template v-if="quality?.snapshotPhysicalTimeRegressions">{{ count(quality.snapshotPhysicalTimeRegressions.regressions) }} / {{ count(quality.snapshotPhysicalTimeRegressions.comparablePairs) }} 对，涉及 {{ count(quality.snapshotPhysicalTimeRegressions.affectedStocks) }} 只。</template><template v-else>未核验。</template></p>
    <div class="table-scroll"><table><thead><tr><th>原始表</th><th>完全重复组</th><th>涉及行 / 全部A股行</th><th>涉及比例</th><th>物理时钟回退 / 可比对</th><th>涉及股票</th></tr></thead><tbody>
      <tr v-for="row in [{ name: 'deal', exact: quality?.dealExactDuplicates, physical: quality?.dealPhysicalTimeRegressions }, { name: 'order_raw', exact: quality?.orderRawExactDuplicates, physical: quality?.orderRawPhysicalTimeRegressions }]" :key="row.name"><th scope="row">{{ row.name }}</th><td>{{ count(row.exact?.groups) }}</td><td>{{ count(row.exact?.affectedRows) }} / {{ count(row.exact?.eligibleRows) }}</td><td>{{ row.exact ? rate(row.exact) : '未核验' }}</td><td>{{ count(row.physical?.regressions) }} / {{ count(row.physical?.comparablePairs) }}</td><td>{{ count(row.physical?.affectedStocks) }}</td></tr>
    </tbody></table></div>
    <p class="footnote">完全重复按全部原始字段逐项相同统计，不自动去重；物理行时钟回退只描述 Parquet 文件排列，不证明交易所源事件顺序。旧报告缺少检查字段时显示未知，不补算。</p>
    </template>
    <details v-if="gate.length"><summary>逐日发布门槛与转换警告</summary><div class="table-scroll"><table><thead><tr><th>日期</th><th>三表</th><th>manifest</th><th>COMMITTED</th><th>警告数</th><th>转换错误</th></tr></thead><tbody><tr v-for="row in gate" :key="row.day"><th scope="row">{{ row.day }}</th><td>{{ row.files ? '齐' : '缺失' }}</td><td>{{ row.manifest ? '有' : '缺失' }}</td><td>{{ row.committed ? '有' : '缺失' }}</td><td>{{ count(row.warnings) }}</td><td>{{ count(row.conversionErrors) }}</td></tr></tbody></table></div></details>
    <details v-if="quality?.linkage" open><summary>候选委托字段匹配（不代表订单身份）</summary><div class="table-scroll"><table><thead><tr><th>字段</th><th>有效编号成交</th><th>匹配成交</th><th>重复键涉及成交</th><th>多方向键涉及成交</th></tr></thead><tbody><tr v-for="(row, key) in quality.linkage" :key="key"><th scope="row">{{ key }}</th><td>{{ count(row.eligibleTrades) }}</td><td>{{ count(row.matchedTrades) }}</td><td>{{ count(row.repeatedKeyTrades) }}</td><td>{{ count(row.multiSideKeyTrades) }}</td></tr></tbody></table></div><p class="footnote">原生来源缺频道；较高匹配率仍不能证明经济订单身份，不自动去重。</p></details>
    <details v-if="quality"><summary>覆盖差异、来源与未完成检查</summary><p v-for="(codes, key) in quality.coverage?.missingByTable || {}" :key="key">{{ key }} 相对三表并集缺少：{{ codes.length ? codes.join('、') : '无' }}</p><p v-for="(row, key) in quality.tables || {}" :key="key">{{ key }}：{{ row.file }}</p><p v-for="(item, index) in quality.limits || []" :key="index">{{ item }}</p><pre>{{ JSON.stringify(quality, null, 2) }}</pre></details>
  </section>
</template>

<style scoped>
.quality-grid.single { grid-template-columns: minmax(0, 1fr); }
</style>
