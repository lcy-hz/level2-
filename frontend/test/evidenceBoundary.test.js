import test, { after, before } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'

let server
let QualitySummary
let MarketTimeline

before(async () => {
  server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
  QualitySummary = (await server.ssrLoadModule('/src/components/QualitySummary.vue')).default
  MarketTimeline = (await server.ssrLoadModule('/src/components/MarketTimeline.vue')).default
})
after(async () => { await server?.close() })

const render = (component, props) => renderToString(createSSRApp(component, props))
const gate = [{ day: '20260922', files: true, manifest: true, committed: true, warnings: 3, conversionErrors: 0 }]

test('legacy snapshot without quality retains only frozen publication evidence', async () => {
  const html = await render(QualitySummary, { quality: null, gate })
  assert.match(html, /1 \/ 1 个交易日三表/)
  assert.match(html, /未保存目标日原始三表质量报告/)
  assert.match(html, /逐日发布门槛与转换警告/)
  assert.doesNotMatch(html, /共同证券覆盖/)
  assert.doesNotMatch(html, /完全重复组/)
  assert.doesNotMatch(html, /候选委托字段匹配/)
})

test('snapshot with saved quality preserves its measured coverage and raw table', async () => {
  const quality = {
    coverage: { intersection: 5209, union: 5209 },
    direction: { unknownAmount: 0, unknownRate: 0, invalidLinkedKeyTrades: 0 },
    candidateDuplicateKey: { groups: 14, affectedRows: 28 },
    tables: { deal: { stocks: 5209, rows: 175765103, badDate: 0, invalidClock: 0, zeroClock: 0, afterClose: 35465 } },
  }
  const html = await render(QualitySummary, { quality, gate })
  assert.match(html, /5,209 \/ 5,209 只/)
  assert.match(html, /175,765,103/)
  assert.match(html, /14 组，涉及 28 行/)
  assert.doesNotMatch(html, /此报告未保存目标日原始三表质量报告/)
})

test('market trajectory labels missing quality without changing frozen figures', async () => {
  const markets = [{ day: '20260922', stocks: 5209, amount: 2135908000000, net: -72588000000, up: 2284, down: 2783, vp95: 0.08035, ap95: 0.07999 }]
  const missing = await render(MarketTimeline, { markets, qualityAvailable: false })
  const present = await render(MarketTimeline, { markets, qualityAvailable: true })
  for (const html of [missing, present]) {
    assert.match(html, /20260922/)
    assert.match(html, /21359\.08 亿/)
    assert.match(html, /-725\.88 亿/)
  }
  assert.match(missing, /不能据此完成方向质量核验/)
  assert.doesNotMatch(present, /不能据此完成方向质量核验/)
  assert.match(present, /各日覆盖与方向质量须结合数据门槛阅读/)
})
