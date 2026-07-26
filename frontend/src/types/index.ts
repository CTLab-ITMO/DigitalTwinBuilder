export interface Session {
  id: string
  title: string | null
  user_id: string
}

export interface Conversation {
  id: string
  session_id: string
  agent_id: number
  conv_idx: number
  created_at: string
  updated_at: string
  metadata: Record<string, any>
}

export interface Message {
  id: string
  conversation_id?: string
  role: 'user' | 'assistant' | 'system'
  content: string
  content_type?: string
  metadata?: Record<string, any>
  created_at?: string
  tokens?: number
}

export interface Task {
  task_id: string
  status: string
  position_in_queue?: number
}

export interface TaskStatus {
  id: string
  agent_id: number
  conv_idx: number
  conversation_id: string
  status: string
  result: string | null
  error: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface AgentStatus {
  agent_id: number
  status: string
  last_heartbeat?: string
  current_task_id?: string | null
}

export interface QueueStatus {
  agent_id: number
  pending_count: number
  active_task: any | null
}

export interface HealthStatus {
  status: string
  database: string
  pool: string
  timestamp: string
}
