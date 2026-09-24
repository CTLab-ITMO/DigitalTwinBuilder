import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../api/client'
import type { Session, Conversation, Message, AgentStatus, QueueStatus, PipelineJob, PipelinePrompts, DbPipelineResult, DesPipelineResult, UiPipelineResult, TwinPipelineResult } from '../types'

const UI_AGENT = 0
const DB_AGENT = 1
const DT_AGENT = 2
/** The DT agent's SimPy slot. The others are GenConf (0) and GenSim (1). */
const DES_CONV_IDX = 2
const POLL_INTERVAL_MS = 1000
const POLL_TIMEOUT_MS = 20 * 60 * 1000

export const useAppStore = defineStore('app', () => {
  // State
  const sessions = ref<Session[]>([])
  const currentSessionId = ref<string | null>(null)
  const conversations = ref<Conversation[]>([])
  const messages = ref<Message[]>([])
  const agentStatuses = ref<AgentStatus[]>([])
  const queueStatuses = ref<Record<number, QueueStatus>>({})
  const activeTab = ref(0)
  const activeConvIdx = ref(0)

  // Interview / DB / Twin state
  const interviewResult = ref<any>(null)
  const dbSchema = ref<string | null>(null)
  const twinConfig = ref<any>(null)
  const simulationCode = ref<string | null>(null)

  // DB / DES pipeline: the verdict of the last run and its per-turn log
  const prompts = ref<PipelinePrompts | null>(null)
  const pipelineJob = ref<PipelineJob | null>(null)
  const dbVerdict = ref<DbPipelineResult | null>(null)
  const desCode = ref<string | null>(null)
  const desVerdict = ref<DesPipelineResult | null>(null)

  // Interview slot: its own job, verdict and in-flight flag — the DB/DES tab
  // reads `pipelineJob` for its per-turn log, so the interview must not write
  // over it (or the DES log would vanish mid-run).
  const uiJob = ref<PipelineJob | null>(null)
  const uiVerdict = ref<UiPipelineResult | null>(null)
  const uiRunning = ref(false)

  // The twin's two slots report their verdict here rather than in `uiVerdict` or
  // `desVerdict`, so the DES card's KPI panel is not overwritten by a
  // configuration turn. There is no per-attempt log to keep: neither slot has a
  // validator, so a run is one turn and the only thing worth showing is whether
  // that turn produced a reply.
  const twinVerdict = ref<TwinPipelineResult | null>(null)

  // Loading states
  const loading = ref(false)
  const error = ref<string | null>(null)

  // Getters
  const currentSession = computed(() =>
    sessions.value.find(s => s.id === currentSessionId.value) || null
  )

  // Actions
  async function loadSessions() {
    try {
      const data = await api.getSessions()
      sessions.value = data.sessions
    } catch (e: any) {
      error.value = e.message
    }
  }

  async function createSession() {
    try {
      const data = await api.createSession()
      currentSessionId.value = data.session_id
      conversations.value = []
      messages.value = []
      interviewResult.value = null
      dbSchema.value = null
      twinConfig.value = null
      simulationCode.value = null
      pipelineJob.value = null
      dbVerdict.value = null
      desCode.value = null
      desVerdict.value = null
      uiJob.value = null
      uiVerdict.value = null
      twinVerdict.value = null
      await loadSessions()
      // Seed the interview slot now rather than on the first send: the greeting
      // is the conversation's opening assistant turn, so a new chat has to show
      // it before the user types anything.
      await ensureConversation(UI_AGENT, 0)
      return data.session_id
    } catch (e: any) {
      error.value = e.message
      return null
    }
  }

  async function loadSession(sessionId: string) {
    try {
      error.value = null
      const data = await api.getSession(sessionId)
      currentSessionId.value = sessionId
      conversations.value = data.conversations
      // The interview's job and verdict belong to the conversation that produced
      // them; another session's report must not be shown over this one.
      uiJob.value = null
      uiVerdict.value = null
      twinVerdict.value = null
      // Every artifact is re-read from the conversations below, so drop them
      // first: a session that has no DB or twin conversation yet must not keep
      // showing the previous session's schema, configuration and models.
      interviewResult.value = null
      dbSchema.value = null
      twinConfig.value = null
      simulationCode.value = null
      dbVerdict.value = null
      desCode.value = null
      desVerdict.value = null
      messages.value = []
      // Replay every slot's conversation. The agents post their own replies
      // there (`BaseAgent.add_to_conversation`), so the last assistant turn of a
      // slot's conversation *is* that slot's artifact — which is what makes a
      // reload able to bring back the DB schema and the twin, not just the
      // interview. `messages` is the interview transcript alone, so it is the
      // one slot that is also loaded into the chat pane.
      for (const conv of data.conversations) {
        const loaded = await fetchConversation(conv.id, conv.agent_id, conv.conv_idx)
        if (conv.agent_id === UI_AGENT && conv.conv_idx === 0) messages.value = loaded
      }
      // A session that has no interview conversation yet gets one here,
      // greeting and all.
      if (!data.conversations.some(c => c.agent_id === UI_AGENT && c.conv_idx === 0)) {
        await ensureConversation(UI_AGENT, 0)
      }
    } catch (e: any) {
      error.value = e.message
    }
  }

  async function renameSession(sessionId: string, title: string) {
    error.value = null
    try {
      const data = await api.renameSession(sessionId, title)
      const session = sessions.value.find(s => s.id === sessionId)
      if (session) session.title = data.title
      return true
    } catch (e: any) {
      error.value = e.message
      return false
    }
  }

  /**
   * Delete a session server-side — it takes its conversations and messages with
   * it — then drop the local copy. If it was the open one, everything derived
   * from it has to go too, or the tabs stay pointed at conversations that no
   * longer exist and the next click is a 404.
   */
  async function deleteSession(sessionId: string) {
    error.value = null
    try {
      await api.deleteSession(sessionId)
      sessions.value = sessions.value.filter(s => s.id !== sessionId)
      if (currentSessionId.value === sessionId) {
        currentSessionId.value = null
        conversations.value = []
        messages.value = []
        interviewResult.value = null
        dbSchema.value = null
        twinConfig.value = null
        simulationCode.value = null
        pipelineJob.value = null
        dbVerdict.value = null
        desCode.value = null
        desVerdict.value = null
        uiJob.value = null
        uiVerdict.value = null
        twinVerdict.value = null
      }
      return true
    } catch (e: any) {
      error.value = e.message
      return false
    }
  }

  /**
   * Fetch a conversation and hand each assistant turn to the processor for the
   * slot it belongs to.
   *
   * A conversation's `agent_id`/`conv_idx` is what says which artifact a reply
   * is: the interview transcript, the DB schema, the twin configuration, the
   * PyChrono code or the DES model. Passing that pair through — instead of the
   * interview's `0, 0` for every conversation, as this used to — is what lets a
   * reload restore the DB tab and the twin, not just the chat.
   */
  async function fetchConversation(conversationId: string, agentId: number, convIdx: number): Promise<Message[]> {
    const data = await api.getConversation(conversationId)
    for (const msg of data.messages) {
      if (msg.role === 'assistant') processResult(msg.content, agentId, convIdx)
    }
    return data.messages
  }

  /** Reload the interview slot: its transcript, and the requirements in it. */
  async function loadConversation(conversationId: string) {
    try {
      messages.value = await fetchConversation(conversationId, UI_AGENT, 0)
    } catch (e: any) {
      error.value = e.message
    }
  }

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
  function extractJsonObject(text: string): string | null {
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
  function stripThink(text: string): string {
    const closed = text.replace(/<think(?:ing)?>[\s\S]*?<\/think(?:ing)?>/gi, '')
    const open = closed.search(/<think(?:ing)?>/i)
    return open === -1 ? closed : closed.slice(0, open)
  }

  /** Parse the first JSON object in a reply, or null if it is not readable. */
  function parseJsonObject(text: string): any | null {
    const raw = extractJsonObject(stripThink(text))
    if (raw === null) return null
    try {
      return JSON.parse(raw)
    } catch {
      return null
    }
  }

  /**
   * Drop a markdown fence the agent added despite being asked not to — the
   * mirror of `sql_runner.strip_code_fence` / `des_runner.strip_code_fence`.
   *
   * The broker hands the schema and the DES program over already unwrapped, but
   * the *stored* reply the agents post is raw, so a reload would otherwise bring
   * the schema back wearing ```sql fences and the DES code back wearing
   * ```python ones. Unwraps only when a fenced block is present, so text that
   * legitimately has no fence is untouched.
   */
  function stripCodeFence(text: string): string {
    const m = /```[A-Za-z0-9_+-]*[ \t]*\r?\n([\s\S]*?)```/.exec(text || '')
    return m ? m[1].replace(/^\n+|\n+$/g, '') : (text || '')
  }

  function processResult(result: string, agentId: number, convIdx: number) {
    if (agentId === 0) {
      // UI/Interview agent — extract JSON
      const parsed = parseJsonObject(result)
      if (parsed) {
        if (parsed.completed) {
          interviewResult.value = parsed.requirements
        }
      } else if (result.includes('{')) {
        // A reply that looks like JSON but cannot be read used to be dropped in
        // silence: the transcript showed a finished interview while the DB tab
        // kept saying the interview was never completed. Say it out loud, and
        // leave the input enabled so the user can ask for the answer again.
        error.value =
          'Ответ агента не удалось разобрать как JSON — попросите его повторить или исправить ответ.'
      }
    } else if (agentId === 1) {
      // DB agent — the broker unwraps the fence before handing the schema over,
      // so the stored reply has to be unwrapped here too or a reload would show
      // the schema fenced.
      dbSchema.value = stripCodeFence(result)
    } else if (agentId === 2) {
      if (convIdx === 0) {
        // Config
        const parsed = parseJsonObject(result)
        if (parsed) twinConfig.value = parsed
        else if (result.includes('{')) {
          error.value = 'Ответ агента не удалось разобрать как JSON — попросите его повторить.'
        }
      } else if (convIdx === 1) {
        // Simulation code
        const start = result.lastIndexOf('</think>')
        simulationCode.value = start !== -1 ? result.substring(start + 8) : result
      } else if (convIdx === DES_CONV_IDX) {
        // SimPy model — the client only sees this when replaying a conversation
        // it did not run itself; a live run takes the artifact from the job,
        // which `des_runner` already unfenced.
        desCode.value = stripCodeFence(result)
      }
    }
  }

  /** The prompts the client needs to seed a conversation, fetched once. */
  async function loadPrompts(): Promise<PipelinePrompts | null> {
    if (prompts.value) return prompts.value
    try {
      prompts.value = await api.getPrompts()
      return prompts.value
    } catch (e: any) {
      error.value = e.message
      return null
    }
  }

  /**
   * The conversation for a slot, created on first use.
   *
   * The interview agent takes its instructions from the conversation's own
   * first message, so the client seeds the system prompt here, then posts the
   * fixed opening assistant turn — the user should see a greeting before they
   * type, not an empty transcript. The DB and DES slots are seeded by the
   * pipeline endpoints instead, which is why only the interview slot needs it
   * from this side.
   */
  async function ensureConversation(agentId: number, convIdx: number): Promise<string | null> {
    const existing = conversations.value.find(c => c.agent_id === agentId && c.conv_idx === convIdx)
    if (existing) return existing.id
    if (!currentSessionId.value) return null

    try {
      const data = await api.createConversation(currentSessionId.value, agentId, convIdx)
      if (agentId === UI_AGENT) {
        const p = await loadPrompts()
        if (p) {
          await api.addMessage(data.conversation_id, 'system', p.ui)
          await api.addMessage(data.conversation_id, 'assistant', p.ui_greeting)
        }
        // Pull back what was just seeded — otherwise the greeting exists on the
        // server but the transcript stays blank until the first task finishes.
        // Only the interview slot does this: `messages` is that slot's
        // transcript, so reloading a DB/DES conversation into it would blank
        // the interview the user is looking at.
        await loadConversation(data.conversation_id)
      }
      const fresh = await api.getSession(currentSessionId.value)
      conversations.value = fresh.conversations
      return data.conversation_id
    } catch (e: any) {
      error.value = e.message
      return null
    }
  }

  /**
   * Follow a pipeline job until it stops running.
   *
   * `publish` receives every poll, so a slot that renders progress turn by turn
   * gets it while the loop is still running. A turn can take minutes (the DES
   * slot runs the generated program), so the budget is the long one, not
   * `pollTask`'s 60 seconds.
   */
  async function waitForJob(
    jobId: string,
    publish: (job: PipelineJob) => void,
  ): Promise<PipelineJob | null> {
    const deadline = Date.now() + POLL_TIMEOUT_MS
    while (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, POLL_INTERVAL_MS))
      try {
        const job = await api.getPipelineJob(jobId)
        publish(job)
        if (job.status !== 'running') return job
      } catch {
        // transient — keep polling
      }
    }
    return null
  }

  /** Follow the DB/DES slot currently running. */
  async function pollJob(jobId: string): Promise<PipelineJob | null> {
    return waitForJob(jobId, job => { pipelineJob.value = job })
  }

  /** Run the DB slot: the broker prompts, validates and repairs, we show it. */
  async function generateDbSchema(conversationId: string): Promise<DbPipelineResult | null> {
    if (!currentSessionId.value) return null
    error.value = null
    try {
      const started = await api.startDbPipeline({
        session_id: currentSessionId.value,
        conversation_id: conversationId,
        requirements: interviewResult.value,
        conv_idx: 0,
      })
      const job = await pollJob(started.job_id)
      if (!job) { error.value = 'Превышено время ожидания генерации схемы'; return null }
      if (job.status === 'failed') { error.value = job.error || 'Ошибка генерации схемы'; return null }

      const result = job.result as DbPipelineResult | null
      if (!result) return null
      dbVerdict.value = result
      dbSchema.value = result.artifact
      return result
    } catch (e: any) {
      error.value = e.message
      return null
    }
  }

  /** Run the DES slot: the generated SimPy model is executed before it is shown. */
  async function generateDesModel(conversationId: string): Promise<DesPipelineResult | null> {
    if (!currentSessionId.value) return null
    error.value = null
    try {
      const started = await api.startDesPipeline({
        session_id: currentSessionId.value,
        conversation_id: conversationId,
        requirements: interviewResult.value,
        db_schema: dbSchema.value || '',
        conv_idx: DES_CONV_IDX,
      })
      const job = await pollJob(started.job_id)
      if (!job) { error.value = 'Превышено время ожидания генерации DES-модели'; return null }
      if (job.status === 'failed') { error.value = job.error || 'Ошибка генерации DES-модели'; return null }

      const result = job.result as DesPipelineResult | null
      if (!result) return null
      desVerdict.value = result
      desCode.value = result.artifact
      return result
    } catch (e: any) {
      error.value = e.message
      return null
    }
  }

  /**
   * Run one of the twin's two slots through the broker.
   *
   * Neither artifact has a validator, so the broker asks once and hands the
   * reply back unread — what it owns is the engineered prompt (which the client
   * cannot build) and the wait. That wait is the bug this replaces: the client
   * used to submit the task itself and give up after 60 seconds, so a
   * configuration turn, which routinely outlasts that, came back to nothing —
   * the button reset and the reply was left unread in the task row.
   */
  async function generateTwin(
    slot: 'gen_conf' | 'gen_sim',
    conversationId: string,
  ): Promise<TwinPipelineResult | null> {
    if (!currentSessionId.value) return null
    error.value = null
    // Drop the previous run's verdict: a retry must not show the old failure.
    twinVerdict.value = null
    try {
      const body = {
        session_id: currentSessionId.value,
        conversation_id: conversationId,
        requirements: interviewResult.value,
        db_schema: dbSchema.value || '',
      }
      const started = slot === 'gen_conf'
        ? await api.startGenConfPipeline({ ...body, conv_idx: 0 })
        : await api.startGenSimPipeline({ ...body, conv_idx: 1 })
      // Nothing to publish while a one-turn ask runs — the whole turn lands at
      // once — so only the finished job is read.
      const job = await waitForJob(started.job_id, () => {})
      if (!job) {
        error.value = 'Превышено время ожидания ответа агента'
        return null
      }
      if (job.status === 'failed') {
        error.value = job.error || 'Ошибка генерации'
        return null
      }

      const result = job.result as TwinPipelineResult | null
      if (!result) return null
      twinVerdict.value = result
      if (!result.ok || !result.artifact) {
        // The turn produced no reply at all — say so rather than leaving the
        // button silently reset with nothing on screen.
        error.value = result.report || 'Агент не вернул ответ'
        return result
      }
      // The broker hands the reply back as it was written; reading it is still
      // this side's job, exactly as it was before.
      if (slot === 'gen_conf') {
        const parsed = parseJsonObject(result.artifact)
        if (parsed) twinConfig.value = parsed
        else error.value = 'Ответ агента не удалось разобрать как JSON — попросите его повторить.'
      } else {
        const start = result.artifact.lastIndexOf('</think>')
        simulationCode.value = start !== -1 ? result.artifact.substring(start + 8) : result.artifact
      }
      return result
    } catch (e: any) {
      error.value = e.message
      return null
    }
  }

  /** Run the twin-configuration slot. */
  async function generateTwinConfig(conversationId: string): Promise<TwinPipelineResult | null> {
    return generateTwin('gen_conf', conversationId)
  }

  /** Run the twin's PyChrono-program slot. */
  async function generateTwinSim(conversationId: string): Promise<TwinPipelineResult | null> {
    return generateTwin('gen_sim', conversationId)
  }

  /**
   * Answer one interview turn through the broker's validate→repair loop.
   *
   * The broker posts the user's message itself (so the stored conversation is
   * exactly what the agent read), submits the task, reads the reply as the
   * schema's JSON, and posts a correction while it does not read. The client
   * shows the transcript and the verdict.
   *
   * A reply the agent can read that asks a question (`completed: false`) is a
   * valid answer: the interview is simply not finished, and the input stays
   * enabled. Only a reply unreadable even after the repairs is an error.
   */
  async function sendInterviewMessage(
    conversationId: string,
    content: string,
    params: Record<string, any> = {},
  ): Promise<UiPipelineResult | null> {
    if (!currentSessionId.value) return null
    error.value = null
    uiRunning.value = true
    try {
      const started = await api.startUiPipeline({
        session_id: currentSessionId.value,
        conversation_id: conversationId,
        message: content,
        conv_idx: 0,
        max_tokens: params.max_tokens,
        attempts: params.attempts,
      })
      const job = await waitForJob(started.job_id, j => { uiJob.value = j })
      if (!job) {
        error.value = 'Превышено время ожидания ответа агента'
        return null
      }
      if (job.status === 'failed') {
        error.value = job.error || 'Ошибка обработки ответа агента'
        return null
      }

      const result = job.result as UiPipelineResult | null
      if (!result) return null
      uiVerdict.value = result

      if (result.completed && result.requirements) {
        interviewResult.value = result.requirements
      } else if (!result.ok) {
        // The reply could not be read as the schema's JSON even after the repair
        // turns. Say it out loud and leave the input enabled — the alternative
        // is a chat that looks finished while the DB tab says otherwise.
        error.value =
          'Ответ агента не удалось разобрать как JSON после нескольких попыток — попросите его повторить или исправить ответ.'
      }
      return result
    } catch (e: any) {
      error.value = e.message
      return null
    } finally {
      // The user's turn, the reply and any repair turns were all written
      // server-side, so the server's copy is the one to show.
      await loadConversation(conversationId)
      uiRunning.value = false
    }
  }

  async function loadAgentStatuses() {
    for (let id = 0; id < 3; id++) {
      try {
        const status = await api.getAgentStatus(id)
        agentStatuses.value[id] = status
        const queue = await api.getQueueStatus(id)
        queueStatuses.value[id] = queue
      } catch { /* ignore */ }
    }
  }

  return {
    // State
    sessions, currentSessionId, conversations, messages,
    agentStatuses, queueStatuses,
    activeTab, activeConvIdx,
    interviewResult, dbSchema, twinConfig, simulationCode,
    prompts, pipelineJob, dbVerdict, desCode, desVerdict,
    uiJob, uiVerdict, uiRunning,
    twinVerdict,
    loading, error,
    // Getters
    currentSession,
    // Actions
    loadSessions, createSession, loadSession, loadConversation,
    renameSession, deleteSession,
    loadAgentStatuses,
    loadPrompts, ensureConversation, pollJob, generateDbSchema, generateDesModel,
    generateTwinConfig, generateTwinSim,
    sendInterviewMessage,
  }
})
