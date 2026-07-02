"""
Модуль для обучения YOLO модели на baseline данных
"""
import os
import shutil
import tempfile
import yaml
import cv2
import numpy as np
from pathlib import Path
from typing import Optional, List
from ultralytics import YOLO
import zipfile


def prepare_dataset_from_cvat_archive(
    archive_path: str,
    output_dir: str,
    object_class_id: int = 0
) -> str:
    """
    Подготавливает датасет из CVAT архива для обучения YOLO
    
    Args:
        archive_path: Путь к CVAT архиву
        output_dir: Директория для сохранения датасета
        object_class_id: ID целевого класса
    
    Returns:
        Путь к директории с датасетом
    """
    os.makedirs(output_dir, exist_ok=True)
    
    images_dir = os.path.join(output_dir, "images", "train")
    labels_dir = os.path.join(output_dir, "labels", "train")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(labels_dir, exist_ok=True)
    
    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
        file_list = zip_ref.namelist()
        image_files = [f for f in file_list if f.endswith(('.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG'))]
        
        for img_path in image_files:
            # Пропускаем файлы не из нужной директории
            if "images" not in img_path and "obj_train_data" not in img_path:
                continue
            
            # Извлекаем изображение
            img_name = Path(img_path).name
            img_data = zip_ref.read(img_path)
            
            # Сохраняем изображение
            img_output_path = os.path.join(images_dir, img_name)
            with open(img_output_path, 'wb') as f:
                f.write(img_data)
            
            # Ищем аннотацию
            img_stem = Path(img_path).stem
            label_path = None
            
            possible_label_paths = [
                img_path.replace("images", "labels").replace(Path(img_path).suffix, '.txt'),
                img_path.replace("obj_train_data", "obj_train_data").replace(Path(img_path).suffix, '.txt'),
                f"labels/{img_stem}.txt",
                f"obj_train_data/{img_stem}.txt",
            ]
            
            for lp in possible_label_paths:
                if lp in file_list:
                    label_path = lp
                    break
            
            if label_path:
                # Читаем аннотацию и конвертируем все классы в 0 (один класс для обучения)
                try:
                    label_data = zip_ref.read(label_path).decode('utf-8')
                    lines = label_data.strip().split('\n')
                    
                    # Конвертируем все классы в 0 (для обучения на одном классе)
                    converted_lines = []
                    for line in lines:
                        if not line.strip():
                            continue
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            try:
                                original_class_id = int(parts[0])
                                # Если класс совпадает с нужным, конвертируем в 0
                                # Если нет, пропускаем (или можно конвертировать все в 0)
                                if original_class_id == object_class_id:
                                    # Заменяем class_id на 0
                                    new_line = f"0 {' '.join(parts[1:])}"
                                    converted_lines.append(new_line)
                            except ValueError:
                                continue
                    
                    # Сохраняем конвертированную аннотацию
                    if converted_lines:
                        label_output_path = os.path.join(labels_dir, f"{img_stem}.txt")
                        with open(label_output_path, 'w') as f:
                            f.write('\n'.join(converted_lines))
                except Exception as e:
                    print(f"Ошибка обработки аннотации {label_path}: {e}")
                    continue
    
    return create_yolo_dataset_yaml(output_dir, class_name="object", num_classes=1)


def create_yolo_dataset_yaml(dataset_dir: str, class_name: str = "object", num_classes: int = 1) -> str:
    """
    Создает YAML файл конфигурации для YOLO датасета
    
    Args:
        dataset_dir: Директория с датасетом
        class_name: Название класса
        num_classes: Количество классов
    
    Returns:
        Путь к YAML файлу
    """
    yaml_path = os.path.join(dataset_dir, "dataset.yaml")
    
    config = {
        'path': os.path.abspath(dataset_dir),
        'train': 'images/train',
        'val': 'images/train',  # Используем train для валидации тоже
        'names': {0: class_name} if num_classes == 1 else {i: f"class_{i}" for i in range(num_classes)},
        'nc': num_classes
    }
    
    with open(yaml_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    
    return yaml_path


def prepare_dataset_from_images(
    images: List[np.ndarray],
    output_dir: str,
    auto_annotate: bool = True
) -> str:
    """
    Подготавливает датасет из списка изображений для обучения YOLO
    
    Args:
        images: Список изображений (кропы объектов)
        output_dir: Директория для сохранения датасета
        auto_annotate: Использовать автоаннотацию для создания разметки
    
    Returns:
        Путь к директории с датасетом
    """
    os.makedirs(output_dir, exist_ok=True)
    
    images_dir = os.path.join(output_dir, "images", "train")
    labels_dir = os.path.join(output_dir, "labels", "train")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(labels_dir, exist_ok=True)
    
    # Сохраняем изображения как есть (для совместимости, но теперь не используется)
    for idx, img in enumerate(images):
        if img is None or img.size == 0:
            continue

        img_path = os.path.join(images_dir, f"image_{idx:06d}.jpg")
        cv2.imwrite(img_path, img)

        # Создаем аннотацию: весь кроп - это один объект класса 0
        # Формат YOLO: class_id center_x center_y width height (нормализованные)
        label_path = os.path.join(labels_dir, f"image_{idx:06d}.txt")
        # Для кропа весь кадр - это объект
        # center_x = 0.5, center_y = 0.5, width = 1.0, height = 1.0
        with open(label_path, 'w') as f:
            f.write("0 0.5 0.5 1.0 1.0\n")

    return create_yolo_dataset_yaml(output_dir, class_name="object", num_classes=1)


def train_yolo_model(
    dataset_yaml: str,
    epochs: int = 50,
    imgsz: int = 640,
    batch: int = 16,
    device: str = "cpu",
    model_name: str = "yolo11l.pt"
) -> str:
    """
    Обучает YOLO модель на датасете
    
    Args:
        dataset_yaml: Путь к YAML файлу датасета
        epochs: Количество эпох
        imgsz: Размер изображений
        batch: Размер батча
        device: Устройство для обучения
        model_name: Название базовой модели
    
    Returns:
        Путь к обученной модели
    """
    print(f"🚀 Начинаем обучение YOLO модели...")
    print(f"Датасет: {dataset_yaml}")
    print(f"Эпохи: {epochs}, Batch: {batch}, Размер: {imgsz}, Устройство: {device}")

    # Загружаем базовую модель
    print(f"Загружаем модель: {model_name}")
    model = YOLO(model_name)
    print("Модель загружена успешно")
    
    # Обучаем модель
    print("Начинаем обучение модели...")
    try:
        results = model.train(
            data=dataset_yaml,
            epochs=epochs,
            imgsz=imgsz,
            batch=batch,
            device=device,
            project="runs/detect",
            name="object_detector",
            exist_ok=True
        )
        print("Обучение завершено!")
    except Exception as e:
        print(f"❌ Ошибка во время обучения: {e}")
        import traceback
        traceback.print_exc()
        raise

    # Возвращаем путь к лучшей модели
    best_model_path = results.save_dir / "weights" / "best.pt"
    last_model_path = results.save_dir / "weights" / "last.pt"

    # Проверяем наличие модели
    if best_model_path.exists():
        model_path = best_model_path
        print(f"✓ Найдена лучшая модель: {model_path}")
    elif last_model_path.exists():
        model_path = last_model_path
        print(f"✓ Найдена последняя модель: {model_path}")
    else:
        # Если модели нет в ожидаемом месте, ищем в других возможных местах
        import glob
        possible_paths = [
            str(results.save_dir / "weights" / "*.pt"),
            str(results.save_dir / "*.pt"),
            "runs/detect/object_detector/weights/best.pt",
            "runs/detect/object_detector/weights/last.pt"
        ]

        found_path = None
        for pattern in possible_paths:
            matches = glob.glob(pattern)
            if matches:
                found_path = matches[0]
                break

        if found_path and os.path.exists(found_path):
            model_path = found_path
            print(f"✓ Найдена модель в альтернативном месте: {model_path}")
        else:
            raise FileNotFoundError(f"Модель не найдена. Проверьте {results.save_dir}")

    print(f"✅ Модель обучена и сохранена: {model_path}")
    print(f"Размер файла модели: {os.path.getsize(model_path) if os.path.exists(model_path) else 'N/A'} байт")
    return str(model_path)
