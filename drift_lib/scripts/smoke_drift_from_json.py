#!/usr/bin/env python3
"""
Smoke: диалог(и) из train_dataset_qwen_32b.json → окна → эмбеддинги intfloat/multilingual-e5-small → онлайн MMD.
Без PostgreSQL. MMD по умолчанию на NumPy. Эмбеддинги только через E5 (нужен sentence-transformers).

  PYTHONPATH=. python drift_lib/scripts/smoke_drift_from_json.py
"""

from __future__ import annotations

import argparse
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

from drift_lib.embedding_model import E5EmbeddingModel, dialog_overlapping_windows  # noqa: E402
from drift_lib.json_dataset import iter_training_records, load_dialog_messages  # noqa: E402
from drift_lib.online_mmd_detector import DriftStepResult, OnlineMMDDriftDetector  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Smoke дрейфа на реальном JSON")
    p.add_argument(
        "--dataset",
        type=Path,
        default=_DATASET_ROOT / "train_dataset_qwen_32b.json",
    )
    p.add_argument("--max-dialogs", type=int, default=1)
    p.add_argument("--window-messages", type=int, default=3)
    p.add_argument("--stride", type=int, default=1)
    p.add_argument("--ref-size", type=int, default=8)
    p.add_argument("--test-size", type=int, default=6)
    p.add_argument("--cold-start", type=int, default=18)
    p.add_argument(
        "--mmd-backend",
        choices=("numpy", "alibi", "auto"),
        default="numpy",
    )
    p.add_argument("--device", type=str, default=None)
    p.add_argument("--json-load-all", action="store_true")
    args = p.parse_args()

    if not args.dataset.is_file():
        raise SystemExit(f"нет файла: {args.dataset}")

    records = list(
        iter_training_records(
            args.dataset,
            args.max_dialogs,
            json_load_all=args.json_load_all,
        )
    )
    if not records:
        raise SystemExit("в датасете не прочитано ни одной записи")

    print("эмбеддинги: intfloat/multilingual-e5-small (первый запуск может скачать веса)…")
    try:
        model = E5EmbeddingModel(device=args.device)
    except Exception as e:
        raise SystemExit(
            f"нужен рабочий E5 (sentence-transformers + torch). Ошибка: {type(e).__name__}: {e}\n"
            "Поставь зависимости: pip install -r drift_lib/requirements.txt\n"
            "Если ломается TensorFlow в transformers: export TRANSFORMERS_NO_TF=1"
        ) from e

    for di, record in enumerate(records):
        messages = load_dialog_messages(record)
        windows = dialog_overlapping_windows(messages, args.window_messages, args.stride)
        print(
            f"\n[dialog {di}] сообщений={len(messages)} окон={len(windows)} "
            f"(window={args.window_messages} stride={args.stride})"
        )
        if not windows:
            raise SystemExit("нет текстовых окон — smoke не пройден")
        if len(windows) < args.cold_start:
            raise SystemExit(
                f"окон {len(windows)} < --cold-start {args.cold_start}: "
                "уменьши cold-start или окно (--window-messages / --stride)"
            )

        emb = model.encode_passages(windows)
        print(f"эмбеддинги: shape={emb.shape} dim={model.embedding_dim}")

        det = OnlineMMDDriftDetector(
            ref_size=args.ref_size,
            test_size=args.test_size,
            cold_start_min=args.cold_start,
            p_val=0.05,
            mmd_backend=args.mmd_backend,
        )

        last_active: DriftStepResult | None = None
        drift_steps = 0
        for t, row in enumerate(emb):
            r = det.push(row)
            last_active = r if r.active else last_active
            if r.active and r.drift:
                drift_steps += 1

        if last_active is None:
            raise SystemExit("детектор не стал активным — проверь cold-start и число окон")
        print(
            f"детектор активен: buf={last_active.buffer_len} "
            f"последний mmd={last_active.mmd_distance} p={last_active.p_value}"
        )
        print(f"шагов с drift=True: {drift_steps}")
        print("smoke json: ок")


if __name__ == "__main__":
    main()
