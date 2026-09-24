import type { Session, Conversation, Message, TaskStatus, AgentStatus, QueueStatus, PipelineJob, PipelinePrompts } from '../types'

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

  renameSession(sessionId: string, title: string): Promise<{ session_id: string; title: string }> {
    return request(`/sessions/${sessionId}`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    })
  },

  deleteSession(sessionId: string): Promise<{ session_id: string; deleted: boolean }> {
    return request(`/sessions/${sessionId}`, { method: 'DELETE' })
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

  // Pipeline — the DB and DES slots, run with validation and repair server-side
  startDbPipeline(body: {
    session_id: string
    conversation_id?: string
    requirements: any
    conv_idx?: number
    max_tokens?: number
    attempts?: number
  }): Promise<{ job_id: string; slot: string; conversation_id: string }> {
    return request('/pipeline/db', { method: 'POST', body: JSON.stringify(body) })
  },

  startDesPipeline(body: {
    session_id: string
    conversation_id?: string
    requirements: any
    db_schema?: string
    conv_idx?: number
    max_tokens?: number
    attempts?: number
  }): Promise<{ job_id: string; slot: string; conversation_id: string }> {
    return request('/pipeline/des', { method: 'POST', body: JSON.stringify(body) })
  },

  // The twin's two slots. Neither artifact has a validator, so these are one
  // turn each — but the broker still builds the engineered prompt and waits for
  // it, which is what the client used to get wrong.
  startGenConfPipeline(body: {
    session_id: string
    conversation_id?: string
    requirements: any
    db_schema?: string
    conv_idx?: number
    max_tokens?: number
  }): Promise<{ job_id: string; slot: string; conversation_id: string }> {
    return request('/pipeline/gen_conf', { method: 'POST', body: JSON.stringify(body) })
  },

  startGenSimPipeline(body: {
    session_id: string
    conversation_id?: string
    requirements: any
    db_schema?: string
    conv_idx?: number
    max_tokens?: number
  }): Promise<{ job_id: string; slot: string; conversation_id: string }> {
    return request('/pipeline/gen_sim', { method: 'POST', body: JSON.stringify(body) })
  },

  // The interview slot: the broker posts the user's turn, reads the agent's
  // reply and asks for a correction while it is not the schema's JSON.
  startUiPipeline(body: {
    session_id: string
    conversation_id?: string
    message: string
    conv_idx?: number
    max_tokens?: number
    attempts?: number
  }): Promise<{ job_id: string; slot: string; conversation_id: string }> {
    return request('/pipeline/ui', { method: 'POST', body: JSON.stringify(body) })
  },

  getPipelineJob(jobId: string): Promise<PipelineJob> {
    return request(`/pipeline/jobs/${jobId}`)
  },

  getPrompts(): Promise<PipelinePrompts> {
    return request('/pipeline/prompts')
  },

  // Health
  checkHealth(): Promise<any> {
    return request('/health')
  },
}
