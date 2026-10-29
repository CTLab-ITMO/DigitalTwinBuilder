<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import { useAppStore } from '../stores/app'
import { t } from '../i18n'
import type { AssistantReply } from '../utils/reply'
import {
  groupTranscript,
  lastUserMessage as findLastUserMessage,
  type TranscriptAttempt,
  type TranscriptTurn,
} from '../utils/transcript'

const store = useAppStore()
const input = ref('')
const scrollArea = ref<HTMLElement | null>(null)
// Covers the short window between the click and the store marking the session
// running: a second Enter there would start a second turn in the same chat.
const starting = ref(false)
const temperature = ref(0.7)
// The finished requirements object plus its `<think>` block runs past 1000
// tokens, and a reply cut off mid-JSON is one the client cannot read at all —
// so the default matches the DB slot's budget rather than the smallest value
// that fits a chat answer.
const maxTokens = ref(3000)

const agentId = 0
const convIdx = 0

// The transcript as the chat shows it. The interview agent answers with a JSON
// envelope and the broker may repair a reply more than once, so the stored
// conversation is grouped into turns: one user message, then every attempt it
// produced. Only the selected attempt is rendered, at most one bubble per turn.
const turns = computed(() => groupTranscript(store.messages))

// How far back from the newest attempt each turn is showing (0 = newest).
// Keyed by turn, so paging one turn's retries does not move another.
const attemptOffset = ref<Record<string, number>>({})

function offsetFor(turn: TranscriptTurn): number {
  return attemptOffset.value[turn.key] ?? 0
}

function attemptIndex(turn: TranscriptTurn): number {
  const offset = Math.min(offsetFor(turn), Math.max(turn.attempts.length - 1, 0))
  return Math.max(turn.attempts.length - 1 - offset, 0)
}

function canOlder(turn: TranscriptTurn): boolean {
  return offsetFor(turn) < turn.attempts.length - 1
}

function canNewer(turn: TranscriptTurn): boolean {
  return offsetFor(turn) > 0
}

/** ‹ steps back through the retries, › returns towards the newest attempt. */
function stepAttempt(turn: TranscriptTurn, direction: number) {
  const next = Math.min(
    Math.max(offsetFor(turn) + direction, 0),
    Math.max(turn.attempts.length - 1, 0),
  )
  attemptOffset.value = { ...attemptOffset.value, [turn.key]: next }
}

const renderedTurns = computed(() =>
  turns.value.map(turn => {
    const index = attemptIndex(turn)
    return { ...turn, selectedIndex: index, attempt: turn.attempts[index] ?? null }
  }),
)

/** Whether this attempt has anything for the Details fold. */
function hasDetails(reply: AssistantReply | null | undefined): boolean {
  return !!reply && (!!reply.think || !!reply.json || (reply.looksLikeJson && !!reply.text))
}

/** The fold's label names what is actually inside it. */
function detailsLabel(reply: AssistantReply): string {
  const hasThink = !!reply.think
  const hasJson = !!reply.json
  const hasRaw = !hasJson && reply.looksLikeJson && !!reply.text
  if (hasThink && (hasJson || hasRaw)) return t('interview.details')
  if (hasJson) return t('interview.jsonAnswer')
  if (hasRaw) return t('interview.rawReply')
  return t('interview.reasoning')
}

const copiedId = ref<string | null>(null)

/**
 * Copy a block of text.
 *
 * `navigator.clipboard` only exists in a secure context, and this app is
 * routinely opened over plain HTTP on a LAN, so fall back to the old hidden
 * textarea trick rather than making the button a no-op there.
 */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch { /* fall through to the fallback */ }

  try {
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    try {
      area.select()
      return document.execCommand('copy')
    } finally {
      document.body.removeChild(area)
    }
  } catch {
    return false
  }
}

async function copyAttempt(attempt: TranscriptAttempt) {
  if (!attempt.reply.json) return
  if (!await copyText(attempt.reply.json)) return
  copiedId.value = attempt.id
  setTimeout(() => {
    if (copiedId.value === attempt.id) copiedId.value = null
  }, 1500)
}

// The broker is answering: it posted the turn, waits for the agent, and may be
// sending the reply back for a correction. Nothing else may be submitted while
// it does, or two jobs would write to the same conversation at once.
const isProcessing = computed(() => store.uiRunning)

// How many correction turns the broker has already asked for. Shown only from
// the second turn on: a repair is why the wait is longer than a single answer.
const repairs = computed(() => Math.max((store.uiJob?.attempts.length ?? 1) - 1, 0))

// Shows "Processing..." only while *this* chat has an interview job in flight.
// It used to also infer a wait from the transcript ending on a user turn, which
// made every chat whose last turn failed or was interrupted look like it was
// still waiting — forever, in every session that was opened.
const isWaiting = isProcessing

// Keep the newest turn in view. The pane has no other scroll management, so a
// message appended below the fold looked like it had never been rendered.
watch(
  () => `${store.messages.length}:${isWaiting.value}`,
  async () => {
    await nextTick()
    const el = scrollArea.value
    if (el) el.scrollTop = el.scrollHeight
  },
)

// Seeded with the interview system prompt on creation: the agent takes its
// instructions from the conversation, and a conversation without them is what
// the DB slot used to be handed — a valid `requirements` object never came out.
async function getOrCreateConv(): Promise<string | null> {
  return store.ensureConversation(agentId, convIdx)
}

// The last thing the user actually said. A failed turn ends the transcript on
// this message — the broker's repair prompts are skipped — so it is what a
// retry re-asks.
const lastUserMessage = computed(() => findLastUserMessage(store.messages))

// A turn whose reply could not be read even after the broker's repairs is
// retryable, as long as there is a user turn left to re-ask.
const canRetry = computed(() =>
  !!store.uiVerdict
  && !store.uiVerdict.ok
  && !store.interviewResult
  && lastUserMessage.value !== ''
)

async function submitTurn(msg: string, retry: boolean) {
  if (starting.value) return
  starting.value = true
  try {
    // Auto-create session if none selected — and wait for a creation already in
    // flight (the "+ New Chat" click) instead of starting a second one, which
    // would wipe the greeting and the message about to be shown.
    if (!store.currentSessionId || store.creatingSession) {
      const sid = await store.createSession()
      if (!sid) {
        store.error = t('error.createSession')
        return
      }
    }

    const convId = await getOrCreateConv()
    if (!convId) {
      store.error = t('error.createConversation')
      return
    }

    // Show the turn first, but only once the session and its conversation
    // exist: creating either of them reloads `messages` from the server, so a
    // push made before that is what used to vanish until the turn finished or
    // the page was reloaded. The broker posts the authoritative copy, and the
    // transcript is reloaded from it when the job finishes.
    if (!retry) {
      store.messages.push({
        id: crypto.randomUUID(),
        role: 'user',
        content: msg,
      })
    }

    // The broker posts the message, reads the reply as the schema's JSON, and
    // sends a correction back while it cannot be read — so an unparseable answer
    // never reaches the transcript-and-DB-tab disagreement this used to cause.
    // On a retry the broker posts its own copy of the re-ask, since the user's
    // question is already in the conversation.
    const pending = store.sendInterviewMessage(convId, msg, {
      temperature: temperature.value,
      max_tokens: maxTokens.value,
      retry,
    })
    // `sendInterviewMessage` marks the session running before its first await,
    // so the in-flight guard passes over to the store's per-session flag here.
    starting.value = false
    await pending
  } catch (e: any) {
    store.error = e?.message || String(e)
  } finally {
    starting.value = false
  }
}

async function send() {
  if (starting.value || isProcessing.value) return
  const msg = input.value.trim()
  if (!msg) return

  // Clear input immediately
  input.value = ''

  await submitTurn(msg, false)
}

// Re-ask the last turn: the same question, submitted as a retry so the message
// the user already sees is not shown a second time.
async function retry() {
  if (!canRetry.value) return
  // The new attempt is about to become the newest one; show it when it lands
  // even if the user had stepped back to an older attempt.
  const lastTurn = turns.value[turns.value.length - 1]
  if (lastTurn) {
    attemptOffset.value = { ...attemptOffset.value, [lastTurn.key]: 0 }
  }
  await submitTurn(lastUserMessage.value, true)
}
</script>

<template>
  <div class="interview-tab">
    <div ref="scrollArea" class="scroll-area">
      <h2>{{ t('interview.title') }}</h2>

      <div v-if="store.interviewResult" class="card completed">
        <strong>{{ t('interview.completed') }}</strong>
        <p class="hint">{{ t('interview.completedHint') }}</p>
      </div>

      <div
        v-if="store.uiVerdict && !store.uiVerdict.ok && !isProcessing && !store.interviewResult"
        class="card failed"
      >
        <strong>{{ t('interview.failed') }}</strong>
        <p class="hint">
          {{ t('interview.failedHint', { n: store.uiVerdict.attempts }) }}
        </p>
        <pre class="report">{{ store.uiVerdict.report }}</pre>
        <button
          class="btn btn-primary retry-btn"
          :disabled="!canRetry"
          @click="retry"
        >
          {{ t('interview.retry') }}
        </button>
      </div>

      <div class="messages">
        <template v-for="turn in renderedTurns" :key="turn.key">
          <div v-if="turn.user" class="message user">
            <div class="msg-content">{{ turn.user.content }}</div>
          </div>

          <template v-if="turn.attempt">
            <div class="message assistant">
              <details v-if="hasDetails(turn.attempt.reply)" class="reply-details">
                <summary>{{ detailsLabel(turn.attempt.reply) }}</summary>

                <section v-if="turn.attempt.reply.think" class="reply-section">
                  <div class="reply-section-head">{{ t('interview.reasoning') }}</div>
                  <pre class="detail-body">{{ turn.attempt.reply.think }}</pre>
                </section>

                <section v-if="turn.attempt.reply.json" class="reply-section">
                  <div class="reply-section-head">
                    <span>{{ t('interview.jsonAnswer') }}</span>
                    <button type="button" class="copy-btn" @click="copyAttempt(turn.attempt)">
                      {{ copiedId === turn.attempt.id ? t('interview.copied') : t('interview.copy') }}
                    </button>
                  </div>
                  <pre class="detail-body">{{ turn.attempt.reply.json }}</pre>
                </section>

                <section
                  v-else-if="turn.attempt.reply.looksLikeJson && turn.attempt.reply.text"
                  class="reply-section"
                >
                  <div class="reply-section-head">{{ t('interview.rawReply') }}</div>
                  <pre class="detail-body">{{ turn.attempt.reply.text }}</pre>
                </section>
              </details>

              <div class="msg-content">
                <template v-if="turn.attempt.reply.isJson">
                  {{ turn.attempt.reply.text || t('interview.noText') }}
                </template>
                <template v-else-if="turn.attempt.reply.looksLikeJson">
                  {{ t('interview.invalidReply') }}
                </template>
                <template v-else>
                  {{ turn.attempt.reply.text || t('interview.noText') }}
                </template>
              </div>
            </div>

            <div v-if="turn.attempts.length > 1" class="attempt-nav">
              <button
                type="button"
                class="attempt-arrow"
                :disabled="!canOlder(turn)"
                :title="t('interview.olderAttempt')"
                :aria-label="t('interview.olderAttempt')"
                @click="stepAttempt(turn, 1)"
              >
                ‹
              </button>
              <span class="attempt-count">
                {{ t('interview.attemptNav', { n: turn.selectedIndex + 1, total: turn.attempts.length }) }}
              </span>
              <button
                type="button"
                class="attempt-arrow"
                :disabled="!canNewer(turn)"
                :title="t('interview.newerAttempt')"
                :aria-label="t('interview.newerAttempt')"
                @click="stepAttempt(turn, -1)"
              >
                ›
              </button>
            </div>
          </template>
        </template>

        <div v-if="isWaiting" class="message assistant">
          <div class="msg-content">
            <span class="spinner" style="display:inline-block;vertical-align:middle" />
            {{ t('interview.processing') }}
            <span v-if="repairs" class="repairs">
              {{ t('interview.repair', { n: repairs }) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <div class="bottom-bar">
      <div class="card params-card">
        <div class="param-row">
          <label>{{ t('interview.temperature') }}</label>
          <input type="range" min="0" max="2" step="0.1" v-model.number="temperature" />
          <span class="param-value">{{ temperature }}</span>
        </div>
        <div class="param-row">
          <label>{{ t('interview.maxTokens') }}</label>
          <input type="number" v-model.number="maxTokens" min="100" max="10000" />
        </div>
      </div>

      <div class="input-area">
        <input
          v-model="input"
          type="text"
          :placeholder="t('interview.placeholder')"
          :disabled="!!store.interviewResult || isProcessing"
          @keydown.enter="send"
        />
        <button class="btn btn-primary" @click="send" :disabled="!input.trim() || isProcessing">
          {{ t('interview.send') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.interview-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.scroll-area {
  flex: 1;
  overflow-y: auto;
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
}

.scroll-area h2 { font-size: 18px; font-weight: 600; margin-bottom: 16px; }

.completed { border-color: var(--green); }
.completed strong { color: var(--green); }
.failed { border-color: var(--red); }
.failed strong { color: var(--red); }
.hint { margin-top: 8px; color: var(--text-muted); font-size: 13px; }

.report {
  background: var(--bg);
  border-radius: var(--radius);
  padding: 12px;
  margin-top: 8px;
  font-size: 12px;
  white-space: pre-wrap;
  max-height: 240px;
  overflow: auto;
}

.retry-btn { margin-top: 12px; }

.repairs { color: var(--text-muted); font-size: 12px; margin-left: 8px; }

.messages {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-bottom: 16px;
}

.message {
  padding: 12px 16px;
  border-radius: var(--radius);
  max-width: 80%;
}
.message.user { background: var(--accent); color: white; align-self: flex-end; }
.message.assistant { background: var(--surface2); align-self: flex-start; }
.message.system { display: none; }

.msg-content { white-space: pre-wrap; word-break: break-word; font-size: 14px; line-height: 1.5; }

/* One fold per assistant turn: the model's reasoning and, when the answer is
   readable, its full JSON. Folded away by default — they are the "why" and the
   envelope, not the message the user is meant to read. */
.reply-details {
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}
.reply-details summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--text-muted);
  user-select: none;
}
.reply-section { margin-top: 8px; }
.reply-section + .reply-section { margin-top: 10px; }
.reply-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--text-muted);
}
.detail-body {
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.45;
  color: var(--text-muted);
  background: rgba(0, 0, 0, 0.22);
  border-radius: 6px;
  padding: 8px 10px;
}
.copy-btn {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-muted);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}
.copy-btn:hover { color: var(--text); border-color: var(--text-muted); }

/* Retry navigation: one small row directly under the assistant bubble. */
.attempt-nav {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: -4px;
  padding-left: 4px;
  font-size: 12px;
  color: var(--text-muted);
  align-self: flex-start;
}
.attempt-arrow {
  border: 1px solid var(--border);
  background: var(--surface2);
  color: var(--text);
  border-radius: 6px;
  width: 22px;
  height: 22px;
  line-height: 1;
  cursor: pointer;
  font-size: 14px;
}
.attempt-arrow:disabled { opacity: 0.4; cursor: default; }
.attempt-count { min-width: 90px; text-align: center; }

.param-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.param-row:last-child { margin-bottom: 0; }
.param-row label { font-size: 13px; color: var(--text-muted); min-width: 100px; }
.param-row input[type="range"] { flex: 1; }
.param-value { font-size: 13px; min-width: 30px; text-align: right; }
.param-row input[type="number"] { width: 100px; }

.bottom-bar {
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
  padding-top: 8px;
}

.params-card {
  margin-bottom: 8px !important;
}

.input-area { display: flex; gap: 8px; }
.input-area input { flex: 1; }
</style>
