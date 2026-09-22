import logging
import uuid
import os
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ImageDetectionResult, Alert
from app.annotations import fire_annotation

logger = logging.getLogger(__name__)

router = APIRouter()


class SeedResponse(BaseModel):
    run_id: str
    categories_loaded: int
    total_images: int


class DetectResponse(BaseModel):
    run_id: str
    detector: str
    category: str
    n_anomalies: int
    n_total: int
    anomaly_ratio: float
    auroc_image: float
    auroc_pixel: float
    pro_score: float


class ImageResultResponse(BaseModel):
    id: int
    category: str
    detector: str
    run_id: str
    timestamp: datetime
    image_name: Optional[str] = None
    label: Optional[str] = None
    is_anomaly: Optional[bool] = None
    anomaly_score: Optional[float] = None
    auroc_image: Optional[float] = None
    auroc_pixel: Optional[float] = None
    pro_score: Optional[float] = None


MVTEC_PATH = os.path.expanduser("~/.cache/kagglehub/datasets/ipythonx/mvtec-ad/versions/2")

MVTEC_CATEGORIES = [
    "bottle", "cable", "capsule", "carpet", "grid",
    "hazelnut", "leather", "metal_nut", "pill", "screw",
    "tile", "toothbrush", "transistor", "wood", "zipper",
]


def _load_mvtec_category(category: str):
    from PIL import Image
    import glob
    import numpy as np

    category_path = os.path.join(MVTEC_PATH, category)
    if not os.path.exists(category_path):
        raise ValueError(f"Category '{category}' not found")

    train_dir = os.path.join(category_path, "train", "good")
    train_images = []
    for img_path in sorted(glob.glob(os.path.join(train_dir, "*.png"))):
        img = np.array(Image.open(img_path).convert("RGB"))
        train_images.append({"path": img_path, "image": img})

    test_images = []
    test_root = os.path.join(category_path, "test")
    gt_root = os.path.join(category_path, "ground_truth")

    for defect_type in sorted(os.listdir(test_root)):
        defect_dir = os.path.join(test_root, defect_type)
        if not os.path.isdir(defect_dir):
            continue

        gt_dir = os.path.join(gt_root, defect_type) if defect_type != "good" else None

        for img_path in sorted(glob.glob(os.path.join(defect_dir, "*.png"))):
            img = np.array(Image.open(img_path).convert("RGB"))
            gt_mask = None
            if gt_dir and os.path.exists(gt_dir):
                gt_name = os.path.splitext(os.path.basename(img_path))[0] + "_mask.png"
                gt_path = os.path.join(gt_dir, gt_name)
                if os.path.exists(gt_path):
                    gt_mask = np.array(Image.open(gt_path))

            test_images.append({
                "path": img_path,
                "image": img,
                "label": defect_type,
                "ground_truth_mask": gt_mask,
            })

    return train_images, test_images


def _compute_summary_metrics(detections: list, test_labels: list, ground_truth_masks: list,
                             test_images_list: list, detector) -> dict:
    from sklearn.metrics import roc_auc_score
    import numpy as np

    is_anomaly_true = np.array([label != "good" for label in test_labels])
    image_scores = np.array([d["anomaly_score"] for d in detections])

    if len(np.unique(is_anomaly_true)) > 1:
        auroc_image = roc_auc_score(is_anomaly_true, image_scores)
    else:
        auroc_image = 0.0

    pixel_scores_list, pixel_labels_list = _extract_pixel_data(detections, ground_truth_masks)
    auroc_pixel = _compute_auroc_pixel(pixel_scores_list, pixel_labels_list) if pixel_scores_list else 0.0
    pro_score = _compute_pro_score(pixel_scores_list, ground_truth_masks) if pixel_scores_list else 0.0

    return {
        "auroc_image": auroc_image,
        "auroc_pixel": auroc_pixel,
        "pro_score": pro_score,
    }


def _extract_pixel_data(detections, ground_truth_masks):
    import numpy as np
    pixel_scores_list = []
    pixel_labels_list = []

    for i, det in enumerate(detections):
        if "anomaly_map" in det.get("details", {}):
            amap = det["details"]["anomaly_map"]
        elif "heatmap" in det.get("details", {}):
            hm = det["details"]["heatmap"]
            amap = np.mean(hm, axis=2) if hm.ndim == 3 else hm
        else:
            continue

        gt_mask = ground_truth_masks[i]
        if gt_mask is None:
            gt_binary = np.zeros_like(amap, dtype=np.int32)
        else:
            gt_binary = (gt_mask > 0.5).astype(np.int32)

        pixel_scores_list.append(amap.reshape(-1))
        pixel_labels_list.append(gt_binary.reshape(-1))

    return pixel_scores_list, pixel_labels_list


def _compute_auroc_pixel(pixel_scores_list, pixel_labels_list):
    from sklearn.metrics import roc_auc_score
    import numpy as np
    all_scores = np.concatenate(pixel_scores_list)
    all_labels = np.concatenate(pixel_labels_list)
    if len(np.unique(all_labels)) > 1:
        return roc_auc_score(all_labels, all_scores)
    return 0.0


def _compute_pro_score(pixel_scores_list, ground_truth_masks):
    from statistics import mean
    import numpy as np
    import pandas as pd
    from skimage import measure

    all_scores = np.concatenate(pixel_scores_list)
    min_th = all_scores.min()
    max_th = all_scores.max()
    delta = (max_th - min_th) / 200 if max_th > min_th else 0.001

    df = pd.DataFrame([], columns=["pro", "fpr", "threshold"])
    for th in np.arange(min_th, max_th, delta):
        pros = []
        fps = 0
        tns = 0
        for img_idx in range(len(ground_truth_masks)):
            if ground_truth_masks[img_idx] is None:
                continue
            mask = ground_truth_masks[img_idx]
            amap = pixel_scores_list[img_idx].reshape(mask.shape)
            binary = (amap > th).astype(np.int32)
            labeled = measure.label(mask)
            for region in measure.regionprops(labeled):
                coords = region.coords
                tp = binary[coords[:, 0], coords[:, 1]].sum()
                pros.append(tp / region.area)
            inv_mask = 1 - (mask > 0.5).astype(np.int32)
            fps += np.sum(binary & inv_mask)
            tns += np.sum(inv_mask)

        fpr = fps / max(tns, 1)
        if pros:
            df = pd.concat([
                df,
                pd.DataFrame({"pro": [mean(pros)], "fpr": [fpr], "threshold": [th]})
            ], ignore_index=True)

    if len(df) == 0:
        return 0.0
    df = df[df["fpr"] < 0.3].copy()
    if len(df) == 0:
        return 0.0
    df["fpr"] = df["fpr"] / df["fpr"].max()
    df = df.sort_values("fpr").reset_index(drop=True)
    return float(np.trapezoid(df["pro"].values, df["fpr"].values))


@router.post("/seed")
async def seed_images(db: AsyncSession = Depends(get_db)):
    run_id = str(uuid.uuid4())

    if not os.path.exists(MVTEC_PATH):
        raise HTTPException(
            status_code=500,
            detail=f"MVTec-AD dataset not found at {MVTEC_PATH}. "
            f"Please download it first.",
        )

    categories_loaded = 0
    total_images = 0

    for category in MVTEC_CATEGORIES:
        try:
            train_images, test_images = _load_mvtec_category(category)
            categories_loaded += 1
            total_images += len(train_images) + len(test_images)
            logger.info(f"  Category '{category}': {len(train_images)} train, {len(test_images)} test")
        except Exception as e:
            logger.warning(f"  Category '{category}': skipped ({e})")

    return SeedResponse(
        run_id=run_id,
        categories_loaded=categories_loaded,
        total_images=total_images,
    )


def _init_image_detector(detector_name: str):
    name = detector_name.lower()
    try:
        if name == "anomalyclip":
            from detection.camera.anomaly import AnomalyCLIPDetector
            return AnomalyCLIPDetector("anomalyclip")
        elif name == "ckaad":
            from detection.camera.anomaly import CKAADAnomalyDetector
            return CKAADAnomalyDetector("ckaad", backbone="wide_resnet50_2",
                                        layers=[1, 2, 3], image_size=256,
                                        epochs=20, topk=100, sigma=4)
        elif name == "placeholder":
            from detection.camera.anomaly import PlaceholderImageAnomalyDetector
            return PlaceholderImageAnomalyDetector("pixel_deviation", threshold=0.15)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown detector: {detector_name}. Use: anomalyclip, ckaad, placeholder",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initialize detector: {e}")


def _run_image_inference(detector, test_images_list, test_labels):
    n_anomalies = 0
    detections = []

    name = getattr(detector, "name", "")
    if hasattr(detector, "detect_batch") and "anomalyclip" not in name.lower():
        batch_results = detector.detect_batch(test_images_list)
        for i, res in enumerate(batch_results):
            detections.append({
                "index": i, "label": test_labels[i],
                "score": res.anomaly_score, "is_anomaly": res.is_anomaly,
                "details": res.details,
            })
            if res.is_anomaly:
                n_anomalies += 1
    else:
        for i, img in enumerate(test_images_list):
            res = detector.detect(img)
            detections.append({
                "index": i, "label": test_labels[i],
                "score": res.anomaly_score, "is_anomaly": res.is_anomaly,
                "details": res.details,
            })
            if res.is_anomaly:
                n_anomalies += 1

    return detections, n_anomalies


@router.post("/detect/{detector_name}")
async def detect_images(
    detector_name: str,
    category: str = Query(..., description="MVTec-AD category"),
    run_id: Optional[str] = Query(None, description="Optional run ID"),
    db: AsyncSession = Depends(get_db),
):
    try:
        train_images_data, test_images_data = _load_mvtec_category(category)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    train_images = [d["image"] for d in train_images_data]
    test_images_list = [d["image"] for d in test_images_data]
    test_labels = [d["label"] for d in test_images_data]
    ground_truth_masks = [d.get("ground_truth_mask") for d in test_images_data]
    image_names = [os.path.basename(d["path"]) for d in test_images_data]

    if not train_images or not test_images_list:
        raise HTTPException(status_code=400, detail=f"No images found for category '{category}'")

    detector = _init_image_detector(detector_name)
    logger.info(f"Training {detector_name} on {len(train_images)} images for '{category}'")
    if not detector.fit(train_images):
        if detector_name.lower() != "anomalyclip":
            raise HTTPException(status_code=500, detail=f"Detector {detector_name} failed to train")

    logger.info(f"Detecting anomalies in {len(test_images_list)} test images")
    detections, n_anomalies = _run_image_inference(detector, test_images_list, test_labels)

    metrics = _compute_summary_metrics(detections, test_labels, ground_truth_masks,
                                       test_images_list, detector)

    run_id = run_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    result_rows, alert_rows = _build_image_result_rows(
        detections, metrics, image_names, detector_name, category, run_id, now, db
    )

    if result_rows:
        await db.execute(insert(ImageDetectionResult), result_rows)
    if alert_rows:
        await db.execute(insert(Alert), alert_rows)

    await db.commit()

    return DetectResponse(
        run_id=run_id,
        detector=detector_name.lower(),
        category=category,
        n_anomalies=n_anomalies,
        n_total=len(detections),
        anomaly_ratio=n_anomalies / len(detections) if detections else 0.0,
        auroc_image=metrics["auroc_image"],
        auroc_pixel=metrics["auroc_pixel"],
        pro_score=metrics["pro_score"],
    )


def _build_image_result_rows(detections, metrics, image_names, detector_name, category, run_id, now, db):
    result_rows = []
    alert_rows = []
    detector_name_lower = detector_name.lower()

    for d in detections:
        result_rows.append({
            "category": category,
            "detector": detector_name_lower,
            "run_id": run_id,
            "timestamp": now,
            "image_name": image_names[d["index"]] if d["index"] < len(image_names) else None,
            "label": d["label"],
            "is_anomaly": d["is_anomaly"],
            "anomaly_score": d["score"],
            "auroc_image": metrics["auroc_image"],
            "auroc_pixel": metrics["auroc_pixel"],
            "pro_score": metrics["pro_score"],
            "details": d["details"],
        })

        if d["is_anomaly"]:
            severity = "medium" if d["score"] >= 0.5 else "low"
            source_id = f"image_{category}"
            alert_rows.append({
                "source_id": source_id,
                "alert_type": "anomaly",
                "severity": severity,
                "message": f"{detector_name}: anomaly in '{category}' image "
                f"{image_names[d['index']]} (label={d['label']}, "
                f"score={d['score']:.4f})",
                "score": d["score"],
                "run_id": run_id,
                "timestamp": now,
            })

            fire_annotation(
                source_id=source_id,
                score=d["score"],
                severity=severity,
                detector_name=detector_name,
                message=f"{detector_name}: anomaly in '{category}' image "
                f"{image_names[d['index']]} (score={d['score']:.4f})",
                db=db,
            )

    return result_rows, alert_rows


@router.get("/results")
async def get_image_results(
    category: Optional[str] = Query(None),
    detector: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ImageDetectionResult).order_by(ImageDetectionResult.id.desc()).limit(limit)

    if category:
        stmt = stmt.where(ImageDetectionResult.source_id == category)
    if detector:
        stmt = stmt.where(ImageDetectionResult.detector == detector)
    if run_id:
        stmt = stmt.where(ImageDetectionResult.run_id == run_id)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    return [
        ImageResultResponse(
            id=r.id,
            category=r.source_id,
            detector=r.detector,
            run_id=r.run_id,
            timestamp=r.timestamp,
            image_name=r.image_name,
            label=r.label,
            is_anomaly=r.is_anomaly,
            anomaly_score=r.anomaly_score,
            auroc_image=r.auroc_image,
            auroc_pixel=r.auroc_pixel,
            pro_score=r.pro_score,
        )
        for r in rows
    ]


ANOMALY_FRAME_DIR = Path("/anomaly_frames")


@router.get("/anomaly/{zone_name}/{camera_id}/{timestamp}")
async def get_anomaly_frame(zone_name: str, camera_id: str, timestamp: int):
    path = ANOMALY_FRAME_DIR / zone_name / camera_id / f"{timestamp}.png"
    if not path.exists():
        path = ANOMALY_FRAME_DIR / zone_name / camera_id / f"{timestamp}.jpg"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Anomaly frame not found")
    return FileResponse(str(path), media_type="image/png")


@router.get("/anomaly/{zone_name}/{camera_id}/{timestamp}/heatmap")
async def get_anomaly_heatmap(zone_name: str, camera_id: str, timestamp: int):
    path = ANOMALY_FRAME_DIR / zone_name / camera_id / f"{timestamp}_heatmap.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Anomaly heatmap not found")
    return FileResponse(str(path), media_type="image/png")


@router.get("/anomaly/{zone_name}/{camera_id}/{timestamp}/overlay")
async def get_anomaly_overlay(zone_name: str, camera_id: str, timestamp: int):
    from PIL import Image
    import io
    orig_path = ANOMALY_FRAME_DIR / zone_name / camera_id / f"{timestamp}.png"
    heat_path = ANOMALY_FRAME_DIR / zone_name / camera_id / f"{timestamp}_heatmap.png"
    if not orig_path.exists():
        raise HTTPException(status_code=404, detail="Anomaly frame not found")
    orig = Image.open(str(orig_path)).convert("RGBA")
    if heat_path.exists():
        heat = Image.open(str(heat_path)).convert("L").resize(orig.size, Image.BILINEAR)
        h = np.array(heat, dtype=np.float32) / 255.0
        r = np.clip((h - 0.35) * 4, 0, 1)
        g = np.clip(1 - np.abs(h - 0.5) * 3.5, 0, 1)
        b = np.clip((0.5 - h) * 3.5, 0, 1)
        alpha = np.clip(h * 0.75, 0, 1)
        overlay_arr = np.stack([
            (r * 255).clip(0, 255).astype(np.uint8),
            (g * 255).clip(0, 255).astype(np.uint8),
            (b * 255).clip(0, 255).astype(np.uint8),
            (alpha * 255).clip(0, 255).astype(np.uint8),
        ], axis=-1)
        overlay = Image.fromarray(overlay_arr, "RGBA")
        orig = Image.alpha_composite(orig, overlay)
    out = orig.convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")
