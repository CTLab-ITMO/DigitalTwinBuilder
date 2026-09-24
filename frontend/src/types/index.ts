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

// The DB/DES/UI slots run server-side: the broker owns the conversation, builds
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
  /** UI only: this turn's reply claimed the interview was finished. */
  completed?: boolean
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

/**
 * The interview slot's verdict. `ok` says the agent's reply could be read as the
 * schema's JSON; `completed` says whether it was the finished `requirements` or
 * a question the agent asked instead — the latter is a valid answer, not a
 * failure, so it comes back with `ok: true` and `requirements: null`.
 */
export interface UiPipelineResult {
  slot: 'ui'
  ok: boolean
  completed: boolean
  requirements: Record<string, any> | null
  message: string
  reply: string | null
  attempts: number
  repaired: number
  report: string
  summary: Record<string, any>
}

export interface PipelineJob {
  id: string
  slot: 'db' | 'des' | 'ui'
  agent_id: number
  conv_idx: number
  conversation_id: string
  status: 'running' | 'completed' | 'failed'
  attempts: PipelineAttempt[]
  result: DbPipelineResult | DesPipelineResult | UiPipelineResult | null
  error: string | null
  created_at: string
  completed_at: string | null
}

export interface PipelinePrompts {
  ui: string
  /** The fixed opening assistant turn, posted right after the system prompt so
   *  the interview starts with a greeting the user can answer. */
  ui_greeting: string
  db: string
  gen_des: string
}

export interface HealthStatus {
  status: string
  database: string
  pool: string
  timestamp: string
}
