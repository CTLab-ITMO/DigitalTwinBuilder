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
                    "sar.anomaly_score AS score, '' AS snapshot "
                    "FROM sensor_anomaly_results sar "
                    "JOIN registered_sources rs ON rs.source_id = sar.source_id "
                    f"WHERE sar.is_anomaly = true AND rs.zone_id = {zone_id} "
                    "UNION ALL "
                    "SELECT idr.timestamp, "
                    "idr.details->>'camera_id' AS source, "
                    "idr.anomaly_score AS score, "
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
    zone_slug = "".join(c if c.isalnum() else "_" for c in zone_name)
    panels.append({
        "title": "Detector Control & Training",
        "type": "text",
        "id": panel_id,
        "gridPos": {"h": DETECTOR_CTRL_H, "w": DETECTOR_CTRL_W, "x": SUMMARY_W + CRITICAL_ALERTS_W, "y": HEADER_Y},
        "options": {
            "mode": "html",
            "content": (
                f'<div id="train-status-{zone_slug}" '
                f'     style="display:flex;flex-direction:column;gap:6px;padding:4px;font-size:11px;">'
                f'<div style="display:flex;align-items:center;gap:6px;">'
                f'  <span style="font-weight:bold;white-space:nowrap;min-width:46px;">M2AD</span>'
                f'  <div class="progress" style="flex:1;height:14px;background:#333;border-radius:6px;overflow:hidden;">'
                f'    <div id="m2ad-bar-{zone_slug}" style="width:0%;height:100%;background:#7eb8da;border-radius:6px;transition:width 0.5s;"></div>'
                f'  </div>'
                f'  <span id="m2ad-status-{zone_slug}" style="white-space:nowrap;min-width:100px;text-align:right;">idle</span>'
                f'  <button id="m2ad-toggle-{zone_slug}" class="btn btn-success btn-small" style="padding:2px 10px;font-size:11px;min-width:34px;border:none;cursor:pointer;">On</button>'
                f'  <button id="m2ad-train-{zone_slug}" class="btn btn-primary btn-small" style="padding:2px 10px;font-size:11px;border:none;cursor:pointer;">Train</button>'
                f'</div>'
                f'<div style="display:flex;align-items:center;gap:6px;">'
                f'  <span style="font-weight:bold;white-space:nowrap;min-width:46px;">CKAAD</span>'
                f'  <div class="progress" style="flex:1;height:14px;background:#333;border-radius:6px;overflow:hidden;">'
                f'    <div id="ckaad-bar-{zone_slug}" style="width:0%;height:100%;background:#7eb8da;border-radius:6px;transition:width 0.5s;"></div>'
                f'  </div>'
                f'  <span id="ckaad-status-{zone_slug}" style="white-space:nowrap;min-width:100px;text-align:right;">idle</span>'
                f'  <button id="ckaad-toggle-{zone_slug}" class="btn btn-success btn-small" style="padding:2px 10px;font-size:11px;min-width:34px;border:none;cursor:pointer;">On</button>'
                f'  <button id="ckaad-train-{zone_slug}" class="btn btn-primary btn-small" style="padding:2px 10px;font-size:11px;border:none;cursor:pointer;">Train</button>'
                f'</div>'
                f'</div>'
                f'<script>'
                f'function _init_{zone_slug}() {{'
                f'  function pctNum(p) {{'
                f'    if (!p || p === "") return 0;'
                f'    return parseInt(p.replace("%",""), 10) || 0;'
                f'  }}'
                f'  function fmtTime(ts) {{'
                f'    if (!ts) return "";'
                f'    var d = new Date(ts * 1000);'
                f'    return d.toLocaleTimeString();'
                f'  }}'
                f'  var ds = {{m2ad: true, ckaad: true}};'
                f'  var zn = "{zone_name}";'
                f'  var m2adBar = document.getElementById("m2ad-bar-{zone_slug}");'
                f'  var m2adSt = document.getElementById("m2ad-status-{zone_slug}");'
                f'  var m2adTog = document.getElementById("m2ad-toggle-{zone_slug}");'
                f'  var m2adTrn = document.getElementById("m2ad-train-{zone_slug}");'
                f'  var ckaadBar = document.getElementById("ckaad-bar-{zone_slug}");'
                f'  var ckaadSt = document.getElementById("ckaad-status-{zone_slug}");'
                f'  var ckaadTog = document.getElementById("ckaad-toggle-{zone_slug}");'
                f'  var ckaadTrn = document.getElementById("ckaad-train-{zone_slug}");'
                f'  if (!m2adBar || !ckaadBar) return;'
                f'  m2adTrn.onclick = function(e) {{'
                f'    m2adBar.style.width = "0%";'
                f'    m2adBar.style.background = "#7eb8da";'
                f'    m2adSt.innerText = "pending...";'
                f"    fetch('{ANOMALY_API_PUBLIC_URL}/admin/detector/train',{{method:'POST',headers:{{'Content-Type':'application/json'}},"
                f"      body:JSON.stringify({{zone_name:zn,detector_type:'m2ad'}})}})"
                f'      .then(function() {{ setTimeout(poll, 2000); }});'
                f'  }};'
                f'  ckaadTrn.onclick = function(e) {{'
                f'    ckaadBar.style.width = "0%";'
                f'    ckaadBar.style.background = "#7eb8da";'
                f'    ckaadSt.innerText = "pending...";'
                f"    fetch('{ANOMALY_API_PUBLIC_URL}/admin/detector/train',{{method:'POST',headers:{{'Content-Type':'application/json'}},"
                f"      body:JSON.stringify({{zone_name:'shared',detector_type:'ckaad'}})}})"
                f'      .then(function() {{ setTimeout(poll, 2000); }});'
                f'  }};'
                f'  m2adTog.onclick = function(e) {{'
                f'    var en = ds.m2ad;'
                f'    var cmd = en ? "disable" : "enable";'
                f"    fetch('{ANOMALY_API_PUBLIC_URL}/admin/detector/control',{{method:'POST',headers:{{'Content-Type':'application/json'}},"
                f"      body:JSON.stringify({{zone_name:zn,detector_type:'m2ad',command:cmd}})}})"
                f'      .then(function() {{'
                f'        ds.m2ad = !en;'
                f'        m2adTog.innerText = ds.m2ad ? "On" : "Off";'
                f'        m2adTog.className = ds.m2ad ? "btn btn-success btn-small" : "btn btn-danger btn-small";'
                f'        setTimeout(poll, 600);'
                f'      }});'
                f'  }};'
                f'  ckaadTog.onclick = function(e) {{'
                f'    var en = ds.ckaad;'
                f'    var cmd = en ? "disable" : "enable";'
                f"    fetch('{ANOMALY_API_PUBLIC_URL}/admin/detector/control',{{method:'POST',headers:{{'Content-Type':'application/json'}},"
                f"      body:JSON.stringify({{zone_name:zn,detector_type:'ckaad',command:cmd}})}})"
                f'      .then(function() {{'
                f'        ds.ckaad = !en;'
                f'        ckaadTog.innerText = ds.ckaad ? "On" : "Off";'
                f'        ckaadTog.className = ds.ckaad ? "btn btn-success btn-small" : "btn btn-danger btn-small";'
                f'        setTimeout(poll, 600);'
                f'      }});'
                f'  }};'
                f'  async function poll() {{'
                f'    try {{'
                f'      var r = await fetch("{ANOMALY_API_PUBLIC_URL}/admin/detector/status");'
                f'      var d = await r.json();'
                f'      var ts = d.training_state || {{}};'
                f'      var m = ts["{zone_name}:m2ad"] || {{}};'
                f'      var p = pctNum(m.progress);'
                f'      m2adBar.style.width = p + "%";'
                f'      m2adBar.style.background = m.status === "complete" ? "#56a64b" : "#7eb8da";'
                f'      m2adSt.innerText = (m.status || "idle")'
                f'        + (m.message ? " - " + m.message : "")'
                f'        + (m.updated_at ? " [" + fmtTime(m.updated_at) + "]" : "");'
                f'      var c = ts["shared:ckaad"] || {{}};'
                f'      var cp = pctNum(c.progress);'
                f'      ckaadBar.style.width = cp + "%";'
                f'      ckaadBar.style.background = c.status === "complete" ? "#56a64b" : "#7eb8da";'
                f'      ckaadSt.innerText = (c.status || "idle")'
                f'        + (c.message ? " - " + c.message : "")'
                f'        + (c.updated_at ? " [" + fmtTime(c.updated_at) + "]" : "");'
                f'      var lc = d.latest_commands || [];'
                f'      for (var i = 0; i < lc.length; i++) {{'
                f'        var cv = lc[i];'
                f'        if (cv.zone === "{zone_name}" && cv.type === "m2ad") {{'
                f'          ds.m2ad = cv.command !== "disable";'
                f'          m2adTog.innerText = ds.m2ad ? "On" : "Off";'
                f'          m2adTog.className = ds.m2ad ? "btn btn-success btn-small" : "btn btn-danger btn-small";'
                f'        }}'
                f'        if (cv.zone === "shared" && cv.type === "ckaad") {{'
                f'          ds.ckaad = cv.command !== "disable";'
                f'          ckaadTog.innerText = ds.ckaad ? "On" : "Off";'
                f'          ckaadTog.className = ds.ckaad ? "btn btn-success btn-small" : "btn btn-danger btn-small";'
                f'        }}'
                f'      }}'
                f'    }} catch(e) {{ console.log("Status poll error", e); }}'
                f'  }}'
                f'  setInterval(poll, 3000);'
                f'  poll();'
                f'}}'
                f'if (document.readyState === "loading") {{'
                f'  document.addEventListener("DOMContentLoaded", _init_{zone_slug});'
                f'}} else {{'
                f'  _init_{zone_slug}();'
                f'}}'
                f'</script>'
            ),
        },
        "fieldConfig": {"defaults": {}},
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
        "tags": ["dynamic", "zone", zone.name],
        "panels": panels,
        "annotations": {
            "list": [],
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
