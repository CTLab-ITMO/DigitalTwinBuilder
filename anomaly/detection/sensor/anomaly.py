import logging
from typing import List, Optional, Tuple, Union
import numpy as np
import pandas as pd
import torch
from detection import (
    SensorData,
    AnomalyDetector,
    AnomalyDetectionResult,
)

from .models.M2AD.src.m2ad import M2AD as M2ADModel

logger = logging.getLogger(__name__)

DataInput = Union[SensorData, np.ndarray, List[float], float]


def _extract_values(data: DataInput, value_field: Optional[str] = None) -> np.ndarray:
    if isinstance(data, list):
        if len(data) == 0:
            return np.array([]).reshape(0, 1)

        if isinstance(data[0], SensorData):
            all_values = []
            for sd in data:
                vals = sd.to_2d()
                if len(vals) > 0:
                    all_values.append(vals[-1])
            if len(all_values) == 0:
                return np.array([]).reshape(0, 1)
            return np.array(all_values)

        return np.asarray(data, dtype=np.float64).reshape(-1, 1)

    if isinstance(data, SensorData):
        return data.to_2d()

    arr = np.asarray(data, dtype=np.float64)

    if arr.ndim == 0:
        return arr.reshape(1, 1)

    if arr.ndim == 1:
        if len(arr) == 0:
            return arr.reshape(0, 1)
        return arr.reshape(-1, 1)

    return arr


class M2AD(AnomalyDetector):

    def __init__(self, detector_id: str = "m2ad",
                 sensors: List[str] = None,
                 covariates: List[str] = None,
                 window_size: int = 100,
                 epochs: int = 35,
                 error_name: str = "point",
                 threshold: float = 0.01,
                 tolerance: int = 10,
                 gamma_thresh: float = 0.001,
                 **kwargs):
        super().__init__(detector_id, threshold=threshold)
        self._sensor_names = sensors
        self._covariate_names = covariates
        self.window_size = window_size
        self.epochs = epochs
        self.error_name = error_name
        self.tolerance = tolerance
        self.gamma_thresh = gamma_thresh
        self.kwargs = kwargs
        self.m2ad_model = None
        self.sensor_indices = []

    def _to_df(self, data: np.ndarray, sensor_names: List[str], covariate_names: List[str]) -> pd.DataFrame:
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        all_names = sensor_names + covariate_names
        df = pd.DataFrame(data, columns=all_names[:data.shape[1]])
        df['time'] = range(len(df))
        return df

    def fit(self, normal_data, progress_callback=None) -> bool:
        try:
            values = _extract_values(normal_data)
            if values.ndim == 1:
                values = values.reshape(-1, 1)

            n_features = values.shape[1]

            if self._sensor_names is None:
                if n_features == 1:
                    sensor_names = ['f0']
                    covariate_names = []
                elif n_features <= 5:
                    sensor_names = [f'f{i}' for i in range(n_features)]
                    covariate_names = []
                else:
                    sensor_names = ['f0']
                    covariate_names = [f'f{i}' for i in range(1, n_features)]
            else:
                sensor_names = self._sensor_names
                covariate_names = self._covariate_names or []

            self.sensor_indices = [i for i, name in enumerate(sensor_names + covariate_names)
                                   if name in sensor_names]

            df = self._to_df(values, sensor_names, covariate_names)

            self.m2ad_model = M2ADModel(
                dataset="default",
                entity="default",
                sensors=sensor_names,
                covariates=covariate_names if covariate_names else None,
                window_size=self.window_size,
                epochs=self.epochs,
                tolerance=self.tolerance,
                gamma_thresh=self.gamma_thresh,
                error_name=self.error_name,
                # CUDA when the machine has it, CPU otherwise: the detector
                # stack runs on the user's hardware, where the base compose
                # profile reserves no GPU. A hard `cuda` made every fit fail
                # there and, because `fit` swallows the error, look like a
                # model that had trained.
                device='cuda' if torch.cuda.is_available() else 'cpu',
                verbose=False,
                **self.kwargs
            )
            self.m2ad_model.fit(df, progress_callback=progress_callback)
            self.is_trained = True
            logger.info(f"M2AD trained on {len(values)} samples, "
                        f"sensors={sensor_names}, covariates={covariate_names[:3]}...")
            return True
        except Exception as e:
            logger.error(f"M2AD fit error: {e}", exc_info=True)
            return False

    def detect_batch_raw(self, data) -> Tuple[np.ndarray, np.ndarray]:
        if not self.is_trained or self.m2ad_model is None:
            n = len(data) if hasattr(data, '__len__') else 1
            return np.zeros(n, dtype=np.float64), np.zeros(n, dtype=bool)
        try:
            values = np.asarray(data, dtype=np.float64)
            if values.ndim == 1:
                values = values.reshape(-1, 1)
            n_features = values.shape[1]
            if self._sensor_names is None:
                if n_features == 1:
                    sensor_names = ['f0']
                    covariate_names = []
                elif n_features <= 5:
                    sensor_names = [f'f{i}' for i in range(n_features)]
                    covariate_names = []
                else:
                    sensor_names = ['f0']
                    covariate_names = [f'f{i}' for i in range(1, n_features)]
            else:
                sensor_names = self._sensor_names
                covariate_names = self._covariate_names or []
            df = self._to_df(values, sensor_names, covariate_names)
            result_df, visuals = self.m2ad_model.detect(df, debug=True)
            anomalyscore = visuals['test_anomaly_score']
            test_timestamps = visuals['test_timestamps']
            scores = np.ones(len(data))
            for ts, sc in zip(test_timestamps, anomalyscore):
                idx = int(ts)
                if 0 <= idx < len(scores):
                    scores[idx] = sc
            predictions = scores < self.threshold
            normalized = 1.0 - np.minimum(scores, 1.0)
            return normalized.astype(np.float64), predictions
        except Exception as e:
            logger.error(f"M2AD batch detect error: {e}", exc_info=True)
            return np.zeros(len(data), dtype=np.float64), np.zeros(len(data), dtype=bool)

    def detect_batch(self, data) -> List[AnomalyDetectionResult]:
        if not self.is_trained or self.m2ad_model is None:
            return [AnomalyDetectionResult(is_anomaly=False, anomaly_score=0.0, anomaly_type=None)
                    for _ in data]

        try:
            values = np.asarray(data, dtype=np.float64)
            if values.ndim == 1:
                values = values.reshape(-1, 1)

            n_features = values.shape[1]
            if self._sensor_names is None:
                if n_features == 1:
                    sensor_names = ['f0']
                    covariate_names = []
                elif n_features <= 5:
                    sensor_names = [f'f{i}' for i in range(n_features)]
                    covariate_names = []
                else:
                    sensor_names = ['f0']
                    covariate_names = [f'f{i}' for i in range(1, n_features)]
            else:
                sensor_names = self._sensor_names
                covariate_names = self._covariate_names or []

            df = self._to_df(values, sensor_names, covariate_names)
            result_df, visuals = self.m2ad_model.detect(df, debug=True)

            anomalyscore = visuals['test_anomaly_score']
            test_timestamps = visuals['test_timestamps']

            scores = np.ones(len(data))
            for i, (ts, score) in enumerate(zip(test_timestamps, anomalyscore)):
                orig_idx = int(ts)
                if 0 <= orig_idx < len(scores):
                    scores[orig_idx] = score

            is_anomaly = scores < self.threshold
            normalized = 1.0 - np.minimum(scores, 1.0)

            return [
                AnomalyDetectionResult(
                    is_anomaly=bool(is_anomaly[i]),
                    anomaly_score=float(normalized[i]),
                    anomaly_type="m2ad_lstm_gmm",
                    details={"raw_pvalue": float(scores[i]), "normalized": float(normalized[i])}
                )
                for i in range(len(data))
            ]

        except Exception as e:
            logger.error(f"M2AD batch detect error: {e}", exc_info=True)
            return [AnomalyDetectionResult(is_anomaly=False, anomaly_score=0.0, anomaly_type=None)
                    for _ in data]

    def detect(self, data) -> AnomalyDetectionResult:
        if not self.is_trained or self.m2ad_model is None:
            return AnomalyDetectionResult(is_anomaly=False, anomaly_score=0.0, anomaly_type=None)
        return AnomalyDetectionResult(is_anomaly=False, anomaly_score=0.0, anomaly_type="m2ad_needs_batch")

    def update(self, data, is_normal: bool = True) -> None:
        pass
