import type { Session, Conversation, Message, TaskStatus, AgentStatus, QueueStatus } from '../types'

const API_BASE = import.meta.env.VITE_API_URL || '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json()
}

export const api = {
  // Sessions
  createSession(userId = 'streamlit_user', title?: string): Promise<{ session_id: string }> {
    const params = new URLSearchParams({ user_id: userId })
    if (title) params.set('title', title)
    return request(`/sessions?${params}`, { method: 'POST' })
  },

  getSessions(userId = 'streamlit_user'): Promise<{ sessions: Session[] }> {
    return request(`/sessions?user_id=${userId}`)
  },

  getSession(sessionId: string): Promise<{ session: Session; conversations: Conversation[] }> {
    return request(`/sessions/${sessionId}`)
  },

  // Conversations
  createConversation(sessionId: string, agentId = 1, convIdx = 0): Promise<{ conversation_id: string; conv_idx: number }> {
    const params = new URLSearchParams({ session_id: sessionId, agent_id: String(agentId), conv_idx: String(convIdx) })
    return request(`/conversations?${params}`, { method: 'POST' })
  },

  getConversation(conversationId: string): Promise<{ conversation: any; messages: Message[] }> {
    return request(`/conversations/${conversationId}`)
  },

  // Messages
  addMessage(conversationId: string, role: string, content: string): Promise<{ message_id: string }> {
    return request(`/conversations/${conversationId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ role, content }),
    })
  },

  // Tasks
  submitTask(agentId: number, conversationId: string, params: Record<string, any>, priority = 5): Promise<any> {
    return request('/tasks', {
      method: 'POST',
      body: JSON.stringify({ agent_id: agentId, conversation_id: conversationId, params, priority, conv_idx: 0 }),
    })
  },

  getTaskStatus(taskId: string): Promise<TaskStatus> {
    return request(`/tasks/${taskId}`)
  },

  // Agents
  getAgentStatus(agentId: number): Promise<AgentStatus> {
    return request(`/agents/${agentId}/status`)
  },

  getQueueStatus(agentId: number): Promise<QueueStatus> {
    return request(`/queue/${agentId}`)
  },

  // Health
  checkHealth(): Promise<any> {
    return request('/health')
  },
}
