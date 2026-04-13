"""
MMD² (RBF, смещённая оценка) + перестановочный p-value только на NumPy.
Нужен, когда alibi-detect не импортируется (например, сломанный TensorFlow в окружении).
"""

from __future__ import annotations

import numpy as np


def _rbf_kernel_sq_norms(x: np.ndarray, y: np.ndarray, gamma: float) -> np.ndarray:
    """Матрица exp(-gamma * ||x_i - y_j||^2), x (n,d), y (m,d)."""
    x2 = (x * x).sum(axis=1, keepdims=True)
    y2 = (y * y).sum(axis=1, keepdims=True).T
    d2 = x2 + y2 - 2.0 * (x @ y.T)
    d2 = np.maximum(d2, 0.0)
    return np.exp(-gamma * d2, dtype=np.float64)


def _median_gamma(x: np.ndarray, y: np.ndarray, rng: np.random.Generator, max_points: int = 400) -> float:
    z = np.vstack([x.astype(np.float64), y.astype(np.float64)])
    n = z.shape[0]
    if n > max_points:
        idx = rng.choice(n, size=max_points, replace=False)
        z = z[idx]
    n = z.shape[0]
    d2 = ((z[:, None, :] - z[None, :, :]) ** 2).sum(axis=-1)
    tri = np.triu_indices(n, k=1)
    dist = np.sqrt(np.maximum(d2[tri], 1e-18))
    med = float(np.median(dist))
    return 1.0 / (2.0 * med * med + 1e-18)


def _mmd2_biased_rbf(x: np.ndarray, y: np.ndarray, gamma: float) -> float:
    """
    Смещённая (но неотрицательная в пределе) оценка MMD² для RBF-ядра:

    ``mean(K_XX) + mean(K_YY) - 2 * mean(K_XY)`` (диагонали внутри средних).

    Несмещённый U-статистик вариант часто даёт слегка отрицательные значения на выборке;
    для мониторинга дрейфа удобнее эта форма + ``max(..., 0)`` против численного шума.
    """
    x = x.astype(np.float64)
    y = y.astype(np.float64)
    n, m = x.shape[0], y.shape[0]
    if n < 1 or m < 1:
        return 0.0
    kxx = _rbf_kernel_sq_norms(x, x, gamma)
    kyy = _rbf_kernel_sq_norms(y, y, gamma)
    kxy = _rbf_kernel_sq_norms(x, y, gamma)
    mmd2 = float(kxx.mean() + kyy.mean() - 2.0 * kxy.mean())
    return max(mmd2, 0.0)


def ref_vs_test(
    x_ref: np.ndarray,
    x_test: np.ndarray,
    p_val: float = 0.05,
    n_permutations: int = 200,
    random_state: int = 0,
) -> tuple[float, float, int]:
    """
    Возвращает (mmd², p_value, is_drift) в том же духе, что и alibi MMDDrift.predict.
    """
    rng = np.random.default_rng(random_state)
    x_ref = np.asarray(x_ref, dtype=np.float64)
    x_test = np.asarray(x_test, dtype=np.float64)
    gamma = _median_gamma(x_ref, x_test, rng)
    obs = _mmd2_biased_rbf(x_ref, x_test, gamma)
    n, m = x_ref.shape[0], x_test.shape[0]
    z = np.vstack([x_ref, x_test])
    ge = 1
    for t in range(n_permutations):
        perm = rng.permutation(n + m)
        px = z[perm[:n]]
        py = z[perm[n:]]
        if _mmd2_biased_rbf(px, py, gamma) >= obs:
            ge += 1
    p = ge / (n_permutations + 1)
    is_drift = int(p < p_val)
    return obs, float(p), is_drift
