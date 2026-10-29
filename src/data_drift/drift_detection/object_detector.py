"""
Модуль детекции объектов с использованием YOLO
"""
import cv2
import numpy as np
from ultralytics import YOLO
from typing import List, Tuple, Optional
import torch


class ObjectDetector:
    """Детектор объектов на основе YOLO"""
    
    def __init__(
        self,
        model_path: Optional[str] = None,
        conf_threshold: float = 0.1,  # Снижен порог для тестирования
        allowed_class_ids: Optional[List[int]] = None,
        allowed_name_tokens: Optional[List[str]] = None,
    ):
        """
        Инициализация детектора
        
        Args:
            model_path: Путь к модели YOLOv11l (если None, загрузит предобученную)
            conf_threshold: Порог уверенности детекции
            allowed_class_ids: Явный список id целевых классов (для кастомной YOLO модели)
            allowed_name_tokens: Список подстрок, по которым фильтровать class_name (для COCO/общих моделей)
        """
        self.conf_threshold = conf_threshold
        self.allowed_class_ids = allowed_class_ids
        self.allowed_name_tokens = [t.lower() for t in allowed_name_tokens] if allowed_name_tokens else None
        # Загружаем модель
        if model_path:
            self.model = YOLO(model_path)
        else:
            # Используем предобученную YOLO (скачается автоматически при первом использовании)
            try:
                self.model = YOLO('yolo11l.pt')
            except Exception:
                # Если не получилось, используем базовую модель
                self.model = YOLO('yolov8n.pt')
    
    def detect_objects(self, image: np.ndarray) -> List[dict]:
        """
        Детектирует объекты на изображении

        Args:
            image: Изображение в формате BGR (OpenCV)

        Returns:
            Список словарей с информацией о детекциях:
            {
                'bbox': [x1, y1, x2, y2],
                'confidence': float,
                'class': int,
                'crop': np.ndarray  # Обрезка изображения объекта
            }
        """
        results = self.model(image, conf=self.conf_threshold, verbose=False)
        detections = []
        if len(results) > 0 and results[0].boxes is not None:
            boxes = results[0].boxes
            for i in range(len(boxes)):
                # Получаем координаты бокса
                x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy()
                conf = boxes.conf[i].cpu().numpy()
                cls = int(boxes.cls[i].cpu().numpy())
                
                # Получаем название класса
                class_name = self.model.names[cls] if cls < len(self.model.names) else str(cls)
                
                # Фильтруем по классу
                should_include = True
                if self.allowed_class_ids is not None:
                    should_include = cls in self.allowed_class_ids
                elif self.allowed_name_tokens is not None:
                    name_lower = str(class_name).lower()
                    should_include = any(tok in name_lower for tok in self.allowed_name_tokens)

                if not should_include:
                    continue
                
                # Обрезаем изображение объекта
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                # Проверяем границы
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(image.shape[1], x2)
                y2 = min(image.shape[0], y2)
                
                if x2 <= x1 or y2 <= y1:
                    continue
                
                object_crop = image[y1:y2, x1:x2]
                
                if object_crop.size == 0:
                    continue
                
                detections.append({
                    'bbox': [x1, y1, x2, y2],
                    'confidence': float(conf),
                    'class': cls,
                    'class_name': class_name,
                    'crop': object_crop
                })
        return detections
    
    def detect_from_video_frame(self, frame: np.ndarray) -> List[dict]:
        """Алиас для detect_objects для совместимости"""
        return self.detect_objects(frame)


if __name__ == "__main__":
    # Тест
    detector = ObjectDetector()
    test_image = cv2.imread("../shljapa.jpg")
    if test_image is not None:
        detections = detector.detect_objects(test_image)
        print(f"Найдено объектов: {len(detections)}")
        for det in detections:
            print(f"  Уверенность: {det['confidence']:.2f}, Класс: {det['class_name']}")
