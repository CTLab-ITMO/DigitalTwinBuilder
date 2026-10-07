import os
import time

from typing import Sequence

from app.models import RegisteredSource, Zone

# Where the browser running Grafana reaches the anomaly API. The detector
# control panel below calls it from the user's machine (Train, detector
# toggles, status poll), so this is the published port, not the in-network one
# (the API listens on 8000 inside compose; docker-compose.yml maps 8001).
ANOMALY_API_PUBLIC_URL = os.environ.get(
    "ANOMALY_API_PUBLIC_URL", "http://localhost:8001"
).rstrip("/")

GRID_COLUMNS = 24

HEADER_Y = 0
SUMMARY_H = 3
SUMMARY_W = 6
CRITICAL_ALERTS_W = 6
DETECTOR_CTRL_H = 6
DETECTOR_CTRL_W = 12

ROW_SEP_H = 1
ROW_SEP_Y = 7

SENSOR_H = 8
SENSOR_W = 12
SENSOR_COLS = GRID_COLUMNS // SENSOR_W

CAMERA_H = 8
CAMERA_COLS = 3
CAMERA_W = GRID_COLUMNS // CAMERA_COLS

ALERTS_H = 8
ALERTS_W = GRID_COLUMNS

CONTENT_START_Y = 7


def _make_sensor_panel(source: RegisteredSource, idx: int) -> dict:
    sid = source.source_id
    title = f"Sensor: {source.display_name or sid} ({sid})"

    return {
        "title": title,
        "type": "timeseries",
        "id": idx,
        "gridPos": {"h": SENSOR_H, "w": SENSOR_W, "x": 0 if idx % SENSOR_COLS == 0 else SENSOR_W, "y": CONTENT_START_Y + (idx // SENSOR_COLS) * SENSOR_H},
        "fieldConfig": {
            "defaults": {
                "custom": {"lineWidth": 1, "fillOpacity": 20, "showPoints": "never"},
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "anomalous_value"},
                    "properties": [
                        {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}},
                        {"id": "custom.lineWidth", "value": 0},
                        {"id": "custom.fillOpacity", "value": 0},
                        {"id": "custom.showPoints", "value": "auto"},
                        {"id": "custom.pointSize", "value": 4},
                        {"id": "displayName", "value": "anomaly"},
                    ],
                }
            ],
        },
        "options": {
            "legend": {"showLegend": True, "placement": "bottom", "calcs": ["mean", "stdDev"]},
            "tooltip": {"mode": "multi"},
        },
        "targets": [
            {
                "datasource": {"type": "postgres", "uid": "postgres"},
                "format": "table",
                "rawSql": (
                    f"SELECT sr.timestamp, sr.value "
                    f"FROM sensor_readings sr "
                    f"WHERE sr.channel_id = '{sid}' "
                    f"ORDER BY sr.timestamp DESC LIMIT 5000"
                ),
                "refId": "A",
            },
            {
                "datasource": {"type": "postgres", "uid": "postgres"},
                "format": "table",
                "rawSql": (
                    f"SELECT sar.timestamp, sar.value AS anomalous_value "
                    f"FROM sensor_anomaly_results sar "
                    f"WHERE sar.source_id = '{sid}' AND sar.is_anomaly = true "
                    # `:sqlstring`/`IN (...)` collapse to `IN ()` when the
                    # variable has no options (e.g. right after the results
                    # table is emptied), and that is a SQL syntax error. `:csv`
                    # inside a quoted literal degrades to `''` instead, and
                    # NULLIF turns that into an empty match set -- no rows, no
                    # parse error -- while a populated list still filters.
                    f"AND sar.detector = ANY(string_to_array(NULLIF('${{detector:csv}}', ''), ',')) "
                    f"AND ('$run_id' = '' OR sar.run_id = '$run_id') "
                    f"ORDER BY sar.timestamp DESC LIMIT 5000"
                ),
                "refId": "B",
            },
        ],
        "transformations": [],
    }


def _make_camera_panel(source: RegisteredSource, idx: int, y_offset: int) -> dict:
    sid = source.source_id
    title = f"Camera: {source.display_name or sid} ({sid})"
    stream_url = f"http://localhost:8500/{sid}/mjpeg"
    width = CAMERA_W
    return {
        "title": title,
        "type": "text",
        "id": idx,
        "gridPos": {"h": CAMERA_H, "w": width, "x": width * (idx % CAMERA_COLS), "y": y_offset + (idx // CAMERA_COLS) * CAMERA_H},
        "options": {
            "mode": "html",
            "content": (
                f"<img src=\"{stream_url}\" "
                f"style=\"width:100%;height:100%;object-fit:contain;background:cover;\" "
                f"alt=\"Camera: {sid}\">"
            ),
        },
        "disable_sanitize_html": True,
    }


def _sql_str(value: str) -> str:
    """A SQL string literal. Zone names now come from a session title, so a
    stray quote would otherwise end the literal early."""
    return "'" + value.replace("'", "''") + "'"


def _make_alerts_panel(idx: int, y: int, zone_id: int) -> dict:
    return {
        "title": "Recent Alerts",
        "type": "table",
        "id": idx,
        "gridPos": {"h": ALERTS_H, "w": ALERTS_W, "x": 0, "y": y},
        "fieldConfig": {
            "defaults": {
                "custom": {"align": "left"},
                "color": {
                    "mode": "thresholds",
                    "seriesBy": "last",
                },
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"value": -1e9, "color": "green"},
                        {"value": 1, "color": "orange"},
                        {"value": 2, "color": "red"},
                    ],
                },
                "mappings": [
                    {
                        "type": "value",
                        "options": {
                            "low": {"color": "green", "text": "low"},
                            "medium": {"color": "orange", "text": "medium"},
                            "high": {"color": "red", "text": "high"},
                            "critical": {"color": "purple", "text": "critical"},
                        },
                    }
                ],
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "severity"},
                    "properties": [
                        {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                    ],
                },
                {
                    "matcher": {"id": "byName", "options": "snapshot"},
                    "properties": [
                        {
                            "id": "links",
                            "value": [
                                {
                                    "title": "view",
                                    "url": "${__value.text}",
                                    "targetBlank": True,
                                }
                            ],
                        },
                        {
                            "id": "displayName",
                            "value": "snapshot",
                        },
                    ],
                },
            ],
        },
        "options": {
            "sortBy": [{"displayName": "Time", "desc": True}],
        },
        "targets": [
            {
                "datasource": {"type": "postgres", "uid": "postgres"},
                "format": "table",
                "rawSql": (
                    "SELECT sar.timestamp, sar.source_id AS source, "
                    "sar.anomaly_score AS score, "
                    "sar.details->>'severity' AS severity, '' AS snapshot "
                    "FROM sensor_anomaly_results sar "
                    "JOIN registered_sources rs ON rs.source_id = sar.source_id "
                    f"WHERE sar.is_anomaly = true AND rs.zone_id = {zone_id} "
                    "UNION ALL "
                    "SELECT idr.timestamp, "
                    "idr.details->>'camera_id' AS source, "
                    "idr.anomaly_score AS score, "
                    "idr.details->>'severity' AS severity, "
                    # The heatmap overlay is the picture that shows *where* the
                    # anomaly is, so prefer it over the bare frame; fall back to
                    # the frame when the detector could not build one.
                    "COALESCE(NULLIF(idr.details->>'heatmap_url', ''), "
                    "         idr.details->>'anomaly_image_url') AS snapshot "
                    "FROM image_detection_results idr "
                    "JOIN registered_sources rs ON rs.source_id = idr.source_id "
                    "WHERE idr.is_anomaly = true AND "
                    "  COALESCE(NULLIF(idr.details->>'heatmap_url', ''), "
                    "           idr.details->>'anomaly_image_url') != '' "
                    f"  AND rs.zone_id = {zone_id} "
                    "ORDER BY timestamp DESC LIMIT 50"
                ),
                "refId": "A",
            }
        ],
    }


# Grafana answers `400 dashboard tag too long, max 50 characters` and refuses
# the whole save. It counts *bytes*, not characters: measured against Grafana
# 13, 49 ASCII and 25 Cyrillic characters pass, 51 ASCII and 26 Cyrillic do not.
MAX_TAG_BYTES = 50


def _zone_tag(zone: Zone) -> str:
    """The zone's dashboard tag, inside Grafana's 50-byte cap.

    A zone is named after the session title, which is arbitrary user text and
    is often Cyrillic — two bytes per character, so a 26-character title is
    already over the limit and its dashboard could never be saved. The title
    still carries the name in full; the tag is a search handle, so it slugifies
    to ASCII and falls back to the zone id when nothing survives (an all-Cyrillic
    name slugs to nothing).
    """
    slug = "".join(
        c if (c.isascii() and (c.isalnum() or c in "-_")) else "_"
        for c in zone.name
    ).strip("_")
    return slug[:MAX_TAG_BYTES] or f"zone-{zone.id}"


def build_zone_dashboard(zone: Zone, sources: Sequence[RegisteredSource]) -> dict:
    uid = f"zone-dashboard-{zone.id}"
    title = f"Zone: {zone.name}"

    panels: list[dict] = []
    panel_id = 1

    sensor_count = sum(1 for s in sources if s.source_type == "sensor")
    camera_count = sum(1 for s in sources if s.source_type == "camera")

    panels.append({
        "title": "Zone Summary",
        "type": "stat",
        "id": panel_id,
        "gridPos": {"h": SUMMARY_H, "w": SUMMARY_W, "x": 0, "y": HEADER_Y},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "fixed", "fixedColor": "blue"},
                "unit": "none",
            },
        },
        "options": {
            "reduceOptions": {"values": False, "calcs": ["lastNotNull"]},
        },
        "targets": [
            {
                "datasource": {"type": "postgres", "uid": "postgres"},
                "format": "table",
                "rawSql": f"SELECT {sensor_count} AS sensors, {camera_count} AS cameras",
                "refId": "A",
            }
        ],
    })
    panel_id += 1

    panels.append({
        "title": "Critical Alerts",
        "type": "stat",
        "id": panel_id,
        "gridPos": {"h": SUMMARY_H, "w": CRITICAL_ALERTS_W, "x": SUMMARY_W, "y": HEADER_Y},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"value": -1e9, "color": "green"},
                        {"value": 1, "color": "red"},
                    ],
                },
            },
        },
        "options": {
            "reduceOptions": {"values": False, "calcs": ["lastNotNull"]},
        },
        "targets": [
            {
                "datasource": {"type": "postgres", "uid": "postgres"},
                "format": "table",
                "rawSql": (
                    "SELECT COUNT(*) AS critical "
                    "FROM alerts a "
                    "LEFT JOIN registered_sources rs ON rs.source_id = a.source_id "
                    "WHERE a.severity IN ('high', 'critical') "
                    f"  AND (rs.zone_id = {zone.id} "
                    f"       OR a.source_id IN ({_sql_str(zone.name)}, "
                    f"                         {_sql_str('zone_' + zone.name)}))"
                ),
                "refId": "A",
            }
        ],
    })
    panel_id += 1

    zone_name = zone.name
    # This used to be the control surface itself: a Text panel with an inline
    # <script> that Grafana 13 does not execute, so it only ever showed its
    # static "idle" rows. The real controls now live on a page the anomaly API
    # serves (`/admin/control`, its own document, same origin as the JSON it
    # calls); this panel is the signpost to it.
    control_url = f"{ANOMALY_API_PUBLIC_URL}/admin/control"
    panels.append({
        "title": "Detector Control & Training",
        "type": "text",
        "id": panel_id,
        "gridPos": {"h": DETECTOR_CTRL_H, "w": DETECTOR_CTRL_W, "x": SUMMARY_W + CRITICAL_ALERTS_W, "y": HEADER_Y},
        "options": {
            "mode": "html",
            "content": (
                '<div style="display:flex;flex-direction:column;gap:10px;padding:6px;font-size:12px;">'
                f'<div>Zone <b>{zone_name}</b>: train-data size, auto-retrain, cadence, '
                'on/off and a manual <b>Train</b> for M2AD and CKAAD.</div>'
                f'<a href="{control_url}" target="_blank" '
                'style="align-self:flex-start;padding:6px 14px;background:#3274d9;color:#fff;'
                'border-radius:4px;text-decoration:none;font-weight:600;">'
                'Open Detector Control &amp; Training</a>'
                '<div style="color:#8e9297;">Live progress and status are shown on that page. '
                'Grafana does not execute the inline scripts a panel would need to drive the '
                'controls itself, which is why this is a link rather than widgets.</div>'
                '</div>'
            ),
        },
        "fieldConfig": {"defaults": {}},
        "disable_sanitize_html": True,
    })
    panel_id += 1

    panels.append({
        "title": f"Zone: {zone.name}",
        "type": "row",
        "id": panel_id,
        "gridPos": {"h": ROW_SEP_H, "w": GRID_COLUMNS, "x": 0, "y": ROW_SEP_Y},
    })
    panel_id += 1

    sensor_panels = []
    camera_panels = []
    for s in sources:
        if s.source_type == "sensor":
            sensor_panels.append(s)
        elif s.source_type == "camera":
            camera_panels.append(s)

    y_cursor = CONTENT_START_Y

    cols = SENSOR_COLS
    for i, s in enumerate(sensor_panels):
        p = _make_sensor_panel(s, panel_id)
        p["gridPos"]["y"] = y_cursor + (i // cols) * SENSOR_H
        panels.append(p)
        panel_id += 1

    if sensor_panels:
        n_rows = (len(sensor_panels) + cols - 1) // cols
        y_cursor += n_rows * SENSOR_H

    cols = CAMERA_COLS
    for i, s in enumerate(camera_panels):
        p = _make_camera_panel(s, i, y_cursor)
        panels.append(p)
        panel_id += 1

    if camera_panels:
        n_rows = (len(camera_panels) + cols - 1) // cols
        y_cursor += n_rows * CAMERA_H

    panels.append(_make_alerts_panel(panel_id, y_cursor, zone.id))

    return {
        "title": title,
        "uid": uid,
        "version": 1,
        "timezone": "browser",
        "schemaVersion": 39,
        "editable": True,
        "tags": ["dynamic", "zone", _zone_tag(zone)],
        "panels": panels,
        "annotations": {
            "list": [
                {
                    # Marks every anomaly interval on every panel of the zone
                    # dashboard, so *when* a detector fired is visible against
                    # the raw sensor traces, not only in the alerts table.
                    "name": "M2AD anomaly",
                    "datasource": {"type": "postgres", "uid": "postgres"},
                    "enable": True,
                    "hide": False,
                    "iconColor": "red",
                    "target": {
                        "format": "table",
                        "refId": "Anno",
                        "rawSql": (
                            "SELECT DISTINCT sar.timestamp AS time, "
                            "'M2AD anomaly' AS text "
                            "FROM sensor_anomaly_results sar "
                            "JOIN registered_sources rs ON rs.source_id = sar.source_id "
                            "WHERE sar.detector = 'm2ad' AND sar.is_anomaly = true "
                            f"  AND rs.zone_id = {zone.id} "
                            "AND $__timeFilter(sar.timestamp) "
                            "ORDER BY 1"
                        ),
                    },
                }
            ],
        },
        "templating": {
            "list": [
                {
                    "name": "run_id",
                    "type": "query",
                    "query": "SELECT DISTINCT run_id FROM sensor_anomaly_results ORDER BY run_id DESC LIMIT 20",
                    "datasource": {"type": "postgres", "uid": "postgres"},
                    "refresh": 1,
                    "includeAll": False,
                    "current": {"text": "latest", "value": ""},
                },
                {
                    "name": "detector",
                    "type": "query",
                    "query": "SELECT DISTINCT detector FROM sensor_anomaly_results ORDER BY detector",
                    "datasource": {"type": "postgres", "uid": "postgres"},
                    "refresh": 1,
                    "includeAll": True,
                    "current": {"text": "All", "value": "$__all"},
                },
            ]
        },
    }
