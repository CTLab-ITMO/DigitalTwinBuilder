import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../api/client'
import type { Session, Conversation, Message, AgentStatus, QueueStatus } from '../types'

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
      }
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
    loading, error,
    // Getters
    currentSession,
    // Actions
    loadSessions, createSession, loadSession, loadConversation,
    sendMessage, pollTask, loadAgentStatuses,
  }
})
