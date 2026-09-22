# api_server.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import asyncio
import uuid
import json
from datetime import datetime
import asyncpg
import os
from contextlib import asynccontextmanager

import config
import pipeline
from prompts import system as system_prompts

# Configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "database": os.getenv("DB_NAME", "llm_agents"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "password")
}

# Global connection pool
pool = None

async def init_db_pool():
    """Initialize database connection pool"""
    global pool
    try:
        # Return UUID columns as plain strings so JSON responses are clean
        async def _init_connection(conn):
            await conn.set_type_codec(
                'uuid',
                encoder=str,
                decoder=str,
                schema='pg_catalog',
                format='text'
            )

        pool = await asyncpg.create_pool(
            min_size=1,
            max_size=10,
            init=_init_connection,
            **DB_CONFIG
        )
        print("✅ Database pool initialized")
        
        # Create tables if they don't exist
        async with pool.acquire() as conn:
            # TODO: full database structure with conversation
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id UUID PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL DEFAULT 'default',
                    title VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id UUID PRIMARY KEY,
                    session_id UUID REFERENCES sessions(id),
                    agent_id INTEGER NOT NULL DEFAULT 1,
                    conv_idx INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata JSONB DEFAULT '{}'
                )
            ''')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id UUID PRIMARY KEY,
                    conversation_id UUID REFERENCES conversations(id),
                    role VARCHAR(20) NOT NULL,
                    content TEXT,
                    content_type VARCHAR(50) DEFAULT 'text',
                    metadata JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    tokens INTEGER
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id UUID PRIMARY KEY,
                    agent_id INTEGER NOT NULL,
                    conversation_id UUID REFERENCES conversations(id),
                    params JSONB DEFAULT '{}',
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    result TEXT,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    priority INTEGER DEFAULT 0
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS agent_status (
                    agent_id INTEGER PRIMARY KEY,
                    status VARCHAR(20) DEFAULT 'idle',
                    last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    current_task_id UUID
                )
            ''')

            # One row per DB/DES pipeline run. The run outlives the HTTP request
            # that starts it (a DES turn may take DES_GEN_TIMEOUT_S and there may
            # be several turns), so its progress is stored here and polled by the
            # client rather than streamed back from the request.
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS pipeline_jobs (
                    id UUID PRIMARY KEY,
                    slot VARCHAR(16) NOT NULL,
                    session_id UUID REFERENCES sessions(id),
                    agent_id INTEGER NOT NULL,
                    conv_idx INTEGER NOT NULL DEFAULT 0,
                    conversation_id UUID REFERENCES conversations(id),
                    status VARCHAR(20) NOT NULL DEFAULT 'running',
                    attempts JSONB DEFAULT '[]',
                    result JSONB,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
            ''')

            # Create indexes
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_tasks_status_agent
                ON tasks(agent_id, status)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_tasks_pending
                ON tasks(status, priority DESC, created_at)
                WHERE status = 'pending'
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_status
                ON pipeline_jobs(status)
            ''')

            # A job whose process died cannot be resumed — the repair loop lives in
            # the process that started it — so a restart marks it failed instead of
            # leaving it 'running' forever for a polling client to wait on.
            swept = await conn.execute('''
                UPDATE pipeline_jobs
                SET status = 'failed',
                    error = 'interrupted by restart',
                    completed_at = CURRENT_TIMESTAMP
                WHERE status = 'running'
            ''')
            if swept and swept.endswith(' 1'):
                print("⚠️  Marked a pipeline job interrupted by restart as failed")

        return pool
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        raise

async def get_db_connection():
    """Get a database connection from the pool"""
    global pool
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return pool

# Lifespan context manager for FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("🚀 Starting API server...")
    await init_db_pool()
    yield
    # Shutdown
    if pool:
        await pool.close()
        print("👋 Database pool closed")

app = FastAPI(
    title="LLM Agent API",
    lifespan=lifespan
)

# Pydantic models
class TaskRequest(BaseModel):
    agent_id: int
    conv_idx: int
    conversation_id: str
    params: Dict[str, Any] = {}
    priority: int = 0

class AgentPollRequest(BaseModel):
    agent_id: int

class MessageRequest(BaseModel):
    role: str
    content: str
    content_type: str = "text"
    metadata: Dict[str, Any] = {}

class ResultSubmission(BaseModel):
    result: str
    error: Optional[str] = None

class PipelineDbRequest(BaseModel):
    """Start the DB slot. `requirements` is the interview result, as an object or
    as the JSON text the UI agent returned; either spelling is accepted."""
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    requirements: Any = None
    conv_idx: int = 0
    max_tokens: int = 3000
    attempts: Optional[int] = None

class PipelineDesRequest(BaseModel):
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    requirements: Any = None
    db_schema: str = ""
    conv_idx: int = 2
    max_tokens: int = config.DES_MAX_TOKENS
    attempts: Optional[int] = None


@app.post("/sessions")
async def create_session(
    user_id: str = "default", 
    title: Optional[str] = None
):
    session_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO sessions (id, user_id, title)
            VALUES ($1, $2, $3)
        """, session_id, user_id, title)

    return {"session_id": session_id}

@app.get("/sessions")
async def get_sessions(
    user_id: str = "default",
    limit: int = 50,
    offset: int = 0
):
    async with pool.acquire() as conn:
        sessions = await conn.fetch("""
            SELECT id, title, user_id
            FROM sessions 
            WHERE user_id = $1
            ORDER BY updated_at DESC
            LIMIT $2 OFFSET $3
        """, user_id, limit, offset)
    
    return {
        "sessions": [dict(c) for c in sessions],
    }

@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    async with pool.acquire() as conn:
        session = await conn.fetchrow("""
            SELECT id, title, user_id
            FROM sessions 
            WHERE id = $1
        """, session_id)
                
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Get conversations
        conversations = await conn.fetch("""
            SELECT id, session_id, agent_id, conv_idx, created_at, metadata
            FROM conversations 
            WHERE session_id = $1
            ORDER BY created_at ASC
        """, session_id)
    
    return {
        "session": dict(session),
        "conversations": [
            {**dict(c), "conv_idx": c["conv_idx"] if "conv_idx" in c else (c["metadata"].get("conv_idx", 0) if c["metadata"] else 0)}
            for c in conversations
        ]
    }

# API endpoints for chat history
@app.post("/conversations")
async def create_conversation(
    session_id: str,
    agent_id: int = 1,
    conv_idx: int = 0
):
    """Create a new conversation"""
    conversation_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO conversations (id, session_id, agent_id, conv_idx, metadata)
            VALUES ($1, $2, $3, $4, $5)
        """, conversation_id, session_id, agent_id, conv_idx, json.dumps({"conv_idx": conv_idx}))
    
    return {"conversation_id": conversation_id, "conv_idx": conv_idx}

@app.get("/conversations")
async def get_conversations(
    agent_id: int = 1,
    limit: int = 50,
    offset: int = 0
):
    """Get list of conversations for a user"""
    async with pool.acquire() as conn:
        conversations = await conn.fetch("""
            SELECT id, created_at, updated_at, conv_idx, metadata
            FROM conversations 
            WHERE agent_id = $3
            ORDER BY updated_at DESC
            LIMIT $1 OFFSET $2
        """, limit, offset, agent_id)
    
    return {
        "conversations": [
            {**dict(c), "conv_idx": c["conv_idx"] if "conv_idx" in c else (c["metadata"].get("conv_idx", 0) if c["metadata"] else 0)}
            for c in conversations
        ]
    }

@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Get full conversation with messages"""
    async with pool.acquire() as conn:
        # Get conversation info
        conversation = await conn.fetchrow("""
            SELECT id, created_at, updated_at, metadata
            FROM conversations 
            WHERE id = $1
            """, conversation_id)
        
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Get messages
        messages = await conn.fetch("""
            SELECT id, role, content, content_type,
                   metadata, created_at, tokens
            FROM messages 
            WHERE conversation_id = $1
            ORDER BY created_at ASC
        """, conversation_id)
    
    return {
        "conversation": dict(conversation),
        "messages": [dict(m) for m in messages]
    }

@app.get("/conversations/{conversation_id}/last_message")
async def get_conversation_last_message(conversation_id: str):
    """Get full conversation with messages"""
    async with pool.acquire() as conn:
        message = await conn.fetchrow("""
            SELECT id, role, content, content_type,
                   metadata, created_at, tokens
            FROM messages
            WHERE conversation_id = $1
            ORDER BY created_at DESC
            LIMIT 1
        """, conversation_id)

    if not message:
        raise HTTPException(status_code=404, detail="No messages found")

    return {
        "last_message": dict(message)
    }

@app.post("/conversations/{conversation_id}/messages")
async def add_message_endpoint(conversation_id: str, req: MessageRequest):
    """Add a message to conversation (from JSON body)"""
    return await add_message(conversation_id, req.role, req.content, req.content_type, req.metadata)

async def add_message(
    conversation_id: str,
    role: str,
    content: str,
    content_type: str = "text",
    metadata: Dict = {}
):
    """Add a message to conversation"""
    async with pool.acquire() as conn:
        # Verify conversation exists
        conv_exists = await conn.fetchval(
            "SELECT 1 FROM conversations WHERE id = $1",
            conversation_id
        )
        if not conv_exists:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Add message
        message_id = str(uuid.uuid4())
        await conn.execute("""
            INSERT INTO messages 
            (id, conversation_id, role, content, content_type, metadata)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, message_id, conversation_id, role, 
            content, content_type, json.dumps(metadata))
        
        # Update conversation timestamp
        await conn.execute("""
            UPDATE conversations 
            SET updated_at = CURRENT_TIMESTAMP 
            WHERE id = $1
        """, conversation_id)
    
    return {"message_id": message_id}

@app.post("/conversations/{conversation_id}/agent-chain")
async def process_agent_chain(
    conversation_id: str,
    user_message: str,
    context: Optional[Dict] = None
):
    """Process a user message through the agent chain"""
    # 1. Store user message
    user_msg_id = await add_message(
        conversation_id=conversation_id,
        role="user",
        content=user_message,
        metadata={"context": context or {}}
    )
    
    # 2. Create task for User Interaction Agent
    result = await _create_task_db(
        agent_id=1,  # UIA
        conversation_id=conversation_id,
        params={
            "user_message_id": user_msg_id["message_id"],
            "context": context
        },
        priority=0,
    )
    task_id = result["task_id"]
    
    return {"task_id": task_id, "conversation_id": conversation_id}

# API Endpoints
async def _create_task_db(agent_id: int, conversation_id: str, params: dict, priority: int = 0) -> dict:
    """Internal helper to create a task in the database. Returns {"task_id": ..., "position_in_queue": ...}."""
    task_id = str(uuid.uuid4())
    async with (await get_db_connection()).acquire() as conn:
        await conn.execute('''
            INSERT INTO tasks (id, agent_id, conversation_id, params, status, priority)
            VALUES ($1, $2, $3, $4, 'pending', $5)
        ''', task_id, agent_id, conversation_id,
            json.dumps(params), priority)

        count = await conn.fetchval('''
            SELECT COUNT(*) FROM tasks
            WHERE agent_id = $1 AND status = 'pending'
        ''', agent_id)

    return {"task_id": task_id, "status": "pending", "position_in_queue": count}

@app.post("/tasks")
async def create_task(task: TaskRequest):
    """Submit a new task from UI"""
    try:
        return await _create_task_db(task.agent_id, task.conversation_id, task.params, task.priority)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/agent/poll")
async def poll_for_tasks(poll: AgentPollRequest):
    """Agent polls for available tasks"""
    try:
        async with (await get_db_connection()).acquire() as conn:
            # Update agent heartbeat
            await conn.execute('''
                INSERT INTO agent_status (agent_id, last_heartbeat, status)
                VALUES ($1, NOW(), 'active')
                ON CONFLICT (agent_id) DO UPDATE 
                SET last_heartbeat = NOW(), status = 'active'
            ''', poll.agent_id)
            
            # Get highest priority pending task with SKIP LOCKED
            task = await conn.fetchrow('''
                SELECT id, conversation_id, params 
                FROM tasks 
                WHERE agent_id = $1 AND status = 'pending'
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            ''', poll.agent_id)
            
            if task:
                # Mark as processing
                await conn.execute('''
                    UPDATE tasks 
                    SET status = 'processing', started_at = NOW()
                    WHERE id = $1
                ''', task['id'])
                
                # Update agent status
                await conn.execute('''
                    UPDATE agent_status 
                    SET status = 'busy', current_task_id = $1
                    WHERE agent_id = $2
                ''', task['id'], poll.agent_id)
                
                return {
                    "task_id": task['id'],
                    "conversation_id": task['conversation_id'],
                    "params": json.loads(task['params'])
                }
            
            return None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/tasks/{task_id}/result")
async def submit_result(task_id: str, result: ResultSubmission):
    """Agent submits task result"""
    try:
        async with (await get_db_connection()).acquire() as conn:
            # Update task with result
            row = await conn.fetchrow('''
                UPDATE tasks 
                SET status = $1, 
                    result = $2, 
                    error = $3, 
                    completed_at = NOW()
                WHERE id = $4
                RETURNING agent_id
            ''', 'failed' if result.error else 'completed',
                result.result, result.error, task_id)
            
            if row:
                # Update agent status back to idle
                await conn.execute('''
                    UPDATE agent_status 
                    SET status = 'idle', current_task_id = NULL
                    WHERE agent_id = $1
                ''', row['agent_id'])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    return {"status": "success"}

@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get task status and result"""
    try:
        async with (await get_db_connection()).acquire() as conn:
            task = await conn.fetchrow('''
                SELECT t.id, t.agent_id, c.conv_idx, t.conversation_id, t.status, t.result, t.error,
                       t.created_at, t.started_at, t.completed_at
                FROM tasks t LEFT JOIN conversations c ON c.id = t.conversation_id
                WHERE t.id = $1;
            ''', task_id)
            
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            
            return dict(task)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# --------------------------------------------------------------------------- #
# DB / DES pipeline slots
#
# `pipeline.py` holds the generate -> validate -> repair loop; what it needs from
# the broker is a synchronous `submit(prompt, attempt)` that posts a user message
# and waits for the agent's reply. The loop runs in a worker thread (the runners
# block on subprocess and HTTP waits), so this section is the bridge between that
# thread and the event loop, plus the job rows that make a multi-minute run
# observable from a client that polls instead of holding one request open.
# --------------------------------------------------------------------------- #

# Same queue priority api_utils submits the interactive tasks with, so a pipeline
# turn is not starved behind other work and not ahead of it either.
PIPELINE_TASK_PRIORITY = 5
# How often the bridge asks whether the agent finished a turn.
PIPELINE_TASK_POLL_S = 0.5
# How long one DB turn may take before it is treated as no reply. The DES slot
# takes config.DES_GEN_TIMEOUT_S instead: the DT agent runs a local model with
# thinking on and a single turn is far slower.
DB_TURN_TIMEOUT_S = 900

# asyncio keeps only a weak reference to a task, so a run that nobody holds a
# reference to may be garbage-collected mid-flight. These keep the live jobs.
_pipeline_tasks: set = set()


def _resolve_agent_id(slot: str) -> int:
    """The agent a slot talks to: agent 1 for SQL, agent 2 for the DES model."""
    return config.DB_AGENT_INDEX if slot == "db" else config.DT_AGENT_INDEX


def _resolve_seed_prompt(slot: str) -> str:
    """The system prompt the conversation must open with for the slot's agent."""
    return system_prompts.DB if slot == "db" else system_prompts.GenDES


async def _prepare_pipeline_conversation(session_id, conversation_id, agent_id,
                                         conv_idx, seed_prompt):
    """The conversation a slot runs in, seeded with its agent's system prompt.

    The agent reads the conversation's messages as its chat context, so a
    conversation without the system message is a slot that runs without its
    instructions — which is what the frontend used to do. The system message is
    written once: a conversation the client already created and seeded is reused
    as it is.

    A `conversation_id` is used when given (the client's own conversation for the
    tab, so it can render the turns); otherwise one is created in `session_id`.
    """
    if not conversation_id and not session_id:
        raise HTTPException(status_code=400,
                            detail="session_id or conversation_id is required")

    async with (await get_db_connection()).acquire() as conn:
        if conversation_id:
            exists = await conn.fetchval(
                "SELECT 1 FROM conversations WHERE id = $1", conversation_id)
            if not exists:
                raise HTTPException(status_code=404,
                                    detail="Conversation not found")
        else:
            conversation_id = str(uuid.uuid4())
            await conn.execute("""
                INSERT INTO conversations
                    (id, session_id, agent_id, conv_idx, metadata)
                VALUES ($1, $2, $3, $4, $5)
            """, conversation_id, session_id, agent_id, conv_idx,
                json.dumps({"conv_idx": conv_idx}))

        seeded = await conn.fetchval("""
            SELECT 1 FROM messages
            WHERE conversation_id = $1 AND role = 'system'
            LIMIT 1
        """, conversation_id)
        if not seeded:
            await conn.execute("""
                INSERT INTO messages
                    (id, conversation_id, role, content, content_type, metadata)
                VALUES ($1, $2, 'system', $3, 'text', '{}')
            """, str(uuid.uuid4()), conversation_id, seed_prompt)

    return conversation_id


async def _create_pipeline_job(slot, session_id, agent_id, conv_idx,
                               conversation_id) -> str:
    """Insert the job row a client polls while the loop runs."""
    job_id = str(uuid.uuid4())
    async with (await get_db_connection()).acquire() as conn:
        await conn.execute("""
            INSERT INTO pipeline_jobs
                (id, slot, session_id, agent_id, conv_idx, conversation_id)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, job_id, slot, session_id, agent_id, conv_idx, conversation_id)
    return job_id


async def _append_pipeline_attempt(job_id, entry) -> None:
    """Append one turn's verdict, so a poller sees progress turn by turn."""
    async with (await get_db_connection()).acquire() as conn:
        await conn.execute("""
            UPDATE pipeline_jobs
            SET attempts = COALESCE(attempts, '[]'::jsonb) || $2::jsonb
            WHERE id = $1
        """, job_id, json.dumps([entry]))


async def _finish_pipeline_job(job_id, result) -> None:
    """Store the outcome and clear `running`.

    A completed job is a job the loop ran to the end of, whether or not the
    artifact passed: `result.ok` says which, and `result.report` says why. The
    job's own `error` is kept for the machinery failing (an exception, or a
    restart), which is the case a client shows differently from a rejected
    artifact.
    """
    async with (await get_db_connection()).acquire() as conn:
        await conn.execute("""
            UPDATE pipeline_jobs
            SET status = 'completed', result = $2, error = NULL,
                completed_at = CURRENT_TIMESTAMP
            WHERE id = $1
        """, job_id, json.dumps(result))


async def _fail_pipeline_job(job_id, error) -> None:
    async with (await get_db_connection()).acquire() as conn:
        await conn.execute("""
            UPDATE pipeline_jobs
            SET status = 'failed', error = $2,
                completed_at = CURRENT_TIMESTAMP
            WHERE id = $1
        """, job_id, error)


async def _await_task_result(task_id, timeout_s):
    """The agent's reply for one task, or None if it failed or ran too long.

    None is the runners' "this turn produced no reply" — it stops the repair loop
    rather than being read as an empty reply. The task row is left as it is: the
    agent is still working on it, and its eventual result stays in the history.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        async with (await get_db_connection()).acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status, result, error FROM tasks WHERE id = $1", task_id)
        if row is None:
            print(f"❌ Pipeline turn {task_id[:8]}: task row disappeared")
            return None
        if row["status"] == "completed":
            return row["result"] or ""
        if row["status"] == "failed":
            print(f"❌ Pipeline turn {task_id[:8]} failed: {row['error']}")
            return None
        if loop.time() >= deadline:
            print(f"❌ Pipeline turn {task_id[:8]} timed out after {timeout_s}s")
            return None
        await asyncio.sleep(PIPELINE_TASK_POLL_S)


async def _ask_agent(agent_id, conversation_id, content, params, timeout_s):
    """Post one turn's prompt and wait for the agent's reply to it."""
    await add_message(conversation_id, "user", content)
    created = await _create_task_db(agent_id, conversation_id, params,
                                   priority=PIPELINE_TASK_PRIORITY)
    return await _await_task_result(created["task_id"], timeout_s)


def _make_submit(loop, agent_id, conversation_id, params, timeout_s):
    """The synchronous `submit` the repair loop calls, from a worker thread.

    The thread cannot await, so each turn is handed back to the event loop and
    the thread blocks on its result until the agent answers or the turn times
    out. Every call acquires and releases its own connection: a pool connection
    must never be held across a wait that can last a whole turn.
    """
    def submit(prompt, attempt):
        return asyncio.run_coroutine_threadsafe(
            _ask_agent(agent_id, conversation_id, prompt, params, timeout_s),
            loop,
        ).result()
    return submit


def _attempt_entry(slot, i, artifact, verdict) -> dict:
    """One turn of the loop, as the client renders it."""
    entry = {
        "attempt": i,
        "ok": bool(verdict.get("ok")),
        "report": verdict.get("report") or "",
        "chars": len(artifact) if artifact else 0,
    }
    if slot == "des":
        entry["status"] = ((verdict.get("execution") or {}).get("status")
                           or ("no_reply" if artifact is None else None))
        entry["kpis"] = verdict.get("kpis") or {}
    return entry


async def _run_pipeline_job(*, job_id, slot, agent_id, conversation_id, params,
                            timeout_s, work) -> None:
    """Drive one slot's loop and record its outcome.

    `work(submit, on_attempt)` is `pipeline.generate_db_schema` /
    `generate_des_model` with its arguments bound. It is synchronous — it blocks
    the thread it runs in on every agent turn and, for DES, on a subprocess — so
    it is run in a worker thread while the loop stays free to serve the polls
    that watch this job.
    """
    loop = asyncio.get_running_loop()

    def on_attempt(i, artifact, verdict):
        try:
            asyncio.run_coroutine_threadsafe(
                _append_pipeline_attempt(job_id, _attempt_entry(slot, i, artifact,
                                                                verdict)),
                loop,
            ).result()
        except Exception as e:  # progress logging must not break the loop
            print(f"⚠️  Pipeline {job_id[:8]}: attempt {i} not recorded: {e}")

    try:
        outcome = await asyncio.to_thread(
            work, _make_submit(loop, agent_id, conversation_id, params, timeout_s),
            on_attempt)
        await _finish_pipeline_job(job_id, pipeline.job_result(slot, outcome))
    except Exception as e:
        print(f"❌ Pipeline {job_id[:8]} ({slot}) failed: {e}")
        await _fail_pipeline_job(job_id, f"{type(e).__name__}: {e}")


async def _start_pipeline_job(*, slot, req, work) -> dict:
    """Prepare the conversation, queue the run, and return the job to poll.

    Returns before the run starts: the caller gets the job id and the client
    watches the job row, while the loop runs on a task of its own.
    """
    agent_id = _resolve_agent_id(slot)
    conv_idx = req.conv_idx

    conversation_id = await _prepare_pipeline_conversation(
        req.session_id, req.conversation_id, agent_id, conv_idx,
        _resolve_seed_prompt(slot))
    job_id = await _create_pipeline_job(slot, req.session_id, agent_id, conv_idx,
                                       conversation_id)

    task = asyncio.create_task(_run_pipeline_job(
        job_id=job_id, slot=slot, agent_id=agent_id,
        conversation_id=conversation_id,
        params={"max_tokens": req.max_tokens},
        timeout_s=(config.DES_GEN_TIMEOUT_S if slot == "des"
                   else DB_TURN_TIMEOUT_S),
        work=work))
    _pipeline_tasks.add(task)
    task.add_done_callback(_pipeline_tasks.discard)

    return {"job_id": job_id, "slot": slot, "conversation_id": conversation_id}


@app.post("/pipeline/db")
async def start_db_pipeline(req: PipelineDbRequest):
    """Generate, validate and repair the PostgreSQL schema for a twin.

    Returns as soon as the job is queued; poll `GET /pipeline/jobs/{job_id}` for
    the schema, the verdict and the per-turn log. The loop runs server-side so
    the prompt text and the validator are the repo's own, not a copy of them.
    """
    work = (lambda submit, on_attempt: pipeline.generate_db_schema(
        submit, req.requirements, attempts=req.attempts, on_attempt=on_attempt))
    return await _safe_start(slot="db", req=req, work=work)


@app.post("/pipeline/des")
async def start_des_pipeline(req: PipelineDesRequest):
    """Generate, run and repair the SimPy model of the twin's line.

    Same job/poll contract as the DB slot. Running the generated program is part
    of the loop — a model that raises on its first `yield` is repaired here, not
    handed to the user.
    """
    work = (lambda submit, on_attempt: pipeline.generate_des_model(
        submit, req.requirements, req.db_schema, attempts=req.attempts,
        on_attempt=on_attempt))
    return await _safe_start(slot="des", req=req, work=work)


async def _safe_start(*, slot, req, work) -> dict:
    try:
        return await _start_pipeline_job(slot=slot, req=req, work=work)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/pipeline/jobs/{job_id}")
async def get_pipeline_job(job_id: str):
    """The job's progress: status, the turns so far, and the result when done."""
    try:
        async with (await get_db_connection()).acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, slot, agent_id, conv_idx, conversation_id, status,
                       attempts, result, error, created_at, completed_at
                FROM pipeline_jobs
                WHERE id = $1
            """, job_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    job = dict(row)
    for key in ("attempts", "result"):
        value = job.get(key)
        if isinstance(value, str):
            try:
                job[key] = json.loads(value)
            except ValueError:
                job[key] = None
    return job


@app.get("/pipeline/prompts")
async def get_pipeline_prompts():
    """The system prompts, so the client seeds a conversation without retyping them.

    `ui` is the one the client needs for the interview slot; `db` and `gen_des`
    are used by the pipeline itself and are returned for transparency.
    """
    return {
        "ui": system_prompts.UI,
        "db": system_prompts.DB,
        "gen_des": system_prompts.GenDES,
    }


@app.get("/agents/{agent_id}/status")
async def get_agent_status(agent_id: int):
    """Get current agent status"""
    try:
        async with (await get_db_connection()).acquire() as conn:
            agent = await conn.fetchrow('''
                SELECT * FROM agent_status WHERE agent_id = $1
            ''', agent_id)
            
            if not agent:
                return {"agent_id": agent_id, "status": "offline"}
            
            # Convert to dict
            agent_dict = dict(agent)
            
            # Check if agent is stale (> 5 minutes since heartbeat)
            if agent_dict['last_heartbeat']:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                last_heartbeat = agent_dict['last_heartbeat'].replace(tzinfo=timezone.utc)
                
                if (now - last_heartbeat).total_seconds() > 300:
                    return {"agent_id": agent_id, "status": "offline"}
            
            return agent_dict
    except Exception as e:
        return {"agent_id": agent_id, "status": "error", "error": str(e)}

@app.get("/queue/{agent_id}")
async def get_queue_status(agent_id: int):
    """Get queue status for agent"""
    try:
        async with (await get_db_connection()).acquire() as conn:
            pending_count = await conn.fetchval('''
                SELECT COUNT(*) FROM tasks 
                WHERE agent_id = $1 AND status = 'pending'
            ''', agent_id)
            
            active_task = await conn.fetchrow('''
                SELECT id, started_at FROM tasks 
                WHERE agent_id = $1 AND status = 'processing'
                LIMIT 1
            ''', agent_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    return {
        "agent_id": agent_id,
        "pending_count": pending_count or 0,
        "active_task": dict(active_task) if active_task else None
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        async with (await get_db_connection()).acquire() as conn:
            # Check database connection
            db_ok = await conn.fetchval("SELECT 1")
            
            # Check pool status
            pool_status = "healthy" if pool else "uninitialized"
            
            return {
                "status": "healthy",
                "database": "connected" if db_ok else "disconnected",
                "pool": pool_status,
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "name": "LLM Agent API",
        "version": "1.0.0",
        "endpoints": {
            "submit_task": "POST /tasks",
            "poll_task": "POST /agent/poll",
            "submit_result": "POST /tasks/{task_id}/result",
            "get_task": "GET /tasks/{task_id}",
            "get_agent": "GET /agents/{agent_id}/status",
            "get_queue": "GET /queue/{agent_id}",
            "start_db_pipeline": "POST /pipeline/db",
            "start_des_pipeline": "POST /pipeline/des",
            "get_pipeline_job": "GET /pipeline/jobs/{job_id}",
            "get_pipeline_prompts": "GET /pipeline/prompts",
            "health": "GET /health"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
