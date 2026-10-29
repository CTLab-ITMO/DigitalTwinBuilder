"""
Модуль детекции объектов с использованием GroundingDINO
Опциональный детектор, который можно использовать вместо или вместе с YOLO
"""
import cv2
import numpy as np
from typing import List, Optional
import sys
import os

# Пытаемся импортировать GroundingDINO
try:
    # Добавляем путь к репозиторию GroundingDINO (если он установлен локально)
    grounding_dino_path = os.environ.get('GROUNDING_DINO_PATH')
    if grounding_dino_path and os.path.exists(grounding_dino_path):
        sys.path.insert(0, grounding_dino_path)
    
    from groundingdino.util.inference import load_model, predict
    from huggingface_hub import hf_hub_download
    GROUNDING_DINO_AVAILABLE = True
except ImportError:
    GROUNDING_DINO_AVAILABLE = False
    print("Предупреждение: GroundingDINO не установлен. Используйте YOLO детектор.")


class GroundingDINODetector:
    """Детектор объектов на основе GroundingDINO"""
    
    def __init__(
        self,
        text_prompt: str = "object",
        box_threshold: float = 0.3,
        text_threshold: float = 0.25,
        config_path: Optional[str] = None,
        checkpoint_path: Optional[str] = None
    ):
        """
        Инициализация детектора GroundingDINO
        
        Args:
            text_prompt: Текстовый запрос для детекции (например, "object")
            box_threshold: Порог для боксов детекции
            text_threshold: Порог для текстовых совпадений
            config_path: Путь к конфигу модели (если None, попытается найти автоматически)
            checkpoint_path: Путь к чекпоинту (если None, скачает автоматически)
        """
        if not GROUNDING_DINO_AVAILABLE:
            raise ImportError(
                "GroundingDINO не установлен. "
                "Установите его или используйте ObjectDetector (YOLO)"
            )
        
        self.text_prompt = text_prompt
        self.box_threshold = box_threshold
        self.text_threshold = text_threshold
        self.model = None
        self.config_path = config_path
        self.checkpoint_path = checkpoint_path
        
        # Загружаем модель
        self._load_model()
    
    def _load_model(self):
        """Загружает модель GroundingDINO"""
        try:
            # Если чекпоинт не указан, скачиваем через HuggingFace
            if self.checkpoint_path is None or not os.path.exists(self.checkpoint_path):
                print("Загрузка чекпоинта GroundingDINO через HuggingFace...")
                self.checkpoint_path = hf_hub_download(
                    repo_id="ShilongLiu/GroundingDINO",
                    filename="groundingdino_swinb_cogcoor.pth"
                )
            
            # Если конфиг не указан, пытаемся найти
            if self.config_path is None:
                # Пытаемся найти конфиг в стандартных местах
                possible_paths = [
                    os.path.join(os.path.dirname(__file__), "..", "GroundingDINO", "groundingdino", "config", "GroundingDINO_SwinB.cfg.py"),
                    os.environ.get('GROUNDING_DINO_CONFIG_PATH'),
                ]
                for path in possible_paths:
                    if path and os.path.exists(path):
                        self.config_path = path
                        break
                
                if self.config_path is None:
                    raise FileNotFoundError(
                        "Не найден конфиг GroundingDINO. "
                        "Укажите config_path явно или установите переменную окружения GROUNDING_DINO_CONFIG_PATH"
                    )
            
            # Загружаем модель
            self.model = load_model(self.config_path, self.checkpoint_path)
            print("GroundingDINO модель загружена успешно")
            
        except Exception as e:
            raise RuntimeError(f"Ошибка загрузки GroundingDINO: {e}")
    
    def detect_objects(self, image: np.ndarray) -> List[dict]:
        """
        Детектирует объекты на изображении используя текстовый запрос
        
        Args:
            image: Изображение в формате BGR (OpenCV)
            
        Returns:
            Список словарей с информацией о детекциях:
            {
                'bbox': [x1, y1, x2, y2],
                'confidence': float,
                'phrase': str,
                'crop': np.ndarray  # Обрезка изображения объекта
            }
        """
        if self.model is None:
            raise RuntimeError("Модель не загружена")
        
        try:
            # GroundingDINO работает с RGB
            if len(image.shape) == 3:
                image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            else:
                image_rgb = image
            
            # Детекция
            boxes, logits, phrases = predict(
                model=self.model,
                image=image_rgb,
                caption=self.text_prompt,
                box_threshold=self.box_threshold,
                text_threshold=self.text_threshold
            )
            
            detections = []
            if boxes is not None and len(boxes) > 0:
                # Конвертируем координаты из формата GroundingDINO (центр + размер) в (x1, y1, x2, y2)
                # GroundingDINO возвращает в формате [cx, cy, w, h] нормализованные [0, 1]
                h, w = image.shape[:2]
                
                for box, logit, phrase in zip(boxes, logits, phrases):
                    # Преобразуем в пиксели
                    cx, cy, bw, bh = box
                    x1 = int((cx - bw / 2) * w)
                    y1 = int((cy - bh / 2) * h)
                    x2 = int((cx + bw / 2) * w)
                    y2 = int((cy + bh / 2) * h)
                    
                    # Проверяем границы
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)
                    
                    # Обрезаем изображение объекта
                    object_crop = image[y1:y2, x1:x2]
                    
                    if object_crop.size > 0:
                        detections.append({
                            'bbox': [x1, y1, x2, y2],
                            'confidence': float(logit),
                            'phrase': phrase,
                            'crop': object_crop
                        })
            
            return detections
            
        except Exception as e:
            print(f"Ошибка детекции GroundingDINO: {e}")
            return []



def is_grounding_dino_available() -> bool:
    """Проверяет, доступен ли GroundingDINO"""
    return GROUNDING_DINO_AVAILABLE
