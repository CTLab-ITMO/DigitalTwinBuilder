# Test Results — Cement Plant Digital Twin Benchmark

Generated: 2026-03-17 09:41:33

## Summary

| File             | Passed | Failed | Total | Percent |
|------------------|--------|--------|-------|---------|
| claude_code.py   |     16 |      0 |    16 |  100.0% |
| deepseek_code.py |     16 |      0 |    16 |  100.0% |
| gemini_code.py   |      1 |     15 |    16 |    6.2% |
| gpt_code.py      |     15 |      1 |    16 |   93.8% |
| qwen_code.py     |     16 |      0 |    16 |  100.0% |
| ya_gpt_code.py   |     12 |      4 |    16 |   75.0% |

---

## claude_code.py  —  16/16 (100.0%)

| # | Test | Result |
|---|------|--------|
| T01 | Non-empty file | + PASS |
| T02 | Syntax valid (ast.parse) | + PASS |
| T03 | Imports pychrono (any submodule) | + PASS |
| T04 | Initializes Chrono system (ChSystemNSC/SMC) | + PASS |
| T05 | Sets gravity (Set_G_acc/SetGravity) | + PASS |
| T06 | Creates physical equipment bodies (>=4 bodies) | + PASS |
| T07 | Adds created objects to Chrono system (Add/AddBody/AddLink/AddSensor) | + PASS |
| T08 | Uses materials (explicit or implicit) | + PASS |
| T09 | Uses joints/constraints (ChLink*) | + PASS |
| T10 | Models required sensors (>=4/5 categories) | + PASS |
| T11 | Advances simulation in a loop (DoStepDynamics inside for/while) | + PASS |
| T12 | Logs data compatible with DB schema (SQL tables or dict keys) | + PASS |
| T13 | Mentions critical parameters (1450/1480 and CO 0.1) | + PASS |
| T14 | Has error handling (try/except) | + PASS |
| T15 | Has cleanup (finally or close/clear/remove) | + PASS |
| T16 | Has __main__ entry point | + PASS |

## deepseek_code.py  —  16/16 (100.0%)

| # | Test | Result |
|---|------|--------|
| T01 | Non-empty file | + PASS |
| T02 | Syntax valid (ast.parse) | + PASS |
| T03 | Imports pychrono (any submodule) | + PASS |
| T04 | Initializes Chrono system (ChSystemNSC/SMC) | + PASS |
| T05 | Sets gravity (Set_G_acc/SetGravity) | + PASS |
| T06 | Creates physical equipment bodies (>=4 bodies) | + PASS |
| T07 | Adds created objects to Chrono system (Add/AddBody/AddLink/AddSensor) | + PASS |
| T08 | Uses materials (explicit or implicit) | + PASS |
| T09 | Uses joints/constraints (ChLink*) | + PASS |
| T10 | Models required sensors (>=4/5 categories) | + PASS |
| T11 | Advances simulation in a loop (DoStepDynamics inside for/while) | + PASS |
| T12 | Logs data compatible with DB schema (SQL tables or dict keys) | + PASS |
| T13 | Mentions critical parameters (1450/1480 and CO 0.1) | + PASS |
| T14 | Has error handling (try/except) | + PASS |
| T15 | Has cleanup (finally or close/clear/remove) | + PASS |
| T16 | Has __main__ entry point | + PASS |

## gemini_code.py  —  1/16 (6.2%)

| # | Test | Result |
|---|------|--------|
| T01 | Non-empty file | + PASS |
| T02 | Syntax valid (ast.parse) | - FAIL |
| T03 | Imports pychrono (any submodule) | - FAIL |
| T04 | Initializes Chrono system (ChSystemNSC/SMC) | - FAIL |
| T05 | Sets gravity (Set_G_acc/SetGravity) | - FAIL |
| T06 | Creates physical equipment bodies (>=4 bodies) | - FAIL |
| T07 | Adds created objects to Chrono system (Add/AddBody/AddLink/AddSensor) | - FAIL |
| T08 | Uses materials (explicit or implicit) | - FAIL |
| T09 | Uses joints/constraints (ChLink*) | - FAIL |
| T10 | Models required sensors (>=4/5 categories) | - FAIL |
| T11 | Advances simulation in a loop (DoStepDynamics inside for/while) | - FAIL |
| T12 | Logs data compatible with DB schema (SQL tables or dict keys) | - FAIL |
| T13 | Mentions critical parameters (1450/1480 and CO 0.1) | - FAIL |
| T14 | Has error handling (try/except) | - FAIL |
| T15 | Has cleanup (finally or close/clear/remove) | - FAIL |
| T16 | Has __main__ entry point | - FAIL |

## gpt_code.py  —  15/16 (93.8%)

| # | Test | Result |
|---|------|--------|
| T01 | Non-empty file | + PASS |
| T02 | Syntax valid (ast.parse) | + PASS |
| T03 | Imports pychrono (any submodule) | + PASS |
| T04 | Initializes Chrono system (ChSystemNSC/SMC) | + PASS |
| T05 | Sets gravity (Set_G_acc/SetGravity) | + PASS |
| T06 | Creates physical equipment bodies (>=4 bodies) | + PASS |
| T07 | Adds created objects to Chrono system (Add/AddBody/AddLink/AddSensor) | + PASS |
| T08 | Uses materials (explicit or implicit) | + PASS |
| T09 | Uses joints/constraints (ChLink*) | + PASS |
| T10 | Models required sensors (>=4/5 categories) | + PASS |
| T11 | Advances simulation in a loop (DoStepDynamics inside for/while) | + PASS |
| T12 | Logs data compatible with DB schema (SQL tables or dict keys) | + PASS |
| T13 | Mentions critical parameters (1450/1480 and CO 0.1) | + PASS |
| T14 | Has error handling (try/except) | + PASS |
| T15 | Has cleanup (finally or close/clear/remove) | + PASS |
| T16 | Has __main__ entry point | - FAIL |

## qwen_code.py  —  16/16 (100.0%)

| # | Test | Result |
|---|------|--------|
| T01 | Non-empty file | + PASS |
| T02 | Syntax valid (ast.parse) | + PASS |
| T03 | Imports pychrono (any submodule) | + PASS |
| T04 | Initializes Chrono system (ChSystemNSC/SMC) | + PASS |
| T05 | Sets gravity (Set_G_acc/SetGravity) | + PASS |
| T06 | Creates physical equipment bodies (>=4 bodies) | + PASS |
| T07 | Adds created objects to Chrono system (Add/AddBody/AddLink/AddSensor) | + PASS |
| T08 | Uses materials (explicit or implicit) | + PASS |
| T09 | Uses joints/constraints (ChLink*) | + PASS |
| T10 | Models required sensors (>=4/5 categories) | + PASS |
| T11 | Advances simulation in a loop (DoStepDynamics inside for/while) | + PASS |
| T12 | Logs data compatible with DB schema (SQL tables or dict keys) | + PASS |
| T13 | Mentions critical parameters (1450/1480 and CO 0.1) | + PASS |
| T14 | Has error handling (try/except) | + PASS |
| T15 | Has cleanup (finally or close/clear/remove) | + PASS |
| T16 | Has __main__ entry point | + PASS |

## ya_gpt_code.py  —  12/16 (75.0%)

| # | Test | Result |
|---|------|--------|
| T01 | Non-empty file | + PASS |
| T02 | Syntax valid (ast.parse) | + PASS |
| T03 | Imports pychrono (any submodule) | + PASS |
| T04 | Initializes Chrono system (ChSystemNSC/SMC) | + PASS |
| T05 | Sets gravity (Set_G_acc/SetGravity) | + PASS |
| T06 | Creates physical equipment bodies (>=4 bodies) | - FAIL |
| T07 | Adds created objects to Chrono system (Add/AddBody/AddLink/AddSensor) | + PASS |
| T08 | Uses materials (explicit or implicit) | + PASS |
| T09 | Uses joints/constraints (ChLink*) | + PASS |
| T10 | Models required sensors (>=4/5 categories) | - FAIL |
| T11 | Advances simulation in a loop (DoStepDynamics inside for/while) | + PASS |
| T12 | Logs data compatible with DB schema (SQL tables or dict keys) | + PASS |
| T13 | Mentions critical parameters (1450/1480 and CO 0.1) | - FAIL |
| T14 | Has error handling (try/except) | + PASS |
| T15 | Has cleanup (finally or close/clear/remove) | + PASS |
| T16 | Has __main__ entry point | - FAIL |
