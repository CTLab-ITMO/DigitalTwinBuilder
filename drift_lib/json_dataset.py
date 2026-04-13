"""Потоковое чтение train_dataset*.json (корневой массив записей)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


def load_dialog_messages(record: dict[str, Any]) -> list[dict[str, Any]]:
    d = record.get("dialog")
    if isinstance(d, dict) and "dialog" in d:
        inner = d.get("dialog")
        if isinstance(inner, list):
            return inner
    if isinstance(d, list):
        return d
    return []


def iter_training_records(
    path: Path,
    max_items: int | None = None,
    *,
    json_load_all: bool = False,
) -> Iterator[dict[str, Any]]:
    """
    Итерирует объекты из JSON-массива. По умолчанию — ijson (без полной загрузки файла).
    """
    if json_load_all:
        with path.open("r", encoding="utf-8") as f:
            arr = json.load(f)
        for i, item in enumerate(arr):
            if max_items is not None and i >= max_items:
                break
            if isinstance(item, dict):
                yield item
        return

    try:
        import ijson
    except ImportError as e:
        raise ImportError(
            "Установите ijson для потокового чтения: pip install ijson\n"
            "Или передайте json_load_all=True только для небольших файлов."
        ) from e

    n = 0
    with path.open("rb") as f:
        for item in ijson.items(f, "item"):
            n += 1
            if isinstance(item, dict):
                yield item
            if max_items is not None and n >= max_items:
                break
