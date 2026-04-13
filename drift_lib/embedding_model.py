from __future__ import annotations

import os
from typing import Iterable, List, Sequence

import hashlib

import numpy as np


def _configure_sentence_transformers_env() -> None:
    """
    Должно выполниться до import sentence_transformers / transformers.

    - Не поднимать TensorFlow из transformers (частая причина падений в «голом» окружении).
    - Отключить лишний параллелизм токенизатора (ворнинги и редкие дедлоки).
    """
    os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
    os.environ.setdefault("USE_TF", "0")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


_configure_sentence_transformers_env()


class HashEmbeddingModel:
    """
    Детерминированные нормированные векторы размерности 384 по тексту.
    Для smoke / CI без torch и без sentence-transformers.
    """

    def __init__(self, model_name: str = "hash384-smoke") -> None:
        self.model_name = model_name

    @property
    def embedding_dim(self) -> int:
        return 384

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        prefixed = [t if t.startswith("query: ") else f"query: {t}" for t in texts]
        return self._encode(prefixed)

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        prefixed = [t if t.startswith("passage: ") else f"passage: {t}" for t in texts]
        return self._encode(prefixed)

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        rows = [_text_to_unit_vector(t, 384) for t in texts]
        return np.stack(rows, axis=0).astype(np.float32)

    def encode_queries_iter(self, texts: Iterable[str]) -> np.ndarray:
        return self.encode_queries(list(texts))


def _text_to_unit_vector(text: str, dim: int) -> np.ndarray:
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "little")
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float64)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        v[0] = 1.0
        n = 1.0
    v /= n
    return v.astype(np.float32)


class E5EmbeddingModel:
    """
    intfloat/multilingual-e5-small (384 dim).

    Для запросов пользователя в онлайне — префикс «query: ».
    Для окон диалога / пассажей — «passage: » (как рекомендует семейство E5).

    По умолчанию ``device="cpu"`` (или переменная окружения ``ST_DEVICE``), чтобы не упираться
    в несовместимый драйвер CUDA при первом импорте torch. Для GPU: ``device="cuda:0"``.
    """

    def __init__(
        self,
        model_name: str = "intfloat/multilingual-e5-small",
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        _configure_sentence_transformers_env()
        resolved = device if device is not None else os.environ.get("ST_DEVICE", "cpu")
        if not resolved:
            resolved = "cpu"

        if resolved == "cpu":
            os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

        try:
            from sentence_transformers import SentenceTransformer

            self.model_name = model_name
            self._model = SentenceTransformer(model_name, device=resolved)
        except Exception as e:
            raise RuntimeError(
                "Не удалось загрузить E5 (sentence-transformers). Частые причины:\n"
                "  • стоят сломанные пакеты tensorflow/keras/tf_keras — удали их из venv: "
                "pip uninstall -y tensorflow tf_keras keras\n"
                "  • нет сети к Hugging Face — дождись кэша или настрой HF_ENDPOINT / зеркало\n"
                "  • конфликт версий torch/transformers — см. drift_lib/requirements.txt\n"
                f"Исходная ошибка: {type(e).__name__}: {e}"
            ) from e

        self.batch_size = batch_size
        dim_fn = getattr(self._model, "get_embedding_dimension", None)
        dim = int(dim_fn()) if callable(dim_fn) else int(self._model.get_sentence_embedding_dimension())
        if dim != 384:
            raise ValueError(f"Ожидалась размерность 384, получено {dim} для {model_name}")

    @property
    def embedding_dim(self) -> int:
        dim_fn = getattr(self._model, "get_embedding_dimension", None)
        if callable(dim_fn):
            return int(dim_fn())
        return int(self._model.get_sentence_embedding_dimension())

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        prefixed = [t if t.startswith("query: ") else f"query: {t}" for t in texts]
        return self._encode(prefixed)

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        prefixed = [t if t.startswith("passage: ") else f"passage: {t}" for t in texts]
        return self._encode(prefixed)

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        emb = self._model.encode(
            list(texts),
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(emb, dtype=np.float32)

    def encode_queries_iter(self, texts: Iterable[str]) -> np.ndarray:
        return self.encode_queries(list(texts))


def dialog_overlapping_windows(
    messages: list[dict],
    window_messages: int,
    stride: int,
) -> list[str]:
    """
    Перекрывающиеся окна по списку сообщений (каждое окно — текст для passage-эмбеддинга).
    """
    if window_messages < 1 or stride < 1:
        raise ValueError("window_messages и stride должны быть >= 1")
    out: list[str] = []
    n = len(messages)
    if n == 0:
        return out
    start = 0
    while start + window_messages <= n:
        chunk = messages[start : start + window_messages]
        text = messages_to_window_text(chunk)
        if text.strip():
            out.append(text)
        start += stride
    if not out and messages:
        out.append(messages_to_window_text(messages))
    return out


def messages_to_window_text(messages: list[dict], roles: set[str] | None = None) -> str:
    """Склеивает сообщения диалога в один текст для одного окна."""
    roles = roles or {"user", "assistant", "system"}
    lines: List[str] = []
    for m in messages:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if role not in roles or not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines)
