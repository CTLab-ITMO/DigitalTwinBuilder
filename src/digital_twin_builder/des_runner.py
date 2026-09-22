"""Execute a generated DES (SimPy) program and judge whether it worked.

The DES agent returns a program; nothing in the pipeline ever runs it, so a
program that raises on its first `yield` reaches the user as if it were a
result. This module closes that gap: it runs the program in a subprocess, checks
that it printed the three KPI lines the prompt asks for, and returns a
human-readable report that can be fed back to the agent for a correction.

It never raises for a broken program — a model that does not run is an outcome
to be reported, not an error of the caller.

The interpreter must have simpy installed. It is taken from `config.DES_PYTHON`
(`DES_PYTHON` in .env), which defaults to the interpreter running the app.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:  # the app imports this as a top-level module; tests may import it as a package
    from config import DES_EXEC_TIMEOUT_S, DES_PYTHON, DES_REPAIR_ATTEMPTS
except ImportError:  # pragma: no cover - fallback for a bare `python des_runner.py`
    DES_EXEC_TIMEOUT_S = 900
    DES_PYTHON = sys.executable
    DES_REPAIR_ATTEMPTS = 3

# The three contract lines the GenDES prompt asks for. These patterns are the
# contract's definition: a program that prints them has reported its KPIs, and
# one that does not has produced no measurement. The comparison harness parses
# the same three patterns, so the two agree on what "printed the contract" means.
THROUGHPUT_RE = re.compile(r"Throughput\s*=\s*([0-9.eE+-]+)\s*parts/hour")
WIP_RE = re.compile(r"WIP\s*=\s*([0-9.eE+-]+)\s*parts")
ENERGY_RE = re.compile(
    r"Mean Energy Consumption per Part\s*=\s*([0-9.eE+-]+)\s*kWh/part")

FENCE_RE = re.compile(r"```[A-Za-z0-9_+-]*[ \t]*\r?\n(.*?)```", re.DOTALL)

# How much of a traceback is fed back to the agent. Enough to carry the last
# frames and the exception line, short enough not to crowd out the program.
REPORT_CHARS = 4000

# Slack on the semantic bounds in `_implausible_kpis`. The bounds themselves are
# exact for an ideal serial line; the slack absorbs the difference between that
# ideal and a real run (a station that is never starved because the source is
# fast, a repair that lands between parts, a station whose availability is
# declared as 100). Each is set from the worst margin the bound has on the five
# reference lines of the comparison suite, whose ground-truth KPIs must pass:
# throughput reaches 0.952 of the ceiling, sits 2.02x above the floor, and
# energy reaches 0.909 of its ceiling.
THROUGHPUT_CEILING_SLACK = 1.05
THROUGHPUT_FLOOR_SLACK = 0.5
ENERGY_CEILING_SLACK = 1.10


def strip_code_fence(text: str) -> str:
    """Drop a markdown fence the agent added despite being asked not to.

    Only unwraps when a fenced block exists; otherwise the text is returned
    unchanged, so a program that legitimately contains no fence is not damaged.
    """
    m = FENCE_RE.search(text or "")
    return m.group(1).strip("\n") if m else (text or "")


def parse_kpis(stdout: str) -> dict:
    """The three headline KPIs, each None when its line is absent.

    Missing is never turned into a value: a stage that did not report an
    indicator must stay distinguishable from a stage that reported zero.
    """
    def num(pat):
        m = pat.search(stdout or "")
        if not m:
            return None
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return {
        "throughput_per_hour": num(THROUGHPUT_RE),
        "wip_parts": num(WIP_RE),
        "energy_per_part_kwh": num(ENERGY_RE),
    }


def execute(code: str, *, workdir=None, timeout_s: float | None = None,
            python: str | None = None, filename: str = "des_model.py") -> dict:
    """Run `code` and collect its output. Never raises for a model failure.

    Returns status (`ok` when the process exited 0, otherwise `timeout` or
    `simulation_error`), stdout, stderr, error, elapsed_s and the parsed KPIs.
    """
    timeout_s = DES_EXEC_TIMEOUT_S if timeout_s is None else timeout_s
    python = python or DES_PYTHON
    tmp = None
    if workdir is None:
        tmp = tempfile.TemporaryDirectory(prefix="des_run_")
        workdir = tmp.name
    run_file = Path(workdir) / filename
    run_file.write_text(strip_code_fence(code), encoding="utf-8")

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [python, str(run_file)],
            cwd=str(workdir), capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "stdout": "", "stderr": "",
                "error": f"the program did not finish within {timeout_s}s",
                "elapsed_s": round(time.perf_counter() - t0, 3), "kpis": {}}
    except OSError as e:
        return {"status": "error", "stdout": "", "stderr": "",
                "error": f"{type(e).__name__}: {e}",
                "elapsed_s": round(time.perf_counter() - t0, 3), "kpis": {}}
    finally:
        if tmp is not None:
            tmp.cleanup()

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    out = {"stdout": stdout, "stderr": stderr,
           "elapsed_s": round(time.perf_counter() - t0, 3),
           "kpis": parse_kpis(stdout)}
    if proc.returncode != 0:
        out["status"] = "simulation_error"
        out["error"] = f"the program exited with code {proc.returncode}"
    else:
        out["status"] = "ok"
        out["error"] = None
    return out


def _all_zero_implausible(kpis: dict, requirements: dict | None) -> str | None:
    """A model that reports three zeros while parts are arriving did not count.

    Only fires when the requirements declare a positive arrival rate: a line
    that genuinely produced nothing is a legitimate (if dull) result. Returns
    the reason, or None when the result is plausible.
    """
    if not isinstance(requirements, dict) or not isinstance(kpis, dict):
        return None
    if not requirements or not kpis:
        return None
    values = [kpis.get("throughput_per_hour"), kpis.get("wip_parts"),
              kpis.get("energy_per_part_kwh")]
    if values != [0.0, 0.0, 0.0]:
        return None
    line = requirements.get("line")
    if not isinstance(line, dict):
        return None
    src = line.get("source")
    if not isinstance(src, dict):
        return None
    rate = _inter_arrival_s(src)
    if rate is None or rate <= 0:
        return None
    return (f"the program ran and printed the three contract lines, but all "
            f"three are zero while the source is declared to feed a part every "
            f"{rate}s — nothing was counted during the run")


def _as_number(value) -> float | None:
    """The value as a float, or None when it is not a real number.

    `bool` is excluded on purpose: `True` is an `int` in Python and would
    otherwise be read as a declared availability of 1.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _inter_arrival_s(source) -> float | None:
    """The source's inter-arrival time in seconds, under either name it takes.

    The requirements write `inter_arrival_time_s`, the case data writes
    `interarrival_time_s`, and both mean the same interval. A key that is
    present but null must not hide the other one — `dict.get` falls back only on
    a *missing* key — so the names are tried in turn and the first real number
    wins. Returns None when the source declares none.
    """
    if not isinstance(source, dict):
        return None
    for key in ("inter_arrival_time_s", "interarrival_time_s"):
        value = _as_number(source.get(key))
        if value is not None:
            return value
    return None


def _availability_fraction(value) -> float | None:
    """A station's availability as a fraction, from either notation.

    The requirements declare `availability_pct` in percent (99.0), but the same
    number is written as a fraction in the case data (0.99); both mean the same
    machine, so both are accepted. A value of exactly 1.0 reads as 100%, because
    a machine declared 1% available would be a different kind of nonsense.
    """
    n = _as_number(value)
    if n is None or n <= 0:
        return None
    return min(n / 100.0 if n > 1.0 else n, 1.0)


def _serial_bounds(line: dict) -> dict | None:
    """The KPI bounds a serial line cannot leave, from its own parameters.

    A serial chain can hold at most one part per station, so it cannot produce
    parts faster than its slowest station, and a part cannot cost more energy
    than the stations' working power draws for its processing time. The bounds
    are dimensional rather than statistical: they hold whatever the arrival
    pattern, the buffer sizes or the failure draws turn out to be, which is what
    lets them judge a single run whose random draws are unknown.

    Returns None when the line is not a serial chain, or when it declares too
    little for a bound to follow from it — a bound invented from missing numbers
    would reject a model for the requirements' gap, not for its own defect.
    """
    if not isinstance(line, dict):
        return None
    topology = line.get("topology")
    if isinstance(topology, str) and topology.strip():
        if topology.strip().lower() != "serial":
            return None
    stations = line.get("stations")
    if not isinstance(stations, (list, tuple)):
        stations = []
    times, avails, work_hours = [], [], 0.0
    says_work_power = False
    idle_never_costs_more = True
    for st in stations:
        if not isinstance(st, dict):
            continue
        pt = _as_number(st.get("processing_time_s"))
        if pt is not None and pt > 0:
            times.append(pt)
        work = _as_number(st.get("power_working_kw"))
        idle = _as_number(st.get("power_idle_kw"))
        if work is not None and work > 0:
            says_work_power = True
            if pt is not None and pt > 0:
                work_hours += work * pt / 3600.0
            if idle is not None and idle > work:
                # A station that draws more while waiting than while working
                # breaks the energy ceiling, which assumes idle is the cheaper
                # state. Rare, but only the requirements can say so.
                idle_never_costs_more = False
        av = _availability_fraction(st.get("availability_pct"))
        if av is not None:
            avails.append(av)
    if not times:
        return None

    slowest_s = max(times)
    min_avail = min(avails) if avails else 1.0
    bounds = {
        "slowest_s": slowest_s,
        "min_avail": min_avail,
        "throughput_ceiling": 3600.0 / slowest_s * THROUGHPUT_CEILING_SLACK,
        "declares_work_power": says_work_power,
    }
    rate = _inter_arrival_s(line.get("source"))
    if rate is not None and rate > 0:
        bounds["inter_arrival_s"] = rate
        bounds["throughput_floor"] = (min(3600.0 / slowest_s, 3600.0 / rate)
                                      * min_avail * THROUGHPUT_FLOOR_SLACK)
    if work_hours > 0 and idle_never_costs_more:
        bounds["energy_ceiling"] = (work_hours / min_avail
                                    * ENERGY_CEILING_SLACK)
    return bounds


def _implausible_kpis(kpis: dict, requirements: dict | None) -> str | None:
    """Do the three reported KPIs contradict the line they claim to simulate?

    The contract check above only asks whether three numbers were printed. This
    one asks whether they could have come from the line the program was given:
    a program that runs, prints the right three lines, and reports a raw part
    count as a rate passes the contract and fails this. Returns the offending
    arithmetic, or None when nothing is contradicted.
    """
    if not isinstance(requirements, dict) or not isinstance(kpis, dict):
        return None
    if not requirements or not kpis:
        return None
    bounds = _serial_bounds(requirements.get("line"))
    if not bounds:
        return None
    tp = kpis.get("throughput_per_hour")
    wip = kpis.get("wip_parts")
    energy = kpis.get("energy_per_part_kwh")

    ceiling = bounds["throughput_ceiling"]
    if tp is not None and tp > ceiling:
        return (
            f"the program ran and printed the three contract lines, but "
            f"Throughput = {tp} parts/hour is above what this line can do. Its "
            f"slowest station takes {bounds['slowest_s']:g}s per part, so the "
            f"line cannot produce more than {3600.0 / bounds['slowest_s']:g} "
            f"parts/hour (3600 / {bounds['slowest_s']:g}) however the parts are "
            f"released. A value above the ceiling means the rate was not divided "
            f"by the measurement window in seconds — a count of parts, or a "
            f"count divided by the window in hours, is not a throughput")
    floor = bounds.get("throughput_floor")
    if tp is not None and floor is not None and 0 <= tp < floor:
        if tp <= 0:
            return (
                f"the program ran and printed the three contract lines, but "
                f"Throughput = 0 parts/hour while the source feeds a part every "
                f"{bounds.get('inter_arrival_s', '?')}s and the stations are "
                f"available {bounds['min_avail'] * 100.0:.1f}% of the time: "
                f"nothing reached the sink in the measurement window. A model "
                f"that lets no part through is blocked (a station waiting for an "
                f"event no one generates, a repair that never ends), or it "
                f"counts departures somewhere the parts never arrive")
        return (
            f"the program ran and printed the three contract lines, but "
            f"Throughput = {tp} parts/hour is far below what this line must "
            f"produce. With a part arriving every "
            f"{bounds.get('inter_arrival_s', '?')}s and the stations available "
            f"{bounds['min_avail'] * 100.0:.1f}% of the time, the line cannot be "
            f"slower than {floor / THROUGHPUT_FLOOR_SLACK:g} parts/hour; {tp} "
            f"means parts left the system without being counted, the measurement "
            f"window was treated as longer than it is, or stations/buffers were "
            f"dropped from the model")
    ec = bounds.get("energy_ceiling")
    if energy is not None and ec is not None and energy > ec:
        return (
            f"the program ran and printed the three contract lines, but Mean "
            f"Energy Consumption per Part = {energy} kWh/part is above what this "
            f"line can consume. Processing one part on all stations costs "
            f"{ec / ENERGY_CEILING_SLACK * bounds['min_avail']:g} kWh while they "
            f"are busy, and idling between parts is cheaper, so a part cannot "
            f"cost more than {ec / ENERGY_CEILING_SLACK:g} kWh/part "
            f"(working energy divided by the worst availability "
            f"{bounds['min_avail']:g}). A value above that means the energy was "
            f"integrated over the whole run rather than the measurement window, "
            f"or that station power was added for time the station was not up")
    if tp is not None and tp > 0:
        if wip is not None and wip <= 0:
            return (
                f"the program ran and printed the three contract lines, but it "
                f"reports WIP = {wip} parts while producing {tp} parts/hour, so "
                f"parts did leave the system while none were ever held in it. "
                f"WIP must be accumulated as the clock advances — a counter read "
                f"by the KPI block but never incremented reports 0 for any line")
        if energy is not None and energy <= 0 and bounds["declares_work_power"]:
            return (
                f"the program ran and printed the three contract lines, but it "
                f"reports Mean Energy Consumption per Part = {energy} kWh/part "
                f"while the stations are declared to draw power while working. "
                f"Energy must be accumulated for the time each station actually "
                f"spends in each state; a total that stays 0 means no station "
                f"was ever observed to draw power")
    return None


def verify(code: str, *, requirements: dict | None = None, workdir=None,
           timeout_s: float | None = None, python: str | None = None,
           reject_all_zero: bool = True) -> dict:
    """Run `code` and decide whether the DES stage succeeded.

    Success needs all three KPI lines, not merely a clean exit: a program that
    runs but reports nothing has produced no measurement. The lines must also be
    consistent with the line they claim to simulate (see `_implausible_kpis`):
    a program that prints a rate above the line's own ceiling measured something
    other than what the contract asks for. `report` is the text handed back to
    the agent on failure — empty when `ok` is True.
    """
    ex = execute(code, workdir=workdir, timeout_s=timeout_s, python=python)
    kpis = ex["kpis"]
    missing = [name for name, key in (
        ("Throughput", "throughput_per_hour"),
        ("WIP", "wip_parts"),
        ("Mean Energy Consumption per Part", "energy_per_part_kwh"))
        if kpis.get(key) is None]

    if ex["status"] != "ok":
        detail = (ex["stderr"] or ex["stdout"] or "").strip()
        reason = (f"The program did not complete: {ex['error']}.\n\n"
                  f"Output (last {REPORT_CHARS} characters):\n"
                  f"{detail[-REPORT_CHARS:] or '(no output)'}")
    elif missing:
        reason = ("The program exited without printing "
                  f"{' and '.join(missing)} as the last line(s) of stdout. "
                  "Every one of the three KPI lines must be printed, exactly in "
                  "the required form, and nothing may print them twice.\n\n"
                  f"Program output (last {REPORT_CHARS} characters):\n"
                  f"{(ex['stdout'] or '').strip()[-REPORT_CHARS:] or '(no output)'}")
    else:
        reason = (_all_zero_implausible(kpis, requirements) if reject_all_zero
                  else None)
        if reason is None:
            reason = _implausible_kpis(kpis, requirements)
        if reason:
            reason = (reason + ".\n\nProgram output:\n"
                      f"{(ex['stdout'] or '').strip()[-REPORT_CHARS:]}")

    return {"ok": reason is None, "report": reason or "", "kpis": kpis,
            "execution": ex}


def generate_with_repair(submit, *, requirements=None, workdir=None,
                         attempts: int | None = None, timeout_s=None,
                         python=None, reject_all_zero: bool = True,
                         repair_prompt=None, on_attempt=None) -> dict:
    """Ask `submit` for a program, run it, and ask again while it fails.

    `submit(prompt_text, attempt)` returns the agent's reply for one turn — or
    None if the turn produced no reply at all (task failed or timed out), which
    stops the loop because there is nothing to run or to correct.
    `repair_prompt(previous_code, report, attempt, total)` builds the follow-up
    message (normally `prompts.user.make_gen_des_repair`). The loop runs the
    returned program after every turn and stops at the first one that passes.
    It always returns the last program, successful or not, together with the
    verdict, so a caller that runs out of attempts still has the program and the
    reason it failed.
    """
    total = DES_REPAIR_ATTEMPTS if attempts is None else attempts
    # `total` counts repairs, so a total of 3 allows 4 programs: the initial
    # one plus three corrections.
    codes: list[str] = []
    verdict: dict | None = None
    prompt = None

    for i in range(total + 1):
        reply = submit(prompt, i)
        if reply is None:
            verdict = {"ok": False, "kpis": {}, "execution": None,
                       "report": ("The agent returned no program for this turn "
                                  "(the task failed or did not complete in time), "
                                  "so there was nothing to run.")}
            if callable(on_attempt):
                on_attempt(i, None, verdict)
            break
        code = strip_code_fence(reply)
        codes.append(code)
        verdict = verify(code, requirements=requirements, workdir=workdir,
                         timeout_s=timeout_s, python=python,
                         reject_all_zero=reject_all_zero)
        if callable(on_attempt):
            on_attempt(i, code, verdict)
        if verdict["ok"] or i == total:
            break
        prompt = (repair_prompt(code, verdict["report"], i + 1, total)
                  if callable(repair_prompt) else verdict["report"])

    return {"code": codes[-1] if codes else None, "codes": codes,
            "ok": bool(verdict and verdict["ok"]),
            "kpis": (verdict or {}).get("kpis", {}),
            "report": (verdict or {}).get("report", ""),
            "repaired": max(len(codes) - 1, 0), "attempts": len(codes),
            "execution": (verdict or {}).get("execution")}
