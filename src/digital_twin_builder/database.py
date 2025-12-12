# database.py
import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import asyncio

import asyncpg
from asyncpg import Connection, Pool
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from psycopg2.pool import ThreadedConnectionPool
import psycopg2.extensions

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration from environment
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "database": os.getenv("DB_NAME", "llm_agents"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "min_connections": int(os.getenv("DB_MIN_CONNECTIONS", "1")),
    "max_connections": int(os.getenv("DB_MAX_CONNECTIONS", "10")),
}

# Synchronous connection pool for Streamlit
_sync_pool = None

# Async connection pool for FastAPI
_async_pool = None

def get_sync_connection_string():
    """Get synchronous PostgreSQL connection string"""
    return f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"

def get_async_connection_string():
    """Get async PostgreSQL connection string"""
    return f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"

# Data models
@dataclass
class Task:
    id: str
    agent_id: int
    prompt: str
    params: Dict[str, Any]
    status: str  # pending, processing, completed, failed, cancelled
    result: Optional[str]
    error: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    priority: int
    metadata: Dict[str, Any]
    queue_position: Optional[int] = None

@dataclass
class AgentStatus:
    agent_id: int
    status: str  # idle, busy, offline
    last_heartbeat: datetime
    current_task_id: Optional[str]
    capabilities: List[str]
    performance_metrics: Optional[Dict[str, Any]]
    last_error: Optional[str]

class DatabaseError(Exception):
    """Custom database exception"""
    pass

# Synchronous functions for Streamlit
def init_sync_pool():
    """Initialize synchronous connection pool"""
    global _sync_pool
    try:
        _sync_pool = ThreadedConnectionPool(
            minconn=DB_CONFIG['min_connections'],
            maxconn=DB_CONFIG['max_connections'],
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            database=DB_CONFIG['database'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            cursor_factory=RealDictCursor
        )
        logger.info("Synchronous PostgreSQL connection pool initialized")
        return _sync_pool
    except Exception as e:
        logger.error(f"Failed to initialize sync pool: {str(e)}")
        raise DatabaseError(f"Database connection failed: {str(e)}")

@contextmanager
def get_sync_connection():
    """Get synchronous database connection from pool"""
    conn = None
    try:
        if _sync_pool is None:
            init_sync_pool()
        
        conn = _sync_pool.getconn()
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database error: {str(e)}")
        raise DatabaseError(str(e))
    finally:
        if conn:
            _sync_pool.putconn(conn)

def close_sync_pool():
    """Close the synchronous connection pool"""
    if _sync_pool:
        _sync_pool.closeall()
        logger.info("Synchronous PostgreSQL connection pool closed")

# Async functions for FastAPI
async def init_async_pool():
    """Initialize async connection pool"""
    global _async_pool
    try:
        _async_pool = await asyncpg.create_pool(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            database=DB_CONFIG['database'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            min_size=DB_CONFIG['min_connections'],
            max_size=DB_CONFIG['max_connections'],
            command_timeout=60
        )
        logger.info("Async PostgreSQL connection pool initialized")
        return _async_pool
    except Exception as e:
        logger.error(f"Failed to initialize async pool: {str(e)}")
        raise DatabaseError(f"Async database connection failed: {str(e)}")

async def get_async_connection() -> Connection:
    """Get async database connection from pool"""
    if _async_pool is None:
        await init_async_pool()
    
    try:
        return await _async_pool.acquire()
    except Exception as e:
        logger.error(f"Failed to acquire async connection: {str(e)}")
        raise DatabaseError(str(e))

async def release_async_connection(conn):
    """Release async connection back to pool"""
    try:
        await _async_pool.release(conn)
    except Exception as e:
        logger.warning(f"Error releasing connection: {str(e)}")

@contextmanager
def sync_cursor():
    """Context manager for synchronous cursor operations"""
    with get_sync_connection() as conn:
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

async def execute_query(query: str, params: tuple = None):
    """Execute a query and return results"""
    conn = await get_async_connection()
    try:
        if params:
            return await conn.fetch(query, *params)
        else:
            return await conn.fetch(query)
    finally:
        await release_async_connection(conn)

# Database schema initialization
def init_database_schema():
    """Initialize PostgreSQL database schema"""
    schema_sql = """
    -- Enable UUID extension
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    
    -- Enable JSONB for better performance
    CREATE EXTENSION IF NOT EXISTS "pg_trgm";
    CREATE EXTENSION IF NOT EXISTS "btree_gin";
    
    -- Tasks table with partitioning by date (for large scale)
    CREATE TABLE IF NOT EXISTS tasks (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        agent_id INTEGER NOT NULL,
        prompt TEXT NOT NULL,
        params JSONB NOT NULL DEFAULT '{}'::jsonb,
        status VARCHAR(20) NOT NULL 
            CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')),
        result TEXT,
        error TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        started_at TIMESTAMP WITH TIME ZONE,
        completed_at TIMESTAMP WITH TIME ZONE,
        priority INTEGER NOT NULL DEFAULT 0,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        
        -- Indexes for performance
        CONSTRAINT valid_status CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled'))
    );
    
    -- Agent status table
    CREATE TABLE IF NOT EXISTS agent_status (
        agent_id INTEGER PRIMARY KEY,
        status VARCHAR(20) NOT NULL DEFAULT 'idle'
            CHECK (status IN ('idle', 'busy', 'offline', 'maintenance')),
        last_heartbeat TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        current_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
        capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
        performance_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
        last_error TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    
    -- Task queue view (for monitoring)
    CREATE OR REPLACE VIEW task_queue AS
    SELECT 
        agent_id,
        COUNT(*) as pending_count,
        AVG(priority) as avg_priority,
        MIN(created_at) as oldest_task
    FROM tasks
    WHERE status = 'pending'
    GROUP BY agent_id;
    
    -- Agent performance view
    CREATE OR REPLACE VIEW agent_performance AS
    SELECT 
        a.agent_id,
        a.status,
        COUNT(t.id) as total_tasks,
        SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) as completed_tasks,
        AVG(EXTRACT(EPOCH FROM (t.completed_at - t.started_at))) as avg_process_time_seconds,
        MAX(t.completed_at) as last_completed
    FROM agent_status a
    LEFT JOIN tasks t ON a.agent_id = t.agent_id
    GROUP BY a.agent_id, a.status;
    
    -- Indexes for performance
    CREATE INDEX IF NOT EXISTS idx_tasks_status_agent ON tasks(status, agent_id);
    CREATE INDEX IF NOT EXISTS idx_tasks_priority_created ON tasks(priority DESC, created_at ASC);
    CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_tasks_params_gin ON tasks USING gin(params);
    CREATE INDEX IF NOT EXISTS idx_tasks_metadata_gin ON tasks USING gin(metadata);
    
    -- Triggers for updated_at
    CREATE OR REPLACE FUNCTION update_updated_at_column()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = CURRENT_TIMESTAMP;
        RETURN NEW;
    END;
    $$ language 'plpgsql';
    
    DROP TRIGGER IF EXISTS update_agent_status_updated_at ON agent_status;
    CREATE TRIGGER update_agent_status_updated_at
        BEFORE UPDATE ON agent_status
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """
    
    with sync_cursor() as cursor:
        cursor.execute(schema_sql)
        logger.info("PostgreSQL schema initialized")

# Table management functions
async def create_task(task_data: Dict[str, Any]) -> str:
    """Create a new task in PostgreSQL"""
    query = """
    INSERT INTO tasks 
    (agent_id, prompt, params, status, priority, metadata)
    VALUES ($1, $2, $3::jsonb, 'pending', $4, $5::jsonb)
    RETURNING id
    """
    
    conn = await get_async_connection()
    try:
        task_id = await conn.fetchval(
            query,
            task_data['agent_id'],
            task_data['prompt'],
            json.dumps(task_data.get('params', {})),
            task_data.get('priority', 0),
            json.dumps(task_data.get('metadata', {}))
        )
        return str(task_id)
    finally:
        await release_async_connection(conn)

async def get_task(task_id: str) -> Optional[Dict]:
    """Get task by ID"""
    query = """
    SELECT 
        t.*,
        (
            SELECT COUNT(*) 
            FROM tasks t2 
            WHERE t2.agent_id = t.agent_id 
            AND t2.status = 'pending'
            AND (
                t2.priority > t.priority 
                OR (t2.priority = t.priority AND t2.created_at < t.created_at)
            )
        ) + 1 as queue_position
    FROM tasks t
    WHERE t.id = $1::uuid
    """
    
    conn = await get_async_connection()
    try:
        result = await conn.fetchrow(query, task_id)
        if result:
            return dict(result)
        return None
    finally:
        await release_async_connection(conn)

async def update_task_status(task_id: str, status: str, 
                           result: Optional[str] = None, 
                           error: Optional[str] = None) -> bool:
    """Update task status and result"""
    conn = await get_async_connection()
    try:
        if status in ['processing', 'completed', 'failed']:
            update_query = """
            UPDATE tasks 
            SET status = $1,
                result = $2,
                error = $3,
                {time_column} = CURRENT_TIMESTAMP
            WHERE id = $4::uuid
            RETURNING id
            """.format(
                time_column='started_at' if status == 'processing' else 'completed_at'
            )
            
            await conn.fetchval(update_query, status, result, error, task_id)
            return True
        else:
            update_query = """
            UPDATE tasks 
            SET status = $1
            WHERE id = $2::uuid
            RETURNING id
            """
            await conn.fetchval(update_query, status, task_id)
            return True
    except Exception as e:
        logger.error(f"Failed to update task {task_id}: {str(e)}")
        return False
    finally:
        await release_async_connection(conn)

async def get_next_pending_task(agent_id: int) -> Optional[Dict]:
    """Get next pending task for an agent with row-level locking"""
    query = """
    WITH next_task AS (
        SELECT id 
        FROM tasks 
        WHERE agent_id = $1 
        AND status = 'pending'
        ORDER BY priority DESC, created_at ASC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    UPDATE tasks t
    SET status = 'processing',
        started_at = CURRENT_TIMESTAMP
    FROM next_task nt
    WHERE t.id = nt.id
    RETURNING t.*
    """
    
    conn = await get_async_connection()
    try:
        result = await conn.fetchrow(query, agent_id)
        if result:
            return dict(result)
        return None
    finally:
        await release_async_connection(conn)

async def update_agent_status(agent_id: int, status: str, 
                            current_task_id: Optional[str] = None,
                            capabilities: Optional[List[str]] = None,
                            error: Optional[str] = None) -> bool:
    """Update agent status"""
    conn = await get_async_connection()
    try:
        query = """
        INSERT INTO agent_status 
        (agent_id, status, current_task_id, capabilities, last_error, last_heartbeat)
        VALUES ($1, $2, $3::uuid, $4::jsonb, $5, CURRENT_TIMESTAMP)
        ON CONFLICT (agent_id) 
        DO UPDATE SET 
            status = EXCLUDED.status,
            current_task_id = EXCLUDED.current_task_id,
            capabilities = EXCLUDED.capabilities,
            last_error = EXCLUDED.last_error,
            last_heartbeat = EXCLUDED.last_heartbeat,
            updated_at = CURRENT_TIMESTAMP
        """
        
        await conn.execute(
            query,
            agent_id,
            status,
            current_task_id,
            json.dumps(capabilities or []),
            error
        )
        return True
    except Exception as e:
        logger.error(f"Failed to update agent status: {str(e)}")
        return False
    finally:
        await release_async_connection(conn)

async def get_agent_status(agent_id: int) -> Optional[Dict]:
    """Get current agent status"""
    query = """
    SELECT * FROM agent_status 
    WHERE agent_id = $1
    """
    
    conn = await get_async_connection()
    try:
        result = await conn.fetchrow(query, agent_id)
        if result:
            return dict(result)
        return None
    finally:
        await release_async_connection(conn)

async def get_queue_status(agent_id: Optional[int] = None) -> Dict:
    """Get queue status for all agents or specific agent"""
    if agent_id:
        query = """
        SELECT 
            agent_id,
            COUNT(*) as pending_count,
            AVG(priority) as avg_priority,
            MIN(created_at) as oldest_task,
            array_agg(
                json_build_object(
                    'id', id,
                    'priority', priority,
                    'created_at', created_at,
                    'prompt_preview', LEFT(prompt, 100)
                )
                ORDER BY priority DESC, created_at ASC
            ) as pending_tasks
        FROM tasks
        WHERE status = 'pending'
        AND agent_id = $1
        GROUP BY agent_id
        """
        conn = await get_async_connection()
        try:
            result = await conn.fetchrow(query, agent_id)
            if result:
                return dict(result)
            return {"agent_id": agent_id, "pending_count": 0, "pending_tasks": []}
        finally:
            await release_async_connection(conn)
    else:
        query = """
        SELECT 
            agent_id,
            COUNT(*) as pending_count,
            AVG(priority) as avg_priority,
            MIN(created_at) as oldest_task
        FROM tasks
        WHERE status = 'pending'
        GROUP BY agent_id
        ORDER BY agent_id
        """
        conn = await get_async_connection()
        try:
            results = await conn.fetch(query)
            return [dict(row) for row in results]
        finally:
            await release_async_connection(conn)

async def cleanup_old_tasks(days_to_keep: int = 30):
    """Clean up old completed tasks"""
    query = """
    DELETE FROM tasks 
    WHERE status IN ('completed', 'failed', 'cancelled')
    AND completed_at < CURRENT_TIMESTAMP - INTERVAL '%s days'
    RETURNING COUNT(*) as deleted_count
    """
    
    conn = await get_async_connection()
    try:
        result = await conn.fetchval(query, days_to_keep)
        logger.info(f"Cleaned up {result} old tasks")
        return result
    except Exception as e:
        logger.error(f"Failed to clean up old tasks: {str(e)}")
        return 0
    finally:
        await release_async_connection(conn)

# Performance monitoring
async def get_system_metrics() -> Dict:
    """Get system-wide metrics"""
    query = """
    SELECT 
        (SELECT COUNT(*) FROM tasks) as total_tasks,
        (SELECT COUNT(*) FROM tasks WHERE status = 'pending') as pending_tasks,
        (SELECT COUNT(*) FROM tasks WHERE status = 'processing') as processing_tasks,
        (SELECT COUNT(*) FROM tasks WHERE status = 'completed') as completed_tasks,
        (SELECT COUNT(*) FROM agent_status WHERE status = 'idle') as idle_agents,
        (SELECT COUNT(*) FROM agent_status WHERE status = 'busy') as busy_agents,
        (SELECT AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) 
         FROM tasks WHERE status = 'completed') as avg_processing_time
    """
    
    conn = await get_async_connection()
    try:
        result = await conn.fetchrow(query)
        return dict(result) if result else {}
    finally:
        await release_async_connection(conn)
