-- init_database.sql
-- Run this first to set up the database

-- Create database (run this separately if needed)
-- CREATE DATABASE llm_agents;

-- Connect to database
\c llm_agents;

-- Drop existing tables if you want a fresh start
DROP TABLE IF EXISTS tasks CASCADE;
DROP TABLE IF EXISTS agent_status CASCADE;

-- Tasks table
CREATE TABLE tasks (
    id VARCHAR(36) PRIMARY KEY,
    agent_id INTEGER NOT NULL,
    prompt TEXT NOT NULL,
    params JSONB DEFAULT '{}',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    result TEXT,
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    priority INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}'
);

-- Agent status table
CREATE TABLE agent_status (
    agent_id INTEGER PRIMARY KEY,
    status VARCHAR(20) DEFAULT 'idle',
    last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    current_task_id VARCHAR(36),
    capabilities JSONB DEFAULT '[]'
);

-- Indexes for performance
CREATE INDEX idx_tasks_agent_status ON tasks(agent_id, status);
CREATE INDEX idx_tasks_status_created ON tasks(status, created_at);
CREATE INDEX idx_tasks_pending_priority ON tasks(priority DESC, created_at) 
    WHERE status = 'pending';
CREATE INDEX idx_tasks_created ON tasks(created_at DESC);

-- Comments for documentation
COMMENT ON TABLE tasks IS 'Stores all tasks submitted to LLM agents';
COMMENT ON COLUMN tasks.params IS 'LLM parameters (temperature, max_tokens, etc)';
COMMENT ON COLUMN tasks.status IS 'pending, processing, completed, failed';
COMMENT ON TABLE agent_status IS 'Current status of each agent';

-- Create a view for easy monitoring
CREATE VIEW task_monitor AS
SELECT 
    t.id,
    t.agent_id,
    LEFT(t.prompt, 50) AS prompt_preview,
    t.status,
    t.created_at,
    t.started_at,
    t.completed_at,
    a.status AS agent_status,
    EXTRACT(EPOCH FROM (t.completed_at - t.started_at)) AS processing_time_seconds
FROM tasks t
LEFT JOIN agent_status a ON t.agent_id = a.agent_id
ORDER BY t.created_at DESC;
