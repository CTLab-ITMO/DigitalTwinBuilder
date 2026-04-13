-- Расширение для типа vector (установите пакет pgvector в кластере PostgreSQL).
-- https://github.com/pgvector/pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Сырые пользовательские запросы и их эмбеддинги (онлайн-поток к мультиагентной системе).
CREATE TABLE IF NOT EXISTS user_query_events (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL,
    turn_index      INTEGER NOT NULL DEFAULT 0,
    query_text      TEXT NOT NULL,
    -- multilingual-e5-small: 384 измерения
    embedding       vector(384) NOT NULL,
    embedding_model TEXT NOT NULL DEFAULT 'intfloat/multilingual-e5-small',
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, turn_index)
);

CREATE INDEX IF NOT EXISTS idx_user_query_events_session
    ON user_query_events (session_id, turn_index);

CREATE INDEX IF NOT EXISTS idx_user_query_events_created
    ON user_query_events (created_at DESC);

-- После накопления данных можно добавить IVFFlat (нужен ANALYZE и подбор lists):
-- CREATE INDEX ... USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Зафиксированные срабатывания дрейфа (после порога MMD / политики калибровки).
CREATE TABLE IF NOT EXISTS embedding_drift_alerts (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL,
    detector_config JSONB NOT NULL,
    -- срезы окон: индексы или временные метки последних точек в окнах
    ref_window_end  TIMESTAMPTZ,
    test_window_end TIMESTAMPTZ,
    mmd_distance    DOUBLE PRECISION,
    p_value         DOUBLE PRECISION,
    is_drift        BOOLEAN NOT NULL,
    extra           JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_embedding_drift_alerts_session
    ON embedding_drift_alerts (session_id, created_at DESC);
