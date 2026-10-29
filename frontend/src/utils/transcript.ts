import type { Message } from '../types'
import { splitAssistantReply, type AssistantReply } from './reply'

/**
 * A message's `metadata.kind`, or undefined when it carries none.
 *
 * The API returns `jsonb` as a JSON *string* rather than an object (asyncpg
 * reads jsonb as text), so both spellings are accepted here.
 */
export function messageKind(msg: Message): string | undefined {
  const raw = msg.metadata
  if (!raw) return undefined
  let meta: any = raw
  if (typeof raw === 'string') {
    try { meta = JSON.parse(raw) } catch { return undefined }
  }
  return meta && typeof meta === 'object' ? meta.kind : undefined
}

/** One assistant attempt: the original reply or one the broker asked to repair. */
export interface TranscriptAttempt {
  id: string
  /** The stored reply exactly as the agent wrote it. */
  raw: string
  reply: AssistantReply
}

/** One logical exchange: what the user said and every reply it produced. */
export interface TranscriptTurn {
  /** Stable key for per-turn UI state (the user message, or the reply alone). */
  key: string
  user: Message | null
  attempts: TranscriptAttempt[]
}

/**
 * Group a stored conversation into the turns the chat shows.
 *
 * The broker serialises a retry as a repair-tagged `user` prompt followed by the
 * corrected assistant reply, so the boundary is positional: everything after a
 * user turn belongs to it until the user speaks again. Repair prompts are not
 * rendered — they are the broker's correction, not the user's words — and the
 * replies they produce become further attempts of the same turn. That is what
 * keeps a failed turn from filling the chat with one bubble per retry.
 *
 * An assistant turn with no user before it (the greeting) is its own turn.
 * System messages are dropped; the pane never showed them.
 */
export function groupTranscript(messages: Message[]): TranscriptTurn[] {
  const turns: TranscriptTurn[] = []
  let current: TranscriptTurn | null = null

  for (const msg of messages) {
    if (msg.role === 'system') continue

    if (msg.role === 'user') {
      if (messageKind(msg) === 'repair') continue
      current = { key: msg.id, user: msg, attempts: [] }
      turns.push(current)
      continue
    }

    if (!current) {
      current = { key: msg.id, user: null, attempts: [] }
      turns.push(current)
    }
    current.attempts.push({
      id: msg.id,
      raw: msg.content,
      reply: splitAssistantReply(msg.content),
    })
  }

  return turns
}

/**
 * The last thing the user actually typed.
 *
 * A failed turn ends the transcript on the user's own message — the broker's
 * repair prompts are skipped, since re-asking them would not be re-asking the
 * user's question.
 */
export function lastUserMessage(messages: Message[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i]
    if (msg.role !== 'user') continue
    if (messageKind(msg) === 'repair') continue
    return msg.content
  }
  return ''
}
