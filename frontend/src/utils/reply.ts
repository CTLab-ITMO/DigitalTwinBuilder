/**
 * Reading the interview agent's replies.
 *
 * The model writes an optional `<think>…</think>` reasoning block followed by
 * its JSON answer. The store parses that JSON for `requirements`; the chat shows
 * the `message` it carries. Both sides need the same split, so the helpers live
 * here rather than as two copies that could drift.
 */

/**
 * The first complete JSON object in a model reply, or null if there is none.
 *
 * Braces inside strings do not count, so the object ends at its own matching
 * brace — not at the last brace in the text. That distinction matters: the
 * agent answers with `<think>…</think>` plus the object, and a small model
 * routinely miscounts the closing braces, leaving an extra `}` after the
 * requirements. Slicing to the *last* brace then hands `JSON.parse` trailing
 * junk and the whole reply is rejected, discarding requirements that are in
 * fact complete.
 */
export function extractJsonObject(text: string): string | null {
  const start = text.indexOf('{')
  if (start === -1) return null
  let depth = 0
  let inString = false
  let escaped = false
  for (let i = start; i < text.length; i++) {
    const ch = text[i]
    if (escaped) { escaped = false; continue }
    if (inString) {
      if (ch === '\\') escaped = true
      else if (ch === '"') inString = false
      continue
    }
    if (ch === '"') inString = true
    else if (ch === '{') depth++
    else if (ch === '}' && --depth === 0) return text.slice(start, i + 1)
  }
  return null
}

/**
 * The model's reasoning block, removed. SmolLM3 writes `<think>…</think>`
 * before its answer, and a brace inside that prose would otherwise be read as
 * the start of the JSON object. An opening tag with no closing one means the
 * turn ended inside the reasoning, so everything from it is dropped.
 */
export function stripThink(text: string): string {
  const closed = text.replace(/<think(?:ing)?>[\s\S]*?<\/think(?:ing)?>/gi, '')
  const open = closed.search(/<think(?:ing)?>/i)
  return open === -1 ? closed : closed.slice(0, open)
}

/** Parse the first JSON object in a reply, or null if it is not readable. */
export function parseJsonObject(text: string): any | null {
  const raw = extractJsonObject(stripThink(text))
  if (raw === null) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

/** One assistant turn, split into what the chat shows and what it folds away. */
export interface AssistantReply {
  /** The reasoning block the model wrote, or null when it wrote none. */
  think: string | null
  /** The JSON's `message`, or the raw reply (minus reasoning) when there is no
   *  readable JSON. The chat shows the former in the bubble and the latter only
   *  inside the Details fold. */
  text: string
  /** The JSON answer's `message` field, when the reply was one. */
  message: string | null
  /** The parsed answer, pretty-printed, or null when it did not parse. */
  json: string | null
  /** Whether the reply was a readable interview JSON object. */
  isJson: boolean
  /** Whether the non-reasoning part of the turn contains a `{` — i.e. it was
   *  meant to be JSON but may not have parsed. Used to tell an unreadable
   *  answer from ordinary prose without dumping the broken object in the chat. */
  looksLikeJson: boolean
}

/**
 * Split an assistant turn for display.
 *
 * The interview's JSON is an envelope: `message` is what the agent says to the
 * user, while `requirements` is the artifact the DB and twin tabs consume. The
 * chat therefore shows only `message` and does not dump the document into the
 * bubble. A plain-prose reply (the greeting) is shown as written. A reply that
 * was meant to be JSON but did not parse keeps its raw text in `text` and sets
 * `looksLikeJson`, so the chat can show a status line and fold the raw answer
 * away instead of painting a truncated object into the message.
 */
export function splitAssistantReply(content: string): AssistantReply {
  // Collect every reasoning block — a model that thinks twice in one turn
  // writes two — and keep the text between them as the candidate answer.
  const thoughts: string[] = []
  const rest = (content || '').replace(
    /<think(?:ing)?>([\s\S]*?)(?:<\/think(?:ing)?>|$)/gi,
    (_match, body: string) => {
      thoughts.push(body.trim())
      return ''
    },
  ).trim()

  const think = thoughts.filter(Boolean).join('\n\n') || null
  const parsed = parseJsonObject(rest)

  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    const message = typeof parsed.message === 'string' ? parsed.message.trim() : ''
    return {
      think,
      text: message,
      message: message || null,
      json: JSON.stringify(parsed, null, 2),
      isJson: true,
      looksLikeJson: true,
    }
  }
  return {
    think,
    text: rest,
    message: null,
    json: null,
    isJson: false,
    looksLikeJson: rest.includes('{'),
  }
}
