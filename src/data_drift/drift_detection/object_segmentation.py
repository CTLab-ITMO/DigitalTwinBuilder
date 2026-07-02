"""
Модуль сегментации объектов с использованием SAM (Segment Anything Model)
Используется для точного извлечения областей объектов из детекций YOLO
"""
import cv2
import numpy as np
import torch
from segment_anything import sam_model_registry, SamPredictor
from typing import List, Tuple, Optional


class ObjectSegmenter:
    """Сегментатор объектов на основе SAM"""
    
    def __init__(self, checkpoint_path: str = "sam_b.pt", model_type: str = "vit_b"):
        """
        Инициализация сегментатора
        
        Args:
            checkpoint_path: Путь к чекпоинту SAM
            model_type: Тип модели SAM (vit_b, vit_l, vit_h)
        """
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.sam = sam_model_registry[model_type](checkpoint=checkpoint_path)
        self.sam.to(device=self.device)
        self.predictor = SamPredictor(self.sam)
        self.checkpoint_path = checkpoint_path
    
    def segment_object(self, image: np.ndarray, bbox: List[int]) -> Optional[np.ndarray]:
        """
        Сегментирует объект по боксу
        
        Args:
            image: Изображение в формате BGR
            bbox: Координаты бокса [x1, y1, x2, y2]
            
        Returns:
            Маска сегментации или None
        """
        if len(bbox) != 4:
            return None
        
        x1, y1, x2, y2 = bbox
        # Проверяем границы
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(image.shape[1], x2), min(image.shape[0], y2)
        
        if x2 <= x1 or y2 <= y1:
            return None
        
        try:
            # Устанавливаем изображение
            self.predictor.set_image(image)
            
            # Преобразуем бокс в формат SAM (центр и размер)
            box = np.array([x1, y1, x2, y2])
            
            # Предсказываем маску
            masks, scores, logits = self.predictor.predict(
                point_coords=None,
                point_labels=None,
                box=box[None, :],
                multimask_output=False,
            )
            
            return masks[0]  # Возвращаем лучшую маску
            
        except Exception as e:
            print(f"Ошибка сегментации: {e}")
            return None
    
    def extract_object_region(self, image: np.ndarray, bbox: List[int]) -> Optional[np.ndarray]:
        """
        Извлекает область объекта с использованием сегментации SAM
        
        Args:
            image: Изображение в формате BGR
            bbox: Координаты бокса [x1, y1, x2, y2]
            
        Returns:
            Обрезанное изображение объекта или None
        """
        mask = self.segment_object(image, bbox)
        if mask is None:
            return None
        
        x1, y1, x2, y2 = bbox
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(image.shape[1], x2), min(image.shape[0], y2)
        
        # Применяем маску к обрезанной области
        crop = image[y1:y2, x1:x2].copy()
        mask_crop = mask[y1:y2, x1:x2]
        
        # Создаем изображение только с областью объекта
        result = np.zeros_like(crop)
        result[mask_crop] = crop[mask_crop]
        
        return result


