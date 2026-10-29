"""
Модуль для загрузки и обработки архивов CVAT с разметкой YOLO
"""
import zipfile
import os
import cv2
import numpy as np
from typing import List, Tuple, Optional
from pathlib import Path
import yaml


def parse_yolo_annotation(line: str, img_width: int, img_height: int) -> Optional[Tuple[int, int, int, int]]:
    """
    Парсит строку аннотации YOLO формата
    
    Формат YOLO: class_id center_x center_y width height (нормализованные [0, 1])
    
    Returns:
        (x1, y1, x2, y2) в пикселях или None
    """
    try:
        parts = line.strip().split()
        if len(parts) < 5:
            return None
        
        class_id = int(parts[0])
        center_x = float(parts[1])
        center_y = float(parts[2])
        width = float(parts[3])
        height = float(parts[4])
        
        # Конвертируем из нормализованных координат в пиксели
        x_center = center_x * img_width
        y_center = center_y * img_height
        w = width * img_width
        h = height * img_height
        
        x1 = int(x_center - w / 2)
        y1 = int(y_center - h / 2)
        x2 = int(x_center + w / 2)
        y2 = int(y_center + h / 2)
        
        return (x1, y1, x2, y2)
    except Exception:
        return None


def extract_objects_from_cvat_archive(
    archive_path: str,
    object_class_id: int = 0,
    images_dir: str = "images",
    labels_dir: str = "labels"
) -> List[np.ndarray]:
    """
    Извлекает изображения объектов из архива CVAT с разметкой YOLO
    
    Args:
        archive_path: Путь к ZIP архиву CVAT
        object_class_id: ID целевого класса в YOLO разметке (по умолчанию 0)
        images_dir: Папка с изображениями в архиве (обычно "images" или "obj_train_data")
        labels_dir: Папка с аннотациями в архиве (обычно "labels" или "obj_train_data")
    
    Returns:
        Список изображений объектов (обрезанных)
    """
    object_images = []
    
    try:
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            # Получаем список всех файлов
            file_list = zip_ref.namelist()
            
            # Находим изображения и соответствующие аннотации
            image_files = [f for f in file_list if f.endswith(('.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG'))]
            
            for img_path in image_files:
                # Пропускаем файлы не из нужной директории
                if images_dir not in img_path:
                    continue
                
                # Читаем изображение
                img_data = zip_ref.read(img_path)
                nparr = np.frombuffer(img_data, np.uint8)
                image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if image is None:
                    continue
                
                img_height, img_width = image.shape[:2]
                
                # Ищем соответствующий файл аннотации
                img_name = Path(img_path).stem
                label_path = None
                
                # Пробуем разные варианты путей
                possible_label_paths = [
                    img_path.replace(images_dir, labels_dir).replace(Path(img_path).suffix, '.txt'),
                    img_path.replace('images', 'labels').replace(Path(img_path).suffix, '.txt'),
                    f"{labels_dir}/{img_name}.txt",
                    f"labels/{img_name}.txt",
                ]
                
                for lp in possible_label_paths:
                    if lp in file_list:
                        label_path = lp
                        break
                
                if label_path is None:
                    # Если аннотации нет, пропускаем
                    continue
                
                # Читаем аннотацию
                try:
                    label_data = zip_ref.read(label_path).decode('utf-8')
                    lines = label_data.strip().split('\n')
                    
                    for line in lines:
                        if not line.strip():
                            continue
                        
                        bbox = parse_yolo_annotation(line, img_width, img_height)
                        if bbox is None:
                            continue
                        
                        x1, y1, x2, y2 = bbox
                        
                        # Проверяем класс (первое число в строке)
                        parts = line.strip().split()
                        if len(parts) > 0:
                            try:
                                class_id = int(parts[0])
                                if class_id != object_class_id:
                                    continue
                            except ValueError:
                                continue
                        
                        # Обрезаем изображение объекта
                        x1, y1 = max(0, x1), max(0, y1)
                        x2, y2 = min(img_width, x2), min(img_height, y2)
                        
                        if x2 > x1 and y2 > y1:
                            object_crop = image[y1:y2, x1:x2]
                            if object_crop.size > 0:
                                object_images.append(object_crop)
                
                except Exception as e:
                    print(f"Ошибка обработки аннотации {label_path}: {e}")
                    continue
    
    except Exception as e:
        raise RuntimeError(f"Ошибка извлечения данных из архива CVAT: {e}")
    
    return object_images


def load_cvat_dataset(
    archive_path: str,
    object_class_id: int = 0
) -> List[np.ndarray]:
    """
    Загружает датасет CVAT и извлекает изображения объектов
    
    Args:
        archive_path: Путь к архиву CVAT
        object_class_id: ID целевого класса (по умолчанию 0)
    
    Returns:
        Список изображений объектов
    """
    return extract_objects_from_cvat_archive(archive_path, object_class_id)


def get_class_id_from_yaml(yaml_path: str, class_name: str = "object") -> Optional[int]:
    """
    Извлекает ID класса из файла data.yaml (формат YOLO)
    
    Args:
        yaml_path: Путь к файлу data.yaml
        class_name: Название класса (например, "object")
    
    Returns:
        ID класса или None
    """
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        if 'names' in data:
            names = data['names']
            if isinstance(names, dict):
                for class_id, name in names.items():
                    if class_name.lower() in str(name).lower():
                        return int(class_id)
            elif isinstance(names, list):
                for idx, name in enumerate(names):
                    if class_name.lower() in str(name).lower():
                        return idx
        
        return None
    except Exception:
        return None


def extract_images_from_archive(archive_path: str) -> List[np.ndarray]:
    """
    Извлекает все изображения из ZIP архива (без разметки)
    
    Args:
        archive_path: Путь к ZIP архиву
    
    Returns:
        Список изображений
    """
    images = []
    
    try:
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            file_list = zip_ref.namelist()
            
            # Находим все изображения
            image_files = [f for f in file_list if f.endswith(('.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG'))]
            
            for img_path in image_files:
                try:
                    img_data = zip_ref.read(img_path)
                    nparr = np.frombuffer(img_data, np.uint8)
                    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    
                    if image is not None:
                        images.append(image)
                except Exception as e:
                    print(f"Ошибка обработки изображения {img_path}: {e}")
                    continue
    
    except Exception as e:
        raise RuntimeError(f"Ошибка извлечения изображений из архива: {e}")
    
    return images
