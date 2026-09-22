import logging
import operator
from functools import partial
from itertools import compress
from statistics import NormalDist
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error
from sklearn.preprocessing import MinMaxScaler
from sklearn.impute import SimpleImputer
from sklearn.mixture import GaussianMixture

LOGGER = logging.getLogger("m2ad_anomaly_head")


def sliding_window_sequences(X, index, y=None, window_size=100,
                             step_size=1, target_size=1):
    if y is None:
        y = X.copy()
    windows, targets, indices = [], [], []
    length = len(X)
    for i in range(0, length - window_size - 1, step_size):
        start = i
        end = i + window_size
        windows.append(X[start:end])
        targets.append(y[end + 1])
        indices.append(index[end + 1])
    return np.array(windows, dtype=np.float32), \
        np.array(targets, dtype=np.float32), \
        np.array(indices)


def _smooth(errors, smoothing_window):
    return pd.DataFrame(errors).ewm(smoothing_window).mean().values


def point_errors(y, pred, smooth=False, smoothing_window=10):
    errors = np.abs(y - pred)
    if smooth:
        errors = _smooth(errors, smoothing_window)
    return np.array(errors)


def area_errors(y, pred, score_window=10, dx=100,
                smooth=False, smoothing_window=10):
    trapz_func = np.trapezoid if hasattr(np, 'trapezoid') else np.trapz
    trapz = partial(trapz_func, dx=dx)
    errors = np.empty_like(y)
    num_signals = errors.shape[1]
    for i in range(num_signals):
        area_y = pd.Series(y[:, i]).rolling(
            score_window, center=True,
            min_periods=score_window // 2).apply(trapz)
        area_pred = pd.Series(pred[:, i]).rolling(
            score_window, center=True,
            min_periods=score_window // 2).apply(trapz)
        error = area_y - area_pred
        if smooth:
            error = _smooth(error, smoothing_window)
        errors[:, i] = error.flatten()
    mu = np.mean(errors)
    std = np.std(errors)
    return (errors - mu) / std


def _get_sum(name, sensors):
    return sum(1 for s in sensors if name in s)


def _divide(x, y):
    return x / y if y else 0


def _get_default(sensors):
    return {s: 1 for s in sensors}


def _find_weights(sensors, prefix=None):
    prefix = prefix or _get_default(sensors)
    pre_weights = {
        st: _divide(sw, _get_sum(st, sensors))
        for st, sw in prefix.items()
    }
    return [pre_weights[k] for s in sensors for k in pre_weights if k in s]


def _compute_cdf(gmm, x):
    means = gmm.means_.flatten()
    sigma = np.sqrt(gmm.covariances_).flatten()
    weights = gmm.weights_.flatten()
    cdf = 0
    for i in range(len(means)):
        cdf += weights[i] * NormalDist(mu=means[i], sigma=sigma[i]).cdf(x)
    return cdf


def _combine_pval(cdf, side=True):
    if side:
        p_val = 1 - cdf
    else:
        p_val = 2 * np.array(list(map(np.min, zip(1 - cdf, cdf))))
    p_val[p_val < 1e-16] = 1e-16
    fisher_pval = -2 * np.log(p_val)
    return fisher_pval, p_val


def _merge_sequences(sequences):
    if len(sequences) == 0:
        return np.array([])
    sorted_sequences = sorted(sequences, key=operator.itemgetter(0))
    new_sequences = [sorted_sequences[0]]
    score = [sorted_sequences[0][2]]
    for sequence in sorted_sequences[1:]:
        prev_sequence = new_sequences[-1]
        if sequence[0] <= prev_sequence[1] + 1:
            score.append(sequence[2])
            average = np.mean(score)
            new_sequences[-1] = (
                prev_sequence[0], max(prev_sequence[1], sequence[1]), average)
        else:
            score = [sequence[2]]
            new_sequences.append(sequence)
    return np.array(new_sequences)


class GMM:
    def _parse_components(self, n_components, sensors, default=1):
        if sensors is None:
            if isinstance(n_components, dict):
                raise ValueError(
                    "Unknown list of sensors but specified in components.")
            elif isinstance(n_components, int):
                return n_components
            return default
        if isinstance(n_components, dict):
            n_components = {
                **n_components,
                **{k: default for k in sensors if k not in n_components}
            }
        elif isinstance(n_components, int):
            n_components = dict(zip(sensors, [n_components] * len(sensors)))
        return n_components

    def __init__(self, sensors, n_components=1, covariance_type='spherical',
                 one_sided=False, weights=None):
        self.sensors = sensors
        self.n_components = self._parse_components(n_components, sensors)
        self.covariance_type = covariance_type
        self.one_sided = one_sided
        self.components = [None] * len(self.sensors) if self.sensors is not None else []
        self.compute_cdf = np.vectorize(_compute_cdf)
        self.weights = [] if self.sensors is None else (weights or _find_weights(self.sensors))
        self.train_combined: Optional[np.ndarray] = None

    def fit(self, X):
        if X is None or X.size == 0 or X.shape[0] < 2:
            raise ValueError(f"X must have at least 2 samples, got shape={X.shape if X is not None else 'None'}")
        combined = 0
        num_sensors = X.shape[1]
        assert num_sensors == len(self.sensors)
        for i, sensor in enumerate(self.sensors):
            x = X[:, i].reshape(-1, 1)
            gmm = GaussianMixture(
                n_components=self.n_components[sensor],
                covariance_type=self.covariance_type,
                reg_covar=1e-6, max_iter=1000)
            gmm.fit(x)
            self.components[i] = gmm
            cdf = self.compute_cdf(gmm, x.flatten())
            fisher, p_val = _combine_pval(cdf, self.one_sided)
            combined += self.weights[i] * fisher
        self.train_combined = combined.copy()

    def p_values(self, X):
        if X.size == 0:
            return np.array([]), np.array([]), np.array([]), np.array([])
        combined = 0
        p_val_sensors = np.zeros_like(X)
        fisher_values = np.zeros_like(X)
        for i, sensor in enumerate(self.sensors):
            y = X[:, i]
            gmm = self.components[i]
            cdf = self.compute_cdf(gmm, y)
            fisher, p_val = _combine_pval(cdf, self.one_sided)
            combined += self.weights[i] * fisher
            p_val_sensors[:, i] = p_val
            fisher_values[:, i] = fisher
        gamma_p_val = np.zeros(len(combined))
        if self.train_combined is not None and len(self.train_combined) > 0:
            sorted_train = np.sort(self.train_combined)
            gamma_p_val = 1.0 - np.searchsorted(
                sorted_train, combined, side='left').astype(np.float64) / len(sorted_train)
        return gamma_p_val, p_val_sensors, combined, fisher_values


class TFT:
    def __init__(self, hidden_dim=80, n_layer=2, dropout=0.2,
                 device='cpu', batch_size=32, lr=1e-3, verbose=True):
        self.hidden_dim = hidden_dim
        self.n_layer = n_layer
        self.dropout = dropout
        self.device = device
        self.batch_size = batch_size
        self.lr = lr
        self.verbose = verbose
        self.model = None

    def fit(self, X, y, epochs=35, validation_split=0.2,
            tolerance=10, min_delta=0.001, progress_callback=None):
        n = len(X)
        split = int(n * (1 - validation_split))
        train, valid = X[:split], X[split:]
        train_y, valid_y = y[:split], y[split:]
        _, seq_len, n_channels = X.shape
        out_channels = y.shape[1]

        import math
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
        from torch.optim import Adam
        from torch.utils.data import DataLoader, TensorDataset

        class GRN(nn.Module):
            def __init__(self, d, d_out=None, dropout=0.1):
                super().__init__()
                d_out = d_out or d
                self.fc1 = nn.Linear(d, d_out)
                self.fc2 = nn.Linear(d_out, d_out)
                self.gate = nn.Linear(d_out, d_out)
                self.layernorm = nn.LayerNorm(d_out)
                self.dropout = nn.Dropout(dropout)

            def forward(self, x):
                elu = F.elu(self.fc1(x))
                fc2 = self.fc2(elu)
                gated = torch.sigmoid(self.gate(fc2)) * fc2
                if x.shape[-1] == gated.shape[-1]:
                    return self.layernorm(x + self.dropout(gated))
                return self.layernorm(self.dropout(gated))

        class VariableSelection(nn.Module):
            def __init__(self, n_channels, hidden):
                super().__init__()
                self.flatten_grn = GRN(n_channels * hidden, hidden)
                self.per_feature = nn.ModuleList([
                    GRN(hidden, hidden) for _ in range(n_channels)
                ])
                self.fc_in = nn.Linear(hidden, n_channels)

            def forward(self, x):
                B, T, C, D = x.shape
                flat = x.reshape(B, T, C * D)
                selector = self.flatten_grn(flat)
                weights = F.softmax(self.fc_in(selector), dim=-1)
                out = 0
                for i, grn in enumerate(self.per_feature):
                    out += grn(x[:, :, i, :]) * weights[:, :, i:i+1]
                return out

        class _TFT(nn.Module):
            def __init__(self, seq_len, n_channels, out_channels,
                         hidden, n_layer, dropout):
                super().__init__()
                self.input_fc = nn.Linear(1, hidden)
                pe = torch.zeros(1, seq_len, hidden)
                for pos in range(seq_len):
                    for i in range(0, hidden, 2):
                        pe[0, pos, i] = math.sin(
                            pos / (10000 ** (i / hidden)))
                        if i + 1 < hidden:
                            pe[0, pos, i + 1] = math.cos(
                                pos / (10000 ** (i / hidden)))
                self.register_buffer('pos_encoding', pe)
                self.vsn = VariableSelection(n_channels, hidden)
                self.lstm = nn.LSTM(
                    hidden, hidden, batch_first=True, bidirectional=False)
                self.lstm_norm = nn.LayerNorm(hidden)
                self.attn = nn.ModuleList([
                    nn.MultiheadAttention(hidden, num_heads=4,
                                          batch_first=True, dropout=dropout)
                    for _ in range(n_layer)
                ])
                self.attn_norm = nn.ModuleList([
                    nn.LayerNorm(hidden) for _ in range(n_layer)
                ])
                self.attn_grn = nn.ModuleList([
                    GRN(hidden, hidden, dropout) for _ in range(n_layer)
                ])
                self.out_grn = GRN(hidden, hidden, dropout)
                self.fc_out = nn.Linear(hidden, out_channels)

            def forward(self, x):
                B, T, C = x.shape
                projected = self.input_fc(x.unsqueeze(-1))
                x = self.vsn(projected)
                x = x + self.pos_encoding[:, :T, :]
                lstm_out, _ = self.lstm(x)
                x = self.lstm_norm(x + lstm_out)
                for attn, norm, grn in zip(
                        self.attn, self.attn_norm, self.attn_grn):
                    attn_out, _ = attn(x, x, x)
                    x = grn(norm(x + attn_out))
                x = self.out_grn(x[:, -1, :])
                return self.fc_out(x)

        self.model = _TFT(
            seq_len, n_channels, out_channels,
            self.hidden_dim, self.n_layer, self.dropout
        ).to(self.device)

        optimizer = Adam(self.model.parameters(), lr=self.lr)
        criterion = nn.MSELoss(reduction='mean').to(self.device)

        train_loader = DataLoader(
            TensorDataset(torch.tensor(train).float(),
                          torch.tensor(train_y).float()),
            batch_size=self.batch_size, shuffle=True)
        valid_loader = DataLoader(
            TensorDataset(torch.tensor(valid).float(),
                          torch.tensor(valid_y).float()),
            batch_size=self.batch_size)

        best_loss = float('inf')
        patience = 0

        for epoch in range(epochs):
            if progress_callback:
                progress_callback(epoch + 1, epochs)

            self.model.train()
            train_losses = []
            for x_b, y_b in train_loader:
                x_b, y_b = x_b.to(self.device), y_b.to(self.device)
                optimizer.zero_grad()
                loss = criterion(self.model(x_b), y_b)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()
                train_losses.append(loss.item())

            self.model.eval()
            valid_losses = []
            with torch.no_grad():
                for x_b, y_b in valid_loader:
                    x_b, y_b = x_b.to(self.device), y_b.to(self.device)
                    loss = criterion(self.model(x_b), y_b)
                    valid_losses.append(loss.item())

            avg_valid = np.mean(valid_losses)
            if avg_valid < best_loss - min_delta:
                best_loss = avg_valid
                patience = 0
            else:
                patience += 1
                if patience >= tolerance:
                    if self.verbose:
                        LOGGER.info(
                            f'Early stopping at epoch {epoch+1}')
                    break

    def predict(self, X):
        import torch
        self.model.eval()
        preds = []
        batch_size = self.batch_size
        with torch.no_grad():
            for i in range(0, len(X), batch_size):
                batch = torch.tensor(
                    X[i:i + batch_size], dtype=torch.float32
                ).to(self.device)
                out = self.model(batch).cpu().numpy()
                out = np.nan_to_num(out, nan=0.0, posinf=1.0, neginf=-1.0)
                preds.append(out)
        return np.concatenate(preds)


class M2AD:
    def __init__(self, dataset, entity, sensors=None, covariates=None,
                 time_column='time', feature_range=(0, 1), strategy='mean',
                 error_name='point', window_size=100, target_size=1,
                 step_size=1, hidden_dim=80, n_layer=2, dropout=0.2,
                 device='cpu', batch_size=32, lr=1e-3, epochs=35,
                 score_window=10, verbose=True, n_components=1,
                 covariance_type='spherical', tolerance=10, min_delta=0.001,
                 gamma_thresh=0.001, forget_factor=0.95, **kwargs):
        self.dataset = dataset
        self.entity = entity
        self.sensors = sensors
        self.covariates = covariates
        self.time_column = time_column
        self.scaler = MinMaxScaler(feature_range=feature_range)
        self.imputer = SimpleImputer(strategy=strategy)
        self.window_size = window_size
        self.target_size = target_size
        self.step_size = step_size
        self.model = TFT(
            hidden_dim=hidden_dim, n_layer=n_layer, dropout=dropout,
            device=device, batch_size=batch_size, lr=lr, verbose=verbose)
        self.error_name = error_name
        self.gamma_thresh = gamma_thresh
        self.epochs = epochs
        self.score_window = score_window
        self.tolerance = tolerance
        self.min_delta = min_delta
        self.n_components = n_components
        self.covariance_type = covariance_type
        self.forget_factor = forget_factor
        if self.error_name == 'point':
            self.one_sided = True
        elif self.error_name == 'area':
            self.one_sided = False
        else:
            raise ValueError(f"Unknown error function {self.error_name}.")

    def _get_data(self, df, fit_scaler=True):
        data = df.copy()
        timestamp = data.pop(self.time_column)
        X = data[self.sensors]
        if self.covariates:
            cov = data[self.covariates]
        else:
            cov = None
        X = self.imputer.fit_transform(X) if fit_scaler else \
            self.imputer.transform(X)
        X = self.scaler.fit_transform(X) if fit_scaler else \
            self.scaler.transform(X)
        y = X.copy()
        X = np.concatenate([X, cov.values], axis=1) if self.covariates else X
        return X, y, cov, timestamp

    def _compute_error(self, y, pred):
        if self.error_name == 'point':
            return point_errors(y, pred, smooth=True)
        elif self.error_name == 'area':
            return area_errors(y, pred, smooth=True)
        raise ValueError(f"Unknown error function {self.error_name}.")

    def create_intervals(self, anomalies, index, score,
                         anomaly_padding=3):
        intervals = []
        length = len(anomalies)
        index_length = len(index)
        anomalies_idx = list(compress(range(length), anomalies))
        for idx in anomalies_idx:
            start = max(0, idx - anomaly_padding)
            end = min(idx + anomaly_padding + 1, length, index_length)
            value = np.mean(score[start:end])
            if start < index_length and end <= index_length:
                intervals.append([
                    index[start],
                    index[end - 1] if end > 0 else index[start],
                    value])
        intervals = _merge_sequences(intervals)
        intervals = sorted(intervals, key=operator.itemgetter(0),
                           reverse=True)
        anomalies = pd.DataFrame(intervals, columns=['start', 'end', 'score'])
        anomalies.insert(0, 'dataset', self.dataset)
        anomalies.insert(1, 'entity', self.entity)
        return anomalies

    def fit(self, df, validation_split=0.2, tolerance=None, min_delta=None,
            progress_callback=None):
        X, y, cov, timestamp = self._get_data(df)
        if self.covariates:
            assert len(cov.columns) == len(self.covariates)
        assert y.shape[1] == len(self.sensors)
        expected = (len(self.covariates) + len(self.sensors)
                    if self.covariates else len(self.sensors))
        assert X.shape[1] == expected
        windows, targets, indices = sliding_window_sequences(
            X=X, y=y, index=timestamp, window_size=self.window_size,
            target_size=self.target_size, step_size=self.step_size)
        tolerance = tolerance if tolerance is not None else self.tolerance
        min_delta = min_delta if min_delta is not None else self.min_delta
        LOGGER.info(f'Training the model with {self.epochs} epochs.')
        self.model.fit(windows, targets, epochs=self.epochs,
                       validation_split=validation_split,
                       tolerance=tolerance, min_delta=min_delta,
                       progress_callback=progress_callback)
        pred = self.model.predict(windows)
        pred = pred.reshape(targets.shape)
        errors = self._compute_error(targets, pred)
        self.gmm_model = GMM(
            sensors=self.sensors, n_components=self.n_components,
            covariance_type=self.covariance_type,
            one_sided=self.one_sided)
        self.gmm_model.fit(errors)
        anomaly_score, p_value, fisher, _ = self.gmm_model.p_values(errors)
        self.threshold = np.percentile(fisher, 99.5)
        self.train_mse = mean_squared_error(targets, pred)
        self.train_errors = errors
        self.train_targets = targets
        self.train_pred = pred
        self.train_p_values = p_value
        self.train_anomaly_score = anomaly_score

    def detect(self, df, debug=False):
        X, y, _, timestamp = self._get_data(df, fit_scaler=False)
        windows, targets, indices = sliding_window_sequences(
            X=X, y=y, index=timestamp, window_size=self.window_size,
            target_size=self.target_size, step_size=self.step_size)
        pred = self.model.predict(windows)
        pred = pred.reshape(targets.shape)
        errors = self._compute_error(targets, pred)
        LOGGER.info('Applying threshold on p-values.')
        anomaly_score, p_value, fisher, fisher_values = \
            self.gmm_model.p_values(errors)
        anomalies = anomaly_score < self.gamma_thresh
        formatted_anomalies = self.create_intervals(
            anomalies, indices, anomaly_score)
        if debug:
            visuals = {
                "anomalies": anomalies,
                "test_targets": targets,
                "test_pred": pred,
                "test_errors": errors,
                "test_pvals": p_value,
                "test_anomaly_score": anomaly_score,
                "test_timestamps": indices,
                "train_targets": self.train_targets,
                "train_pred": self.train_pred,
                "train_errors": self.train_errors,
                "train_pvals": self.train_p_values,
                "train_anomaly_score": self.train_anomaly_score,
            }
            return formatted_anomalies, visuals
        return formatted_anomalies

    def update(self, normal_data, forget_factor=None):
        if self.gmm_model is None:
            LOGGER.warning("No GMM fitted yet, skipping update.")
            return
        beta = forget_factor if forget_factor is not None else \
            self.forget_factor
        for i, sensor in enumerate(self.sensors):
            gmm = self.gmm_model.components[i]
            if gmm is None:
                continue
            new_x = normal_data[:, i].reshape(-1, 1)
            new_gmm = GaussianMixture(
                n_components=gmm.n_components,
                covariance_type=self.covariance_type)
            new_gmm.fit(new_x)
            gmm.means_[:] = beta * gmm.means_ + \
                (1 - beta) * new_gmm.means_
            gmm.covariances_[:] = beta * gmm.covariances_ + \
                (1 - beta) * new_gmm.covariances_
        _, _, combined, _ = self.gmm_model.p_values(self.train_errors)
        self.gmm_model.train_combined = combined.copy()
        LOGGER.info(
            "GMM updated (β=%.2f): train_combined n=%d, μ=%.4f",
            beta, len(combined), float(np.mean(combined)))
