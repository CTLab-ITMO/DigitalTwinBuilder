"""
Модуль анализа дрейфа данных для детекции касок
Использует PSI, KL divergence, Page-Hinkley тест
"""
import cv2
import numpy as np
from scipy.stats import ks_2samp, wasserstein_distance
from scipy.special import rel_entr
from scipy.spatial.distance import jensenshannon
from torchvision import models, transforms
import torch
from typing import List, Dict, Optional
from collections import deque


# Максимальная сторона изображения для расчёта дрейфа (ограничение памяти и CPU)
MAX_DRIFT_EDGE = 320


# Пороги для нормализации агрегированной метрики (значение 1.0 = на пороге)
DEFAULT_THRESHOLDS = {
    "psi_mean": 0.2,
    "kl_mean": 1.0,
    "js_divergence": 0.3,
    "ks_pvalue": 0.05,
    "wasserstein_distance": 30.0,
}

# Веса для взвешенной агрегированной метрики (сумма = 1)
DEFAULT_WEIGHTS = {
    "psi_mean": 0.25,
    "kl_mean": 0.25,
    "js_divergence": 0.2,
    "ks_statistic": 0.15,
    "wasserstein_distance": 0.15,
}


class DriftAnalyzer:
    """Анализатор дрейфа данных для изображений."""

    def __init__(
        self,
        baseline_images: List[np.ndarray],
        bins: int = 32,
        weights: Optional[Dict[str, float]] = None,
        thresholds: Optional[Dict[str, float]] = None,
    ):
        """
        Args:
            baseline_images: Эталонные изображения (baseline).
            bins: Количество бинов для гистограмм.
            weights: Веса для агрегированной метрики (по умолчанию DEFAULT_WEIGHTS).
            thresholds: Пороги для нормализации (по умолчанию DEFAULT_THRESHOLDS).
        """
        self.bins = bins
        self.baseline_images = baseline_images
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self.thresholds = thresholds or DEFAULT_THRESHOLDS.copy()
        
        # Уменьшаем baseline для расчёта метрик, чтобы не OOM на больших кадрах
        baseline_small = [self._resize_for_drift(img) for img in baseline_images]
        self.baseline_hists = [self._compute_rgb_hist(img) for img in baseline_small]
        self.baseline_features = [self._get_cnn_features(img) for img in baseline_small]
        self.baseline_brightness = np.concatenate(
            [self._compute_brightness(img) for img in baseline_small]
        )
        
        # Инициализация Page-Hinkley
        self.page_hinkley = PageHinkley(delta=0.005, threshold=50)
        
        # История метрик для мониторинга
        self.metric_history = deque(maxlen=100)
    
    def _resize_for_drift(self, image: np.ndarray) -> np.ndarray:
        """Уменьшает изображение для расчёта дрейфа (ограничение памяти при полных кадрах)."""
        h, w = image.shape[:2]
        if max(h, w) <= MAX_DRIFT_EDGE:
            return image
        scale = MAX_DRIFT_EDGE / max(h, w)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    
    def _compute_rgb_hist(self, image: np.ndarray) -> np.ndarray:
        """Вычисляет RGB гистограмму изображения"""
        if len(image.shape) == 2:
            # Grayscale
            h, _ = np.histogram(image, bins=self.bins, range=(0, 256))
            h = h / (h.sum() + 1e-8)
            return h
        
        chans = cv2.split(image)
        hist = []
        for c in chans:
            h, _ = np.histogram(c, bins=self.bins, range=(0, 256))
            h = h / (h.sum() + 1e-8)
            hist.append(h)
        return np.concatenate(hist)
    
    def _compute_brightness(self, image: np.ndarray) -> np.ndarray:
        """Вычисляет яркость изображения"""
        if len(image.shape) == 3:
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            return hsv[:, :, 2].flatten()
        else:
            return image.flatten()
    
    def _get_cnn_features(self, image: np.ndarray) -> np.ndarray:
        """Извлекает CNN признаки используя ResNet50"""
        # Используем простую CNN для извлечения признаков
        transform = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], 
                               std=[0.229, 0.224, 0.225])
        ])
        
        # Преобразуем BGR в RGB
        if len(image.shape) == 3:
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            image_rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        
        try:
            x = transform(image_rgb).unsqueeze(0)
            
            # Используем предобученный ResNet50
            # Берем все слои кроме последнего (классификатора)
            # Это дает нам признаки из слоя перед avgpool (последний слой перед классификацией)
            # Размерность признаков: 2048 (после avgpool и flatten)
            # Эти признаки содержат высокоуровневые семантические характеристики изображения
            if not hasattr(self, '_resnet'):
                try:
                    # Пробуем новый API PyTorch
                    self._resnet = models.resnet50(weights='IMAGENET1K_V2')
                except TypeError:
                    # Если новый API не работает, используем старый
                    self._resnet = models.resnet50(pretrained=True)
                self._resnet.eval()
                # [:-1] убирает последний слой (классификатор), оставляя все до avgpool
                # Это слои: conv1, bn1, relu, maxpool, layer1, layer2, layer3, layer4, avgpool
                self._feature_extractor = torch.nn.Sequential(
                    *list(self._resnet.children())[:-1]
                )
            
            with torch.no_grad():
                feat = self._feature_extractor(x).flatten().numpy()
            
            # Нормализуем
            feat = feat / (np.linalg.norm(feat) + 1e-12)
            return feat
            
        except Exception as e:
            print(f"Ошибка извлечения признаков: {e}")
            # Возвращаем нулевой вектор
            return np.zeros(2048)
    
    def _calc_psi(self, hist_baseline: np.ndarray, hist_new: np.ndarray, eps: float = 1e-8) -> float:
        """Вычисляет PSI (Population Stability Index)"""
        psi = np.sum((hist_baseline - hist_new) * np.log((hist_baseline + eps) / (hist_new + eps)))
        return psi
    
    def _kl_divergence(self, p: np.ndarray, q: np.ndarray, eps: float = 1e-9) -> float:
        """Вычисляет KL divergence"""
        p = p + eps
        q = q + eps
        return np.sum(rel_entr(p, q))

    def _jensen_shannon_divergence(self, p: np.ndarray, q: np.ndarray, eps: float = 1e-9) -> float:
        """Дивергенция Дженсена-Шеннона (симметричная, ограниченная). JSD = distance^2."""
        p = (p + eps) / (p.sum() + eps * len(p))
        q = (q + eps) / (q.sum() + eps * len(q))
        d = jensenshannon(p, q, base=2)
        return float(d * d)
    
    def analyze_drift(self, new_images: List[np.ndarray], baseline_override: Optional[List[np.ndarray]] = None) -> Dict:
        """
        Анализирует дрейф данных.

        Args:
            new_images: Список новых изображений.
            baseline_override: Если задан, сравнение идёт с ним вместо self.baseline_* (для stream-режима).
        Returns:
            Словарь с метриками дрейфа:
            {
                'psi_mean': float,  # Средний PSI
                'psi_max': float,   # Максимальный PSI
                'kl_mean': float,   # Средний KL divergence
                'kl_max': float,    # Максимальный KL divergence
                'ks_statistic': float,  # KS статистика
                'ks_pvalue': float,     # KS p-value
                'wasserstein_distance': float,  # Расстояние Вассерштейна
                'page_hinkley_alert': bool,  # Срабатывание Page-Hinkley
                'drift_detected': bool  # Общее определение дрейфа
            }
        """
        if len(new_images) == 0:
            return {
                'psi_mean': 0.0,
                'psi_max': 0.0,
                'kl_mean': 0.0,
                'kl_max': 0.0,
                'js_divergence': 0.0,
                'ks_statistic': 0.0,
                'ks_pvalue': 1.0,
                'wasserstein_distance': 0.0,
                'aggregate_score': 0.0,
                'page_hinkley_alert': False,
                'drift_detected': False
            }

        new_images_small = [self._resize_for_drift(img) for img in new_images]
        if baseline_override is not None:
            base_small = [self._resize_for_drift(img) for img in baseline_override]
            base_hists = [self._compute_rgb_hist(img) for img in base_small]
            base_features = [self._get_cnn_features(img) for img in base_small]
            base_brightness = np.concatenate([self._compute_brightness(img) for img in base_small])
        else:
            base_hists = self.baseline_hists
            base_features = self.baseline_features
            base_brightness = self.baseline_brightness

        baseline_mean_hist = np.mean(base_hists, axis=0)
        new_hists = [self._compute_rgb_hist(img) for img in new_images_small]
        new_mean_hist = np.mean(new_hists, axis=0)
        
        # Вычисляем PSI между средними гистограммами
        psi_mean = self._calc_psi(baseline_mean_hist, new_mean_hist)
        
        psi_values = []
        for b_hist in base_hists:
            for new_hist in new_hists:
                psi = self._calc_psi(b_hist, new_hist)
                psi_values.append(psi)
        psi_max = np.max(psi_values) if psi_values else 0.0

        new_brightness = np.concatenate([self._compute_brightness(img) for img in new_images_small])
        ks_stat, ks_p = ks_2samp(base_brightness, new_brightness)

        baseline_sample = base_brightness if len(base_brightness) <= 10000 else np.random.choice(base_brightness, 10000, replace=False)
        new_sample = new_brightness if len(new_brightness) <= 10000 else np.random.choice(new_brightness, 10000, replace=False)
        wasserstein_dist = wasserstein_distance(baseline_sample, new_sample)
        
        baseline_mean_feat = np.mean(base_features, axis=0)
        new_features = [self._get_cnn_features(img) for img in new_images_small]
        new_mean_feat = np.mean(new_features, axis=0)
        baseline_probs = (baseline_mean_feat + 1e-9) / (np.sum(baseline_mean_feat) + 1e-9)
        new_probs = (new_mean_feat + 1e-9) / (np.sum(new_mean_feat) + 1e-9)
        kl_mean = self._kl_divergence(baseline_probs, new_probs)
        js_divergence = self._jensen_shannon_divergence(baseline_probs, new_probs)
        
        kl_values = []
        for b_feat in base_features:
            for new_feat in new_features:
                b_probs = (b_feat + 1e-9) / (np.sum(b_feat) + 1e-9)
                n_probs = (new_feat + 1e-9) / (np.sum(new_feat) + 1e-9)
                kl = self._kl_divergence(b_probs, n_probs)
                kl_values.append(kl)
        kl_max = np.max(kl_values) if kl_values else 0.0
        
        # Page-Hinkley тест
        ph_alert = self.page_hinkley.update(kl_mean)
        
        # Агрегированная метрика: взвешенная сумма нормализованных (0..1) компонент
        psi_n = min(1.0, psi_mean / self.thresholds.get("psi_mean", 0.2))
        kl_n = min(1.0, kl_mean / self.thresholds.get("kl_mean", 1.0))
        js_n = min(1.0, js_divergence / self.thresholds.get("js_divergence", 0.3))
        ks_p_th = self.thresholds.get("ks_pvalue", 0.05)
        ks_n = min(1.0, (ks_p_th - ks_p) / ks_p_th) if ks_p < ks_p_th else 0.0
        wass_n = min(1.0, wasserstein_dist / self.thresholds.get("wasserstein_distance", 30.0))
        w = self.weights
        aggregate_score = (
            w.get("psi_mean", 0) * psi_n
            + w.get("kl_mean", 0) * kl_n
            + w.get("js_divergence", 0) * js_n
            + w.get("ks_statistic", 0) * ks_n
            + w.get("wasserstein_distance", 0) * wass_n
        )

        drift_detected = (
            psi_mean > 0.2
            or kl_mean > 1.0
            or js_divergence > 0.3
            or ks_p < 0.05
            or wasserstein_dist > 30.0
            or ph_alert
        )

        result = {
            'psi_mean': float(psi_mean),
            'psi_max': float(psi_max),
            'kl_mean': float(kl_mean),
            'kl_max': float(kl_max),
            'js_divergence': float(js_divergence),
            'ks_statistic': float(ks_stat),
            'ks_pvalue': float(ks_p),
            'wasserstein_distance': float(wasserstein_dist),
            'aggregate_score': float(aggregate_score),
            'page_hinkley_alert': ph_alert,
            'drift_detected': drift_detected
        }
        
        self.metric_history.append(result)
        return result

    def analyze_drift_stream(self, new_images: List[np.ndarray]) -> Dict:
        """
        Дрейф по скользящему окну без внешнего baseline.

        Окно = последние W секунд (в кадрах). На каждом шаге сравниваем:
        - reference = старшая половина окна (например [t-10, t-5] сек),
        - current = младшая половина (например [t-5, t] сек).
        При сдвиге на следующий кадр окно сдвигается (deque), получаем новое значение дрейфа.
        Итог: одна метрика дрейфа на каждый шаг (каждый N-й кадр), как «считают за 10 сек, сдвиг на шаг, снова 10 сек».
        """
        if len(new_images) < 2:
            return {
                'psi_mean': 0.0, 'psi_max': 0.0, 'kl_mean': 0.0, 'kl_max': 0.0,
                'js_divergence': 0.0, 'ks_statistic': 0.0, 'ks_pvalue': 1.0,
                'wasserstein_distance': 0.0, 'aggregate_score': 0.0,
                'page_hinkley_alert': False, 'drift_detected': False
            }
        mid = len(new_images) // 2
        return self.analyze_drift(new_images[mid:], baseline_override=new_images[:mid])


class PageHinkley:
    """Реализация теста Page-Hinkley для детекции дрейфа"""
    
    def __init__(self, delta: float = 0.005, threshold: float = 50):
        """
        Args:
            delta: Параметр чувствительности
            threshold: Порог срабатывания
        """
        self.mean = 0.0
        self.cum_sum = 0.0
        self.min_cum_sum = 0.0
        self.delta = delta
        self.threshold = threshold
        self.n = 0
    
    def update(self, value: float) -> bool:
        """
        Обновляет тест с новым значением
        
        Args:
            value: Новое значение метрики
            
        Returns:
            True если дрейф детектирован
        """
        self.n += 1
        self.mean = self.mean + (value - self.mean) / self.n
        self.cum_sum += (value - self.mean - self.delta)
        self.min_cum_sum = min(self.min_cum_sum, self.cum_sum)
        
        if (self.cum_sum - self.min_cum_sum) > self.threshold:
            # Сброс после детекции
            self.cum_sum = 0.0
            self.min_cum_sum = 0.0
            self.n = 0
            return True
        return False

