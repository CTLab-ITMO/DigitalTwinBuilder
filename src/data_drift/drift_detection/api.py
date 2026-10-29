"""
FastAPI приложение для загрузки данных и отслеживания дрейфа объектов.
"""
from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import cv2
import numpy as np
import math
import os
import tempfile
import shutil
from pathlib import Path
import time
import pickle
import zipfile
import uuid
import threading
import json
from collections import deque, defaultdict
from datetime import datetime
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from drift_detector import ObjectDriftDetector
from cvat_loader import extract_images_from_archive

DATA_DIR = os.path.join(os.getcwd(), "data")
os.makedirs(DATA_DIR, exist_ok=True)
MODEL_PATH_FILE = os.path.join(DATA_DIR, "model_path.txt")
MODEL_WEIGHTS_PATH = os.path.join(DATA_DIR, "trained_model.pt")
DATASET_PATH_FILE = os.path.join(DATA_DIR, "dataset_path.txt")
DATASET_CONFIG_PATH = os.path.join(DATA_DIR, "dataset_config.yaml")
BASELINE_IMAGES_FILE = os.path.join(DATA_DIR, "baseline_images.pkl")
TRAINING_STATUS_FILE = os.path.join(DATA_DIR, "training_status.txt")
TRAINING_ERROR_FILE = os.path.join(DATA_DIR, "training_error.txt")

print(f"Директория состояния: {DATA_DIR}")
print(f"Файл модели: {MODEL_PATH_FILE}")
print(f"Файл весов модели: {MODEL_WEIGHTS_PATH}")
print(f"Файл статуса обучения: {TRAINING_STATUS_FILE}")
print(f"Файл ошибки обучения: {TRAINING_ERROR_FILE}")

app = FastAPI(
    title="Drift Detection API",
    description="API для отслеживания дрейфа данных в системе детекции объектов",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

drift_detector: Optional[ObjectDriftDetector] = None
trained_model_path: Optional[str] = None
baseline_dataset_path: Optional[str] = None
baseline_images: List[np.ndarray] = []
baseline_ready: bool = False
training_status: str = "not_started"
training_error: Optional[str] = None

_pretrained_detector: Optional[ObjectDriftDetector] = None
_pretrained_object_classes: Optional[List[str]] = None


def get_pretrained_detector(object_classes: Optional[List[str]] = None) -> ObjectDriftDetector:
    """Детектор на YOLO11l (качается при первом вызове), без SAM. object_classes — фильтр по классам COCO (person, car, ...)."""
    global _pretrained_detector, _pretrained_object_classes
    if object_classes is None:
        object_classes = []
    same = _pretrained_object_classes == object_classes if _pretrained_object_classes is not None else not object_classes
    if _pretrained_detector is not None and same:
        return _pretrained_detector
    dummy = [np.zeros((64, 64, 3), dtype=np.uint8)]
    _pretrained_detector = ObjectDriftDetector(
        baseline_images=dummy,
        yolo_model_path=None,
        allowed_class_ids=None,
        allowed_name_tokens=object_classes if object_classes else None,
        use_sam=False,
    )
    _pretrained_object_classes = object_classes[:] if object_classes else []
    return _pretrained_detector

# Метрики Prometheus
drift_detections = Counter('object_drift_detections_total', 'Общее количество детекций дрейфа')
drift_psi = Histogram('object_drift_psi', 'PSI метрика дрейфа')
drift_kl_divergence = Histogram('object_drift_kl_divergence', 'KL divergence метрика дрейфа')
drift_ks_statistic = Histogram('object_drift_ks_statistic', 'KS статистика дрейфа')
drift_ks_pvalue = Histogram('object_drift_ks_pvalue', 'KS p-value (дрейф при < 0.05)')
drift_wasserstein = Histogram('object_drift_wasserstein', 'Расстояние Вассерштейна по яркости')
drift_js_divergence = Histogram('object_drift_js_divergence', 'Дивергенция Дженсена-Шеннона')
drift_aggregate_score = Histogram('object_drift_aggregate_score', 'Агрегированная метрика дрейфа (взвешенная)')
# Варианты взвешенной суммы с разными весами для компонент (PSI, KL, KS, JS, Wasserstein)
aggregate_weighted_default_gauge = Gauge('object_drift_aggregate_weighted_default', 'Агрегат: веса по умолчанию (PSI/KL 0.25, JS 0.2, KS/Wass 0.15)')
aggregate_weighted_wass_gauge = Gauge('object_drift_aggregate_weighted_wass', 'Агрегат: акцент на Wasserstein (0.4)')
aggregate_weighted_kl_psi_gauge = Gauge('object_drift_aggregate_weighted_kl_psi', 'Агрегат: акцент на KL+PSI (0.35+0.35)')
aggregate_weighted_max_gauge = Gauge('object_drift_aggregate_weighted_max', 'Агрегат: max из нормализованных компонент')
aggregate_v1_gauge = Gauge('object_drift_aggregate_v1', 'Агрегат v1 (исходный)')
aggregate_v2_gauge = Gauge('object_drift_aggregate_v2', 'Агрегат v2: 0.85*agg + 0.15*(1-mean_conf)')
aggregate_v3_gauge = Gauge('object_drift_aggregate_v3', 'Агрегат v3: agg * (2 - mean_conf), рост при низкой уверенности')
aggregate_v4_gauge = Gauge('object_drift_aggregate_v4', 'Агрегат v4: 0.6*agg + 0.4*(1-conf)')
aggregate_v5_gauge = Gauge('object_drift_aggregate_v5', 'Агрегат v5: agg / (0.5+0.5*conf), рост при низкой уверенности')
aggregate_v5_ema_gauge = Gauge('object_drift_aggregate_v5_ema', 'Агрегат v5 после EMA-сглаживания (alpha задаётся в /process_video_pretrained)')
# Нормализованные компоненты agg (0..1) — для дашборда разложения v5
component_psi_n_gauge = Gauge('object_drift_component_psi_n', 'Компонента PSI норм.: min(1, PSI/0.2)')
component_kl_n_gauge = Gauge('object_drift_component_kl_n', 'Компонента KL норм.: min(1, KL/1.0)')
component_js_n_gauge = Gauge('object_drift_component_js_n', 'Компонента JS норм.: min(1, JS/0.3)')
component_ks_n_gauge = Gauge('object_drift_component_ks_n', 'Компонента KS норм.: (0.05-p)/0.05 при p<0.05, иначе 0')
component_wass_n_gauge = Gauge('object_drift_component_wass_n', 'Компонента Wasserstein норм.: min(1, W/30)')
v5_area_window_gauge = Gauge(
    'object_drift_v5_area_cumulative',
    'Площадь под v5 за последние drift_window_sec секунд (∫v5·dt, скользящее окно)',
)
processing_gauge = Gauge('object_drift_processing', '1 = идёт обработка видео/архива, 0 = нет активных задач; линии на графиках только при 1')
video_processing_seconds = Histogram('object_video_processing_seconds', 'Время обработки видео в секундах')
detections_count = Gauge('object_detections_count', 'Количество детекций объектов на текущем видео')
detections_by_class_gauge = Gauge('object_detections_by_class', 'Количество детекций по классам (временной ряд)', ['class'])
confidence_by_class_gauge = Gauge('object_detection_confidence_mean', 'Средняя уверенность модели по классам на текущем кадре/фото', ['class'])
video_seconds_gauge = Gauge('object_drift_video_seconds', 'Текущая секунда видео (одна серия: при запуске нового видео график по сути начинается заново)')
drift_alert_gauge = Gauge('object_drift_alert', 'Детекция дрейфа (1=да, 0=нет)')
ph_alert_gauge = Gauge('object_drift_ph_alert', 'Page-Hinkley алерт (1=да, 0=нет)')
ground_truth_drift_gauge = Gauge('object_drift_ground_truth', 'Отметка «реального» дрейфа из загруженного файла сегментов (1=дрейф в этом сегменте, 0=нет)')
segment_index_gauge = Gauge('object_drift_segment_index', 'Номер сегмента из файла границ (1, 2, 3, …); скачки на графике = границы смены')
detection_rate_diff_pct_gauge = Gauge('object_drift_detection_rate_diff_pct', 'Отличие детекций на кадр (по классам) в % от предыдущих запусков с тем же video_id за тот же час')

# Оценка того, насколько drift-метрика (v5) коррелирует с границами сегментов (segments_file).
# Эти gauge обновляются во время обработки (приближённая оценка по накопленным точкам)
# и фиксируются финальным значением в конце обработки видео.
eval_pr_auc_gauge = Gauge('object_drift_eval_pr_auc', 'PR-AUC для v5 vs метка "в окне около границы сегмента" (чем выше, тем лучше)')
eval_tpr_at_fpr_gauge = Gauge('object_drift_eval_tpr_at_fpr', 'TPR@FPR для v5 (порог выбирается по отрицательным точкам на целевом FPR)')
eval_delta_mean_gauge = Gauge('object_drift_eval_delta_mean', 'Δmean = mean(v2|near_boundary) - mean(v2|not_near_boundary)')
eval_event_recall_gauge = Gauge('object_drift_eval_event_recall', 'Event recall: доля границ сегментов, где v2 превышал порог в окне ±Δ')
eval_points_total_gauge = Gauge('object_drift_eval_points_total', 'Сколько точек использовано для оценки (v2 и метка)')
eval_points_pos_gauge = Gauge('object_drift_eval_points_pos', 'Сколько "позитивных" точек (в окне ±Δ около границ)')

# Итоговые метрики качества для разных агрегатов (выставляются ПОСЛЕ завершения обработки видео).
# Лейбл agg: какая формула агрегата оценивалась.
eval_pr_auc_by_agg_gauge = Gauge('object_drift_eval_pr_auc_by_agg', 'Final PR-AUC (v2 vs метка границ), по агрегатам', ['agg'])
eval_tpr_at_fpr_by_agg_gauge = Gauge('object_drift_eval_tpr_at_fpr_by_agg', 'Final TPR@FPR, по агрегатам', ['agg'])
eval_delta_mean_by_agg_gauge = Gauge('object_drift_eval_delta_mean_by_agg', 'Final Δmean, по агрегатам', ['agg'])
eval_event_recall_by_agg_gauge = Gauge('object_drift_eval_event_recall_by_agg', 'Final event recall, по агрегатам', ['agg'])


def _is_near_any_boundary_post_only(boundaries: Optional[List[float]], t: float, delta: float) -> bool:
    """True если t в пределах [boundary, boundary+delta] для какой-то границы."""
    if not boundaries or delta is None or delta <= 0:
        return False
    for b in boundaries:
        try:
            bb = float(b)
        except Exception:
            continue
        if bb == 0.0:
            continue
        if bb <= float(t) <= (bb + float(delta)):
            return True
    return False


def _boundary_label(boundaries: Optional[List[float]], t: float, delta: float, mode: str) -> int:
    """
    mode:
      - 'symmetric': |t - boundary| <= delta
      - 'post_only': boundary <= t <= boundary + delta
    """
    m = (mode or "symmetric").strip().lower()
    if m == "post_only":
        return 1 if _is_near_any_boundary_post_only(boundaries, t, delta) else 0
    return 1 if _is_near_any_boundary_symmetric(boundaries, t, delta) else 0


def _is_near_any_boundary_symmetric(boundaries: Optional[List[float]], t: float, delta: float) -> bool:
    """True если t в пределах ±delta от какой-то границы (обычно boundaries из segments_file)."""
    if not boundaries or delta is None or delta <= 0:
        return False
    # Игнорируем нулевую границу, если она есть (часто это просто "старт видео").
    for b in boundaries:
        try:
            bb = float(b)
        except Exception:
            continue
        if bb == 0.0:
            continue
        if abs(float(t) - bb) <= float(delta):
            return True
    return False


def _average_precision(y_true: List[int], y_score: List[float]) -> Optional[float]:
    """
    Average Precision (PR-AUC) без sklearn.
    Возвращает None, если нет позитивов или список пуст.
    """
    n = len(y_true)
    if n == 0:
        return None
    pos_total = sum(1 for y in y_true if y == 1)
    if pos_total == 0:
        return None
    order = sorted(range(n), key=lambda i: float(y_score[i]), reverse=True)
    tp = 0
    fp = 0
    ap_sum = 0.0
    for idx in order:
        if y_true[idx] == 1:
            tp += 1
            ap_sum += tp / max(1, (tp + fp))
        else:
            fp += 1
    return ap_sum / pos_total


def _threshold_for_fpr(neg_scores: List[float], fpr_target: float) -> Optional[float]:
    """
    Порог по отрицательным примерам так, чтобы FP доля была примерно <= fpr_target.
    """
    if not neg_scores:
        return None
    n = len(neg_scores)
    fpr = float(fpr_target)
    if fpr <= 0.0:
        return max(neg_scores) + 1e-12
    if fpr >= 1.0:
        return min(neg_scores) - 1e-12
    allowed_fp = int(math.floor(fpr * n))
    s = sorted((float(x) for x in neg_scores), reverse=True)
    if allowed_fp <= 0:
        return s[0] + 1e-12
    # k-й по величине (ties могут дать небольшое превышение — допустимо для мониторинга)
    return s[min(allowed_fp - 1, n - 1)]


def _compute_eval_metrics(
    times: List[float],
    scores: List[float],
    labels: List[int],
    boundaries: Optional[List[float]],
    delta: float,
    fpr_target: float,
) -> Dict[str, Optional[float]]:
    """
    4 метрики качества:
    - pr_auc
    - tpr_at_fpr
    - delta_mean
    - event_recall
    """
    n = len(scores)
    if n == 0 or len(labels) != n or len(times) != n:
        return {"pr_auc": None, "tpr_at_fpr": None, "delta_mean": None, "event_recall": None, "thr": None}

    pos_scores = [float(scores[i]) for i in range(n) if labels[i] == 1]
    neg_scores = [float(scores[i]) for i in range(n) if labels[i] == 0]

    pr_auc = _average_precision(labels, [float(s) for s in scores])

    thr = _threshold_for_fpr(neg_scores, fpr_target)
    tpr_at_fpr = None
    if thr is not None and pos_scores:
        tpr_at_fpr = sum(1 for s in pos_scores if s >= thr) / max(1, len(pos_scores))

    delta_mean = None
    if pos_scores and neg_scores:
        delta_mean = (sum(pos_scores) / len(pos_scores)) - (sum(neg_scores) / len(neg_scores))

    event_recall = None
    if boundaries and thr is not None and delta is not None and delta > 0:
        boundary_times = []
        for b in boundaries:
            try:
                bb = float(b)
            except Exception:
                continue
            if bb != 0.0:
                boundary_times.append(bb)
        if boundary_times:
            detected = 0
            for b in boundary_times:
                lo = b - float(delta)
                hi = b + float(delta)
                ok = False
                for t, s in zip(times, scores):
                    if lo <= float(t) <= hi and float(s) >= thr:
                        ok = True
                        break
                if ok:
                    detected += 1
            event_recall = detected / max(1, len(boundary_times))

    return {"pr_auc": pr_auc, "tpr_at_fpr": tpr_at_fpr, "delta_mean": delta_mean, "event_recall": event_recall, "thr": thr}

DETECTION_COUNTS_DIR = os.path.join(DATA_DIR, "detection_counts")
os.makedirs(DETECTION_COUNTS_DIR, exist_ok=True)

def _detection_counts_path(video_id: int) -> str:
    return os.path.join(DETECTION_COUNTS_DIR, f"{video_id}.json")

def load_detection_counts(video_id: int) -> dict:
    path = _detection_counts_path(video_id)
    if not os.path.exists(path):
        return {"slots": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"slots": {}}

def save_detection_counts(video_id: int, data: dict):
    path = _detection_counts_path(video_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=0)


def _flush_detection_counts_to_hour(
    prev_counts: dict,
    hour_str: str,
    run_frames: int,
    run_detections: dict,
    video_id: int,
):
    """Записать накопленные за текущий час run_detections/run_frames в prev_counts и сохранить на диск."""
    if run_frames <= 0:
        return
    if "slots" not in prev_counts:
        prev_counts["slots"] = {}
    if hour_str not in prev_counts["slots"]:
        prev_counts["slots"][hour_str] = {}
    for c, cnt in run_detections.items():
        if c not in prev_counts["slots"][hour_str]:
            prev_counts["slots"][hour_str][c] = {"detections": 0, "frames": 0}
        prev_counts["slots"][hour_str][c]["detections"] += cnt
        prev_counts["slots"][hour_str][c]["frames"] += run_frames
    for c in set(prev_counts["slots"][hour_str].keys()) - set(run_detections.keys()):
        prev_counts["slots"][hour_str][c]["frames"] += run_frames
    save_detection_counts(video_id, prev_counts)


VIDEO_JOBS: Dict[str, Dict[str, Any]] = {}
VIDEO_JOBS_LOCK = threading.Lock()
PROCESSED_FRAMES_DIR = os.path.join(DATA_DIR, "processed_frames")
os.makedirs(PROCESSED_FRAMES_DIR, exist_ok=True)
DRIFT_FRAME_MAX_EDGE = 320

class TrainingResponse(BaseModel):
    message: str
    status: str
    epochs: Optional[int] = None
    model_path: Optional[str] = None


class VideoJobResponse(BaseModel):
    job_id: str
    message: str

def extract_archive_to_temp_dir(archive_path: str):
    """Распаковывает ZIP во временную директорию, возвращает (путь_к_директории, отсортированный список путей к изображениям)."""
    temp_dir = tempfile.mkdtemp()
    with zipfile.ZipFile(archive_path, 'r') as z:
        z.extractall(temp_dir)
    exts = ('.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG')
    paths = []
    for root, _, files in os.walk(temp_dir):
        for f in files:
            if f.endswith(exts):
                paths.append(os.path.join(root, f))
    paths.sort()
    return temp_dir, paths


def parse_segments_file_video(content: str) -> Optional[List[float]]:
    """
    Парсит файл границ для видео. Формат: UTF-8, по одной секунде в строке (границы смены).
    Пример: 0\\n120.5\\n300 — три сегмента [0, 120.5), [120.5, 300), [300, конец].
    """
    out = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.replace(',', ' ').split()
        if not parts:
            continue
        try:
            out.append(float(parts[0]))
        except (ValueError, IndexError):
            continue
    if not out:
        return None
    out.sort()
    return out


def parse_segments_file_archive(content: str) -> Optional[List[str]]:
    """
    Парсит файл границ для архива. Формат: UTF-8, по одному имени файла (без расширения) в строке.
    Порядок строк = порядок сегментов; имя — первое фото сегмента.
    """
    out = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name = line.split('\t')[0].strip().lower()
        if name:
            out.append(name)
    return out if out else None


def get_segment_index_for_video_second(boundaries: List[float], current_second: float) -> int:
    """Номер сегмента для current_second: последняя граница <= current_second (индекс в списке)."""
    if not boundaries:
        return 0
    idx = 0
    for i, b in enumerate(boundaries):
        if current_second >= b:
            idx = i
    return idx


def validate_and_save_archive(archive: UploadFile) -> str:
    """Валидирует и сохраняет ZIP архив"""
    if not archive.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail="Файл должен быть в формате ZIP")

    temp_path = tempfile.mktemp(suffix='.zip')
    try:
        with open(temp_path, 'wb') as f:
            content = archive.file.read()
            f.write(content)

        with zipfile.ZipFile(temp_path, 'r') as zip_ref:
            zip_ref.testzip()

        return temp_path
    except Exception as e:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(status_code=400, detail=f"Невалидный ZIP архив: {str(e)}")

def validate_and_save_video(video: UploadFile) -> str:
    """Валидирует и сохраняет видеофайл"""
    if not video.filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
        raise HTTPException(status_code=400, detail="Видео должно быть в формате MP4/AVI/MOV/MKV")

    temp_path = tempfile.mktemp(suffix=Path(video.filename).suffix)
    try:
        with open(temp_path, 'wb') as f:
            content = video.file.read()
            f.write(content)
        return temp_path
    except Exception as e:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(status_code=400, detail=f"Не удалось сохранить видео: {str(e)}")


def apply_distortion(
    frame: np.ndarray,
    brightness: float = 0.0,
    contrast: float = 1.0,
    noise_std: float = 0.0,
    hue_shift: int = 0,
    saturation_scale: float = 1.0
) -> np.ndarray:
    """Применяет искажения к кадру (яркость, контраст, шум, цвет)."""
    distorted = frame.astype(np.float32)

    if contrast != 1.0 or brightness != 0.0:
        distorted = distorted * contrast + brightness

    if noise_std > 0.0:
        noise = np.random.normal(0, noise_std, distorted.shape).astype(np.float32)
        distorted = distorted + noise

    distorted = np.clip(distorted, 0, 255).astype(np.uint8)

    if hue_shift != 0 or saturation_scale != 1.0:
        hsv = cv2.cvtColor(distorted, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 0] = (hsv[..., 0] + hue_shift) % 180
        hsv[..., 1] = np.clip(hsv[..., 1] * saturation_scale, 0, 255)
        distorted = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    return distorted


BRIGHT_COLORS_BGR = [
    (0, 255, 0),    # зелёный
    (0, 0, 255),    # красный
    (255, 0, 0),    # синий
    (0, 255, 255),  # жёлтый
    (255, 0, 255),  # magenta
    (255, 165, 0),  # оранжевый (BGR)
    (0, 191, 255),  # deep sky blue
    (203, 192, 255), # lavender
]


def draw_detections(
    frame: np.ndarray,
    detections: List[dict],
    class_colors: Optional[Dict[str, tuple]] = None,
) -> np.ndarray:
    """
    Отрисовывает боксы детекций на кадре.
    class_colors: словарь class_name -> (B, G, R); если None — все зелёные.
    """
    output = frame.copy()
    for det in detections:
        x1, y1, x2, y2 = det['bbox']
        conf = det.get('confidence', 0.0)
        class_name = det.get('class_name', 'object')
        label = f"{class_name} {conf:.2f}"
        color = (0, 255, 0)
        if class_colors and class_name in class_colors:
            color = class_colors[class_name]
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            output,
            label,
            (x1, max(0, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )
    return output


def _get_or_assign_class_colors(detections: List[dict], class_colors: Dict[str, tuple]) -> None:
    """Дополняет class_colors новыми классами из detections (цвета из BRIGHT_COLORS_BGR)."""
    for det in detections:
        name = det.get('class_name', 'object')
        if name not in class_colors:
            class_colors[name] = BRIGHT_COLORS_BGR[len(class_colors) % len(BRIGHT_COLORS_BGR)]

def _default_component_flags() -> Dict[str, bool]:
    return {"psi": True, "kl": True, "js": True, "ks": True, "wass": True}


# Базовые веса агрегата (сумма = 1). При отключении метрик веса перераспределяются пропорционально.
DEFAULT_AGG_WEIGHTS: Dict[str, float] = {
    "psi": 0.25,
    "kl": 0.25,
    "js": 0.2,
    "ks": 0.15,
    "wass": 0.15,
}
_COMPONENT_NORM_KEYS = {
    "psi": "psi_n",
    "kl": "kl_n",
    "js": "js_n",
    "ks": "ks_n",
    "wass": "wass_n",
}


def _normalize_drift_components(metrics_dict: dict) -> Optional[Dict[str, float]]:
    """Нормализация PSI/KL/JS/KS/Wass в [0,1] — те же формулы, что для agg и v5."""
    _psi = metrics_dict.get('psi') or metrics_dict.get('psi_mean')
    _kl = metrics_dict.get('kl_divergence') or metrics_dict.get('kl_mean')
    _ks_p = metrics_dict.get('ks_pvalue')
    _js = metrics_dict.get('js_divergence')
    _wass = metrics_dict.get('wasserstein_distance')
    if _psi is None or _kl is None or _ks_p is None or _js is None or _wass is None:
        return None
    return {
        "psi_n": min(1.0, float(_psi) / 0.2),
        "kl_n": min(1.0, float(_kl) / 1.0),
        "js_n": min(1.0, float(_js) / 0.3),
        "ks_n": min(1.0, (0.05 - float(_ks_p)) / 0.05) if float(_ks_p) < 0.05 else 0.0,
        "wass_n": min(1.0, float(_wass) / 30.0),
    }


def _compute_weighted_sum(
    norm: Dict[str, float],
    component_flags: Dict[str, bool],
    weights: Dict[str, float],
) -> float:
    """Взвешенная сумма: веса включённых метрик перенормируются на 1 (пропорции сохраняются)."""
    weighted = 0.0
    weight_sum = 0.0
    for key, w in weights.items():
        if not component_flags.get(key, True):
            continue
        weighted += float(w) * float(norm[_COMPONENT_NORM_KEYS[key]])
        weight_sum += float(w)
    if weight_sum <= 0:
        return 0.0
    return weighted / weight_sum


def _compute_agg_base(norm: Dict[str, float], component_flags: Dict[str, bool]) -> float:
    return _compute_weighted_sum(norm, component_flags, DEFAULT_AGG_WEIGHTS)


def _weighted_variant(norm: Dict[str, float], component_flags: Dict[str, bool], coeffs: Dict[str, float]) -> float:
    return _compute_weighted_sum(norm, component_flags, coeffs)


def _publish_normalized_component_gauges(norm: Dict[str, float]) -> None:
    try:
        component_psi_n_gauge.set(norm["psi_n"])
        component_kl_n_gauge.set(norm["kl_n"])
        component_js_n_gauge.set(norm["js_n"])
        component_ks_n_gauge.set(norm["ks_n"])
        component_wass_n_gauge.set(norm["wass_n"])
    except Exception:
        pass


def _update_v5_area_window(
    job_id: Optional[str],
    video_second: Optional[float],
    v5: float,
    window_sec: float,
) -> None:
    """Площадь под v5 только за последние window_sec секунд видео (не с начала ролика)."""
    if job_id is None or video_second is None or window_sec is None or float(window_sec) <= 0:
        return
    t = float(video_second)
    v = float(v5)
    w = float(window_sec)
    with VIDEO_JOBS_LOCK:
        job = VIDEO_JOBS.get(job_id)
        if not job:
            return
        pts: List[List[float]] = job.setdefault("v5_area_points", [])
        pts.append([t, v])
        cutoff = t - w
        pts[:] = [p for p in pts if p[0] >= cutoff]
        area = 0.0
        for i in range(1, len(pts)):
            t0, v0 = pts[i - 1]
            t1, v1 = pts[i]
            dt = t1 - t0
            if dt > 0:
                area += (v0 + v1) * 0.5 * dt
    try:
        v5_area_window_gauge.set(area)
    except Exception:
        pass


def record_drift_metrics(
    metrics_dict: dict,
    processing_time: float,
    job_id: Optional[str] = None,
    video_second: Optional[float] = None,
    detections_by_class: Optional[Dict[str, int]] = None,
    confidence_by_class: Optional[Dict[str, float]] = None,
    ground_truth_drift: Optional[int] = None,
    segment_index: Optional[int] = None,
    detection_rate_diff_pct: Optional[float] = None,
    component_flags: Optional[Dict[str, bool]] = None,
    drift_window_sec: Optional[float] = None,
):
    try:
        if video_second is not None:
            video_seconds_gauge.set(video_second)
        if detections_by_class is not None:
            for class_name, count in detections_by_class.items():
                detections_by_class_gauge.labels(**{"class": class_name}).set(int(count))
        if confidence_by_class is not None:
            for class_name, conf in confidence_by_class.items():
                confidence_by_class_gauge.labels(**{"class": class_name}).set(float(conf))
        if ground_truth_drift is not None:
            ground_truth_drift_gauge.set(int(ground_truth_drift))
        elif segment_index is not None:
            ground_truth_drift_gauge.set(int(segment_index) + 1)
        else:
            ground_truth_drift_gauge.set(0)
        if segment_index is not None:
            segment_index_gauge.set(int(segment_index) + 1)
        if detection_rate_diff_pct is not None:
            detection_rate_diff_pct_gauge.set(float(detection_rate_diff_pct))
        # drift_detected ожидается как булев флаг
        if metrics_dict.get('drift_detected'):
            drift_detections.inc()
            drift_alert_gauge.set(1)
        else:
            drift_alert_gauge.set(0)
        ph_alert_gauge.set(1 if metrics_dict.get('page_hinkley_alert') else 0)

        psi_value = metrics_dict.get('psi')
        if psi_value is None:
            psi_value = metrics_dict.get('psi_mean')
        if psi_value is not None:
            drift_psi.observe(float(psi_value))

        kl_value = metrics_dict.get('kl_divergence')
        if kl_value is None:
            kl_value = metrics_dict.get('kl_mean')
        if kl_value is not None:
            drift_kl_divergence.observe(float(kl_value))

        ks_value = metrics_dict.get('ks_statistic')
        if ks_value is not None:
            drift_ks_statistic.observe(float(ks_value))
        ks_pval = metrics_dict.get('ks_pvalue')
        if ks_pval is not None:
            drift_ks_pvalue.observe(float(ks_pval))

        w_value = metrics_dict.get('wasserstein_distance')
        if w_value is not None:
            drift_wasserstein.observe(float(w_value))

        js_value = metrics_dict.get('js_divergence')
        if js_value is not None:
            drift_js_divergence.observe(float(js_value))
        flags = component_flags or _default_component_flags()
        norm = _normalize_drift_components(metrics_dict)
        agg_value = None
        if norm is not None:
            agg_value = _compute_agg_base(norm, flags)
            _publish_normalized_component_gauges(norm)
            w_default = _compute_agg_base(norm, flags)
            w_wass = _weighted_variant(norm, flags, {"psi": 0.1, "kl": 0.15, "js": 0.15, "ks": 0.2, "wass": 0.4})
            w_kl_psi = _weighted_variant(norm, flags, {"psi": 0.35, "kl": 0.35, "js": 0.1, "ks": 0.1, "wass": 0.1})
            enabled_vals = [
                norm["psi_n"] if flags.get("psi", True) else None,
                norm["kl_n"] if flags.get("kl", True) else None,
                norm["js_n"] if flags.get("js", True) else None,
                norm["ks_n"] if flags.get("ks", True) else None,
                norm["wass_n"] if flags.get("wass", True) else None,
            ]
            w_max = max(v for v in enabled_vals if v is not None) if any(v is not None for v in enabled_vals) else 0.0
            try:
                aggregate_weighted_default_gauge.set(w_default)
                aggregate_weighted_wass_gauge.set(w_wass)
                aggregate_weighted_kl_psi_gauge.set(w_kl_psi)
                aggregate_weighted_max_gauge.set(w_max)
            except Exception:
                pass
        elif metrics_dict.get('aggregate_score') is not None:
            agg_value = float(metrics_dict.get('aggregate_score'))
        if agg_value is not None:
            drift_aggregate_score.observe(float(agg_value))
        v5_value = None
        if agg_value is not None and confidence_by_class is not None and len(confidence_by_class) > 0:
            mean_conf = sum(confidence_by_class.values()) / len(confidence_by_class)
            agg = float(agg_value)
            aggregate_v1_gauge.set(agg)
            aggregate_v2_gauge.set(0.85 * agg + 0.15 * (1.0 - mean_conf))
            aggregate_v3_gauge.set(min(1.0, agg * (2.0 - mean_conf)))
            aggregate_v4_gauge.set(0.6 * agg + 0.4 * (1.0 - mean_conf))
            v5_value = min(1.0, agg / (0.5 + 0.5 * mean_conf))
            aggregate_v5_gauge.set(v5_value)
            _update_v5_area_window(job_id, video_second, v5_value, drift_window_sec or 10.0)

        if processing_time is not None:
            video_processing_seconds.observe(float(processing_time))

        detections_count.set(int(metrics_dict.get('total_detections', 0)))
    except Exception as e:
        print(f"Ошибка записи метрик: {e}")


def convert_numpy_types(obj):
    if isinstance(obj, dict):
        return {k: convert_numpy_types(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    if hasattr(obj, 'item'):
        return obj.item()
    return obj


def _update_processing_gauge():
    """Выставить object_drift_processing=1 если есть хотя бы один running job, иначе 0."""
    with VIDEO_JOBS_LOCK:
        any_running = any(j.get("status") == "running" for j in VIDEO_JOBS.values())
    try:
        processing_gauge.set(1 if any_running else 0)
    except Exception:
        pass


def init_video_job(job_id: str, output_dir: str):
    with VIDEO_JOBS_LOCK:
        VIDEO_JOBS[job_id] = {
            "status": "running",
            "message": "Обработка видео запущена",
            "output_dir": output_dir,
            "processed_frames": 0,
            "total_frames": None,
            "metrics_history": [],
            "last_metrics": None,
            "last_detection_second": None,
            "started_at": time.time(),
            "finished_at": None,
            "error": None,
            "v5_area_points": [],
            "component_flags": _default_component_flags(),
        }
    try:
        v5_area_window_gauge.set(0.0)
    except Exception:
        pass
    _update_processing_gauge()


def update_video_job(job_id: str, **kwargs):
    with VIDEO_JOBS_LOCK:
        if job_id in VIDEO_JOBS:
            VIDEO_JOBS[job_id].update(kwargs)
    if kwargs.get("status") in ("completed", "error"):
        _update_processing_gauge()


def get_video_job(job_id: str) -> Optional[Dict[str, Any]]:
    with VIDEO_JOBS_LOCK:
        return VIDEO_JOBS.get(job_id)


def process_video_job(
    job_id: str,
    video_path: str,
    loop_video: bool,
    loop_count: int,
    frame_stride: int,
    drift_window_frames: int,
    drift_window_sec: Optional[float],
    only_frames_with_detections: bool,
    distortion_mode: str,
    brightness: float,
    contrast: float,
    noise_std: float,
    hue_shift: int,
    saturation_scale: float,
    segment_duration_sec: float,
    max_duration_sec: Optional[float],
):
    output_dir = os.path.join(PROCESSED_FRAMES_DIR, job_id)
    os.makedirs(output_dir, exist_ok=True)
    init_video_job(job_id, output_dir)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        update_video_job(job_id, status="error", error="Не удалось открыть видео")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    update_video_job(job_id, total_frames=total_frames)
    if drift_window_sec is not None and drift_window_sec > 0:
        drift_window_frames = max(2, int(drift_window_sec * fps / max(1, frame_stride)))

    stages = [
        {"name": "original", "brightness": 0.0, "contrast": 1.0, "noise_std": 0.0, "hue_shift": 0, "saturation_scale": 1.0},
        {"name": "brightness", "brightness": brightness, "contrast": 1.0, "noise_std": 0.0, "hue_shift": 0, "saturation_scale": 1.0},
        {"name": "contrast", "brightness": 0.0, "contrast": contrast, "noise_std": 0.0, "hue_shift": 0, "saturation_scale": 1.0},
        {"name": "noise", "brightness": 0.0, "contrast": 1.0, "noise_std": noise_std, "hue_shift": 0, "saturation_scale": 1.0},
        {"name": "color", "brightness": 0.0, "contrast": 1.0, "noise_std": 0.0, "hue_shift": hue_shift, "saturation_scale": saturation_scale},
    ]

    processed_frames = 0
    global_frame_index = 0
    loops_done = 0
    start_time = time.time()
    last_detection_second = None
    frame_window = deque(maxlen=drift_window_frames)
    class_colors = {}

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                loops_done += 1
                if not loop_video or (loop_count > 0 and loops_done >= loop_count):
                    break
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            global_frame_index += 1
            current_second = global_frame_index / fps
            if max_duration_sec is not None and current_second >= max_duration_sec:
                break

            if frame_stride > 1 and (global_frame_index % frame_stride != 0):
                continue

            if distortion_mode == "uniform":
                processed_frame = apply_distortion(
                    frame,
                    brightness=brightness,
                    contrast=contrast,
                    noise_std=noise_std,
                    hue_shift=hue_shift,
                    saturation_scale=saturation_scale,
                )
                stage_name = "uniform"
            elif distortion_mode == "staged":
                stage_index = int(current_second / max(segment_duration_sec, 0.1)) % len(stages)
                stage = stages[stage_index]
                processed_frame = apply_distortion(
                    frame,
                    brightness=stage["brightness"],
                    contrast=stage["contrast"],
                    noise_std=stage["noise_std"],
                    hue_shift=stage["hue_shift"],
                    saturation_scale=stage["saturation_scale"],
                )
                stage_name = stage["name"]
            else:
                processed_frame = frame
                stage_name = "original"

            result = drift_detector.process_frame(processed_frame)
            detections = result['detections']
            object_images = result['object_images']

            # В окно кладём уменьшенную копию кадра для дрейфа (экономия памяти, без OOM)
            h, w = processed_frame.shape[:2]
            if max(h, w) > DRIFT_FRAME_MAX_EDGE:
                scale = DRIFT_FRAME_MAX_EDGE / max(h, w)
                small_frame = cv2.resize(
                    processed_frame,
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    interpolation=cv2.INTER_AREA,
                )
            else:
                small_frame = processed_frame.copy()
            if not only_frames_with_detections or len(detections) > 0:
                frame_window.append(small_frame)
            drift_metrics_raw = None
            if len(frame_window) > 0:
                try:
                    drift_metrics_raw = drift_detector.analyzer.analyze_drift(list(frame_window))
                except Exception as e:
                    print(f"Ошибка расчёта метрик дрейфа: {e}")
                    drift_metrics_raw = None

            drift_metrics = convert_numpy_types(drift_metrics_raw or {})

            if detections:
                last_detection_second = current_second
            _get_or_assign_class_colors(detections, class_colors)
            overlay = draw_detections(processed_frame, detections, class_colors)
            frame_filename = os.path.join(output_dir, f"frame_{processed_frames:06d}.jpg")
            cv2.imwrite(frame_filename, overlay)

            processed_frames += 1
            metrics_entry = {
                "frame_index": global_frame_index,
                "second": current_second,
                "processed_frames": processed_frames,
                "detections_count": len(detections),
                "drift_metrics": drift_metrics,
                "distortion_stage": stage_name,
            }

            with VIDEO_JOBS_LOCK:
                job = VIDEO_JOBS.get(job_id)
                if job is not None:
                    job["metrics_history"].append(metrics_entry)
                    job["last_metrics"] = metrics_entry
                    job["processed_frames"] = processed_frames
                    job["last_detection_second"] = last_detection_second

            if drift_metrics:
                metrics_payload = drift_metrics.copy()
                metrics_payload["total_detections"] = len(detections)
                record_drift_metrics(
                    metrics_payload,
                    time.time() - start_time,
                    job_id=job_id,
                    video_second=current_second,
                )

    except Exception as e:
        update_video_job(job_id, status="error", error=str(e))
        return
    finally:
        cap.release()
        if os.path.exists(video_path):
            os.unlink(video_path)

    update_video_job(job_id, status="completed", message="Обработка видео завершена", finished_at=time.time())


def process_video_job_pretrained(
    job_id: str,
    video_path: str,
    object_classes: List[str],
    frame_stride: int,
    drift_window_sec: float,
    only_frames_with_detections: bool,
    loop_video: bool,
    loop_count: int,
    max_duration_sec: Optional[float],
    boundaries: Optional[List[float]] = None,
    video_id: Optional[int] = None,
    eval_transition_window_sec: Optional[float] = None,
    eval_fpr_target: float = 0.01,
    eval_update_every_n: int = 25,
    eval_label_mode: str = "symmetric",
    ema_alpha: Optional[float] = 0.2,
    component_use_psi: bool = True,
    component_use_kl: bool = True,
    component_use_js: bool = True,
    component_use_ks: bool = True,
    component_use_wass: bool = True,
):
    """
    Обработка видео предобученной YOLO11l без baseline.
    video_id: при указании детекции по классам накапливаются по часам (текущий час стенного времени при обработке кадра; при переходе на следующий час данные сбрасываются в слот предыдущего часа); метрика % отличия от прошлых запусков за тот же час.
    Дрейф: скользящее окно W сек, на каждом шаге сравниваем старшую половину окна с младшей.
    Кадры с разметкой сохраняются в output_dir, скачать: GET /video_jobs/{job_id}/download.
    """
    output_dir = os.path.join(PROCESSED_FRAMES_DIR, job_id)
    os.makedirs(output_dir, exist_ok=True)
    init_video_job(job_id, output_dir)
    component_flags = {
        "psi": bool(component_use_psi),
        "kl": bool(component_use_kl),
        "js": bool(component_use_js),
        "ks": bool(component_use_ks),
        "wass": bool(component_use_wass),
    }
    with VIDEO_JOBS_LOCK:
        if job_id in VIDEO_JOBS:
            VIDEO_JOBS[job_id]["component_flags"] = component_flags

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        update_video_job(job_id, status="error", error="Не удалось открыть видео")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    update_video_job(job_id, total_frames=total_frames)

    # Окно в кадрах: из секунд и frame_stride
    frames_per_window = max(2, int(drift_window_sec * fps / max(1, frame_stride)))
    frame_window = deque(maxlen=frames_per_window)

    det = get_pretrained_detector(object_classes)
    detector, analyzer = det.detector, det.analyzer
    class_colors = {}

    processed_frames = 0
    global_frame_index = 0
    loops_done = 0
    start_time = time.time()
    last_detection_second = None
    prev_counts = load_detection_counts(video_id) if video_id is not None else {"slots": {}}
    run_start_wall = time.time()
    run_hour = datetime.fromtimestamp(run_start_wall).hour
    run_detections = defaultdict(int)
    run_frames = 0

    # --- Оценка корреляции v2 с границами сегментов ---
    # delta: окно около границы (симметричное). Если не задано — берём половину drift_window_sec.
    eval_delta = float(eval_transition_window_sec) if eval_transition_window_sec is not None else float(drift_window_sec) / 2.0
    eval_delta = max(0.0, eval_delta)
    eval_fpr_target = float(eval_fpr_target) if eval_fpr_target is not None else 0.01
    eval_update_every_n = int(eval_update_every_n) if eval_update_every_n is not None else 25
    if eval_update_every_n <= 0:
        eval_update_every_n = 25

    eval_times: List[float] = []
    eval_scores: List[float] = []
    eval_labels: List[int] = []

    # Итоговый расчёт по 8 агрегатам (накапливаем только скор).
    # 8 агрегатов:
    # - v1, v2, v3, v4, v5
    # - weighted_wass, weighted_kl_psi, weighted_max
    eval_scores_by_agg: Dict[str, List[float]] = {
        "v1": [],
        "v2": [],
        "v3": [],
        "v4": [],
        "v5": [],
        "v5_ema": [],
        "weighted_default": [],
        "weighted_wass": [],
        "weighted_kl_psi": [],
    }
    # EMA-сглаживание v5 для более стабильного сигнала (в проде нет сегментов, важна устойчивость).
    # Если ema_alpha=None или <=0 — сглаживание выключено.
    _ema_alpha = None
    try:
        if ema_alpha is not None and float(ema_alpha) > 0.0 and float(ema_alpha) <= 1.0:
            _ema_alpha = float(ema_alpha)
    except Exception:
        _ema_alpha = None
    v5_ema_state: Optional[float] = None

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                loops_done += 1
                if not loop_video or (loop_count > 0 and loops_done >= loop_count):
                    break
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            global_frame_index += 1
            current_second = global_frame_index / fps
            if max_duration_sec is not None and current_second >= max_duration_sec:
                break

            if frame_stride > 1 and (global_frame_index % frame_stride != 0):
                continue

            processed_frame = frame
            h, w = processed_frame.shape[:2]
            if max(h, w) > DRIFT_FRAME_MAX_EDGE:
                scale = DRIFT_FRAME_MAX_EDGE / max(h, w)
                small_frame = cv2.resize(processed_frame, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
            else:
                small_frame = processed_frame.copy()

            detections = detector.detect_objects(processed_frame)
            if not only_frames_with_detections or len(detections) > 0:
                frame_window.append(small_frame)

            drift_metrics_raw = None
            if len(frame_window) >= 2:
                try:
                    drift_metrics_raw = analyzer.analyze_drift_stream(list(frame_window))
                except Exception as e:
                    print(f"Ошибка расчёта дрейфа (stream): {e}")
            drift_metrics = convert_numpy_types(drift_metrics_raw or {})

            if detections:
                last_detection_second = current_second
            _get_or_assign_class_colors(detections, class_colors)
            overlay = draw_detections(processed_frame, detections, class_colors)
            cv2.imwrite(os.path.join(output_dir, f"frame_{processed_frames:06d}.jpg"), overlay)
            processed_frames += 1
            if video_id is not None:
                current_hour = datetime.fromtimestamp(time.time()).hour
                if current_hour != run_hour and run_frames > 0:
                    _flush_detection_counts_to_hour(prev_counts, str(run_hour), run_frames, run_detections, video_id)
                    run_hour = current_hour
                    run_frames = 0
                    run_detections = defaultdict(int)
                run_frames += 1
                for d in detections:
                    cn = d.get('class_name', 'object')
                    run_detections[cn] += 1

            metrics_entry = {
                "frame_index": global_frame_index,
                "second": current_second,
                "processed_frames": processed_frames,
                "detections_count": len(detections),
                "drift_metrics": drift_metrics,
                "distortion_stage": "original",
            }
            with VIDEO_JOBS_LOCK:
                job = VIDEO_JOBS.get(job_id)
                if job:
                    job["metrics_history"].append(metrics_entry)
                    job["last_metrics"] = metrics_entry
                    job["processed_frames"] = processed_frames
                    job["last_detection_second"] = last_detection_second

            if drift_metrics:
                metrics_payload = drift_metrics.copy()
                metrics_payload["total_detections"] = len(detections)
                counts = {c: 0 for c in object_classes}
                conf_by_class = {}
                for c in object_classes:
                    confs = [d.get('confidence', 0.0) for d in detections if d.get('class_name') == c]
                    conf_by_class[c] = sum(confs) / len(confs) if confs else 0.0
                for d in detections:
                    cn = d.get('class_name', 'object')
                    if cn in counts:
                        counts[cn] += 1
                seg_idx = get_segment_index_for_video_second(boundaries, current_second) if boundaries else None

                # v2 = 0.85*agg + 0.15*(1-mean_conf) и метка "рядом с границей" из segments_file
                # Считаем только если есть segments_file (boundaries) и доступен aggregate_score.
                try:
                    norm_eval = _normalize_drift_components(metrics_payload)
                    agg_eval = _compute_agg_base(norm_eval, component_flags) if norm_eval is not None else None
                    if boundaries and agg_eval is not None and conf_by_class:
                        mean_conf = sum(conf_by_class.values()) / max(1, len(conf_by_class))
                        agg = float(agg_eval)
                        v1 = agg
                        v2 = 0.85 * agg + 0.15 * (1.0 - float(mean_conf))
                        v3 = min(1.0, agg * (2.0 - float(mean_conf)))
                        v4 = 0.6 * agg + 0.4 * (1.0 - float(mean_conf))
                        v5_raw = min(1.0, agg / (0.5 + 0.5 * float(mean_conf)))

                        # EMA(v5): s_t = a*v5_raw + (1-a)*s_{t-1}
                        v5 = v5_raw
                        v5_ema = None
                        if _ema_alpha is not None:
                            if v5_ema_state is None:
                                v5_ema_state = float(v5_raw)
                            else:
                                v5_ema_state = _ema_alpha * float(v5_raw) + (1.0 - _ema_alpha) * float(v5_ema_state)
                            v5_ema = float(v5_ema_state)
                            try:
                                aggregate_v5_ema_gauge.set(float(v5_ema))
                            except Exception:
                                pass

                        w_default = _compute_agg_base(norm_eval, component_flags) if norm_eval is not None else None
                        w_wass = _weighted_variant(norm_eval, component_flags, {"psi": 0.1, "kl": 0.15, "js": 0.15, "ks": 0.2, "wass": 0.4}) if norm_eval is not None else None
                        w_kl_psi = _weighted_variant(norm_eval, component_flags, {"psi": 0.35, "kl": 0.35, "js": 0.1, "ks": 0.1, "wass": 0.1}) if norm_eval is not None else None

                        y = _boundary_label(boundaries, float(current_second), float(eval_delta), eval_label_mode)
                        eval_times.append(float(current_second))
                        # В live-дашборде хотим видеть оценку для v5 (по просьбе).
                        eval_scores.append(float(v5))
                        eval_labels.append(int(y))
                        eval_scores_by_agg["v1"].append(float(v1))
                        eval_scores_by_agg["v2"].append(float(v2))
                        eval_scores_by_agg["v3"].append(float(v3))
                        eval_scores_by_agg["v4"].append(float(v4))
                        eval_scores_by_agg["v5"].append(float(v5))
                        if v5_ema is not None:
                            eval_scores_by_agg["v5_ema"].append(float(v5_ema))
                        else:
                            eval_scores_by_agg["v5_ema"].append(float('nan'))
                        if w_default is not None:
                            eval_scores_by_agg["weighted_default"].append(float(w_default))
                        else:
                            eval_scores_by_agg["weighted_default"].append(float('nan'))
                        if w_wass is not None:
                            eval_scores_by_agg["weighted_wass"].append(float(w_wass))
                        else:
                            eval_scores_by_agg["weighted_wass"].append(float('nan'))
                        if w_kl_psi is not None:
                            eval_scores_by_agg["weighted_kl_psi"].append(float(w_kl_psi))
                        else:
                            eval_scores_by_agg["weighted_kl_psi"].append(float('nan'))

                        # Периодически обновляем gauge, чтобы видеть динамику во время обработки
                        if len(eval_scores) % eval_update_every_n == 0:
                            m = _compute_eval_metrics(eval_times, eval_scores, eval_labels, boundaries, eval_delta, eval_fpr_target)
                            if m.get("pr_auc") is not None:
                                eval_pr_auc_gauge.set(float(m["pr_auc"]))
                            if m.get("tpr_at_fpr") is not None:
                                eval_tpr_at_fpr_gauge.set(float(m["tpr_at_fpr"]))
                            if m.get("delta_mean") is not None:
                                eval_delta_mean_gauge.set(float(m["delta_mean"]))
                            if m.get("event_recall") is not None:
                                eval_event_recall_gauge.set(float(m["event_recall"]))
                            eval_points_total_gauge.set(float(len(eval_scores)))
                            eval_points_pos_gauge.set(float(sum(1 for yy in eval_labels if yy == 1)))
                except Exception:
                    # Оценка не должна ломать основной пайплайн
                    pass

                diff_pct = None
                if video_id is not None and run_frames >= 1:
                    prev_slots = prev_counts.get("slots", {}).get(str(run_hour), {})
                    diffs = []
                    all_classes = set(run_detections.keys()) | set(prev_slots.keys())
                    for c in all_classes:
                        rate_now = run_detections[c] / run_frames
                        prev_d = prev_slots.get(c, {"detections": 0, "frames": 0})
                        prev_f = max(prev_d.get("frames", 0), 1e-9)
                        rate_prev = prev_d.get("detections", 0) / prev_f
                        denom = max(rate_now, rate_prev, 1e-9)
                        if denom > 0:
                            diffs.append((rate_now - rate_prev) / denom * 100.0)
                    diff_pct = sum(diffs) / len(diffs) if diffs else 0.0
                record_drift_metrics(
                    metrics_payload,
                    time.time() - start_time,
                    job_id=job_id,
                    video_second=current_second,
                    detections_by_class=counts,
                    confidence_by_class=conf_by_class,
                    segment_index=seg_idx,
                    detection_rate_diff_pct=diff_pct,
                    component_flags=component_flags,
                    drift_window_sec=drift_window_sec,
                )
    except Exception as e:
        update_video_job(job_id, status="error", error=str(e))
        return
    finally:
        cap.release()
        if os.path.exists(video_path):
            os.unlink(video_path)
        if video_id is not None and run_frames > 0:
            _flush_detection_counts_to_hour(prev_counts, str(run_hour), run_frames, run_detections, video_id)

        # Финальная фиксация eval-метрик в Prometheus (последние значения останутся на графике)
        try:
            if boundaries and eval_scores:
                m = _compute_eval_metrics(eval_times, eval_scores, eval_labels, boundaries, eval_delta, eval_fpr_target)
                if m.get("pr_auc") is not None:
                    eval_pr_auc_gauge.set(float(m["pr_auc"]))
                if m.get("tpr_at_fpr") is not None:
                    eval_tpr_at_fpr_gauge.set(float(m["tpr_at_fpr"]))
                if m.get("delta_mean") is not None:
                    eval_delta_mean_gauge.set(float(m["delta_mean"]))
                if m.get("event_recall") is not None:
                    eval_event_recall_gauge.set(float(m["event_recall"]))
                eval_points_total_gauge.set(float(len(eval_scores)))
                eval_points_pos_gauge.set(float(sum(1 for yy in eval_labels if yy == 1)))

            # Итоговые метрики по 8 агрегатам (считаем только в конце).
            # Важно: если для weighted_* на каких-то точках нет компонент — там будет nan; такие точки игнорируем.
            if boundaries and eval_labels:
                for agg_name, sc in eval_scores_by_agg.items():
                    # фильтруем nan, синхронно выкидывая times/labels
                    ft = []
                    fs = []
                    fl = []
                    for t, s, y in zip(eval_times, sc, eval_labels):
                        if s is None:
                            continue
                        ss = float(s)
                        if math.isnan(ss) or math.isinf(ss):
                            continue
                        ft.append(float(t))
                        fs.append(ss)
                        fl.append(int(y))
                    if not fs:
                        continue
                    mm = _compute_eval_metrics(ft, fs, fl, boundaries, eval_delta, eval_fpr_target)
                    if mm.get("pr_auc") is not None:
                        eval_pr_auc_by_agg_gauge.labels(agg=agg_name).set(float(mm["pr_auc"]))
                    if mm.get("tpr_at_fpr") is not None:
                        eval_tpr_at_fpr_by_agg_gauge.labels(agg=agg_name).set(float(mm["tpr_at_fpr"]))
                    if mm.get("delta_mean") is not None:
                        eval_delta_mean_by_agg_gauge.labels(agg=agg_name).set(float(mm["delta_mean"]))
                    if mm.get("event_recall") is not None:
                        eval_event_recall_by_agg_gauge.labels(agg=agg_name).set(float(mm["event_recall"]))
        except Exception:
            pass
    update_video_job(job_id, status="completed", message="Обработка видео (pretrained) завершена", finished_at=time.time())


def process_archive_job_pretrained(
    job_id: str,
    archive_path: str,
    object_classes: List[str],
    drift_window_photos: int,
    only_frames_with_detections: bool,
    boundaries: Optional[List[str]] = None,
    video_id: Optional[int] = None,
):
    """
    Обработка архива с фото предобученной YOLO11l. video_id: накопление по часу старта и % отличия от прошлых запусков.
    """
    extract_dir = None
    try:
        extract_dir, image_paths = extract_archive_to_temp_dir(archive_path)
    except Exception as e:
        update_video_job(job_id, status="error", error=f"Ошибка распаковки архива: {e}")
        if os.path.exists(archive_path):
            os.unlink(archive_path)
        return

    if not image_paths:
        update_video_job(job_id, status="error", error="В архиве не найдено изображений (jpg/png)")
        try:
            shutil.rmtree(extract_dir, ignore_errors=True)
        except Exception:
            pass
        if os.path.exists(archive_path):
            os.unlink(archive_path)
        return

    output_dir = os.path.join(PROCESSED_FRAMES_DIR, job_id)
    os.makedirs(output_dir, exist_ok=True)
    init_video_job(job_id, output_dir)
    update_video_job(job_id, total_frames=len(image_paths))

    window_size = max(2, int(drift_window_photos))
    frame_window = deque(maxlen=window_size)
    det = get_pretrained_detector(object_classes)
    detector, analyzer = det.detector, det.analyzer
    class_colors = {}
    processed_frames = 0
    start_time = time.time()
    last_detection_index = None
    segment_index = 0
    prev_counts = load_detection_counts(video_id) if video_id is not None else {"slots": {}}
    run_start_wall = time.time()
    run_hour = datetime.fromtimestamp(run_start_wall).hour
    run_detections = defaultdict(int)
    run_frames = 0

    try:
        for photo_index, img_path in enumerate(image_paths):
            current_photo_name = os.path.splitext(os.path.basename(img_path))[0].lower()
            if boundaries:
                while segment_index + 1 < len(boundaries) and boundaries[segment_index + 1] == current_photo_name:
                    segment_index += 1
            frame = cv2.imread(img_path)
            if frame is None:
                continue
            h, w = frame.shape[:2]
            if max(h, w) > DRIFT_FRAME_MAX_EDGE:
                scale = DRIFT_FRAME_MAX_EDGE / max(h, w)
                small_frame = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
            else:
                small_frame = frame.copy()

            detections = detector.detect_objects(frame)
            if not only_frames_with_detections or len(detections) > 0:
                frame_window.append(small_frame)

            drift_metrics_raw = None
            if len(frame_window) >= 2:
                try:
                    drift_metrics_raw = analyzer.analyze_drift_stream(list(frame_window))
                except Exception as e:
                    print(f"Ошибка расчёта дрейфа (archive): {e}")
            drift_metrics = convert_numpy_types(drift_metrics_raw or {})

            if detections:
                last_detection_index = photo_index
            _get_or_assign_class_colors(detections, class_colors)
            overlay = draw_detections(frame, detections, class_colors)
            cv2.imwrite(os.path.join(output_dir, f"frame_{processed_frames:06d}.jpg"), overlay)
            processed_frames += 1
            if video_id is not None:
                current_hour = datetime.fromtimestamp(time.time()).hour
                if current_hour != run_hour and run_frames > 0:
                    _flush_detection_counts_to_hour(prev_counts, str(run_hour), run_frames, run_detections, video_id)
                    run_hour = current_hour
                    run_frames = 0
                    run_detections = defaultdict(int)
                run_frames += 1
                for d in detections:
                    cn = d.get('class_name', 'object')
                    run_detections[cn] += 1

            pseudo_second = float(photo_index)
            metrics_entry = {
                "frame_index": photo_index,
                "second": pseudo_second,
                "processed_frames": processed_frames,
                "detections_count": len(detections),
                "drift_metrics": drift_metrics,
                "distortion_stage": "original",
            }
            with VIDEO_JOBS_LOCK:
                job = VIDEO_JOBS.get(job_id)
                if job:
                    job["metrics_history"].append(metrics_entry)
                    job["last_metrics"] = metrics_entry
                    job["processed_frames"] = processed_frames
                    job["last_detection_second"] = float(last_detection_index) if last_detection_index is not None else None

            if drift_metrics:
                metrics_payload = drift_metrics.copy()
                metrics_payload["total_detections"] = len(detections)
                counts = {c: 0 for c in object_classes}
                conf_by_class = {}
                for c in object_classes:
                    confs = [d.get('confidence', 0.0) for d in detections if d.get('class_name') == c]
                    conf_by_class[c] = sum(confs) / len(confs) if confs else 0.0
                for d in detections:
                    cn = d.get('class_name', 'object')
                    if cn in counts:
                        counts[cn] += 1
                seg_idx = segment_index if boundaries and segment_index < len(boundaries) else None
                diff_pct = None
                if video_id is not None and run_frames >= 1:
                    prev_slots = prev_counts.get("slots", {}).get(str(run_hour), {})
                    diffs = []
                    all_classes = set(run_detections.keys()) | set(prev_slots.keys())
                    for c in all_classes:
                        rate_now = run_detections[c] / run_frames
                        prev_d = prev_slots.get(c, {"detections": 0, "frames": 0})
                        prev_f = max(prev_d.get("frames", 0), 1e-9)
                        rate_prev = prev_d.get("detections", 0) / prev_f
                        denom = max(rate_now, rate_prev, 1e-9)
                        if denom > 0:
                            diffs.append((rate_now - rate_prev) / denom * 100.0)
                    diff_pct = sum(diffs) / len(diffs) if diffs else 0.0
                record_drift_metrics(metrics_payload, time.time() - start_time, job_id=job_id, video_second=pseudo_second, detections_by_class=counts, confidence_by_class=conf_by_class, segment_index=seg_idx, detection_rate_diff_pct=diff_pct)
    except Exception as e:
        update_video_job(job_id, status="error", error=str(e))
    finally:
        try:
            shutil.rmtree(extract_dir, ignore_errors=True)
        except Exception:
            pass
        if os.path.exists(archive_path):
            os.unlink(archive_path)
        if video_id is not None and run_frames > 0:
            _flush_detection_counts_to_hour(prev_counts, str(run_hour), run_frames, run_detections, video_id)
    update_video_job(job_id, status="completed", message="Обработка архива (pretrained) завершена", finished_at=time.time())


@app.on_event("startup")
def _startup_set_processing_gauge():
    """При старте API выставить object_drift_processing=0, чтобы графики не рисовали линии без обработки."""
    _update_processing_gauge()


# API endpoints
@app.get("/status")
async def get_status():
    """Получить статус системы"""
    return {
        "model_trained": trained_model_path is not None and os.path.exists(trained_model_path),
        "trained_model_path": trained_model_path,
        "detector_ready": drift_detector is not None,
        "data_directory": DATA_DIR,
        "training_status": training_status,
        "training_error": training_error,
        "ready_for_drift_detection": drift_detector is not None and trained_model_path is not None
    }

@app.get("/metrics")
def get_metrics():
    """Получить метрики Prometheus"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/upload_baseline")
async def upload_baseline(
    cvat_archive: UploadFile = File(..., description="CVAT ZIP архив с изображениями для baseline")
):
    """
    Загружает baseline-изображения из CVAT ZIP архива без переобучения модели.

    Из архива извлекаются все изображения (игнорируя разметку), они сохраняются
    в файл BASELINE_IMAGES_FILE и используются для инициализации DriftAnalyzer.
    """
    global baseline_images, baseline_ready, drift_detector, trained_model_path

    temp_archive = validate_and_save_archive(cvat_archive)

    try:
        images = extract_images_from_archive(temp_archive)
        if not images:
            raise HTTPException(
                status_code=400,
                detail="В архиве не найдено ни одного изображения (jpg/png)"
            )

        baseline_images = images
        baseline_ready = True

        try:
            with open(BASELINE_IMAGES_FILE, 'wb') as f:
                pickle.dump(baseline_images, f)
        except Exception as e:
            print(f"✗ Ошибка сохранения baseline изображений: {e}")

        if trained_model_path is not None and os.path.exists(trained_model_path):
            try:
                sam_path = "sam_b.pt" if os.path.exists("sam_b.pt") else None
                drift_detector = ObjectDriftDetector(
                    baseline_images=baseline_images,
                    yolo_model_path=trained_model_path,
                    allowed_class_ids=None,
                    sam_checkpoint_path=sam_path if sam_path else "sam_b.pt",
                    use_sam=sam_path is not None
                )
            except Exception as e:
                print(f"✗ Ошибка переинициализации детектора с новым baseline: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Baseline сохранён, но не удалось инициализировать детектор: {e}"
                )

        return {
            "message": f"Baseline успешно загружен: {len(baseline_images)} изображений",
            "images_count": len(baseline_images),
            "model_ready": trained_model_path is not None and os.path.exists(trained_model_path),
        }
    finally:
        if os.path.exists(temp_archive):
            os.unlink(temp_archive)

@app.post("/train_model")
async def train_model(
    cvat_archive: UploadFile = File(..., description="CVAT архив с изображениями и аннотациями YOLO"),
    epochs: int = Form(default=50, description="Количество эпох обучения (минимум 50 для хорошего результата)"),
    batch_size: int = Form(default=2, description="Размер батча"),
    imgsz: int = Form(default=320, description="Размер изображений")
):
    """
    Обучает YOLO модель на данных из CVAT архива.

    Args:
        cvat_archive: CVAT архив с изображениями и аннотациями YOLO
        epochs: Количество эпох обучения
        batch_size: Размер батча
        imgsz: Размер изображений

    ВНИМАНИЕ: Обучение выполняется синхронно и может занять много времени.
    """
    global drift_detector, trained_model_path, baseline_dataset_path, training_status, training_error

    temp_archive = validate_and_save_archive(cvat_archive)

    try:
        print("Создаем датасет из CVAT архива...")
        from model_trainer import prepare_dataset_from_cvat_archive
        import tempfile

        temp_dataset_dir = tempfile.mkdtemp(prefix="cvat_dataset_")
        print(f"Временная директория датасета: {temp_dataset_dir}")

        try:
            dataset_yaml = prepare_dataset_from_cvat_archive(
                archive_path=temp_archive,
                output_dir=temp_dataset_dir,
                object_class_id=0
            )
            baseline_dataset_path = dataset_yaml
            print(f"✓ Датасет из CVAT создан: {dataset_yaml}")
        except Exception as e:
            import shutil
            if os.path.exists(temp_dataset_dir):
                shutil.rmtree(temp_dataset_dir)
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка обработки CVAT архива: {str(e)}"
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка сохранения архива: {str(e)}"
        )

    import threading

    training_status = "training"
    training_error = None
    with open(TRAINING_STATUS_FILE, 'w') as f:
        f.write("training")

    def train_sync():
        import shutil
        global trained_model_path, drift_detector, training_status, training_error

        data_dir = os.path.join(os.getcwd(), "data")

        try:
            print("🚀 Начинаем обучение модели в фоне...")
            print(f"Количество baseline изображений: {len(baseline_images)}")
            print(f"Путь к датасету: {baseline_dataset_path}")

            if epochs < 10:
                print(f"⚠️  КРИТИЧНО: {epochs} эпох - ЭТОГО НЕДОСТАТОЧНО!")
                print("   YOLO модели нуждаются минимум в 50-100 эпохах для обучения")
                print("   С 1 эпохой модель работает как случайный классификатор!")
            elif epochs < 50:
                print(f"⚠️  ВНИМАНИЕ: {epochs} эпох маловато, результат будет плохим")

            # Вызываем обучение
            from model_trainer import train_yolo_model
            model_path = train_yolo_model(
                dataset_yaml=baseline_dataset_path,
                epochs=epochs,
                batch=batch_size,
                imgsz=imgsz,
                device="cpu"
            )

            print("Обучение завершено, сохраняем модель...")

            print(f"Проверяем файл модели: {model_path}")
            print(f"Файл модели существует: {os.path.exists(model_path)}")
            if os.path.exists(model_path):
                file_size = os.path.getsize(model_path)
                print(f"Размер файла модели: {file_size} байт")

                model_in_data = os.path.join(data_dir, "trained_model.pt")
                shutil.copy2(model_path, model_in_data)
                print(f"✓ Модель сохранена в папку data: {model_in_data}")
                print(f"Файл в data существует: {os.path.exists(model_in_data)}")

                shutil.copy2(model_path, MODEL_WEIGHTS_PATH)
                print(f"✓ Модель скопирована в постоянную директорию: {MODEL_WEIGHTS_PATH}")
                print(f"Файл весов существует: {os.path.exists(MODEL_WEIGHTS_PATH)}")

                trained_model_path = MODEL_WEIGHTS_PATH
                with open(MODEL_PATH_FILE, 'w') as f:
                    f.write(MODEL_WEIGHTS_PATH)
                print(f"✓ Путь к модели сохранен в {MODEL_PATH_FILE}: {MODEL_WEIGHTS_PATH}")
                print("✅ Модель успешно сохранена!")

                if len(baseline_images) > 0:
                    try:
                        with open(BASELINE_IMAGES_FILE, 'wb') as f:
                            pickle.dump(baseline_images, f)
                        print(f"✓ Baseline сохранен: {len(baseline_images)} изображений в {BASELINE_IMAGES_FILE}")
                    except Exception as e:
                        print(f"✗ Предупреждение: не удалось сохранить baseline: {e}")

                try:
                    sam_path = "sam_b.pt" if os.path.exists("sam_b.pt") else None
                    drift_detector = ObjectDriftDetector(
                        baseline_images=baseline_images,
                        yolo_model_path=trained_model_path,
                        allowed_class_ids=None,
                        sam_checkpoint_path=sam_path if sam_path else "sam_b.pt",
                        use_sam=sam_path is not None
                    )
                    training_status = "completed"
                    with open(TRAINING_STATUS_FILE, 'w') as f:
                        f.write("completed")
                    print("✅ Детектор инициализирован с новой моделью")
                except Exception as e:
                    training_status = "error"
                    training_error = f"Ошибка инициализации детектора: {str(e)}"
                    with open(TRAINING_STATUS_FILE, 'w') as f:
                        f.write("error")
                    with open(TRAINING_ERROR_FILE, 'w') as f:
                        f.write(str(e))
                    print(f"❌ Ошибка инициализации детектора: {e}")
            else:
                print(f"✗ Файл модели не найден: {model_path}")
                training_status = "error"
                training_error = f"Обученная модель не найдена по пути: {model_path}"
                with open(TRAINING_STATUS_FILE, 'w') as f:
                    f.write("error")
                with open(TRAINING_ERROR_FILE, 'w') as f:
                    f.write(training_error)

        except Exception as e:
            training_status = "error"
            training_error = str(e)
            with open(TRAINING_STATUS_FILE, 'w') as f:
                f.write("error")
            with open(TRAINING_ERROR_FILE, 'w') as f:
                f.write(str(e))
            print(f"❌ Ошибка обучения модели: {e}")
            import traceback
            print("Traceback:")
            traceback.print_exc()

    print("Запускаем обучение...")
    train_sync()

    if training_status == "completed":
        return {
            "message": "Обучение модели завершено успешно",
            "status": "completed",
            "epochs": epochs,
            "model_path": trained_model_path
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка обучения модели: {training_error}"
        )

@app.post("/process_video", response_model=VideoJobResponse)
async def process_video(
    video: UploadFile = File(..., description="Видео файл для анализа дрейфа"),
    loop_video: bool = Form(False, description="Зацикливать видео"),
    loop_count: int = Form(1, description="Количество циклов (0 = бесконечно, если задан max_duration_sec)"),
    frame_stride: int = Form(5, description="Обрабатывать каждый N-й кадр"),
    drift_window_frames: int = Form(30, description="Размер скользящего окна по кадрам для расчёта дрейфа"),
    drift_window_sec: Optional[float] = Form(None, description="Окно в секундах (если задано, переопределяет drift_window_frames по fps)"),
    distortion_mode: str = Form("none", description="none | uniform | staged"),
    brightness: float = Form(0.0, description="Смещение яркости (0-255)"),
    contrast: float = Form(1.0, description="Коэффициент контраста (1.0 = без изменений)"),
    noise_std: float = Form(0.0, description="Стандартное отклонение шума"),
    hue_shift: int = Form(0, description="Сдвиг оттенка (0-180)"),
    saturation_scale: float = Form(1.0, description="Множитель насыщенности"),
    segment_duration_sec: float = Form(10.0, description="Длительность одного сегмента при staged-режиме"),
    max_duration_sec: Optional[float] = Form(None, description="Ограничение по длительности обработки (секунды)"),
    only_frames_with_detections: bool = Form(False, description="Считать дрейф только по кадрам, где есть хотя бы одна детекция"),
):
    """
    Обработка видео для определения дрейфа.

    Поддерживаются режимы:
    - none: без искажений;
    - uniform: одно искажение на весь поток;
    - staged: последовательные искажения по сегментам.
    """
    global drift_detector, trained_model_path, baseline_ready

    if trained_model_path is None or not os.path.exists(trained_model_path):
        raise HTTPException(
            status_code=400,
            detail="Модель не обучена. Сначала обучите модель через /train_model с CVAT архивом"
        )

    if drift_detector is None:
        raise HTTPException(status_code=400, detail="Детектор не инициализирован")

    if not baseline_ready:
        raise HTTPException(
            status_code=400,
            detail="Baseline изображения не загружены. Сначала загрузите baseline через /upload_baseline"
        )

    if frame_stride < 1:
        raise HTTPException(status_code=400, detail="frame_stride должен быть >= 1")

    if drift_window_frames < 1 and (drift_window_sec is None or drift_window_sec <= 0):
        raise HTTPException(status_code=400, detail="Задайте drift_window_frames >= 1 или drift_window_sec > 0")

    if distortion_mode not in {"none", "uniform", "staged"}:
        raise HTTPException(status_code=400, detail="distortion_mode должен быть none|uniform|staged")

    if loop_video and loop_count == 0 and max_duration_sec is None:
        raise HTTPException(
            status_code=400,
            detail="При loop_count=0 укажите max_duration_sec, чтобы остановить бесконечный цикл"
        )

    temp_video = validate_and_save_video(video)
    job_id = str(uuid.uuid4())

    worker = threading.Thread(
        target=process_video_job,
        args=(
            job_id,
            temp_video,
            loop_video,
            loop_count,
            frame_stride,
            drift_window_frames,
            drift_window_sec,
            only_frames_with_detections,
            distortion_mode,
            brightness,
            contrast,
            noise_std,
            hue_shift,
            saturation_scale,
            segment_duration_sec,
            max_duration_sec,
        ),
        daemon=True,
    )
    worker.start()

    return VideoJobResponse(job_id=job_id, message="Задача обработки видео запущена")


@app.post("/process_video_pretrained", response_model=VideoJobResponse)
async def process_video_pretrained(
    video: UploadFile = File(..., description="Видео для анализа (предобученная YOLO11l, без baseline)"),
    object_classes: str = Form("person,car", description="Классы COCO через запятую: person, car, truck, ..."),
    frame_stride: int = Form(5, description="Обрабатывать каждый N-й кадр"),
    drift_window_sec: float = Form(10.0, description="Скользящее окно для дрейфа (секунды)"),
    only_frames_with_detections: bool = Form(False, description="Считать дрейф только по кадрам с детекциями"),
    loop_video: bool = Form(False),
    loop_count: int = Form(1),
    max_duration_sec: Optional[float] = Form(None),
    segments_file: Optional[UploadFile] = File(None, description="Опционально: TXT, по одной секунде в строке — границы смены (0, 120.5, 300…)"),
    eval_transition_window_sec: Optional[float] = Form(None, description="Опционально: окно ±Δ (сек) вокруг границ из segments_file для оценки (по умолчанию drift_window_sec/2)"),
    eval_fpr_target: float = Form(0.01, description="Опционально: целевой FPR (доля ложных срабатываний вдали от границ) для метрики TPR@FPR"),
    eval_update_every_n: int = Form(25, description="Опционально: как часто (в точках) пересчитывать и обновлять eval-метрики во время обработки"),
    eval_label_mode: str = Form("symmetric", description="Опционально: режим метки около границы: symmetric (±Δ) или post_only ([T, T+Δ])"),
    ema_alpha: Optional[float] = Form(0.2, description="Опционально: EMA-сглаживание v5 (0..1). Если <=0 — выключено. По умолчанию 0.2"),
    video_id: Optional[int] = Form(None, description="Условный id видео: при указании детекции по классам накапливаются по часу старта в data/detection_counts/{id}.json, считается % отличия от прошлых запусков"),
    component_use_psi: bool = Form(True, description="PSI в агрегате (базовый вес 0.25). Выкл. — вес остальных перераспределяется"),
    component_use_kl: bool = Form(True, description="KL (базовый вес 0.25)"),
    component_use_js: bool = Form(True, description="JS (базовый вес 0.20)"),
    component_use_ks: bool = Form(True, description="KS (базовый вес 0.15)"),
    component_use_wass: bool = Form(True, description="Wasserstein (базовый вес 0.15)"),
):
    """
    Обработка видео предобученной YOLO11l. Без baseline: дрейф по скользящему окну.
    video_id: при указании — накопление детекций/мин по часам и метрика отличия от предыдущих запусков с тем же id.
    """
    classes = [c.strip().lower() for c in object_classes.split(",") if c.strip()]
    if not classes:
        classes = ["person", "car"]

    segments = None
    if segments_file and segments_file.filename:
        body = await segments_file.read()
        try:
            segments = parse_segments_file_video(body.decode("utf-8", errors="replace"))
        except Exception:
            segments = None

    if not any([component_use_psi, component_use_kl, component_use_js, component_use_ks, component_use_wass]):
        raise HTTPException(status_code=400, detail="В агрегате должна быть включена хотя бы одна метрика")

    temp_video = validate_and_save_video(video)
    job_id = str(uuid.uuid4())
    worker = threading.Thread(
        target=process_video_job_pretrained,
        args=(
            job_id,
            temp_video,
            classes,
            frame_stride,
            drift_window_sec,
            only_frames_with_detections,
            loop_video,
            loop_count,
            max_duration_sec,
            segments,
            video_id,
            eval_transition_window_sec,
            eval_fpr_target,
            eval_update_every_n,
            eval_label_mode,
            ema_alpha,
            component_use_psi,
            component_use_kl,
            component_use_js,
            component_use_ks,
            component_use_wass,
        ),
        daemon=True,
    )
    worker.start()
    return VideoJobResponse(job_id=job_id, message="Задача обработки видео (pretrained) запущена")


@app.post("/process_archive_pretrained", response_model=VideoJobResponse)
async def process_archive_pretrained(
    archive: UploadFile = File(..., description="ZIP архив с изображениями для анализа (предобученная YOLO11l)"),
    object_classes: str = Form("person,car", description="Классы COCO через запятую"),
    drift_window_photos: int = Form(30, description="Размер скользящего окна в количестве фото для дрейфа"),
    only_frames_with_detections: bool = Form(False, description="Считать дрейф только по кадрам с детекциями"),
    segments_file: Optional[UploadFile] = File(None, description="Опционально: TXT, по одному имени файла без расширения в строке — границы смены"),
    video_id: Optional[int] = Form(None, description="Условный id: накопление детекций по часу старта и % отличия от прошлых запусков"),
):
    """
    Обработка архива с фото предобученной YOLO11l. video_id: как у видео — накопление по часам и метрика отличия.
    """
    classes = [c.strip().lower() for c in object_classes.split(",") if c.strip()]
    if not classes:
        classes = ["person", "car"]

    segments = None
    if segments_file and segments_file.filename:
        body = await segments_file.read()
        try:
            segments = parse_segments_file_archive(body.decode("utf-8", errors="replace"))
        except Exception:
            segments = None

    temp_archive = validate_and_save_archive(archive)
    job_id = str(uuid.uuid4())
    worker = threading.Thread(
        target=process_archive_job_pretrained,
        args=(job_id, temp_archive, classes, drift_window_photos, only_frames_with_detections, segments, video_id),
        daemon=True,
    )
    worker.start()
    return VideoJobResponse(job_id=job_id, message="Задача обработки архива (pretrained) запущена")


@app.get("/video_jobs/{job_id}")
async def get_video_job_status(job_id: str):
    job = get_video_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return job


@app.get("/video_jobs/{job_id}/metrics")
async def get_video_job_metrics(job_id: str, limit: int = 100):
    job = get_video_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    metrics_history = job.get("metrics_history", [])
    return metrics_history[-limit:]


@app.get("/video_jobs/{job_id}/download")
async def download_video_job_frames(job_id: str):
    job = get_video_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    output_dir = job.get("output_dir")
    if not output_dir or not os.path.exists(output_dir):
        raise HTTPException(status_code=404, detail="Архив с кадрами пока не готов")

    archive_base = os.path.join(DATA_DIR, f"processed_frames_{job_id}")
    archive_path = shutil.make_archive(archive_base, 'zip', output_dir)
    with open(archive_path, 'rb') as f:
        content = f.read()

    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=processed_frames_{job_id}.zip"}
    )

def load_saved_state():
    """Загружает сохраненное состояние при старте приложения"""
    global trained_model_path, baseline_dataset_path, baseline_images, drift_detector, baseline_ready

    print(f"Загрузка состояния из: {DATA_DIR}")

    # Загружаем статус обучения
    global training_status, training_error
    if os.path.exists(TRAINING_STATUS_FILE):
        try:
            with open(TRAINING_STATUS_FILE, 'r') as f:
                saved_status = f.read().strip()
                if saved_status in ["not_started", "training", "completed", "error"]:
                    training_status = saved_status
                    print(f"✓ Загружен статус обучения: {training_status}")
        except Exception as e:
            print(f"✗ Ошибка загрузки статуса обучения: {e}")

    if os.path.exists(TRAINING_ERROR_FILE):
        try:
            with open(TRAINING_ERROR_FILE, 'r') as f:
                training_error = f.read().strip()
                if training_error:
                    print(f"✓ Загружена ошибка обучения: {training_error}")
        except Exception as e:
            print(f"✗ Ошибка загрузки ошибки обучения: {e}")
    # Временно отключено: загрузка baseline и инициализация ObjectDriftDetector (работа только с pretrained YOLO11l)
    baseline_images = []
    baseline_ready = False
    drift_detector = None
    trained_model_path = MODEL_WEIGHTS_PATH if os.path.exists(MODEL_WEIGHTS_PATH) else None

# Загружаем состояние при импорте модуля
from flood_router import router as flood_router
app.include_router(flood_router)

load_saved_state()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
