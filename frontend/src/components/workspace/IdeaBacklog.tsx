/**
 * IdeaBacklog — the quiet side inbox of the living workspace (Phase 21, T-289).
 *
 * Moment-of-use feeling: a calm place to jot the next idea without breaking
 * flow — a soft pile of notes, not a ticket queue. Ideas captured here (and
 * ones that flowed back from GitHub issues labelled idea/enhancement) wait until
 * you're ready to fold one into an increment.
 *
 * Layout sketch (a child block beneath the timeline, same panel rhythm):
 *   IDEAS
 *   [ Jot an idea…                                   ＋ ]
 *   ✦ Dark mode toggle                        Promote
 *   ⌗ Webhook retries  (from GitHub)          Promote
 *
 * Visual hierarchy: the capture input invites first; ideas are soft slate
 * chips, provenance legible by a small bespoke mark (GitHub vs. spark). The one
 * restraint: "Promote" is a quiet text action that *composes* — it prefills the
 * increment input above for the user to confirm — never a loud button, never a
 * silent state mutation.
 */

import { useState } from "react"

import type { IncrementIdea } from "../../types/github"
import { GitHubIcon, IdeaIcon } from "../shared/icons"

const IDEA_MAX = 2000

interface IdeaBacklogProps {
  ideas: IncrementIdea[]
  capturing: boolean
  onCapture: (text: string) => void
  onPromote: (idea: IncrementIdea) => void
}

const STATUS_NOTE: Record<IncrementIdea["status"], string | null> = {
  open: null,
  planned: "Planned",
  done: "Shipped",
  dismissed: "Dismissed",
}

export function IdeaBacklog({
  ideas,
  capturing,
  onCapture,
  onPromote,
}: IdeaBacklogProps) {
  const [draft, setDraft] = useState("")

  function submit() {
    const text = draft.trim()
    if (!text || capturing) return
    onCapture(text)
    setDraft("")
  }

  return (
    <div className="ws-ideas">
      <div className="ws-ideas-header">
        <span className="ws-ideas-title">Ideas</span>
        {ideas.length > 0 && (
          <span className="ws-ideas-count">{ideas.length}</span>
        )}
      </div>

      <div className="ws-ideas-capture">
        <input
          className="ws-ideas-input"
          type="text"
          value={draft}
          maxLength={IDEA_MAX}
          placeholder="Jot an idea…"
          aria-label="Capture an idea"
          spellCheck
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              submit()
            }
          }}
        />
        <button
          type="button"
          className="ws-ideas-add"
          aria-label="Add idea"
          disabled={!draft.trim() || capturing}
          onClick={submit}
        >
          {capturing ? "…" : "＋"}
        </button>
      </div>

      {ideas.length === 0 ? (
        <p className="ws-ideas-empty">
          Nothing yet — capture a feature as it occurs to you, and fold it into
          an increment when you're ready.
        </p>
      ) : (
        <ul className="ws-ideas-list">
          {ideas.map((idea) => {
            const fromGitHub = idea.source === "github"
            const note = STATUS_NOTE[idea.status]
            const promotable = idea.status === "open"
            return (
              <li
                key={idea.id}
                className={`ws-idea${promotable ? "" : " resolved"}`}
              >
                <span
                  className="ws-idea-mark"
                  aria-hidden="true"
                  title={fromGitHub ? "From a GitHub issue" : "Captured idea"}
                >
                  {fromGitHub ? <GitHubIcon /> : <IdeaIcon />}
                </span>
                <span className="ws-idea-text">{idea.text}</span>
                {note ? (
                  <span className="ws-idea-note">{note}</span>
                ) : (
                  <button
                    type="button"
                    className="ws-idea-promote"
                    onClick={() => onPromote(idea)}
                    aria-label="Promote idea to increment"
                  >
                    Promote
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
