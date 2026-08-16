import { useEffect, useMemo, useState } from 'react'
import { fetchRepos, fetchSummary, removeRepo } from './api.js'
import SummaryBar from './components/SummaryBar.jsx'
import RepoTable from './components/RepoTable.jsx'
import RepoDetail from './components/RepoDetail.jsx'
import SearchBar from './components/SearchBar.jsx'
import ThemeToggle from './components/ThemeToggle.jsx'
import AddRepoModal from './components/AddRepoModal.jsx'

function getInitialTheme() {
  const saved = localStorage.getItem('bft-theme')
  if (saved === 'light' || saved === 'dark') return saved
  // Fall back to the user's OS preference on first visit.
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export default function App() {
  const [repos, setRepos] = useState(null)
  const [summary, setSummary] = useState(null)
  const [filter, setFilter] = useState('All')
  const [search, setSearch] = useState('')
  const [error, setError] = useState(null)
  const [selectedRepo, setSelectedRepo] = useState(null) // { owner, name } or null
  const [showAddModal, setShowAddModal] = useState(false)
  const [theme, setTheme] = useState(getInitialTheme)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('bft-theme', theme)
  }, [theme])

  function reload() {
    fetchSummary().then(setSummary).catch((e) => setError(e.message))
    fetchRepos({ risk: filter === 'All' ? undefined : filter, sort: 'risk' })
      .then(setRepos)
      .catch((e) => setError(e.message))
  }

  useEffect(() => {
    fetchSummary().then(setSummary).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    setRepos(null)
    fetchRepos({ risk: filter === 'All' ? undefined : filter, sort: 'risk' })
      .then(setRepos)
      .catch((e) => setError(e.message))
  }, [filter])

  // Client-side filter on top of whatever the backend already returned —
  // the repo list is small enough (tens to low hundreds) that a full round
  // trip per keystroke would be overkill; filtering what's already loaded
  // is instant and simpler.
  const visibleRepos = useMemo(() => {
    if (!repos) return repos
    const q = search.trim().toLowerCase()
    if (!q) return repos
    return repos.filter(
      (r) => r.owner.toLowerCase().includes(q) || r.name.toLowerCase().includes(q)
    )
  }, [repos, search])

  async function handleRemoveRepo(repo) {
    try {
      await removeRepo(repo.owner, repo.name)
      reload()
    } catch (e) {
      setError(e.message)
    }
  }

  function handleRepoAdded() {
    setShowAddModal(false)
    reload()
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-title">
          <span className="signal-dot" />
          Bus Factor Tracker
        </h1>
        <div className="header-controls">
          <span className="app-subtitle">{summary ? `${summary.total_repos_tracked} repos tracked` : ''}</span>
          <ThemeToggle theme={theme} onToggle={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))} />
        </div>
      </header>

      {error && <div className="state-message error">{error} — is the backend running on localhost:8000?</div>}

      {!error && selectedRepo && <RepoDetail repoRef={selectedRepo} onBack={() => setSelectedRepo(null)} />}

      {!error && !selectedRepo && (
        <>
          <SummaryBar summary={summary} />

          <div className="toolbar">
            <SearchBar value={search} onChange={setSearch} />
            <button className="add-repo-btn" onClick={() => setShowAddModal(true)}>
              + Add repo
            </button>
          </div>

          {repos === null ? (
            <div className="state-message">Loading…</div>
          ) : (
            <RepoTable
              repos={visibleRepos}
              activeFilter={filter}
              onFilterChange={setFilter}
              onSelectRepo={(repo) => setSelectedRepo({ owner: repo.owner, name: repo.name })}
              onRemoveRepo={handleRemoveRepo}
            />
          )}
        </>
      )}

      {showAddModal && <AddRepoModal onClose={() => setShowAddModal(false)} onAdded={handleRepoAdded} />}
    </div>
  )
}
