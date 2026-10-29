"""
API: детекция паводка по руслу — отдельный роутер /flood/*.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import cv2
from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel

from flood_contour import (
    auto_canny_thresholds,
    compare_to_baseline,
    draw_frame_caption,
    extract_main_contours,
    snapshot_from_contours,
)

router = APIRouter(prefix="/flood", tags=["flood-contours"])

DATA_DIR = os.path.join(os.getcwd(), "data")
FLOOD_OUTPUT_DIR = os.path.join(DATA_DIR, "flood_frames")
os.makedirs(FLOOD_OUTPUT_DIR, exist_ok=True)

FLOOD_JOBS: Dict[str, Dict[str, Any]] = {}
FLOOD_JOBS_LOCK = threading.Lock()


class FloodJobResponse(BaseModel):
    job_id: str
    message: str


def _save_upload_video(video: UploadFile) -> str:
    if not video.filename or not video.filename.lower().endswith((".mp4", ".avi", ".mov", ".mkv", ".webm")):
        raise HTTPException(status_code=400, detail="Нужен видеофайл (mp4, avi, mov, mkv, webm)")
    temp_path = tempfile.mktemp(suffix=os.path.splitext(video.filename)[1] or ".mp4")
    with open(temp_path, "wb") as f:
        shutil.copyfileobj(video.file, f)
    cap = cv2.VideoCapture(temp_path)
    if not cap.isOpened():
        os.unlink(temp_path)
        raise HTTPException(status_code=400, detail="Не удалось открыть видео")
    cap.release()
    return temp_path


def _init_job(job_id: str, output_dir: str, params: Dict[str, Any]) -> None:
    with FLOOD_JOBS_LOCK:
        FLOOD_JOBS[job_id] = {
            "status": "running",
            "message": "Анализ контуров запущен",
            "output_dir": output_dir,
            "params": params,
            "processed_frames": 0,
            "total_frames": None,
            "started_at": time.time(),
            "finished_at": None,
            "error": None,
            "baseline": None,
            "summary": None,
            "frames": [],
        }


def _update_job(job_id: str, **kwargs: Any) -> None:
    with FLOOD_JOBS_LOCK:
        if job_id in FLOOD_JOBS:
            FLOOD_JOBS[job_id].update(kwargs)


def _get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with FLOOD_JOBS_LOCK:
        return FLOOD_JOBS.get(job_id)


def process_flood_video_job(
    job_id: str,
    video_path: str,
    *,
    frame_stride: int,
    detection_mode: str,
    canny_low: int,
    canny_high: int,
    use_auto_canny: bool,
    max_contours: int,
    min_contour_area_frac: float,
    min_bbox_area_frac: float,
    roi_y_start_frac: float,
    roi_y_end_frac: float,
    exclude_top_frac: float,
    flood_score_threshold: float,
    max_duration_sec: Optional[float],
) -> None:
    output_dir = os.path.join(FLOOD_OUTPUT_DIR, job_id)
    os.makedirs(output_dir, exist_ok=True)
    params = {
        "frame_stride": frame_stride,
        "detection_mode": detection_mode,
        "canny_low": canny_low,
        "canny_high": canny_high,
        "use_auto_canny": use_auto_canny,
        "max_contours": max_contours,
        "min_contour_area_frac": min_contour_area_frac,
        "min_bbox_area_frac": min_bbox_area_frac,
        "roi_y_start_frac": roi_y_start_frac,
        "roi_y_end_frac": roi_y_end_frac,
        "exclude_top_frac": exclude_top_frac,
        "flood_score_threshold": flood_score_threshold,
    }
    _init_job(job_id, output_dir, params)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        _update_job(job_id, status="error", error="Не удалось открыть видео")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    _update_job(job_id, total_frames=total_frames)

    baseline_snap = None
    used_low, used_high = canny_low, canny_high
    frame_idx = 0
    saved = 0
    comparisons: List[Dict[str, Any]] = []
    alert_frames = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if max_duration_sec is not None and frame_idx / fps > float(max_duration_sec):
                break

            if frame_idx % max(1, frame_stride) != 0:
                frame_idx += 1
                continue

            annotated, edges, contours, (y0, y1), source, raw_count, wl_y = extract_main_contours(
                frame,
                detection_mode=detection_mode,
                canny_low=canny_low,
                canny_high=canny_high,
                min_contour_area_frac=min_contour_area_frac,
                min_bbox_area_frac=min_bbox_area_frac,
                max_contours=max_contours,
                roi_y_start_frac=roi_y_start_frac,
                roi_y_end_frac=roi_y_end_frac,
                use_auto_canny=use_auto_canny,
                exclude_top_frac=exclude_top_frac,
            )
            if saved == 0 and detection_mode == "canny":
                gray = cv2.cvtColor(frame[y0:y1], cv2.COLOR_BGR2GRAY)
                used_low, used_high = (
                    auto_canny_thresholds(cv2.GaussianBlur(gray, (5, 5), 0))
                    if use_auto_canny
                    else (canny_low, canny_high)
                )

            rh = max(1, y1 - y0)
            snap = snapshot_from_contours(
                contours, (rh, frame.shape[1]), edges, source, raw_count, wl_y,
            )
            t_sec = frame_idx / fps

            if baseline_snap is None:
                baseline_snap = snap
                area_delta, waterline_rise, score, alert = 0.0, 0.0, 0.0, False
            else:
                area_delta, waterline_rise, score, alert = compare_to_baseline(
                    snap,
                    baseline_snap,
                    flood_score_threshold=flood_score_threshold,
                )

            if alert:
                alert_frames += 1

            comp = {
                "frame_index": frame_idx,
                "time_sec": round(t_sec, 2),
                "snapshot": snap.to_dict(),
                "area_delta_frac": round(area_delta, 5),
                "waterline_rise_frac": round(waterline_rise, 5),
                "flood_score": round(score, 5),
                "flood_alert": alert,
            }
            comparisons.append(comp)

            out_img = draw_frame_caption(
                annotated,
                time_sec=t_sec,
                snap=snap,
                area_delta=area_delta,
                waterline_rise=waterline_rise,
                score=score,
                alert=alert,
                canny_low=used_low,
                canny_high=used_high,
                edges=edges,
                y0=y0,
            )
            fname = f"frame_{saved:05d}_t{t_sec:.1f}s.jpg"
            cv2.imwrite(os.path.join(output_dir, fname), out_img)
            saved += 1
            frame_idx += 1

            if saved % 5 == 0:
                _update_job(job_id, processed_frames=saved, frames=comparisons[-20:])

        if baseline_snap is None:
            _update_job(job_id, status="error", error="Не удалось прочитать ни одного кадра")
            return

        flood_detected = alert_frames > 0
        max_score = max((c["flood_score"] for c in comparisons), default=0.0)
        no_contours = baseline_snap.n_contours == 0
        summary = {
            "method": "color_segmentation_vs_baseline",
            "frames_analyzed": saved,
            "flood_detected": flood_detected,
            "alert_frames": alert_frames,
            "max_flood_score": max_score,
            "flood_score_threshold": flood_score_threshold,
            "canny_low": used_low,
            "canny_high": used_high,
            "baseline": baseline_snap.to_dict(),
            "warning": (
                "Русло не найдено на опорном кадре: проверьте ROI и миниатюру score справа. "
                "Попробуйте roi_y_start_frac=0.4, exclude_top_frac=0.35."
                if no_contours
                else None
            ),
            "interpretation": {
                "area_delta_frac": "рост суммарной площади крупных контуров относительно 1-го кадра",
                "waterline_rise_frac": "смещение верхней границы главного контура вверх (больше = выше вода)",
                "flood_score": "0.6·Δплощадь + 0.4·Δлиния_воды (если оба ≥ 0)",
            },
        }
        with open(os.path.join(output_dir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "frames": comparisons}, f, ensure_ascii=False, indent=2)

        _update_job(
            job_id,
            status="completed",
            message="Готово",
            processed_frames=saved,
            finished_at=time.time(),
            baseline=baseline_snap.to_dict(),
            summary=summary,
            frames=comparisons,
        )
    except Exception as e:
        _update_job(job_id, status="error", error=str(e))
    finally:
        cap.release()
        if os.path.exists(video_path):
            try:
                os.unlink(video_path)
            except OSError:
                pass


@router.post("/process_video", response_model=FloodJobResponse)
async def flood_process_video(
    video: UploadFile = File(..., description="Видео с руслом/водой"),
    frame_stride: int = Form(10, description="Анализировать каждый N-й кадр"),
    detection_mode: str = Form(
        "river",
        description="river — сегментация по цвету Lab+K-means, контуры на границах областей; canny — Canny",
    ),
    canny_low: int = Form(30, description="Canny low (только для detection_mode=canny)"),
    canny_high: int = Form(120, description="Canny high"),
    use_auto_canny: bool = Form(True, description="Автопорог Canny (режим canny)"),
    max_contours: int = Form(2, description="Макс. контуров (режим canny)"),
    min_contour_area_frac: float = Form(0.0003, description="Мин. площадь контура (canny)"),
    min_bbox_area_frac: float = Form(0.002, description="Мин. площадь bbox (canny)"),
    roi_y_start_frac: float = Form(0.35, description="ROI: верх (0..1)"),
    roi_y_end_frac: float = Form(1.0, description="ROI: низ"),
    exclude_top_frac: float = Form(
        0.3,
        description="Игнор верхней доли ROI при поиске воды (мост/деревья), 0.3 = верхние 30%",
    ),
    flood_score_threshold: float = Form(0.08, description="Порог score (паводок = линия воды поднялась)"),
    max_duration_sec: Optional[float] = Form(None, description="Ограничение длины видео, сек"),
):

    if frame_stride < 1:
        raise HTTPException(status_code=400, detail="frame_stride должен быть >= 1")
    if max_contours < 1:
        raise HTTPException(status_code=400, detail="max_contours должен быть >= 1")
    mode = (detection_mode or "river").strip().lower()
    if mode not in ("river", "waterline", "canny"):
        raise HTTPException(status_code=400, detail="detection_mode: river, waterline или canny")

    temp_video = _save_upload_video(video)
    job_id = str(uuid.uuid4())
    worker = threading.Thread(
        target=process_flood_video_job,
        kwargs={
            "job_id": job_id,
            "video_path": temp_video,
            "frame_stride": frame_stride,
            "detection_mode": mode,
            "canny_low": canny_low,
            "canny_high": canny_high,
            "use_auto_canny": use_auto_canny,
            "max_contours": max_contours,
            "min_contour_area_frac": min_contour_area_frac,
            "min_bbox_area_frac": min_bbox_area_frac,
            "roi_y_start_frac": roi_y_start_frac,
            "roi_y_end_frac": roi_y_end_frac,
            "exclude_top_frac": exclude_top_frac,
            "flood_score_threshold": flood_score_threshold,
            "max_duration_sec": max_duration_sec,
        },
        daemon=True,
    )
    worker.start()
    return FloodJobResponse(job_id=job_id, message="Задача анализа контуров запущена")


@router.get("/jobs/{job_id}")
async def flood_job_status(job_id: str):
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return job


@router.get("/jobs/{job_id}/download")
async def flood_job_download(job_id: str):
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    output_dir = job.get("output_dir")
    if not output_dir or not os.path.isdir(output_dir):
        raise HTTPException(status_code=404, detail="Архив ещё не готов")

    archive_base = os.path.join(DATA_DIR, f"flood_contours_{job_id}")
    archive_path = shutil.make_archive(archive_base, "zip", output_dir)
    with open(archive_path, "rb") as f:
        content = f.read()
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=flood_contours_{job_id}.zip"},
    )
