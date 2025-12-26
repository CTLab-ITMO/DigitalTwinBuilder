# api_server.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import uuid
import json
from datetime import datetime
import asyncpg
import os
from contextlib import asynccontextmanager

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
        pool = await asyncpg.create_pool(
            min_size=1,
            max_size=10,
            **DB_CONFIG
        )
        print("✅ Database pool initialized")
        
        # Create tables if they don't exist
        async with pool.acquire() as conn:
            # TODO: full database structure with conversation
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id VARCHAR(36) PRIMARY KEY,
                    agent_id INTEGER NOT NULL,
                    conversation_id UUID, 
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
                    current_task_id VARCHAR(36)
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
    conversation_id: str
    params: Dict[str, Any] = {}
    priority: int = 0

class AgentPollRequest(BaseModel):
    agent_id: int

class ResultSubmission(BaseModel):
    result: str
    error: Optional[str] = None

# API endpoints for chat history
@app.post("/conversations")
async def create_conversation(
    user_id: str = "default",
    agent_id: int = 1,
    title: Optional[str] = None
):
    """Create a new conversation"""
    conversation_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO conversations (id, user_id, title, agent_id)
            VALUES ($1, $2, $3, $4)
        """, conversation_id, user_id, title, agent_id)
    
    return {"conversation_id": conversation_id}

@app.get("/conversations")
async def get_conversations(
    user_id: str = "default",
    agent_id: int = 1,
    limit: int = 50,
    offset: int = 0
):
    """Get list of conversations for a user"""
    async with pool.acquire() as conn:
        conversations = await conn.fetch("""
            SELECT id, title, created_at, updated_at, metadata
            FROM conversations 
            WHERE user_id = $1 AND is_active = TRUE AND agent_id = $4
            ORDER BY updated_at DESC
            LIMIT $2 OFFSET $3
        """, user_id, limit, offset, agent_id)
        
        total = await conn.fetchval("""
            SELECT COUNT(*) FROM conversations 
            WHERE user_id = $1 AND is_active = TRUE
        """, user_id)
    
    return {
        "conversations": [dict(c) for c in conversations],
        "total": total
    }

@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Get full conversation with messages"""
    async with pool.acquire() as conn:
        # Get conversation info
        conversation = await conn.fetchrow("""
            SELECT id, title, created_at, updated_at, metadata
            FROM conversations 
            WHERE id = $1 AND is_active = TRUE
        """, conversation_id)
        
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Get messages
        messages = await conn.fetch("""
            SELECT id, role, content, content_type,
                   metadata, created_at, tokens
            FROM messages 
            WHERE conversation_id = $1 AND is_hidden = FALSE
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
        message = await conn.fetch("""
            SELECT id, role, content, content_type,
                   metadata, created_at, tokens
            FROM messages
            WHERE conversation_id = $1
            ORDER BY created_at DESC
            LIMIT 1
        """, conversation_id)
    
    return {
        "last_message": message
    }

@app.post("/conversations/{conversation_id}/messages")
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
            "SELECT 1 FROM conversations WHERE id = $1 AND is_active = TRUE",
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
    task_id = await create_task({
        "agent_id": 1,  # UIA
        "conversation_id": conversation_id,
        "params": {
            "user_message_id": user_msg_id["message_id"],
            "context": context
        }
    })
    
    return {"task_id": task_id, "conversation_id": conversation_id}

# API Endpoints
@app.post("/tasks")
async def create_task(task: TaskRequest):
    """Submit a new task from UI"""
    task_id = str(uuid.uuid4())
    
    try:
        async with (await get_db_connection()).acquire() as conn:
            # Insert task
            await conn.execute('''
                INSERT INTO tasks (id, agent_id, conversation_id, params, status, priority)
                VALUES ($1, $2, $3, $4, 'pending', $5)
            ''', task_id, task.agent_id, task.conversation_id, 
                json.dumps(task.params), task.priority)
            
            # Get queue position
            count = await conn.fetchval('''
                SELECT COUNT(*) FROM tasks 
                WHERE agent_id = $1 AND status = 'pending'
            ''', task.agent_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    return {
        "task_id": task_id,
        "status": "pending",
        "position_in_queue": count
    }

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
                SELECT id, agent_id, conversation_id, status, result, error,
                       created_at, started_at, completed_at
                FROM tasks WHERE id = $1
            ''', task_id)
            
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            
            return dict(task)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

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
            "health": "GET /health"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
