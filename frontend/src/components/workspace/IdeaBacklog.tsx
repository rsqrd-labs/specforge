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
 * restraint: "Use idea" prefills the version input for confirmation and the
 * parent carries the idea identity through generation, so this is never a
 * silent or frontend-only state mutation.
 */

import { useState } from "react"

import type { IncrementIdea } from "../../types/github"
import { GitHubIcon, IdeaIcon } from "../shared/icons"

const IDEA_MAX = 2000

interface IdeaBacklogProps {
  ideas: IncrementIdea[]
  capturing: boolean
  onCapture: (text: string) => Promise<boolean>
  onPromote: (idea: IncrementIdea) => void
  selectedIdeaId?: string
  disabled?: boolean
  disabledReason?: string
}

const STATUS_NOTE: Record<IncrementIdea["status"], string | null> = {
  open: null,
  planned: "Added to version",
  done: "Shipped",
  dismissed: "Dismissed",
}

export function IdeaBacklog({
  ideas,
  capturing,
  onCapture,
  onPromote,
  selectedIdeaId,
  disabled = false,
  disabledReason,
}: IdeaBacklogProps) {
  const [draft, setDraft] = useState("")
  const disabledReasonId = disabledReason ? "idea-backlog-disabled-reason" : undefined

  async function submit() {
    const text = draft.trim()
    if (!text || capturing || disabled) return
    const saved = await onCapture(text)
    if (saved) setDraft("")
  }

  return (
    <div className="ws-ideas">
      <div className="ws-ideas-header">
        <div>
          <span className="ws-ideas-title">Ideas for later</span>
          <p>Save rough thoughts here without generating tasks yet.</p>
        </div>
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
          placeholder="For example: Support dark mode"
          aria-label="Capture an idea"
          aria-describedby={disabled ? disabledReasonId : undefined}
          disabled={disabled}
          title={disabled ? disabledReason : undefined}
          spellCheck
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              void submit()
            }
          }}
        />
        <button
          type="button"
          className="ws-ideas-add"
          aria-label="Save idea"
          disabled={!draft.trim() || capturing || disabled}
          title={disabled ? disabledReason : undefined}
          aria-describedby={disabled ? disabledReasonId : undefined}
          onClick={() => void submit()}
        >
          {capturing ? "Saving…" : "Save idea"}
        </button>
      </div>
      {disabled && disabledReason ? (
        <p id={disabledReasonId} className="workspace-lock-inline-note">
          {disabledReason}
        </p>
      ) : null}

      {ideas.length === 0 ? (
        <p className="ws-ideas-empty">
          No saved ideas yet. Add one above when something is worth remembering
          but not ready to become a version.
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
                className={`ws-idea${promotable ? "" : " resolved"}${
                  selectedIdeaId === idea.id ? " selected" : ""
                }`}
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
                    onClick={() => {
                      if (!disabled) onPromote(idea)
                    }}
                    disabled={disabled || selectedIdeaId === idea.id}
                    title={disabled ? disabledReason : undefined}
                    aria-describedby={disabled ? disabledReasonId : undefined}
                    aria-label={`Use idea for next version: ${idea.text}`}
                  >
                    {selectedIdeaId === idea.id ? "Using" : "Use idea"}
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
