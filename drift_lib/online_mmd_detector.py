from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Literal, Optional

import numpy as np

from .mmd_numpy import ref_vs_test as mmd_ref_vs_test_numpy

MmdBackend = Literal["auto", "alibi", "numpy"]


@dataclass
class DriftStepResult:
    """Результат одного шага после добавления нового эмбеддинга в поток."""

    active: bool
    """False в фазе cold start (меньше N наблюдений в буфере)."""

    drift: Optional[bool]
    """True/False если active, иначе None."""

    mmd_distance: Optional[float]
    p_value: Optional[float]
    buffer_len: int
    ref_size: int
    test_size: int


class OnlineMMDDriftDetector:
    """
    Онлайн-детектор дрейфа по эмбеддингам: два скользящих окна подряд в истории.

    - reference: ``ref_size`` последних точек *до* тестового окна
    - test: ``test_size`` последних точек в буфере

    MMD между двумя выборками: по умолчанию пробуем ``alibi_detect.cd.MMDDrift`` (pytorch),
    при ошибке импорта или ``mmd_backend="numpy"`` — чистый NumPy (``drift_lib/mmd_numpy.py``).

    Cold start: пока ``len(buffer) < cold_start_min``, детектор неактивен.

    Self-calibrating (опционально): после ``calibration_warmup`` активных шагов без дрейфа
    накапливаются значения MMD; порог = ``quantile(mmd_history, calibration_quantile)``.
    Если задан ``use_calibration_threshold``, дрейф = ``mmd > threshold``, иначе — по p-value из alibi.
    """

    def __init__(
        self,
        ref_size: int = 32,
        test_size: int = 16,
        cold_start_min: int = 64,
        p_val: float = 0.05,
        *,
        use_calibration_threshold: bool = False,
        calibration_quantile: float = 0.99,
        calibration_warmup: int = 200,
        calibration_max_history: int = 2000,
        max_buffer: int = 4096,
        mmd_backend: MmdBackend = "auto",
    ) -> None:
        if ref_size < 2 or test_size < 2:
            raise ValueError("ref_size и test_size должны быть >= 2 для устойчивого MMD.")
        if cold_start_min < ref_size + test_size:
            raise ValueError(
                "cold_start_min должен быть >= ref_size + test_size, "
                "чтобы оба окна были полными."
            )
        self.ref_size = ref_size
        self.test_size = test_size
        self.cold_start_min = cold_start_min
        self.p_val = p_val
        self.use_calibration_threshold = use_calibration_threshold
        self.calibration_quantile = calibration_quantile
        self.calibration_warmup = calibration_warmup
        self.calibration_max_history = calibration_max_history
        self._buf: Deque[np.ndarray] = deque(maxlen=max_buffer)
        self._mmd_history: List[float] = []
        self._steps_since_start = 0
        self.mmd_backend: MmdBackend = mmd_backend
        self._use_numpy_mmd: bool = mmd_backend == "numpy"

    def push(self, embedding: np.ndarray) -> DriftStepResult:
        e = np.asarray(embedding, dtype=np.float32).ravel()
        self._buf.append(e)
        self._steps_since_start += 1
        n = len(self._buf)
        if n < self.cold_start_min:
            return DriftStepResult(
                active=False,
                drift=None,
                mmd_distance=None,
                p_value=None,
                buffer_len=n,
                ref_size=self.ref_size,
                test_size=self.test_size,
            )

        arr = np.stack(list(self._buf), axis=0)
        x_test = arr[-self.test_size :]
        x_ref = arr[-(self.test_size + self.ref_size) : -self.test_size]

        mmd_dist, p_val, is_drift_alibi = self._mmd_predict(x_ref, x_test)

        drift_flag: Optional[bool] = bool(is_drift_alibi)
        if self.use_calibration_threshold and self._steps_since_start > self.calibration_warmup:
            thr = self._calibration_threshold()
            if thr is not None:
                drift_flag = bool(mmd_dist > thr)

        if drift_flag is False and mmd_dist is not None:
            self._mmd_history.append(float(mmd_dist))
            if len(self._mmd_history) > self.calibration_max_history:
                self._mmd_history = self._mmd_history[-self.calibration_max_history :]

        return DriftStepResult(
            active=True,
            drift=drift_flag,
            mmd_distance=mmd_dist,
            p_value=p_val,
            buffer_len=n,
            ref_size=self.ref_size,
            test_size=self.test_size,
        )

    def _calibration_threshold(self) -> Optional[float]:
        if len(self._mmd_history) < 50:
            return None
        return float(np.quantile(np.array(self._mmd_history), self.calibration_quantile))

    def _mmd_predict(
        self, x_ref: np.ndarray, x_test: np.ndarray
    ) -> tuple[float, Optional[float], int]:
        if self._use_numpy_mmd or self.mmd_backend == "numpy":
            dist, p_val, is_drift = mmd_ref_vs_test_numpy(
                x_ref, x_test, p_val=self.p_val, random_state=self._steps_since_start
            )
            return dist, p_val, is_drift

        if self.mmd_backend == "alibi":
            return self._mmd_predict_alibi(x_ref, x_test)

        # auto: alibi, при первой же ошибке — только numpy
        try:
            return self._mmd_predict_alibi(x_ref, x_test)
        except Exception:
            self._use_numpy_mmd = True
            dist, p_val, is_drift = mmd_ref_vs_test_numpy(
                x_ref, x_test, p_val=self.p_val, random_state=self._steps_since_start
            )
            return dist, p_val, is_drift

    def _mmd_predict_alibi(
        self, x_ref: np.ndarray, x_test: np.ndarray
    ) -> tuple[float, Optional[float], int]:
        from alibi_detect.cd import MMDDrift

        cd = MMDDrift(x_ref, backend="pytorch", p_val=self.p_val)
        preds = cd.predict(x_test, return_p_val=True)
        data = preds.get("data") if isinstance(preds, dict) else getattr(preds, "data", preds)
        dist = 0.0
        if isinstance(data, dict):
            for key in ("distance", "mmd2", "statistic"):
                if key in data and data[key] is not None:
                    dist = float(data[key])
                    break
            p_val = data.get("p_val")
            is_drift = int(data.get("is_drift", 0))
        else:
            for key in ("distance", "mmd2", "statistic"):
                v = getattr(data, key, None)
                if v is not None:
                    dist = float(v)
                    break
            p_val = getattr(data, "p_val", None)
            is_drift = int(getattr(data, "is_drift", 0))
        if p_val is not None:
            p_val = float(p_val)
        return dist, p_val, is_drift
