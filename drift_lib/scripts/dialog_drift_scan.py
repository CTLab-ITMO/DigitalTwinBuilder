#!/usr/bin/env python3
"""
Сканирование train_dataset_qwen_32b.json: перекрывающиеся окна сообщений → эмбеддинги E5,
затем (1) онлайн MMD по потоку окон внутри диалога, (2) сравнение «окно i» vs «окно i−k»
двумя выборками точек вокруг этих индексов (MMD через alibi-detect).

Запуск из корня каталога dataset:
  PYTHONPATH=. python drift_lib/scripts/dialog_drift_scan.py --max-dialogs 3
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Iterator

import numpy as np

os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# dataset/ — родитель пакета drift_lib
_DATASET_ROOT = Path(__file__).resolve().parents[2]
if str(_DATASET_ROOT) not in sys.path:
    sys.path.insert(0, str(_DATASET_ROOT))

from drift_lib.embedding_model import (  # noqa: E402
    E5EmbeddingModel,
    dialog_overlapping_windows,
)
from drift_lib.json_dataset import iter_training_records, load_dialog_messages  # noqa: E402
from drift_lib.online_mmd_detector import OnlineMMDDriftDetector  # noqa: E402


def lag_block_mmd(
    emb: np.ndarray,
    i: int,
    k: int,
    n_ref: int,
    n_test: int,
) -> tuple[float, float | None, int] | None:
    """
    Референс: n_ref эмбеддингов с индексами [i-k-n_ref, i-k),
    тест: n_test эмбеддингов с индексами [i-n_test, i).
    Требует i >= k + n_ref и i >= n_test.
    """
    if i < k + n_ref or i < n_test:
        return None
    lo_r = i - k - n_ref
    hi_r = i - k
    lo_t = i - n_test
    hi_t = i
    if lo_r < 0 or lo_t < 0:
        return None
    x_ref = emb[lo_r:hi_r]
    x_test = emb[lo_t:hi_t]
    if x_ref.shape[0] < 2 or x_test.shape[0] < 2:
        return None
    try:
        from alibi_detect.cd import MMDDrift

        cd = MMDDrift(x_ref.astype(np.float32), backend="pytorch", p_val=0.05)
        preds = cd.predict(x_test.astype(np.float32), return_p_val=True)
        data = preds.get("data", preds) if isinstance(preds, dict) else preds.data
        dist = 0.0
        for key in ("distance", "mmd2", "statistic"):
            if isinstance(data, dict) and key in data and data[key] is not None:
                dist = float(data[key])
                break
        p_val = data.get("p_val") if isinstance(data, dict) else None
        if p_val is not None:
            p_val = float(p_val)
        is_drift = int(data.get("is_drift", 0)) if isinstance(data, dict) else 0
        return dist, p_val, is_drift
    except Exception:
        from drift_lib.mmd_numpy import ref_vs_test as _mmd_np

        dist, p_val, is_drift = _mmd_np(x_ref, x_test, p_val=0.05, random_state=i)
        return dist, p_val, is_drift


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--dataset",
        type=Path,
        default=_DATASET_ROOT / "train_dataset_qwen_32b.json",
    )
    p.add_argument("--max-dialogs", type=int, default=5)
    p.add_argument("--window-messages", type=int, default=4, help="Сообщений в одном окне")
    p.add_argument("--stride", type=int, default=2, help="Шаг окна (перекрытие при stride < window)")
    p.add_argument("--k-lag", type=int, default=3, help="Сдвиг i vs i−k для блочного MMD")
    p.add_argument("--n-ref", type=int, default=8, help="Точек в референсном блоке вокруг i−k")
    p.add_argument("--n-test", type=int, default=8, help="Точек в тестовом блоке, заканчивающемся в i")
    p.add_argument("--ref-size", type=int, default=16, help="Онлайн-детектор: размер референсного окна")
    p.add_argument("--test-size", type=int, default=8, help="Онлайн-детектор: размер тестового окна")
    p.add_argument(
        "--cold-start",
        type=int,
        default=48,
        help="Минимум эмбеддингов в буфере до активации онлайн-детектора",
    )
    p.add_argument("--json-load-all", action="store_true", help="json.load всего файла (осторожно с RAM)")
    args = p.parse_args()

    model = E5EmbeddingModel()

    def records() -> Iterator[dict[str, Any]]:
        yield from iter_training_records(
            args.dataset,
            args.max_dialogs,
            json_load_all=args.json_load_all,
        )

    for di, record in enumerate(records()):
        det = OnlineMMDDriftDetector(
            ref_size=args.ref_size,
            test_size=args.test_size,
            cold_start_min=args.cold_start,
            p_val=0.05,
        )
        messages = load_dialog_messages(record)
        windows = dialog_overlapping_windows(messages, args.window_messages, args.stride)
        if not windows:
            print(f"[dialog {di}] нет окон, сообщений={len(messages)}")
            continue
        emb = model.encode_passages(windows)
        print(f"\n=== dialog {di} | windows={len(windows)} | shape={emb.shape} ===")

        online_drifts = 0
        for t, row in enumerate(emb):
            r = det.push(row)
            if r.active and r.drift:
                online_drifts += 1
                print(
                    f"  online t={t} DRIFT mmd={r.mmd_distance:.6g} p={r.p_value} "
                    f"buf={r.buffer_len}"
                )
        print(f"  online drift steps: {online_drifts}")

        k, nr, nt = args.k_lag, args.n_ref, args.n_test
        lag_hits = 0
        for i in range(max(k + nr, nt), emb.shape[0] + 1):
            out = lag_block_mmd(emb, i, k, nr, nt)
            if out is None:
                continue
            dist, pv, is_d = out
            if is_d:
                lag_hits += 1
                print(
                    f"  lag-k i={i} MMD={dist:.6g} p={pv} "
                    f"(ref=[{i-k-nr}:{i-k}), test=[{i-nt}:{i}))"
                )
        print(f"  lag-k drift positions: {lag_hits}")


if __name__ == "__main__":
    main()
