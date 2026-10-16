// Thin wrapper around the FastAPI backend (Phase 5). No caching, no state
// management library — the dashboard is small enough that plain fetch +
// React state is the right amount of complexity, not less.

const API_ROOT = 'http://localhost:8000'

async function getJSON(path) {
  const res = await fetch(`${API_ROOT}${path}`)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

export function fetchRepos({ risk, sort } = {}) {
  const params = new URLSearchParams()
  if (risk) params.set('risk', risk)
  if (sort) params.set('sort', sort)
  const qs = params.toString()
  return getJSON(`/api/repos${qs ? `?${qs}` : ''}`)
}

export function fetchRepoDetail(owner, name) {
  return getJSON(`/api/repos/${owner}/${name}`)
}

export function fetchRepoTrend(owner, name) {
  return getJSON(`/api/repos/${owner}/${name}/trend`)
}

export function fetchSummary() {
  return getJSON('/api/stats/summary')
}

export function fetchAlerts(limit = 10) {
  return getJSON(`/api/alerts?limit=${limit}`)
}

export function searchGithub(query) {
  return getJSON(`/api/github/search?q=${encodeURIComponent(query)}`)
}

export async function addRepo(owner, name) {
  const res = await fetch(`${API_ROOT}/api/repos`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ owner, name }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

export async function removeRepo(owner, name) {
  const res = await fetch(`${API_ROOT}/api/repos/${owner}/${name}`, { method: 'DELETE' })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}
