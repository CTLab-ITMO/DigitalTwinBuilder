import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../api/client'
import type { Session, Conversation, Message, AgentStatus, QueueStatus, PipelineJob, PipelinePrompts, DbPipelineResult, DesPipelineResult } from '../types'

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
  const pendingTasks = ref<Record<string, boolean>>({})
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
      await loadSessions()
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
      // Load messages for the first conversation
      if (data.conversations.length > 0) {
        await loadConversation(data.conversations[0].id)
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
      }
      return true
    } catch (e: any) {
      error.value = e.message
      return false
    }
  }

  async function loadConversation(conversationId: string) {
    try {
      const data = await api.getConversation(conversationId)
      messages.value = data.messages

      // Process assistant messages for structured data
      for (const msg of data.messages) {
        if (msg.role === 'assistant') {
          processResult(msg.content, 0, 0) // simplified
        }
      }
    } catch (e: any) {
      error.value = e.message
    }
  }

  async function sendMessage(agentId: number, convIdx: number, conversationId: string, content: string, params: Record<string, any> = {}) {
    try {
      await api.addMessage(conversationId, 'user', content)

      const task = await api.submitTask(agentId, conversationId, params)
      const taskId = task.task_id

      pendingTasks.value[taskId] = true

      // Start polling
      await pollTask(taskId, agentId, convIdx)
    } catch (e: any) {
      error.value = e.message
    }
  }

  async function pollTask(taskId: string, agentId: number, convIdx: number) {
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 1000))
      try {
        const status = await api.getTaskStatus(taskId)
        if (status.status === 'completed' || status.status === 'failed') {
          pendingTasks.value[taskId] = false
          if (status.result) {
            processResult(status.result, agentId, convIdx)
          }
          // Reload messages
          if (status.conversation_id) {
            const data = await api.getConversation(status.conversation_id)
            messages.value = data.messages
          }
          return
        }
      } catch {
        // retry
      }
    }
    pendingTasks.value[taskId] = false
  }

  function processResult(result: string, agentId: number, convIdx: number) {
    if (agentId === 0) {
      // UI/Interview agent — extract JSON
      try {
        const start = result.indexOf('{')
        const end = result.lastIndexOf('}')
        if (start !== -1 && end > start) {
          const parsed = JSON.parse(result.substring(start, end + 1))
          if (parsed.completed) {
            interviewResult.value = parsed.requirements
          }
        }
      } catch { /* ignore */ }
    } else if (agentId === 1) {
      // DB agent
      dbSchema.value = result
    } else if (agentId === 2) {
      if (convIdx === 0) {
        // Config
        try {
          const start = result.indexOf('{')
          const end = result.lastIndexOf('}')
          if (start !== -1 && end > start) {
            twinConfig.value = JSON.parse(result.substring(start, end + 1))
          }
        } catch { /* ignore */ }
      } else if (convIdx === 1) {
        // Simulation code
        const start = result.lastIndexOf('</think>')
        simulationCode.value = start !== -1 ? result.substring(start + 8) : result
      } else if (convIdx === DES_CONV_IDX) {
        // SimPy model — the client only sees this when replaying a conversation
        // it did not run itself; a live run takes the artifact from the job.
        desCode.value = result
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
      }
      const fresh = await api.getSession(currentSessionId.value)
      conversations.value = fresh.conversations
      // Pull back what was just seeded — otherwise the greeting exists on the
      // server but the transcript stays blank until the first task finishes.
      await loadConversation(data.conversation_id)
      return data.conversation_id
    } catch (e: any) {
      error.value = e.message
      return null
    }
  }

  /** Follow a pipeline job until it stops running, publishing each step. */
  async function pollJob(jobId: string): Promise<PipelineJob | null> {
    const deadline = Date.now() + POLL_TIMEOUT_MS
    while (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, POLL_INTERVAL_MS))
      try {
        const job = await api.getPipelineJob(jobId)
        pipelineJob.value = job
        if (job.status !== 'running') return job
      } catch {
        // transient — keep polling
      }
    }
    return null
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
    agentStatuses, queueStatuses, pendingTasks,
    activeTab, activeConvIdx,
    interviewResult, dbSchema, twinConfig, simulationCode,
    prompts, pipelineJob, dbVerdict, desCode, desVerdict,
    loading, error,
    // Getters
    currentSession,
    // Actions
    loadSessions, createSession, loadSession, loadConversation,
    renameSession, deleteSession,
    sendMessage, pollTask, loadAgentStatuses,
    loadPrompts, ensureConversation, pollJob, generateDbSchema, generateDesModel,
  }
})
