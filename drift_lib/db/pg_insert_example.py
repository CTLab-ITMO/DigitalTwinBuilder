"""
Запись пользовательского запроса и эмбеддинга в PostgreSQL + pgvector.

Перед вставкой выполни drift_lib/db/schema.sql в базе (расширение vector на сервере).

Рекомендуемый способ — пакет ``pgvector`` + ``register_vector(conn)``: вектор передаётся
как numpy/list, без ручной сборки строки ``'[...]'``.

Строка подключения: postgresql://USER:PASS@HOST:5432/DB
"""

from __future__ import annotations

import uuid
from typing import Any

import numpy as np


def register_pgvector(conn: Any) -> None:
    """
    Один раз после ``psycopg2.connect`` — регистрирует тип vector для параметров запроса.
    """
    from pgvector.psycopg2 import register_vector

    register_vector(conn)


def insert_user_query(
    conn: Any,
    session_id: uuid.UUID,
    turn_index: int,
    query_text: str,
    embedding: np.ndarray,
    metadata: dict | None = None,
    model_name: str = "intfloat/multilingual-e5-small",
    *,
    use_pgvector_package: bool = True,
) -> int:
    """
    Возвращает id вставленной строки.

    По умолчанию использует пакет ``pgvector`` (вызови ``register_pgvector(conn)`` один раз
    после подключения, либо он будет вызван здесь при ``use_pgvector_package=True``).

    Если пакета нет, установи ``use_pgvector_package=False`` — тогда в БД уходит литерал
    ``[...]`` + приведение ``::vector`` (менее удобно, но без зависимости ``pgvector``).
    """
    from psycopg2.extras import Json

    meta = metadata or {}
    emb = np.asarray(embedding, dtype=np.float32).ravel()
    if emb.shape[0] != 384:
        raise ValueError(f"ожидался вектор длины 384, получено {emb.shape[0]}")

    with conn.cursor() as cur:
        if use_pgvector_package:
            try:
                register_pgvector(conn)
            except ImportError as e:
                raise ImportError(
                    "Для вставки вектора установи пакет: pip install pgvector\n"
                    "или передай use_pgvector_package=False для режима строкового литерала."
                ) from e
            cur.execute(
                """
                INSERT INTO user_query_events
                    (session_id, turn_index, query_text, embedding, embedding_model, metadata)
                VALUES (%s::uuid, %s, %s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (str(session_id), turn_index, query_text, emb, model_name, Json(meta)),
            )
        else:
            vec_lit = _vector_literal(emb)
            cur.execute(
                """
                INSERT INTO user_query_events
                    (session_id, turn_index, query_text, embedding, embedding_model, metadata)
                VALUES (%s::uuid, %s, %s, %s::vector, %s, %s::jsonb)
                RETURNING id
                """,
                (str(session_id), turn_index, query_text, vec_lit, model_name, Json(meta)),
            )
        row = cur.fetchone()
    conn.commit()
    return int(row[0])


def _vector_literal(embedding: np.ndarray) -> str:
    flat = np.asarray(embedding, dtype=float).ravel()
    return "[" + ",".join(str(x) for x in flat.tolist()) + "]"


def embedding_to_sql_literal(embedding: np.ndarray) -> str:
    """Отладка в psql: ``SELECT '[0.1,0.2,...]'::vector``."""
    inner = ",".join(str(float(x)) for x in np.asarray(embedding, dtype=float).ravel())
    return f"'[{inner}]'"
