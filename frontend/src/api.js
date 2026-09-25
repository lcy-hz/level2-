export async function getJson(path, options = {}) {
  const response = await fetch(path, { cache: 'no-store', ...options })
  const data = await response.json()
  if (!response.ok) throw new Error(data.message || `请求失败 (${response.status})`)
  return data
}

export async function postJson(path, body) {
  const response = await fetch(path, { method: 'POST', cache: 'no-store',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const data = await response.json()
  if (!response.ok) throw new Error(data.message || `请求失败 (${response.status})`)
  return data
}

export const dates = () => getJson('/api/dates')
export const report = day => getJson(`/api/report/data?date=${encodeURIComponent(day)}`)
export const snapshot = id => getJson(`/api/snapshot/data?id=${encodeURIComponent(id)}`)
export const snapshots = () => getJson('/api/snapshots')
export const startState = (day, window) => postJson('/api/state', { day, window })
export const stateView = (day, window) => getJson(`/api/state/view?date=${encodeURIComponent(day)}&window=${window}`)
export const chart = (kind, code, day, signal) => getJson(`/api/chart/${kind}/${encodeURIComponent(code)}?date=${encodeURIComponent(day)}`, { signal })
export const detailStatus = (code, day) => getJson(`/api/detail/${encodeURIComponent(code)}?date=${encodeURIComponent(day)}`)
export const startDetail = (code, day) => postJson(`/api/detail?date=${encodeURIComponent(day)}`, { code })
export const saveSnapshot = request => postJson('/api/snapshots', request)
