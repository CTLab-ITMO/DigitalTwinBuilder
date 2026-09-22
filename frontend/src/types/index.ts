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

// The DB/DES slots run server-side: the broker owns the conversation, builds
// the engineered prompt, validates each reply and asks for a repair until the
// artifact passes. The client only starts a job and reads its verdict.

export interface PipelineAttempt {
  attempt: number
  ok: boolean
  report: string
  chars: number
  /** DES only: how the generated program ended (`ok`, `timeout`, ...). */
  status?: string | null
  /** DES only: the KPIs the program printed on this turn. */
  kpis?: Record<string, number | null>
}

export interface DbPipelineResult {
  slot: 'db'
  ok: boolean
  artifact: string | null
  attempts: number
  repaired: number
  report: string
  summary: Record<string, any>
}

export interface DesPipelineResult {
  slot: 'des'
  ok: boolean
  artifact: string | null
  attempts: number
  repaired: number
  report: string
  kpis: {
    throughput_per_hour?: number | null
    wip_parts?: number | null
    energy_per_part_kwh?: number | null
  }
  status: string | null
  elapsed_s: number | null
}

export interface PipelineJob {
  id: string
  slot: 'db' | 'des'
  agent_id: number
  conv_idx: number
  conversation_id: string
  status: 'running' | 'completed' | 'failed'
  attempts: PipelineAttempt[]
  result: DbPipelineResult | DesPipelineResult | null
  error: string | null
  created_at: string
  completed_at: string | null
}

export interface PipelinePrompts {
  ui: string
  db: string
  gen_des: string
}

export interface HealthStatus {
  status: string
  database: string
  pool: string
  timestamp: string
}
