#!/usr/bin/env python3
"""
Semantic static analysis test suite for cement plant digital twin PyChrono code.

Goal: validate *meaningful structure and intent* from task.md without executing PyChrono.
We rely on AST-based checks (more robust than substring matching).

Usage:
    python tests.py                    # test all *_code.py, print table, write results.md
    python tests.py qwen_code.py       # test single file
    python tests.py --json             # output raw JSON
"""

from __future__ import annotations

import ast
import sys
import json
from pathlib import Path
from datetime import datetime

TEST_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_source(filepath: Path) -> str:
    if not filepath.exists():
        return ""
    return filepath.read_text(encoding="utf-8", errors="replace")


def try_parse(source: str):
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def iter_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def call_name(call: ast.Call) -> str | None:
    fn = call.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return None


def dotted_name(expr: ast.AST) -> str | None:
    # Best-effort for `pychrono.core as chrono` style: `chrono.ChSystemNSC`
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        left = dotted_name(expr.value)
        if left:
            return f"{left}.{expr.attr}"
        return expr.attr
    return None


def contains_number_literal(tree: ast.AST, value: float) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if float(node.value) == float(value):
                return True
    return False


def contains_any_string(tree: ast.AST, needles: set[str]) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value.lower()
            for n in needles:
                if n in s:
                    return True
    return False


def has_import_pychrono(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            else:
                if node.module:
                    names = [node.module]
            if any(n.startswith("pychrono") for n in names):
                return True
    return False


def find_chsystem_inits(tree: ast.AST) -> int:
    count = 0
    for c in iter_calls(tree):
        n = dotted_name(c.func) or ""
        if n.endswith("ChSystemNSC") or n.endswith("ChSystemSMC"):
            count += 1
    return count


def has_gravity_set(tree: ast.AST) -> bool:
    # Accept Set_G_acc or SetGravity
    for c in iter_calls(tree):
        n = call_name(c)
        if n in ("Set_G_acc", "SetGravity"):
            return True
    return False


EQUIPMENT_CONSTRUCTORS = {
    "ChBodyEasyBox",
    "ChBodyEasyCylinder",
    "ChBodyEasySphere",
}


def equipment_instances_created(tree: ast.AST) -> int:
    count = 0
    for c in iter_calls(tree):
        n = dotted_name(c.func) or ""
        if any(n.endswith("." + ctor) or n == ctor for ctor in EQUIPMENT_CONSTRUCTORS):
            count += 1
    return count


def has_add_to_system(tree: ast.AST) -> bool:
    # Accept Add/AddBody/AddLink/AddSensor as evidence objects are registered into system.
    for c in iter_calls(tree):
        n = call_name(c)
        if n in ("Add", "AddBody", "AddLink", "AddSensor"):
            return True
    return False


def has_materials_semantic(tree: ast.AST) -> bool:
    # Accept either explicit materials (ChMaterialSurface*) OR material assignment OR density-based bodies.
    explicit = False
    for c in iter_calls(tree):
        n = dotted_name(c.func) or ""
        if "ChMaterialSurface" in n:
            explicit = True
            break

    set_surface = False
    for c in iter_calls(tree):
        if call_name(c) in ("SetMaterialSurface", "SetMaterial"):
            set_surface = True
            break

    # Density-based: many ChBodyEasy* signatures include density as 4th numeric arg (heuristic).
    density_like = False
    for c in iter_calls(tree):
        n = dotted_name(c.func) or ""
        if any(n.endswith("." + ctor) or n == ctor for ctor in EQUIPMENT_CONSTRUCTORS):
            if len(c.args) >= 4:
                a = c.args[3]
                if isinstance(a, ast.Constant) and isinstance(a.value, (int, float)) and a.value > 0:
                    density_like = True
                    break

    return explicit or set_surface or density_like


def has_joints_or_constraints(tree: ast.AST) -> bool:
    # Strong signal: explicit Chrono links/motors
    for c in iter_calls(tree):
        n = dotted_name(c.func) or ""
        if ".ChLink" in n or n.startswith("ChLink") or "ChLink" in n:
            return True

    # Weaker-but-semantic signal: the script constrains bodies via fixed bodies and explicit rotations/frames.
    # This keeps the test common across different coding styles (some scripts use fixed supports instead of links).
    has_fixed = False
    for c in iter_calls(tree):
        if call_name(c) == "SetBodyFixed":
            has_fixed = True
            break

    has_rot_or_frame = False
    for c in iter_calls(tree):
        n = dotted_name(c.func) or ""
        if call_name(c) in ("SetRot", "Initialize") or "Q_from_" in n or "ChFrame" in n or "ChCoordsys" in n:
            has_rot_or_frame = True
            break

    return has_fixed and has_rot_or_frame


def do_step_inside_loop(tree: ast.AST) -> bool:
    """
    True if the simulation advances in a loop.

    Accepts two patterns:
    - direct: DoStepDynamics is called inside a for/while loop
    - indirect: a function/method called inside the loop contains DoStepDynamics
    """

    # Collect which functions contain DoStepDynamics
    funcs_with_step: set[str] = set()

    class StepFinder(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef):
            has_step = False
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call) and call_name(inner) == "DoStepDynamics":
                    has_step = True
                    break
            if has_step:
                funcs_with_step.add(node.name)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            self.visit_FunctionDef(node)  # type: ignore[arg-type]

    StepFinder().visit(tree)

    class LoopVisitor(ast.NodeVisitor):
        def __init__(self):
            self.in_loop = 0
            self.found = False

        def visit_For(self, node: ast.For):
            self.in_loop += 1
            self.generic_visit(node)
            self.in_loop -= 1

        def visit_While(self, node: ast.While):
            self.in_loop += 1
            self.generic_visit(node)
            self.in_loop -= 1

        def visit_Call(self, node: ast.Call):
            if self.in_loop > 0:
                # Direct
                if call_name(node) == "DoStepDynamics":
                    self.found = True
                    return
                # Indirect
                callee = call_name(node)
                if callee and callee in funcs_with_step:
                    self.found = True
                    return
            self.generic_visit(node)

    v = LoopVisitor()
    v.visit(tree)
    return v.found


def has_try_except(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and node.handlers:
            return True
    return False


def has_cleanup(tree: ast.AST) -> bool:
    # finally block OR explicit conn.close/system.RemoveAll/application.Clear etc.
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and node.finalbody:
            return True
    for c in iter_calls(tree):
        n = call_name(c)
        if n in ("close", "RemoveAll", "Clear", "RemoveAllBodies"):
            return True
    return False


def has_db_logging_semantic(tree: ast.AST) -> bool:
    # Accept either SQL usage mentioning plant_data/sensor_metadata/metadata or dict keys for log records.
    sql_words = {"plant_data", "sensor_metadata", "metadata"}
    if contains_any_string(tree, sql_words):
        return True

    # Dict logging: look for dict literals containing required keys.
    required = {"timestamp", "value", "sensor_id", "plant_id"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = set()
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
            if required.issubset(keys):
                return True
    return False


def has_required_sensors_semantic(tree: ast.AST) -> bool:
    # We accept a file if it clearly models at least 4/5 sensor categories from task.md.
    # Categories: temperature, pressure/vacuum, fineness/grind, gas(CO/NOx), mill load.
    cats = {
        "temperature": {"температур", "temperature", "kiln temperature", "kiln temp"},
        "pressure": {"pressure", "vacuum", "разреж", "cyclone pressure", "cyclone vacuum"},
        "fineness": {"fineness", "grind", "тонкост", "помол"},
        "gas": {"co", "nox", "газ", "gas", "gas_analysis", "emission"},
        "load": {"load", "mill_load", "загруз", "mill loading"},
    }
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value.lower()
            for cat, needles in cats.items():
                if cat in found:
                    continue
                for n in needles:
                    if n in s:
                        found.add(cat)
                        break
    # Also allow identifiers to contribute (variable names, attr names)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id.lower() if isinstance(node, ast.Name) else node.attr.lower()
            for cat, needles in cats.items():
                if cat in found:
                    continue
                for n in needles:
                    if n in name:
                        found.add(cat)
                        break
    return len(found) >= 4


def has_critical_params_semantic(tree: ast.AST) -> bool:
    # Two acceptable semantics:
    # 1) Explicit thresholds: mentions 1450 & 1480 & 0.1
    # 2) Operational setpoints aligned to spec: has a kiln/furnace temperature ~1450-1480 and CO values clearly below 0.1
    has_1450 = contains_number_literal(tree, 1450) or contains_any_string(tree, {"1450"})
    has_1480 = contains_number_literal(tree, 1480) or contains_any_string(tree, {"1480"})
    has_co_limit = contains_number_literal(tree, 0.1) or contains_any_string(tree, {"0.1"})
    if (has_1450 and has_1480) and has_co_limit:
        return True

    # Operational evidence (heuristic): typical setpoints inside required range.
    # We accept any literal 1450..1480 and any CO literal 0.0..0.09.
    has_temp_in_range = False
    has_co_good = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            v = float(node.value)
            if 1450.0 <= v <= 1480.0:
                has_temp_in_range = True
            if 0.0 <= v <= 0.09:
                # This is a broad heuristic; presence of CO-like strings is checked in sensor test.
                has_co_good = True
    return has_temp_in_range and has_co_good


def has_main_entry(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            # Look for: if __name__ == "__main__"
            test = node.test
            if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == "__name__":
                for comp in test.comparators:
                    if isinstance(comp, ast.Constant) and comp.value == "__main__":
                        return True
    return False


# ---------------------------------------------------------------------------
# Semantic tests (common for all)
# Each test returns bool (pass/fail). We keep test count stable for scoring.
# ---------------------------------------------------------------------------


def t01_non_empty(src: str):
    """T01 Non-empty file"""
    return len(src.strip()) > 0


def t02_syntax_valid(src: str):
    """T02 Syntax valid (ast.parse)"""
    return try_parse(src) is not None


def t03_imports_pychrono_sem(src: str):
    """T03 Imports pychrono (any submodule)"""
    tree = try_parse(src)
    return bool(tree) and has_import_pychrono(tree)


def t04_chsystem_init_sem(src: str):
    """T04 Initializes Chrono system (ChSystemNSC/SMC)"""
    tree = try_parse(src)
    return bool(tree) and find_chsystem_inits(tree) > 0


def t05_gravity_sem(src: str):
    """T05 Sets gravity (Set_G_acc/SetGravity)"""
    tree = try_parse(src)
    return bool(tree) and has_gravity_set(tree)


def t06_equipment_created_sem(src: str):
    """T06 Creates physical equipment bodies (>=4 bodies)"""
    tree = try_parse(src)
    return bool(tree) and equipment_instances_created(tree) >= 4


def t07_added_to_system_sem(src: str):
    """T07 Adds created objects to Chrono system (Add/AddBody/AddLink/AddSensor)"""
    tree = try_parse(src)
    return bool(tree) and has_add_to_system(tree)


def t08_materials_sem(src: str):
    """T08 Uses materials (explicit or implicit)"""
    tree = try_parse(src)
    return bool(tree) and has_materials_semantic(tree)


def t09_joints_sem(src: str):
    """T09 Uses joints/constraints (ChLink*)"""
    tree = try_parse(src)
    return bool(tree) and has_joints_or_constraints(tree)


def t10_sensors_sem(src: str):
    """T10 Models required sensors (>=4/5 categories)"""
    tree = try_parse(src)
    return bool(tree) and has_required_sensors_semantic(tree)


def t11_simulation_step_in_loop_sem(src: str):
    """T11 Advances simulation in a loop (DoStepDynamics inside for/while)"""
    tree = try_parse(src)
    return bool(tree) and do_step_inside_loop(tree)


def t12_db_logging_sem(src: str):
    """T12 Logs data compatible with DB schema (SQL tables or dict keys)"""
    tree = try_parse(src)
    return bool(tree) and has_db_logging_semantic(tree)


def t13_critical_params_sem(src: str):
    """T13 Mentions critical parameters (1450/1480 and CO 0.1)"""
    tree = try_parse(src)
    return bool(tree) and has_critical_params_semantic(tree)


def t14_error_handling_sem(src: str):
    """T14 Has error handling (try/except)"""
    tree = try_parse(src)
    return bool(tree) and has_try_except(tree)


def t15_cleanup_sem(src: str):
    """T15 Has cleanup (finally or close/clear/remove)"""
    tree = try_parse(src)
    return bool(tree) and has_cleanup(tree)


def t16_main_entry_sem(src: str):
    """T16 Has __main__ entry point"""
    tree = try_parse(src)
    return bool(tree) and has_main_entry(tree)


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------

ALL_TESTS = [
    t01_non_empty,
    t02_syntax_valid,
    t03_imports_pychrono_sem,
    t04_chsystem_init_sem,
    t05_gravity_sem,
    t06_equipment_created_sem,
    t07_added_to_system_sem,
    t08_materials_sem,
    t09_joints_sem,
    t10_sensors_sem,
    t11_simulation_step_in_loop_sem,
    t12_db_logging_sem,
    t13_critical_params_sem,
    t14_error_handling_sem,
    t15_cleanup_sem,
    t16_main_entry_sem,
]


def extract_test_id(fn) -> str:
    return fn.__doc__.split()[0]


def extract_test_name(fn) -> str:
    return " ".join(fn.__doc__.split()[1:])


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_tests_for_file(filepath: Path) -> dict:
    src = read_source(filepath)
    results = []
    passed = 0
    for fn in ALL_TESTS:
        tid = extract_test_id(fn)
        name = extract_test_name(fn)
        try:
            ok = bool(fn(src))
        except Exception as e:
            ok = False
        results.append({"id": tid, "name": name, "passed": ok})
        if ok:
            passed += 1
    total = len(ALL_TESTS)
    return {
        "file": filepath.name,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "percent": round(passed / total * 100, 1) if total else 0,
        "tests": results,
    }


def discover_code_files() -> list[Path]:
    files = sorted(TEST_DIR.glob("*_code.py"))
    return files


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def print_summary_table(all_results: list[dict]):
    files = [r["file"] for r in all_results]
    col_w = max(max((len(f) for f in files), default=10), 10)

    header_file = "File".ljust(col_w)
    header = f"| {header_file} | Passed | Failed | Total | Percent |"
    sep = f"|{'-' * (col_w + 2)}|--------|--------|-------|---------|"

    print()
    print(header)
    print(sep)
    for r in all_results:
        name = r["file"].ljust(col_w)
        print(f"| {name} | {r['passed']:>6} | {r['failed']:>6} | {r['total']:>5} | {r['percent']:>6.1f}% |")
    print()


def print_detail_table(result: dict):
    print(f"\n{'=' * 60}")
    print(f"  {result['file']}  —  {result['passed']}/{result['total']} passed ({result['percent']}%)")
    print(f"{'=' * 60}")
    for t in result["tests"]:
        status = "PASS" if t["passed"] else "FAIL"
        mark = "+" if t["passed"] else "-"
        print(f"  [{mark}] {t['id']} {t['name']:.<45} {status}")


def generate_results_md(all_results: list[dict], outpath: Path):
    lines = []
    lines.append("# Test Results — Cement Plant Digital Twin Benchmark")
    lines.append("")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")

    files = [r["file"] for r in all_results]
    col_w = max(max((len(f) for f in files), default=10), 10)

    lines.append(f"| {'File'.ljust(col_w)} | Passed | Failed | Total | Percent |")
    lines.append(f"|{'-' * (col_w + 2)}|--------|--------|-------|---------|")
    for r in all_results:
        name = r["file"].ljust(col_w)
        lines.append(f"| {name} | {r['passed']:>6} | {r['failed']:>6} | {r['total']:>5} | {r['percent']:>6.1f}% |")

    lines.append("")
    lines.append("---")
    lines.append("")

    for r in all_results:
        lines.append(f"## {r['file']}  —  {r['passed']}/{r['total']} ({r['percent']}%)")
        lines.append("")
        lines.append("| # | Test | Result |")
        lines.append("|---|------|--------|")
        for t in r["tests"]:
            mark = "PASS" if t["passed"] else "FAIL"
            icon = "+" if t["passed"] else "-"
            lines.append(f"| {t['id']} | {t['name']} | {icon} {mark} |")
        lines.append("")

    outpath.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    output_json = "--json" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("-")]

    if args:
        targets = [TEST_DIR / a for a in args]
    else:
        targets = discover_code_files()

    if not targets:
        print("No *_code.py files found in", TEST_DIR)
        sys.exit(1)

    all_results = []
    for fp in targets:
        result = run_tests_for_file(fp)
        all_results.append(result)

    if output_json:
        print(json.dumps(all_results, indent=2, ensure_ascii=False))
    else:
        for r in all_results:
            print_detail_table(r)
        print_summary_table(all_results)

    results_path = TEST_DIR / "results.md"
    generate_results_md(all_results, results_path)
    if not output_json:
        print(f"Results written to {results_path}")

    total_pass = sum(r["passed"] for r in all_results)
    total_all = sum(r["total"] for r in all_results)
    sys.exit(0 if total_pass == total_all else 1)


if __name__ == "__main__":
    main()
