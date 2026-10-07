"""The detector control page the anomaly API serves at `/admin/control`.

It replaced a Grafana Text panel whose inline `<script>` Grafana 13 would not
execute (the panel rendered its static "idle" markup and nothing else). A page
served by the API is same-origin with the JSON endpoints it calls, so there is
no CORS dance and no dashboard-renderer in between to strip the script.

Everything is plain `<script>`: fetch the settings, draw a row per detector,
PUT a knob back when it changes, POST a Train press. The status half of each
row polls `/admin/detector/settings`, which merges the DB settings with the
detector's live train state.
"""

CONTROL_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Detector Control &amp; Training</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; background: #111217; color: #d8d9da;
         font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  header { display: flex; align-items: baseline; gap: 12px;
           padding: 16px 20px; border-bottom: 1px solid #2a2d33; }
  h1 { font-size: 16px; margin: 0; font-weight: 600; }
  header .hint { color: #8e9297; font-size: 12px; }
  header button { margin-left: auto; }
  main { padding: 16px 20px; display: flex; flex-direction: column; gap: 14px; max-width: 1080px; }
  .card { background: #181b1f; border: 1px solid #2a2d33; border-radius: 6px; padding: 14px 16px; }
  .card h2 { font-size: 14px; margin: 0 0 2px; font-weight: 600; }
  .card .sub { color: #8e9297; font-size: 12px; margin-bottom: 10px; }
  .status { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
  .bar { flex: 1; height: 12px; background: #2a2d33; border-radius: 6px; overflow: hidden; }
  .bar > div { height: 100%; width: 0%; background: #5794f2; transition: width .4s; }
  .bar > div.done { background: #56a64b; }
  .bar > div.error { background: #e02f44; }
  .state { white-space: nowrap; min-width: 260px; color: #c7c9cc; }
  .controls { display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end; }
  label { display: flex; flex-direction: column; gap: 4px; font-size: 11px; color: #8e9297; }
  label.check { flex-direction: row; align-items: center; gap: 6px; color: #c7c9cc; font-size: 12px; }
  .samples { color: #5794f2; font-size: 11px; white-space: nowrap; }
  input[type=number] { width: 90px; }
  input, button { background: #22252b; color: #d8d9da; border: 1px solid #383b42;
                  border-radius: 4px; padding: 5px 8px; font: inherit; }
  button { cursor: pointer; }
  button.train { background: #3274d9; border-color: #3274d9; color: #fff; }
  button:disabled { opacity: .5; cursor: default; }
  .saved { color: #56a64b; font-size: 11px; min-width: 46px; }
  .err { color: #e02f44; font-size: 11px; min-width: 46px; }
  .zonelist { margin-top: 12px; border-top: 1px solid #2a2d33; padding-top: 10px;
              display: flex; flex-direction: column; gap: 8px; }
  .zonelist .sub { margin-bottom: 2px; }
  .zrow { display: flex; align-items: center; gap: 10px; }
  .zrow .zname { min-width: 160px; color: #c7c9cc; font-size: 12px; }
  .zrow .zsaved { color: #56a64b; font-size: 11px; min-width: 56px; }
  .zrow .zerr { color: #e02f44; font-size: 11px; min-width: 56px; }
  .empty { color: #8e9297; }
</style>
</head>
<body>
<header>
  <h1>Detector Control &amp; Training</h1>
  <span class="hint">changes apply within ~5s (the detector polls this API)</span>
  <button id="refresh">Refresh</button>
</header>
<main>
  <div id="rows"></div>
  <div id="empty" class="empty">Loading…</div>
</main>
<script>
(function () {
  "use strict";

  var REFRESH_MS = 5000;
  var rows = {};       // "zone:type" -> element refs

  function cssId(k) { return k.replace(/[^A-Za-z0-9_-]/g, "_"); }
  function el(tag, props, children) {
    var n = document.createElement(tag);
    if (props) { for (var p in props) { n[p] = props[p]; } }
    (children || []).forEach(function (c) { n.appendChild(c); });
    return n;
  }
  function isCkaad(s) { return s.detector_type === "ckaad"; }
  function isFusion(s) { return s.detector_type === "fusion"; }
  function zoneLabel(s) {
    if (isCkaad(s)) { return "CKAAD (global)"; }
    if (isFusion(s)) { return "Cross-modal fusion · " + s.zone_name; }
    return "M2AD · " + s.zone_name;
  }

  // Fusion is not a model: it owns no training and no per-modality knob, so
  // it gets its own card with a single control — the cross-modal sensitivity.
  // The value is stored in the `score_threshold` column under the `fusion`
  // detector_type (0 = fire as soon as both modalities are past their cutoff).
  function buildFusionRow(s) {
    var k = s.zone_name + ":" + s.detector_type;
    var id = cssId(k);

    var title = el("h2", { textContent: zoneLabel(s) });
    var sub = el("div", { className: "sub", textContent:
      "Writes a cross-modal alert only when M2AD and CKAAD are both past " +
      "their own cutoffs. Sensitivity is how far past, normalized 0–1: 0 " +
      "fires at the boundary, higher values demand stronger corroboration." });

    var sens = el("input", { type: "number", min: "0", max: "1", step: "0.01",
                             id: "sens-" + id });
    var sensLabel = el("label", {}, [
      el("span", { textContent: "Cross-modal sensitivity" }), sens
    ]);
    var saved = el("span", { className: "saved", textContent: "" });
    var controls = el("div", { className: "controls" }, [sensLabel, saved]);
    var card = el("div", { className: "card" }, [title, sub, controls]);

    rows[k] = { card: card, type: "fusion", sens: sens, saved: saved };

    function flash(msg, cls) {
      saved.textContent = msg;
      saved.className = cls || "saved";
      clearTimeout(saved._t);
      saved._t = setTimeout(function () { saved.textContent = ""; }, 2500);
    }
    sens.addEventListener("change", function () {
      var v = parseFloat(sens.value);
      if (isNaN(v) || v < 0 || v > 1) { flash("need 0..1", "err"); poll(); return; }
      fetch("/admin/detector/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ zone_name: s.zone_name, detector_type: "fusion",
                               score_threshold: v })
      }).then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        flash("saved");
        poll();
      }).catch(function (e) { flash(String(e.message || e), "err"); });
    });

    return card;
  }

  function buildRow(s) {
    if (isFusion(s)) { return buildFusionRow(s); }

    var k = s.zone_name + ":" + s.detector_type;
    var id = cssId(k);

    var title = el("h2", { textContent: zoneLabel(s) });
    var sub = el("div", { className: "sub", textContent:
      isCkaad(s) ? "shared image model, one fit across every camera"
              : "sensor model for zone " + s.zone_name });

    var bar = el("div", { className: "bar" }, [el("div", {})]);
    var state = el("div", { className: "state", textContent: "idle" });
    var status = el("div", { className: "status" }, [bar, state]);

    var en = el("input", { type: "checkbox", id: "en-" + id });
    var enLabel = el("label", { className: "check" }, [en, el("span", { textContent: "Enabled" })]);

    var auto = el("input", { type: "checkbox", id: "auto-" + id });
    var autoLabel = el("label", { className: "check" }, [auto, el("span", { textContent: "Auto-retrain" })]);

    var minIn = el("input", { type: "number", min: "1", id: "min-" + id });
    var minHint = el("span", { className: "samples", textContent: "" });
    var minLabel = el("label", {}, [
      el("span", { textContent: "Train samples" }), minIn, minHint
    ]);

    var every = el("input", { type: "number", min: "1", id: "every-" + id });
    var everyHint = el("span", { className: "samples", textContent: "" });
    var everyLabel = el("label", {}, [
      el("span", { textContent: "Retrain every (runs)" }), every, everyHint
    ]);

    var pv = el("input", { type: "number", min: "0", step: "0.001", id: "pv-" + id });
    var pvLabel = el("label", {}, [el("span", { textContent: "p-value cutoff" }), pv]);

    // CKAAD's cutoff is a raw score, not a p-value. This is the fallback every
    // camera without an override of its own uses; blank clears it back to the
    // model's calibrated cutoff.
    var gt = el("input", { type: "number", min: "0", step: "0.01", id: "gt-" + id });
    var gtLabel = el("label", {}, [
      el("span", { textContent: "Global cutoff (fallback)" }), gt
    ]);

    // One threshold row per zone, rebuilt from `ckaad_zones` on each poll. Only
    // the shared CKAAD card has these; an M2AD zone has no such override.
    var zoneBox = el("div", { className: "zonelist" });

    var trainBtn = el("button", { className: "train", textContent: "Train now" });
    var saved = el("span", { className: "saved", textContent: "" });

    var controls = el("div", { className: "controls" }, [
      enLabel, autoLabel, minLabel, everyLabel
    ]);
    if (!isCkaad(s)) { controls.appendChild(pvLabel); }
    else { controls.appendChild(gtLabel); }
    controls.appendChild(trainBtn);
    controls.appendChild(saved);

    var card = el("div", { className: "card" }, [title, sub, status, controls]);
    if (isCkaad(s)) {
      zoneBox.appendChild(el("div", { className: "sub", textContent:
        "Per-zone cutoff overrides (raw score). Blank uses the global cutoff, " +
        "or the model's calibrated value if that is blank too." }));
      card.appendChild(zoneBox);
    }
    rows[k] = { card: card, bar: bar.firstChild, state: state,
                en: en, auto: auto, min: minIn, every: every, pv: pv, gt: gt,
                minHint: minHint, everyHint: everyHint,
                zoneBox: zoneBox, zoneInputs: {},
                train: trainBtn, saved: saved, sig: null };

    function flash(msg, cls) {
      saved.textContent = msg;
      saved.className = cls || "saved";
      clearTimeout(saved._t);
      saved._t = setTimeout(function () { saved.textContent = ""; }, 2500);
    }

    function save(field, value) {
      var body = { zone_name: s.zone_name, detector_type: s.detector_type };
      body[field] = value;
      fetch("/admin/detector/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      }).then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        flash("saved");
        poll();
      }).catch(function (e) { flash(String(e.message || e), "err"); });
    }

    en.addEventListener("change", function () { save("enabled", en.checked); });
    auto.addEventListener("change", function () { save("auto_retrain", auto.checked); });
    function numHandler(input, field) {
      return function () {
        var v = parseInt(input.value, 10);
        if (isNaN(v) || v < 1) { flash("need >= 1", "err"); poll(); return; }
        save(field, v);
      };
    }
    minIn.addEventListener("change", numHandler(minIn, "min_train_samples"));
    every.addEventListener("change", numHandler(every, "retrain_every"));
    pv.addEventListener("change", function () {
      var v = parseFloat(pv.value);
      if (isNaN(v) || v < 0) { flash("need >= 0", "err"); poll(); return; }
      save("pvalue_threshold", v);
    });
    gt.addEventListener("change", function () {
      var raw = gt.value.trim();
      // Blank means "no global fallback" — the API treats an explicit null as a
      // clear, which is the only field for which null is meaningful.
      if (raw === "") { save("score_threshold", null); return; }
      var v = parseFloat(raw);
      if (isNaN(v) || v < 0) { flash("need >= 0", "err"); poll(); return; }
      save("score_threshold", v);
    });

    trainBtn.addEventListener("click", function () {
      trainBtn.disabled = true;
      fetch("/admin/detector/train", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ zone_name: s.zone_name, detector_type: s.detector_type })
      }).then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        flash("queued");
        setTimeout(poll, 1000);
      }).catch(function (e) { flash(String(e.message || e), "err"); })
        .then(function () { trainBtn.disabled = false; });
    });

    return card;
  }

  function pctNum(p) {
    if (!p) { return 0; }
    var n = parseInt(String(p).replace("%", ""), 10);
    return isNaN(n) ? 0 : n;
  }

  function fmtDur(secs) {
    function r(x) { return Math.round(x * 10) / 10; }
    if (secs >= 86400) { return r(secs / 86400) + " days"; }
    if (secs >= 3600) { return r(secs / 3600) + " h"; }
    if (secs >= 90) { return r(secs / 60) + " min"; }
    return Math.round(secs) + " s";
  }

  // "Retrain every" counts detection runs, not seconds or samples. Convert a
  // run count to wall-clock time using the interval the detector reports in
  // its train-state snapshot, so the number means something to a human.
  function cadenceHint(every, intervalS) {
    var n = parseInt(every, 10);
    var iv = parseFloat(intervalS);
    if (!n || n < 1 || !iv || iv <= 0) { return ""; }
    return "≈ " + fmtDur(n * iv) + " (1 run every " + Math.round(iv) + "s)";
  }

  // Per-zone CKAAD threshold rows: built once per zone and only updated after
  // that, so the 5s poll never clobbers what the user is typing.
  function ensureZoneRow(r, zname) {
    var zi = r.zoneInputs[zname];
    if (zi) { return zi; }

    var input = el("input", { type: "number", min: "0", step: "0.01" });
    var clearBtn = el("button", { textContent: "Clear" });
    var saved = el("span", { className: "zsaved", textContent: "" });
    var row = el("div", { className: "zrow" }, [
      el("span", { className: "zname", textContent: zname }), input, clearBtn, saved
    ]);
    r.zoneBox.appendChild(row);
    zi = { row: row, input: input, saved: saved };
    r.zoneInputs[zname] = zi;

    function flash(msg, cls) {
      saved.textContent = msg;
      saved.className = cls || "zsaved";
      clearTimeout(saved._t);
      saved._t = setTimeout(function () { saved.textContent = ""; }, 2500);
    }
    function put(value) {
      fetch("/admin/detector/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          zone_name: zname, detector_type: "ckaad", score_threshold: value
        })
      }).then(function (res) {
        if (!res.ok) { throw new Error("HTTP " + res.status); }
        flash("saved");
        poll();
      }).catch(function (e) { flash(String(e.message || e), "zerr"); });
    }
    input.addEventListener("change", function () {
      var raw = input.value.trim();
      if (raw === "") { put(null); return; }
      var v = parseFloat(raw);
      if (isNaN(v) || v < 0) { flash("need >= 0", "zerr"); poll(); return; }
      put(v);
    });
    clearBtn.addEventListener("click", function () { put(null); });
    return zi;
  }

  function updateZoneThresholds(r, zones) {
    var seen = {};
    (zones || []).forEach(function (z) {
      seen[z.zone_name] = true;
      var zi = ensureZoneRow(r, z.zone_name);
      var shown = (z.score_threshold === null || z.score_threshold === undefined)
        ? "" : String(z.score_threshold);
      if (document.activeElement !== zi.input && zi.input.value !== shown) {
        zi.input.value = shown;
      }
    });
    Object.keys(r.zoneInputs).forEach(function (zname) {
      if (!seen[zname]) { r.zoneInputs[zname].row.remove(); delete r.zoneInputs[zname]; }
    });
  }

  function updateRow(s, ckaadZones) {
    var k = s.zone_name + ":" + s.detector_type;
    var r = rows[k];
    if (!r) { return; }
    if (r.type === "fusion") {
      // Only the sensitivity input; never touch it while it has focus.
      if (document.activeElement !== r.sens) {
        var shown = (s.score_threshold === null || s.score_threshold === undefined)
          ? "" : String(s.score_threshold);
        if (r.sens.value !== shown) { r.sens.value = shown; }
      }
      return;
    }
    var ts = s.training_state || {};
    var p = pctNum(ts.progress);
    r.bar.style.width = p + "%";
    r.bar.className = ts.status === "complete" ? "done" : (ts.status === "error" ? "error" : "");
    var stamp = ts.updated_at ? " [" + new Date(ts.updated_at * 1000).toLocaleTimeString() + "]" : "";
    r.state.textContent = (ts.status || "idle") + (ts.message ? " — " + ts.message : "") + stamp;

    function setIfIdle(input, value, prop) {
      if (document.activeElement === input) { return; }
      if (input[prop] !== value) { input[prop] = value; }
    }
    setIfIdle(r.en, !!s.enabled, "checked");
    setIfIdle(r.auto, !!s.auto_retrain, "checked");
    setIfIdle(r.min, s.min_train_samples, "value");
    setIfIdle(r.every, s.retrain_every, "value");
    if (s.pvalue_threshold !== null && s.pvalue_threshold !== undefined) {
      setIfIdle(r.pv, s.pvalue_threshold, "value");
    }
    if (isCkaad(s)) {
      setIfIdle(r.gt,
        (s.score_threshold === null || s.score_threshold === undefined)
          ? "" : s.score_threshold,
        "value");
      updateZoneThresholds(r, ckaadZones);
    }

    if (typeof ts.available_samples === "number") {
      var target = ts.target_samples;
      r.minHint.textContent = ts.available_samples + " available" +
        (typeof target === "number" ? " · needs " + target + " to train" : "");
    } else {
      r.minHint.textContent = "";
    }
    r.everyHint.textContent = cadenceHint(s.retrain_every, ts.detect_interval_s);
  }

  function poll() {
    fetch("/admin/detector/settings")
      .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
      .then(function (d) {
        var list = d.settings || [];
        var root = document.getElementById("rows");
        document.getElementById("empty").style.display = list.length ? "none" : "block";
        document.getElementById("empty").textContent = list.length ? "" : "No detectors yet.";
        var seen = {};
        list.forEach(function (s) {
          var k = s.zone_name + ":" + s.detector_type;
          seen[k] = true;
          if (!rows[k]) { root.appendChild(buildRow(s)); }
          updateRow(s, d.ckaad_zones || []);
        });
        Object.keys(rows).forEach(function (k) {
          if (!seen[k]) { rows[k].card.remove(); delete rows[k]; }
        });
      })
      .catch(function (e) {
        var empty = document.getElementById("empty");
        empty.style.display = "block";
        empty.textContent = "Could not load settings: " + (e.message || e);
      });
  }

  document.getElementById("refresh").addEventListener("click", poll);
  poll();
  setInterval(poll, REFRESH_MS);
})();
</script>
</body>
</html>
"""
