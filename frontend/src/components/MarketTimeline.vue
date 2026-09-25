<script setup>
defineProps({ markets: { type: Array, required: true }, qualityAvailable: { type: Boolean, default: false } })
const money = value => value == null ? '未知' : `${(value / 1e8).toFixed(2)} 亿`
const tone = value => value == null ? '' : value > 0 ? 'positive' : value < 0 ? 'negative' : ''
</script>

<template>
  <section class="panel timeline" aria-labelledby="market-title">
    <div class="section-heading"><div><span class="eyebrow">MARKET TRAJECTORY</span><h2 id="market-title">市场逐日轨迹</h2></div><span class="hint">原始 7 交易日日级统计</span></div>
    <div class="table-scroll">
      <table>
        <thead><tr><th>交易日</th><th>覆盖</th><th>成交额</th><th>主动净额</th><th>上涨 / 下跌</th><th>量差 P95</th><th>额差 P95</th></tr></thead>
        <tbody>
          <tr v-for="row in markets" :key="row.day">
            <th scope="row">{{ row.day }}</th><td>{{ row.stocks?.toLocaleString() ?? '未知' }}</td>
            <td>{{ money(row.amount) }}</td><td :class="tone(row.net)">{{ money(row.net) }}</td>
            <td>{{ row.up ?? '未知' }} / {{ row.down ?? '未知' }}</td><td>{{ row.vp95 == null ? '未知' : row.vp95 + '%' }}</td><td>{{ row.ap95 == null ? '未知' : row.ap95 + '%' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="qualityAvailable" class="footnote">各日覆盖与方向质量须结合数据门槛阅读；未知净额不显示为零。</p>
    <p v-else class="footnote">此报告未保存目标日原始三表质量报告；市场逐日值只按已冻结结果展示，不能据此完成方向质量核验。未知净额不显示为零。</p>
  </section>
</template>
