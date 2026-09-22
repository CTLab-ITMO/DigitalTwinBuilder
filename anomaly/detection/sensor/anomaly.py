import logging
import os
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
                device='cuda',
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


class MTGFlowDetector(AnomalyDetector):

    def __init__(self, detector_id: str = "mtgflow",
                 window_size: int = 60,
                 n_blocks: int = 2,
                 hidden_size: int = 32,
                 epochs: int = 40,
                 batch_size: int = 256,
                 lr: float = 2e-3,
                 threshold: float = 0.5,
                 **kwargs):
        super().__init__(detector_id, threshold=threshold)
        self.window_size = window_size
        self.n_blocks = n_blocks
        self.hidden_size = hidden_size
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.kwargs = kwargs
        self.mtgflow_model = None
        self.scaler = None
        self.n_sensors = 0

    def fit(self, normal_data) -> bool:
        try:
            import sys
            mtgflow_dir = os.path.join(os.path.dirname(__file__), 'models', 'MTGFLOW')
            if mtgflow_dir not in sys.path:
                sys.path.insert(0, mtgflow_dir)
            from models.MTGFLOW import MTGFLOW

            values = _extract_values(normal_data)
            if values.ndim == 1:
                values = values.reshape(-1, 1)

            self.n_sensors = values.shape[1]

            from sklearn.preprocessing import StandardScaler
            self.scaler = StandardScaler()
            values_scaled = self.scaler.fit_transform(values)

            max_train_samples = min(len(values_scaled), 5000)
            step = max(1, len(values_scaled) // max_train_samples)
            values_scaled = values_scaled[::step][:max_train_samples]

            windows = self._make_windows(values_scaled)

            device = torch.device('cpu')

            self.mtgflow_model = MTGFLOW(
                n_blocks=self.n_blocks,
                input_size=1,
                hidden_size=self.hidden_size,
                n_hidden=1,
                window_size=self.window_size,
                n_sensor=self.n_sensors,
                dropout=0.0,
                model="MAF",
                batch_norm=False,
                **self.kwargs
            ).to(device)

            optimizer = torch.optim.Adam(self.mtgflow_model.parameters(),
                                         lr=self.lr, weight_decay=5e-4)
            effective_batch_size = min(self.batch_size, 64)
            n_batches = max(1, len(windows) // effective_batch_size)

            logger.info(f"Training MTGFlow on {len(windows)} windows, "
                        f"{self.n_sensors} sensors, {self.epochs} epochs")

            for epoch in range(self.epochs):
                self.mtgflow_model.train()
                epoch_loss = 0.0
                indices = np.random.permutation(len(windows))
                for b in range(n_batches):
                    batch_idx = indices[b * effective_batch_size:(b + 1) * effective_batch_size]
                    batch = torch.tensor(windows[batch_idx], dtype=torch.float32).to(device)
                    optimizer.zero_grad()
                    loss = -self.mtgflow_model(batch)
                    loss.backward()
                    torch.nn.utils.clip_grad_value_(self.mtgflow_model.parameters(), 1)
                    optimizer.step()
                    epoch_loss += loss.item()
                    del batch
                    torch.cuda.empty_cache() if torch.cuda.is_available() else None
                logger.info(f"MTGFlow epoch {epoch+1}/{self.epochs} loss={epoch_loss/n_batches:.4f}")

            self.is_trained = True
            return True

        except Exception as e:
            logger.error(f"MTGFlow fit error: {e}", exc_info=True)
            return False

    def _make_windows(self, data: np.ndarray) -> np.ndarray:
        n_steps = len(data)
        if n_steps < self.window_size:
            padded = np.zeros((self.window_size, self.n_sensors))
            padded[self.window_size - n_steps:] = data
            return padded.T[np.newaxis, :, :, np.newaxis]

        stride = max(1, self.window_size // 6)
        windows = np.lib.stride_tricks.sliding_window_view(
            data, window_shape=(self.window_size,), axis=0
        )[::stride]
        windows = windows[:, :, :, np.newaxis].copy()
        return windows

    def detect_batch_raw(self, data) -> Tuple[np.ndarray, np.ndarray]:
        if not self.is_trained or self.mtgflow_model is None:
            n = len(data) if hasattr(data, '__len__') else 1
            return np.zeros(n, dtype=np.float64), np.zeros(n, dtype=bool)

        try:
            import sys
            mtgflow_dir = os.path.join(os.path.dirname(__file__), 'models', 'MTGFLOW')
            if mtgflow_dir not in sys.path:
                sys.path.insert(0, mtgflow_dir)

            values = np.asarray(data, dtype=np.float64)
            if values.ndim == 1:
                values = values.reshape(-1, 1)

            values_scaled = self.scaler.transform(values)

            windows = self._make_windows(values_scaled)

            device = next(self.mtgflow_model.parameters()).device
            self.mtgflow_model.eval()
            all_scores = []

            det_batch_size = min(16, len(windows))
            with torch.no_grad():
                for i in range(0, len(windows), det_batch_size):
                    batch = torch.tensor(windows[i:i + det_batch_size], dtype=torch.float32).to(device)
                    log_prob = self.mtgflow_model.test(batch)
                    all_scores.append(-log_prob.cpu().numpy())
                    del batch

            window_scores = np.concatenate(all_scores)

            scores = np.full(len(values), -np.inf)
            stride = max(1, self.window_size // 6)
            n_w = len(window_scores)
            starts = np.arange(n_w) * stride
            idx = np.clip(starts[:, None] + np.arange(self.window_size), 0, len(scores) - 1)
            for pos in range(self.window_size):
                np.maximum.at(scores, idx[:, pos], window_scores)

            covered_mask = np.isfinite(scores)
            if np.sum(covered_mask) > 0:
                median_covered = np.median(scores[covered_mask])
                scores[~covered_mask] = median_covered

            s_max = scores.max()
            s_min = scores.min()
            if s_max > s_min:
                scores = (scores - s_min) / (s_max - s_min)
            else:
                scores = np.zeros_like(scores)

            is_anomaly = scores > self.threshold
        except Exception as e:
            logger.error(f"MTGFlow batch detect error: {e}", exc_info=True)
            is_anomaly = np.zeros(len(scores), dtype=bool)

        return scores.astype(np.float64), is_anomaly

    def detect_batch(self, data) -> List[AnomalyDetectionResult]:
        scores, is_anomaly = self.detect_batch_raw(data)
        return [
            AnomalyDetectionResult(
                is_anomaly=bool(is_anomaly[i]),
                anomaly_score=float(scores[i]),
                anomaly_type="mtgflow_density",
                details={"neg_log_prob": float(scores[i])}
            )
            for i in range(len(data))
        ]

    def detect(self, data) -> AnomalyDetectionResult:
        if not self.is_trained or self.mtgflow_model is None:
            return AnomalyDetectionResult(is_anomaly=False, anomaly_score=0.0, anomaly_type=None)
        return AnomalyDetectionResult(is_anomaly=False, anomaly_score=0.0, anomaly_type="mtgflow_needs_batch")

    def update(self, data, is_normal: bool = True) -> None:
        pass
