/**
 * RepoPicker — filterable existing-repository chooser inside the GitHub export
 * modal.
 *
 * The moment-of-use feeling: recognising your own repo in a short, calm list —
 * not recalling and spelling its exact name. A quiet filter input sits above a
 * bounded scrollable list; each row is the bare repo name (every repo in an
 * installation shares one owner, so repeating it 500× is noise) plus a small
 * private/public badge. Selection is a saffron ring, mirroring the export-mode
 * options below it.
 *
 * Rows are sorted locally by name and filtered case-insensitively. The list is
 * capped upstream (backend fetches ≤5 pages of 100), so plain DOM rendering is
 * fine — no virtualisation. When the upstream list is truncated, a one-line
 * note points at the type-a-name escape hatch (the modal's "manual" mode).
 */

import { useMemo, useState } from "react"

import type { RepositoryOption } from "../../types/github"

interface RepoPickerProps {
  repos: RepositoryOption[]
  selectedRepoId: number | null
  onSelect: (repo: RepositoryOption) => void
  truncated: boolean
}

export function RepoPicker({
  repos,
  selectedRepoId,
  onSelect,
  truncated,
}: RepoPickerProps) {
  const [filter, setFilter] = useState("")

  const sorted = useMemo(
    () => [...repos].sort((a, b) => a.name.localeCompare(b.name)),
    [repos],
  )
  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return sorted
    return sorted.filter((repo) => repo.full_name.toLowerCase().includes(needle))
  }, [sorted, filter])

  return (
    <div className="gh-repo-picker">
      <input
        type="text"
        className="modal-input gh-repo-filter"
        placeholder="Filter repositories…"
        aria-label="Filter repositories"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        spellCheck={false}
        autoComplete="off"
      />
      <ul className="gh-repo-list" role="listbox" aria-label="Repositories">
        {visible.map((repo) => {
          const selected = repo.id === selectedRepoId
          return (
            <li key={repo.id} role="option" aria-selected={selected}>
              <button
                type="button"
                className={`gh-repo-row${selected ? " selected" : ""}`}
                onClick={() => onSelect(repo)}
              >
                <span className="gh-repo-row-name">{repo.name}</span>
                <span className="gh-repo-row-badge">
                  {repo.private ? "Private" : "Public"}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      {visible.length === 0 && (
        <p className="gh-repo-list-empty">No repositories match the filter.</p>
      )}
      {truncated && (
        <p className="gh-repo-truncated-note">
          Not every repository is listed — narrow the filter, or type the
          repository name instead.
        </p>
      )}
    </div>
  )
}
