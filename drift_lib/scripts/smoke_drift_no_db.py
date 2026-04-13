#!/usr/bin/env python3
"""
Проверка без PostgreSQL и без JSON: E5 → эмбеддинги двух «тем» → OnlineMMDDriftDetector (MMD на NumPy).

Запуск из корня каталога dataset:
  TRANSFORMERS_NO_TF=1 PYTHONPATH=. python drift_lib/scripts/smoke_drift_no_db.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

_DATASET_ROOT = Path(__file__).resolve().parents[2]
if str(_DATASET_ROOT) not in sys.path:
    sys.path.insert(0, str(_DATASET_ROOT))

from drift_lib.embedding_model import E5EmbeddingModel  # noqa: E402
from drift_lib.online_mmd_detector import OnlineMMDDriftDetector  # noqa: E402


def _texts_industrial() -> list[str]:
    """Однотипные технические фразы (цифровой двойник / ЧПУ)."""
    return [
        f"Показатель вибрации шпинделя {i} мм/с, протокол Profinet, станок пятикоординатный."
        for i in range(45)
    ]


def _texts_kitchen() -> list[str]:
    """Другая лексика — чтобы распределение эмбеддингов заметно сместилось."""
    return [
        f"Рецепт десерта: сахар, яйца, выпечка в духовке, шаг {i}, крем и ягоды."
        for i in range(90)
    ]


def main() -> None:
    print("загрузка E5…")
    try:
        model = E5EmbeddingModel()
    except Exception as e:
        raise SystemExit(
            f"нужен рабочий E5 (sentence-transformers + torch). Ошибка: {type(e).__name__}: {e}\n"
            "pip install -r drift_lib/requirements.txt\n"
            "При конфликте TF: export TRANSFORMERS_NO_TF=1"
        ) from e

    emb_a = model.encode_passages(_texts_industrial())
    emb_b = model.encode_passages(_texts_kitchen())

    det = OnlineMMDDriftDetector(
        ref_size=12,
        test_size=10,
        cold_start_min=30,
        p_val=0.05,
        mmd_backend="numpy",
    )

    cold_seen = False
    drift_seen = False

    for e in emb_a:
        r = det.push(e)
        if not r.active:
            cold_seen = True
        elif r.drift:
            drift_seen = True

    for step, e in enumerate(emb_b):
        r = det.push(e)
        if r.active and r.drift:
            drift_seen = True
            print(f"после смены темы, шаг={step}: drift=True mmd={r.mmd_distance:.5g} p={r.p_value}")
            break

    print("cold_start был (неактивные шаги):", cold_seen)
    print("дрейф поймали:", drift_seen)
    if not cold_seen:
        raise SystemExit("ожидалась фаза cold start")
    if not drift_seen:
        raise SystemExit(
            "дрейф не сработал на этом разделении тем — для смоука это редко, "
            "но повтори запуск; при необходимости ослабь p_val в скрипте"
        )
    print("smoke: ок")


if __name__ == "__main__":
    main()
