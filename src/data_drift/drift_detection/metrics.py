"""
Опциональный модуль метрик. Основное приложение (api.py) объявляет свои метрики Prometheus;
этот модуль можно использовать отдельно (например, в тестах), но не импортировать вместе с api.
"""
from typing import Dict, Optional
from prometheus_client import Counter, Histogram, Gauge
import time


# Prometheus метрики
drift_detections_total = Counter(
    'object_drift_detections_total',
    'Общее количество детекций дрейфа',
    ['status']  # status: 'detected' или 'no_drift'
)

drift_psi_metric = Histogram(
    'object_drift_psi',
    'PSI метрика дрейфа',
    buckets=[0.0, 0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0, float('inf')]
)

drift_kl_metric = Histogram(
    'object_drift_kl_divergence',
    'KL divergence метрика дрейфа',
    buckets=[0.0, 0.5, 1.0, 2.0, 5.0, 10.0, float('inf')]
)

drift_ks_statistic = Histogram(
    'object_drift_ks_statistic',
    'KS статистика дрейфа',
    buckets=[0.0, 0.1, 0.2, 0.3, 0.5, 1.0, float('inf')]
)

video_processing_time = Histogram(
    'object_video_processing_seconds',
    'Время обработки видео в секундах'
)

detections_count = Gauge(
    'object_detections_count',
    'Количество детекций объектов на текущем видео'
)


def record_drift_metrics(metrics: Dict, processing_time: Optional[float] = None):
    """
    Записывает метрики дрейфа в Prometheus
    
    Args:
        metrics: Словарь с метриками дрейфа
        processing_time: Время обработки в секундах (опционально)
    """
    # Записываем детекцию дрейфа
    status = 'detected' if metrics.get('drift_detected', False) else 'no_drift'
    drift_detections_total.labels(status=status).inc()
    
    # Записываем метрики
    if 'psi_mean' in metrics:
        drift_psi_metric.observe(metrics['psi_mean'])
    
    if 'kl_mean' in metrics:
        drift_kl_metric.observe(metrics['kl_mean'])
    
    if 'ks_statistic' in metrics:
        drift_ks_statistic.observe(metrics['ks_statistic'])
    
    # Записываем время обработки
    if processing_time is not None:
        video_processing_time.observe(processing_time)
    
    # Записываем количество детекций (если есть)
    if 'total_detections' in metrics:
        detections_count.set(metrics['total_detections'])


def get_metrics_endpoint():
    """
    Возвращает endpoint для Prometheus
    
    Использование:
        from prometheus_client import generate_latest
        from drift_detection.metrics import get_metrics_endpoint
        
        @app.get("/metrics")
        async def metrics():
            return Response(generate_latest(), media_type="text/plain")
    """
    from prometheus_client import generate_latest
    from fastapi import Response
    
    def metrics():
        return Response(generate_latest(), media_type="text/plain")
    
    return metrics
