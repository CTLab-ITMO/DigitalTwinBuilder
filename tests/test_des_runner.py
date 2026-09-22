"""Tests for the DES acceptance gate in `des_runner`.

The gate has two halves: the contract (three KPI lines were printed) and the
semantic bounds (the three numbers could have come from the line the program was
given). The bounds are the half that was missing until 2026-09-21: a program
that ran, printed the contract and reported a raw part count as a rate was
accepted, scoring 126x the true throughput.

The evidence has two sides, and both are pinned here:

* false positives — the five reference lines of the comparison suite, from their
  ground-truth parameters and KPIs. Every one of them must pass the bounds, with
  the margin the bound slacks are derived from.
* true positives — the programs C actually accepted, verbatim from
  `runs/20260920_064710_des-repair`. Every one of them must be rejected, and by
  the bound that its defect actually violates.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "digital_twin_builder"))

import des_runner  # noqa: E402
from prompts import system as system_prompts  # noqa: E402


# --------------------------------------------------------------------------- #
# the five reference lines (comparison/cases/*/manifest.json, in C's line shape)
# --------------------------------------------------------------------------- #
# (id, processing_time_s, availability_pct, mttr_s, power_working_kw,
#  power_idle_kw), plus the arrival interval, buffer capacities and ground truth.
CASES = {
    "case_0001_serial_line": {
        "stations": [
            ("M1", 150, 98.0, 600, 4.0, 0.4),
            ("M2", 120, 97.0, 900, 5.0, 0.5),
            ("M3", 180, 95.0, 1200, 6.0, 0.6),
            ("M4", 120, 97.0, 900, 5.0, 0.5),
            ("M5", 150, 98.0, 600, 4.0, 0.4),
        ],
        "buffers": [20, 8, 8, 8, 8],
        "inter_arrival_s": 130,
        "truth": (19.868056, 40.386633, 0.989219),
    },
    "case_0002_saturated_short_line": {
        "stations": [
            ("M1", 90, 99.0, 600, 3.0, 0.3),
            ("M2", 70, 98.0, 900, 4.5, 0.45),
            ("M3", 110, 99.0, 1200, 6.0, 0.6),
        ],
        "buffers": [15, 5, 5],
        "inter_arrival_s": 60,
        "truth": (32.62, 27.91672, 0.352459),
    },
    "case_0003_starved_six_line": {
        "stations": [
            ("M1", 200, 97.0, 900, 5.0, 0.5),
            ("M2", 220, 97.0, 1000, 5.5, 0.55),
            ("M3", 240, 96.0, 1200, 6.0, 0.6),
            ("M4", 260, 96.0, 1400, 7.0, 0.7),
            ("M5", 230, 97.0, 1100, 6.5, 0.65),
            ("M6", 210, 97.0, 1000, 6.0, 0.6),
        ],
        "buffers": [10, 10, 10, 10, 10, 10],
        "inter_arrival_s": 300,
        "truth": (11.990833, 5.25071, 2.353658),
    },
    "case_0004_failure_heavy_line": {
        "stations": [
            ("M1", 100, 90.0, 2400, 4.0, 0.4),
            ("M2", 130, 92.0, 3000, 5.0, 0.5),
            ("M3", 90, 88.0, 3600, 4.5, 0.45),
            ("M4", 140, 91.0, 4800, 7.0, 0.7),
            ("M5", 110, 93.0, 2400, 5.5, 0.55),
        ],
        "buffers": [6, 3, 3, 3, 3],
        "inter_arrival_s": 150,
        "truth": (22.400833, 7.28912, 0.873547),
    },
    "case_0005_high_rate_line": {
        "stations": [
            ("M1", 60, 99.5, 300, 3.0, 0.3),
            ("M2", 80, 99.0, 600, 5.0, 0.5),
            ("M3", 70, 99.0, 600, 4.5, 0.45),
            ("M4", 75, 99.5, 300, 4.0, 0.4),
        ],
        "buffers": [25, 10, 10, 10],
        "inter_arrival_s": 45,
        "truth": (44.990833, 38.88238, 0.335373),
    },
}


def requirements_for(spec: dict, topology: str = "serial") -> dict:
    """The `requirements` object as C's UI agent declares it: `line` in seconds,
    availability in percent, station field names as the GenDES prompt names them.
    """
    return {
        "line": {
            "topology": topology,
            "source": {"inter_arrival_time_s": spec["inter_arrival_s"]},
            "stations": [
                {"id": mid, "processing_time_s": pt, "availability_pct": av,
                 "mttr_s": mttr, "power_working_kw": pw, "power_idle_kw": pi}
                for mid, pt, av, mttr, pw, pi in spec["stations"]],
            "buffers": [
                {"id": f"B{i}", "capacity": cap} for i, cap in enumerate(spec["buffers"])],
        },
        "des_horizon": {"warmup_s": 21600, "window_s": 432000, "replications": 10},
    }


def kpis(throughput, wip, energy) -> dict:
    return {"throughput_per_hour": throughput, "wip_parts": wip,
            "energy_per_part_kwh": energy}


# --------------------------------------------------------------------------- #
# false positives: the ground truth of the reference lines must pass
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("case", sorted(CASES))
def test_ground_truth_kpis_pass_the_bounds(case):
    spec = CASES[case]
    tp, wip, energy = spec["truth"]
    assert des_runner._implausible_kpis(
        kpis(tp, wip, energy), requirements_for(spec)) is None


def test_the_bounds_leave_the_margin_they_claim():
    """The slacks are only safe while the truth stays inside them. These are the
    margins the comments in des_runner quote (0.952, 2.02x, 0.909); a case whose
    truth moves past one has to be re-derived, not silently accommodated.

    A ceiling is a `max` statistic (the closest truth to the ceiling is the
    largest ratio) and a floor is a `min` one (the closest truth to the floor is
    the smallest ratio) — taking the wrong one would let a single case cross its
    bound with the test still green.
    """
    worst_ceiling = worst_energy = 0.0
    worst_floor = float("inf")
    for spec in CASES.values():
        b = des_runner._serial_bounds(requirements_for(spec)["line"])
        tp, _, energy = spec["truth"]
        worst_ceiling = max(worst_ceiling, tp / b["throughput_ceiling"])
        worst_floor = min(worst_floor, tp / b["throughput_floor"])
        worst_energy = max(worst_energy, energy / b["energy_ceiling"])
    assert worst_ceiling < 1.0
    assert worst_floor > 1.0
    assert worst_energy < 1.0


# --------------------------------------------------------------------------- #
# true positives: what C accepted, and why each must be rejected
# --------------------------------------------------------------------------- #
# case, throughput, wip, energy -> the phrase the repair message must contain.
ACCEPTED_AND_WRONG = [
    # 126 hours of parts reported as parts/hour: the count was never divided by
    # the window. The line's ceiling is 45 parts/hour.
    ("case_0005_high_rate_line", 5666.2, 26.626337962962964, 0.3072613173445137,
     "above what this line can do"),
    # The same defect one order of magnitude milder, plus energy over its
    # ceiling by 100x.
    ("case_0005_high_rate_line", 246.62, 0.05, 0.702782,
     "above what this line can do"),
    # Energy per part of 47.2 kWh where processing one part costs 0.38 kWh.
    ("case_0002_saturated_short_line", 29.36, 23.3, 47.2033,
     "above what this line can consume"),
    # WIP read by the KPI block from a counter that is never incremented.
    ("case_0003_starved_six_line", 12.57, 0.0, 2.285905,
     "while producing 12.57 parts/hour"),
    # Energy accumulated for no station state at all.
    ("case_0004_failure_heavy_line", 8.06, 11.21, 0.0,
     "far below what this line must produce"),
    # A blocked or uncounted model: nothing reached the sink in 120 hours.
    ("case_0004_failure_heavy_line", 0.0, 68.29, 0.0,
     "nothing reached the sink"),
]


@pytest.mark.parametrize("case,tp,wip,energy,phrase", ACCEPTED_AND_WRONG)
def test_accepted_but_wrong_programs_are_rejected(case, tp, wip, energy, phrase):
    reason = des_runner._implausible_kpis(
        kpis(tp, wip, energy), requirements_for(CASES[case]))
    assert reason is not None, f"{case} {tp}/{wip}/{energy} should not pass"
    assert phrase in reason


def test_raw_part_count_as_a_rate_is_named_in_the_message():
    """The historical defect should be recognisable to the model that reads the
    repair message: it is told the count was not divided by the window."""
    reason = des_runner._implausible_kpis(
        kpis(5666.2, 26.6, 0.307), requirements_for(CASES["case_0005_high_rate_line"]))
    assert "not divided by the measurement window" in reason


# --------------------------------------------------------------------------- #
# no bound is invented from parameters that are not there
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("topology", ["serial_with_parallel", "assembly", "other"])
def test_a_non_serial_line_is_not_bounded(topology):
    """A parallel branch can beat the single-chain ceiling legitimately, so the
    bounds must not fire on a topology they were not derived for."""
    spec = CASES["case_0005_high_rate_line"]
    assert des_runner._serial_bounds(requirements_for(spec, topology)["line"]) is None
    assert des_runner._implausible_kpis(
        kpis(5666.2, 26.6, 0.307), requirements_for(spec, topology)) is None


def test_an_absent_topology_is_treated_as_serial():
    spec = CASES["case_0002_saturated_short_line"]
    req = requirements_for(spec)
    del req["line"]["topology"]
    assert des_runner._implausible_kpis(kpis(500.0, 27.0, 0.35), req) is not None


def test_a_line_with_no_numbers_gets_no_bounds():
    """Null parameters are the requirements' gap, not the model's defect."""
    assert des_runner._serial_bounds({"stations": [
        {"id": "M1", "processing_time_s": None, "availability_pct": None,
         "power_working_kw": None}]}) is None
    assert des_runner._serial_bounds({}) is None


def test_missing_kpis_are_not_judged():
    """A missing KPI is the contract's business, handled before this."""
    spec = CASES["case_0002_saturated_short_line"]
    req = requirements_for(spec)
    assert des_runner._implausible_kpis(kpis(None, None, None), req) is None
    assert des_runner._implausible_kpis(kpis(32.0, None, None), req) is None


# --------------------------------------------------------------------------- #
# a malformed requirements object is a gap, never a crash
# --------------------------------------------------------------------------- #
# The requirements are authored by an LLM agent, so `line` or `source` can come
# back as a string or a list where a mapping was asked for. The gate runs on
# every replication, and a raise here aborts the whole replication (the harness
# records it as `generation_error` and loses the measurement), whereas the
# contract-only gate it replaced returned a verdict. A shape the bounds cannot
# read must therefore mean "no bounds", not an exception.
MALFORMED_LINES = ["serial", [], 5, True]
# Every shape here has to be survivable. The first group has no readable line
# at all and so no bound can follow from it; the last one has readable stations
# and an unreadable source, so the ceiling it can still derive must fire.
MALFORMED_REQUIREMENTS = [
    None,
    [],
    "serial line",
    {"line": None},
    {"line": "M1 -> M2 -> M3"},
    {"line": ["M1", "M2"]},
    {"line": {"stations": "M1, M2"}},
    {"line": {"stations": [None, "M1", {"processing_time_s": None}]}},
    # A non-iterable here is what a hand-written scalar in a JSON field looks
    # like; it reached the `for st in stations` loop and raised TypeError.
    {"line": {"stations": 5}},
    {"line": {"stations": True}},
    {"line": {"stations": 3.5}},
    {"line": {"stations": {"M1": 1}}},
]
UNREADABLE_LINE_REQUIREMENTS = MALFORMED_REQUIREMENTS
READABLE_STATIONS_BAD_SOURCE = {
    "line": {"topology": "serial", "source": "every 60s", "stations": [
        {"processing_time_s": 90, "availability_pct": 99.0,
         "power_working_kw": 3.0}]}}


@pytest.mark.parametrize("requirements",
                         [*MALFORMED_REQUIREMENTS, READABLE_STATIONS_BAD_SOURCE])
def test_malformed_requirements_never_raise(requirements):
    """Whatever the agent writes, the gate returns a verdict, not a traceback."""
    des_runner._implausible_kpis(kpis(500.0, 27.0, 0.35), requirements)
    des_runner._all_zero_implausible(kpis(0.0, 0.0, 0.0), requirements)


@pytest.mark.parametrize("requirements", UNREADABLE_LINE_REQUIREMENTS)
def test_an_unreadable_line_yields_no_bounds(requirements):
    assert des_runner._implausible_kpis(kpis(500.0, 27.0, 0.35),
                                       requirements) is None


def test_a_bad_source_does_not_suppress_the_ceiling():
    """The ceiling needs only the stations; a source the bounds cannot read
    costs the floor, not the bound that is still derivable."""
    reason = des_runner._implausible_kpis(kpis(500.0, 27.0, 0.35),
                                         READABLE_STATIONS_BAD_SOURCE)
    assert reason is not None and "above what this line can do" in reason


@pytest.mark.parametrize("line", MALFORMED_LINES)
def test_malformed_line_is_read_as_no_bounds(line):
    assert des_runner._serial_bounds(line) is None


@pytest.mark.parametrize("kpis_", [None, [], "throughput = 1", 5])
def test_malformed_kpis_are_not_judged(kpis_):
    spec = CASES["case_0002_saturated_short_line"]
    assert des_runner._implausible_kpis(kpis_, requirements_for(spec)) is None


def test_the_all_zero_check_still_fires_on_well_formed_requirements():
    assert des_runner._all_zero_implausible(
        kpis(0.0, 0.0, 0.0), {"line": {"source": {"inter_arrival_time_s": 60}}}
    ) is not None


# --------------------------------------------------------------------------- #
# the source's interval, under either of the two names it is written
# --------------------------------------------------------------------------- #
def test_the_arrival_interval_reads_under_either_name():
    assert des_runner._inter_arrival_s({"inter_arrival_time_s": 60}) == 60.0
    assert des_runner._inter_arrival_s({"interarrival_time_s": 60}) == 60.0
    assert des_runner._inter_arrival_s({}) is None
    assert des_runner._inter_arrival_s("every 60s") is None


def test_a_null_primary_name_does_not_hide_the_alias():
    """`dict.get("a", b)` falls back only on a *missing* key, so a key that is
    present and null hides the alias. The requirements are agent-authored and
    can carry both names; the interval must still be found."""
    src = {"inter_arrival_time_s": None, "interarrival_time_s": 60}
    assert des_runner._inter_arrival_s(src) == 60.0
    line = {"topology": "serial", "source": src, "stations": [
        {"processing_time_s": 90, "availability_pct": 99.0,
         "power_working_kw": 3.0}]}
    assert des_runner._serial_bounds(line)["inter_arrival_s"] == 60.0
    assert des_runner._all_zero_implausible(
        kpis(0.0, 0.0, 0.0), {"line": line}) is not None


@pytest.mark.parametrize("rate", [True, False])
def test_a_boolean_arrival_interval_is_not_a_number(rate):
    """`True` is 1 in Python; a declared interval of `true` is nonsense, not a
    one-second interval, and must not put the floor at its 1s value."""
    assert des_runner._inter_arrival_s({"inter_arrival_time_s": rate}) is None
    line = {"topology": "serial", "source": {"inter_arrival_time_s": rate},
            "stations": [{"processing_time_s": 90, "availability_pct": 99.0,
                          "power_working_kw": 3.0}]}
    assert "throughput_floor" not in des_runner._serial_bounds(line)


def test_availability_reads_in_both_notations():
    """`availability_pct` is percent in the requirements and a fraction in the
    case data; both name the same machine and must yield the same bound."""
    pct = {"stations": [{"processing_time_s": 100, "availability_pct": 90,
                         "power_working_kw": 4.0}]}
    frac = {"stations": [{"processing_time_s": 100, "availability_pct": 0.9,
                          "power_working_kw": 4.0}]}
    assert des_runner._serial_bounds(pct) == des_runner._serial_bounds(frac)


def test_a_station_that_idles_harder_than_it_works_has_no_energy_ceiling():
    line = {"stations": [{"processing_time_s": 100, "availability_pct": 99.0,
                          "power_working_kw": 1.0, "power_idle_kw": 5.0}]}
    assert "energy_ceiling" not in des_runner._serial_bounds(line)


# --------------------------------------------------------------------------- #
# end to end: the shipped blueprint passes the whole gate
# --------------------------------------------------------------------------- #
BEGIN, END = "# --- BEGIN PARAMETERS ---", "# --- END PARAMETERS ---"


def instantiate_blueprint(spec: dict, *, warmup_s: int, window_s: int,
                          replications: int) -> str:
    """The blueprint C ships in `GenDES`, with a case's numbers in its PARAMS."""
    rows = "".join(
        f'    {{"id": {mid!r}, "processing_time_s": {pt}, '
        f'"availability_pct": {av}, "mttr_s": {mttr}, '
        f'"power_working_kw": {pw}, "power_idle_kw": {pi}}},\n'
        for mid, pt, av, mttr, pw, pi in spec["stations"])
    params = (f"STATIONS = [\n{rows}]\n"
              f"BUFFERS = {spec['buffers']}\n"
              f'INTER_ARRIVAL_S = {spec["inter_arrival_s"]}\n'
              f"WARMUP_S = {warmup_s}\nWINDOW_S = {window_s}\n"
              f"REPLICATIONS = {replications}\n")
    head, rest = system_prompts.DES_BLUEPRINT.split(BEGIN)
    _, tail = rest.split(END)
    return f"{head}{BEGIN}\n{params}{END}{tail}"


def test_the_blueprint_as_shipped_in_the_prompt_is_accepted_by_the_gate():
    """The prompt's reference program must pass the very check the prompt's
    output has to pass, on a real line. A short horizon keeps it quick: the
    bounds are dimensional, so they do not depend on how long the run is."""
    pytest.importorskip("simpy")
    spec = CASES["case_0002_saturated_short_line"]
    code = instantiate_blueprint(spec, warmup_s=3600, window_s=7200,
                                 replications=3)
    verdict = des_runner.verify(code, requirements=requirements_for(spec),
                               python=sys.executable, timeout_s=300)
    assert verdict["ok"], verdict["report"]
    tp = verdict["kpis"]["throughput_per_hour"]
    assert 0 < tp <= 3600 / max(s[1] for s in spec["stations"])


def test_the_blueprint_is_embedded_in_the_prompt_the_agent_is_given():
    assert system_prompts.DES_BLUEPRINT in system_prompts.GenDES
    assert re.search(r"^import random$", system_prompts.DES_BLUEPRINT, re.M)
