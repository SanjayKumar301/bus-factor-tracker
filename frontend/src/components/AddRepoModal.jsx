import { useEffect, useState } from 'react'
import { searchGithub, addRepo } from '../api.js'

export default function AddRepoModal({ onClose, onAdded }) {
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState(null)
  const [adding, setAdding] = useState(null) // full_name of the repo currently being added, or null
  const [addError, setAddError] = useState(null)

  // Debounced search-as-you-type: wait 350ms after the user stops typing
  // before calling GitHub, so we're not firing a request on every keystroke.
  useEffect(() => {
    if (query.trim().length < 2) {
      setSuggestions([])
      setSearchError(null)
      return
    }
    setSearching(true)
    setSearchError(null)
    const timeout = setTimeout(() => {
      searchGithub(query.trim())
        .then((results) => setSuggestions(results))
        .catch((e) => setSearchError(e.message))
        .finally(() => setSearching(false))
    }, 350)
    return () => clearTimeout(timeout)
  }, [query])

  async function handleAdd(repo) {
    setAdding(repo.full_name)
    setAddError(null)
    try {
      const added = await addRepo(repo.owner, repo.name)
      onAdded(added)
    } catch (e) {
      setAddError(e.message)
      setAdding(null)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">Add a repository to track</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <input
          type="text"
          className="modal-search-input"
          placeholder="Search GitHub — e.g. sindresorhus/ky"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
        />

        {adding && (
          <div className="modal-status">
            Syncing {adding}… this takes 10-15s, same as one repo in the batch sync.
          </div>
        )}

        {addError && <div className="modal-status error">{addError}</div>}

        {searching && <div className="modal-status">Searching…</div>}
        {searchError && <div className="modal-status error">{searchError}</div>}

        <div className="suggestion-list">
          {suggestions.map((repo) => (
            <div key={repo.full_name} className="suggestion-row">
              <div className="suggestion-info">
                <div className="suggestion-name">{repo.full_name}</div>
                {repo.description && <div className="suggestion-desc">{repo.description}</div>}
                <div className="suggestion-meta">
                  {repo.language || 'unknown'} · {repo.stars.toLocaleString()} stars
                </div>
              </div>
              <button
                className="suggestion-add-btn"
                onClick={() => handleAdd(repo)}
                disabled={adding !== null}
              >
                {adding === repo.full_name ? 'Syncing…' : 'Add'}
              </button>
            </div>
          ))}
        </div>

        {!searching && query.trim().length >= 2 && suggestions.length === 0 && !searchError && (
          <div className="modal-status">No repositories found.</div>
        )}
      </div>
    </div>
  )
}
