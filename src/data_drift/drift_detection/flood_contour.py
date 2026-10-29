"""
Детекция воды
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class ContourSnapshot:
    n_contours: int
    total_area_frac: float
    largest_area_frac: float
    mean_centroid_y_frac: float
    waterline_y_frac: Optional[float]
    edge_pixel_frac: float = 0.0
    raw_contours_before_filter: int = 0
    detection_source: str = "river"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clip_roi_bounds(h: int, w: int, roi_y_start_frac: float, roi_y_end_frac: float) -> Tuple[int, int]:
    y0 = int(max(0.0, min(1.0, roi_y_start_frac)) * h)
    y1 = int(max(0.0, min(1.0, roi_y_end_frac)) * h)
    if y1 <= y0:
        y1 = min(h, y0 + 1)
    return y0, y1


def auto_canny_thresholds(gray: np.ndarray, sigma: float = 0.33) -> Tuple[int, int]:
    v = float(np.median(gray))
    lower = int(max(0, (1.0 - sigma) * v))
    upper = int(min(255, (1.0 + sigma) * v * 1.5))
    return lower, max(upper, lower + 20)


def _local_texture_std(gray: np.ndarray, ksize: int = 15) -> np.ndarray:
    g = gray.astype(np.float32)
    mean = cv2.boxFilter(g, ddepth=-1, ksize=(ksize, ksize))
    mean_sq = cv2.boxFilter(g * g, ddepth=-1, ksize=(ksize, ksize))
    return np.sqrt(np.maximum(mean_sq - mean * mean, 0.0))


def _lab_color_gradient(lab: np.ndarray) -> np.ndarray:
    grad = np.zeros(lab.shape[:2], np.float32)
    for c in range(3):
        gx = cv2.Scharr(lab[:, :, c], cv2.CV_32F, 1, 0)
        gy = cv2.Scharr(lab[:, :, c], cv2.CV_32F, 0, 1)
        grad += gx * gx + gy * gy
    return np.sqrt(grad)


def _region_boundary_strength(label_id: int, labels: np.ndarray, grad: np.ndarray) -> float:
    mask = labels == label_id
    er = cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8), 1).astype(bool)
    border = mask & ~er
    if border.sum() < 8:
        return 0.0
    return float(grad[border].mean())


def _color_region_labels(sub_bgr: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    smooth = cv2.pyrMeanShiftFiltering(sub_bgr, sp=8, sr=22)
    lab = cv2.cvtColor(smooth, cv2.COLOR_BGR2LAB).astype(np.float32)
    gray = cv2.cvtColor(smooth, cv2.COLOR_BGR2GRAY)
    tex = _local_texture_std(gray, 13)
    grad = _lab_color_gradient(lab)
    tex_n = np.clip(tex / (float(np.percentile(tex, 90)) + 1e-6), 0.0, 1.0)
    grad_eff = grad * (1.0 - 0.85 * tex_n)
    thr = float(np.percentile(grad_eff, 74))
    edges = (grad_eff >= thr).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    edges = cv2.dilate(edges, k, 1)
    closed = cv2.morphologyEx(255 - edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)), 2)
    _, labels = cv2.connectedComponents(closed)
    return labels, grad_eff, lab, tex


def _pick_water_region(labels: np.ndarray, grad: np.ndarray, lab: np.ndarray, tex: np.ndarray) -> int:
    h, w = labels.shape
    frame = max(1, h * w)
    tex_med = float(np.median(tex))
    L_hi = float(np.percentile(lab[:, :, 0], 88))
    best_id, best_score = -1, -1.0
    for rid in range(1, int(labels.max()) + 1):
        mask = labels == rid
        area = int(mask.sum())
        if area < frame * 0.02:
            continue
        tex_mean = float(tex[mask].mean())
        L_mean = float(lab[:, :, 0][mask].mean())
        a_mean = float(lab[:, :, 1][mask].mean())
        if L_mean > L_hi:
            continue
        mu8 = mask.astype(np.uint8)
        x, y, bw, bh = cv2.boundingRect(mu8 * 255)
        if bw < w * 0.08 or bh < h * 0.04:
            continue
        bnd = _region_boundary_strength(rid, labels, grad)
        if bnd < float(np.percentile(grad, 55)) * 0.85:
            continue
        homog = 1.0 / (tex_mean / (tex_med + 1e-6) + 0.1)
        if a_mean > 138:
            continue
        green_pen = 1.0 if a_mean < 132 else max(0.2, 1.0 - (a_mean - 132) / 30.0)
        aspect = bw / max(bh, 1)
        width_frac = bw / max(w, 1)
        if aspect < 0.2:
            continue
        score = (area / frame) * bnd * homog * green_pen * min(2.0, aspect + 0.15) * (0.4 + width_frac)
        if score > best_score:
            best_score, best_id = score, rid
    return best_id


def _boundary_debug(labels: np.ndarray, grad: np.ndarray) -> np.ndarray:
    lbl = labels.astype(np.int32)
    gx = np.abs(np.diff(lbl, axis=1, prepend=lbl[:, :1]))
    gy = np.abs(np.diff(lbl, axis=0, prepend=lbl[:1, :]))
    edge = ((gx > 0) | (gy > 0)).astype(np.uint8) * 255
    mix = cv2.addWeighted(
        cv2.applyColorMap(cv2.normalize(grad, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8), cv2.COLORMAP_TURBO),
        0.55,
        cv2.cvtColor(edge, cv2.COLOR_GRAY2BGR),
        0.45,
        0,
    )
    return mix


def _segment_water_mask(roi_bgr: np.ndarray, exclude_top_frac: float) -> Tuple[Optional[np.ndarray], np.ndarray, int]:
    h = roi_bgr.shape[0]
    y_off = int(h * max(0.0, min(0.45, exclude_top_frac)))
    if y_off >= h - 24:
        y_off = 0
    sub = roi_bgr[y_off:]
    sh, sw = sub.shape[:2]
    labels, grad, lab, tex = _color_region_labels(sub)
    rid = _pick_water_region(labels, grad, lab, tex)
    debug = _boundary_debug(labels, grad)
    if rid < 0:
        return None, debug, y_off
    mask = (labels == rid).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, 2), cv2.MORPH_OPEN, k, 1)
    if mask.sum() < sh * sw * 0.015:
        return None, debug, y_off
    return mask, debug, y_off


def _best_contour(mask: np.ndarray, min_area_frac: float = 0.015):
    sh, sw = mask.shape[:2]
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cnts:
        if cv2.contourArea(c) >= min_area_frac * sh * sw:
            if best is None or cv2.contourArea(c) > cv2.contourArea(best):
                best = c
    return best, len(cnts)


def extract_river_contours(bgr, *, roi_y_start_frac, roi_y_end_frac, exclude_top_frac=0.3):
    h, w = bgr.shape[:2]
    y0, y1 = _clip_roi_bounds(h, w, roi_y_start_frac, roi_y_end_frac)
    roi = bgr[y0:y1, :]
    mask, debug, y_off = _segment_water_mask(roi, exclude_top_frac)
    raw_count = 0
    contour = None
    if mask is not None:
        contour, raw_count = _best_contour(mask, 0.015)
    contours, waterline_y = [], None
    if contour is not None:
        c = contour.copy()
        c[:, :, 1] += y_off
        contours = [c]
        waterline_y = y_off + int(np.min(contour[:, 0, 1]))
    annotated = bgr.copy()
    cv2.rectangle(annotated, (0, y0), (w - 1, y1 - 1), (255, 200, 0), 2)
    if contours:
        c_draw = contours[0].copy()
        c_draw[:, :, 1] += y0
        overlay = annotated.copy()
        cv2.drawContours(overlay, [c_draw], -1, (255, 160, 0), -1)
        annotated = cv2.addWeighted(overlay, 0.35, annotated, 0.65, 0)
        cv2.drawContours(annotated, [c_draw], -1, (0, 255, 255), 3)
        if waterline_y is not None:
            cv2.line(annotated, (0, y0 + waterline_y), (w - 1, y0 + waterline_y), (0, 255, 255), 2)
    return annotated, debug, contours, (y0, y1), "color_seg", raw_count, waterline_y


def extract_canny_contours(bgr, *, canny_low, canny_high, min_contour_area_frac, min_bbox_area_frac,
                           max_contours, roi_y_start_frac, roi_y_end_frac, use_auto_canny, exclude_top_frac):
    h, w = bgr.shape[:2]
    y0, y1 = _clip_roi_bounds(h, w, roi_y_start_frac, roi_y_end_frac)
    roi = bgr[y0:y1, :]
    gray = cv2.GaussianBlur(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), (7, 7), 0)
    low, high = auto_canny_thresholds(gray) if use_auto_canny else (canny_low, canny_high)
    edges = cv2.Canny(gray, low, high)
    roi_area = max(1, roi.shape[0] * roi.shape[1])
    raw, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    y_cut = roi.shape[0] * exclude_top_frac
    kept = [c for c in raw if cv2.contourArea(c) >= min_contour_area_frac * roi_area
            and cv2.boundingRect(c)[2] >= roi.shape[1] * 0.15
            and (not cv2.moments(c)["m00"] or cv2.moments(c)["m01"] / cv2.moments(c)["m00"] >= y_cut)]
    kept.sort(key=cv2.contourArea, reverse=True)
    contours = kept[:max(1, int(max_contours))]
    annotated = bgr.copy()
    cv2.rectangle(annotated, (0, y0), (w - 1, y1 - 1), (255, 200, 0), 2)
    for i, c in enumerate(contours):
        cg = c.copy()
        cg[:, :, 1] += y0
        cv2.drawContours(annotated, [cg], -1, (0, 255, 255) if i == 0 else (0, 200, 0), 3)
    return annotated, edges, contours, (y0, y1), "canny", len(raw)


def extract_main_contours(bgr, *, detection_mode="river", canny_low=30, canny_high=120,
                          min_contour_area_frac=0.0003, min_bbox_area_frac=0.002, max_contours=2,
                          roi_y_start_frac=0.35, roi_y_end_frac=1.0, use_auto_canny=True,
                          exclude_top_frac=0.3, **kw):
    mode = (detection_mode or "river").strip().lower()
    if mode in ("waterline", "river", "color", "color_seg"):
        return extract_river_contours(bgr, roi_y_start_frac=roi_y_start_frac,
                                      roi_y_end_frac=roi_y_end_frac, exclude_top_frac=exclude_top_frac)
    a, e, c, b, s, r = extract_canny_contours(
        bgr, canny_low=canny_low, canny_high=canny_high, min_contour_area_frac=min_contour_area_frac,
        min_bbox_area_frac=min_bbox_area_frac, max_contours=max_contours, roi_y_start_frac=roi_y_start_frac,
        roi_y_end_frac=roi_y_end_frac, use_auto_canny=use_auto_canny, exclude_top_frac=exclude_top_frac)
    return a, e, c, b, s, r, None


def snapshot_from_contours(contours, roi_shape, edges, source, raw_count, waterline_y_roi=None):
    rh, rw = roi_shape
    roi_area = max(1, rh * rw)
    edge_frac = float(np.count_nonzero(edges)) / (roi_area * 3 if edges is not None and edges.ndim == 3 else roi_area)
    wl_frac = float(waterline_y_roi / max(1, rh)) if waterline_y_roi is not None else None
    if not contours:
        return ContourSnapshot(0, 0, 0, 0, wl_frac, round(edge_frac, 5), raw_count, source)
    areas = [float(cv2.contourArea(c)) for c in contours]
    total = sum(areas)
    cy_sum = sum((cv2.moments(c)["m01"] / cv2.moments(c)["m00"]) * a
                 for c, a in zip(contours, areas) if cv2.moments(c)["m00"] > 0)
    mean_cy = cy_sum / max(total, 1e-9)
    _, y, _, _ = cv2.boundingRect(max(contours, key=cv2.contourArea))
    if wl_frac is None:
        wl_frac = float(y / max(1, rh))
    return ContourSnapshot(len(contours), total / roi_area, max(areas) / roi_area,
                           float(mean_cy / max(1, rh)), wl_frac, round(edge_frac, 5), raw_count, source)


def compare_to_baseline(snap, baseline, area_weight=0.45, waterline_weight=0.55, flood_score_threshold=0.06):
    area_delta = snap.total_area_frac - baseline.total_area_frac
    waterline_rise = 0.0
    if snap.waterline_y_frac is not None and baseline.waterline_y_frac is not None:
        waterline_rise = baseline.waterline_y_frac - snap.waterline_y_frac
    score = area_weight * max(0.0, area_delta) + waterline_weight * max(0.0, waterline_rise)
    return area_delta, waterline_rise, score, score >= float(flood_score_threshold)


def draw_frame_caption(image, *, time_sec, snap, area_delta, waterline_rise, score, alert,
                       canny_low, canny_high, edges=None, y0=0):
    out = image.copy()
    if edges is not None and edges.size > 0:
        thumb = cv2.resize(edges, (max(1, int(edges.shape[1] * 88 / max(1, edges.shape[0]))), 88))
        x_off = out.shape[1] - thumb.shape[1] - 8
        out[y0 + 8:y0 + 8 + thumb.shape[0], x_off:x_off + thumb.shape[1]] = thumb
    wl_s = f"{snap.waterline_y_frac:.3f}" if snap.waterline_y_frac is not None else "—"
    lines = [f"t={time_sec:.1f}s {snap.detection_source} n={snap.n_contours}",
             f"waterline={wl_s} area={snap.total_area_frac:.3f} d_w={waterline_rise:+.3f}",
             f"score={score:.3f} {'ПАВОДОК' if alert else 'норма'}"]
    y = 22
    for i, line in enumerate(lines):
        cv2.putText(out, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 0, 255) if alert and i == 2 else (255, 255, 255), 1, cv2.LINE_AA)
        y += 20
    return out
