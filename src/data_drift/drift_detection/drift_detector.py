"""
Главный модуль для детекции дрейфа данных объектов
Объединяет детекцию YOLO, сегментацию SAM и анализ дрейфа
"""
import cv2
import numpy as np
from typing import List, Dict, Optional
import os

from object_detector import ObjectDetector
from object_segmentation import ObjectSegmenter
from drift_analyzer import DriftAnalyzer


class ObjectDriftDetector:
    """Главный класс для отслеживания дрейфа данных объектов"""
    
    def __init__(
        self,
        baseline_images: List[np.ndarray],
        yolo_model_path: Optional[str] = None,
        allowed_class_ids: Optional[List[int]] = None,
        allowed_name_tokens: Optional[List[str]] = None,
        sam_checkpoint_path: str = "sam_b.pt",
        use_sam: bool = True
    ):
        """
        Инициализация детектора дрейфа
        
        Args:
            baseline_images: Список эталонных изображений объектов
            yolo_model_path: Путь к модели YOLO (опционально)
            allowed_class_ids: Явный список id классов, которые считаем целевыми (для кастомной YOLO модели)
            allowed_name_tokens: Список подстрок, по которым фильтровать class_name (для COCO/общих моделей)
            sam_checkpoint_path: Путь к чекпоинту SAM
            use_sam: Использовать ли SAM для сегментации
        """
        self.use_sam = use_sam
        
        # Инициализация детектора объектов
        self.detector = ObjectDetector(
            model_path=yolo_model_path,
            allowed_class_ids=allowed_class_ids,
            allowed_name_tokens=allowed_name_tokens,
        )
        
        # Инициализация сегментатора (если используется)
        if self.use_sam and os.path.exists(sam_checkpoint_path):
            try:
                self.segmenter = ObjectSegmenter(checkpoint_path=sam_checkpoint_path)
            except Exception as e:
                print(f"Предупреждение: Не удалось загрузить SAM: {e}")
                self.use_sam = False
                self.segmenter = None
        else:
            self.use_sam = False
            self.segmenter = None
        
        # Инициализация анализатора дрейфа
        # Используем пустой baseline для совместимости
        if len(baseline_images) == 0:
            baseline_images = [np.zeros((64, 64, 3), dtype=np.uint8)]
        self.analyzer = DriftAnalyzer(baseline_images)
    
    def process_frame(self, frame: np.ndarray) -> Dict:
        """
        Обрабатывает один кадр видео
        
        Args:
            frame: Кадр видео в формате BGR
            
        Returns:
            Словарь с результатами:
            {
                'detections': List[dict],  # Детекции объектов
                'object_images': List[np.ndarray],  # Изображения объектов
                'drift_metrics': Dict  # Метрики дрейфа
            }
        """
        # Детектируем объекты
        detections = self.detector.detect_objects(frame)
        
        # Извлекаем изображения объектов
        object_images = []
        for det in detections:
            if self.use_sam and self.segmenter:
                # Используем SAM для точной сегментации
                object_img = self.segmenter.extract_object_region(frame, det['bbox'])
                if object_img is not None and object_img.size > 0:
                    object_images.append(object_img)
            else:
                # Используем простое обрезание по боксу
                x1, y1, x2, y2 = det['bbox']
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
                object_crop = frame[y1:y2, x1:x2]
                if object_crop.size > 0:
                    object_images.append(object_crop)
        
        # Анализируем дрейф (если есть объекты)
        drift_metrics = None
        if len(object_images) > 0:
            drift_metrics = self.analyzer.analyze_drift(object_images)
        
        return {
            'detections': detections,
            'object_images': object_images,
            'drift_metrics': drift_metrics
        }
    
    def process_video(self, video_path: str, sample_rate: int = 30) -> Dict:
        """
        Обрабатывает видео
        
        Args:
            video_path: Путь к видео файлу
            sample_rate: Каждый N-й кадр обрабатывать (для экономии ресурсов)
            
        Returns:
            Словарь с результатами обработки
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {'error': f'Не удалось открыть видео: {video_path}'}
        
        all_detections = []
        all_object_images = []
        frame_count = 0
        
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                frame_count += 1
                # Обрабатываем каждый N-й кадр
                if frame_count % sample_rate == 0:
                    result = self.process_frame(frame)
                    all_detections.extend(result['detections'])
                    all_object_images.extend(result['object_images'])
        
        finally:
            cap.release()
        
        # Финальный анализ дрейфа по всем кадрам
        drift_metrics = None
        if len(all_object_images) > 0:
            drift_metrics = self.analyzer.analyze_drift(all_object_images)
        
        return {
            'total_frames': frame_count,
            'processed_frames': frame_count // sample_rate,
            'total_detections': len(all_detections),
            'total_object_images': len(all_object_images),
            'drift_metrics': drift_metrics
        }

