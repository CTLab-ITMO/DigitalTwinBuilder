"""Tests for the DB acceptance gate in `sql_runner`.

Agent 1 is asked for PostgreSQL `CREATE TABLE` / `CREATE VIEW` statements. Until
2026-09-21 nothing read its reply as SQL: `streamlit-app.py` put whatever came
back straight into `st.session_state.db_schema` and showed it, so a reply that
was a JSON document, or prose, or a file with one unclosed literal reached the
user as if it were a schema. The comparison harness was worse still — for
`runs/20260917_200458/case_0001_serial_line/C/rep0` it recorded
`artifacts/dtb_schema.json` as `{"длина": "100 мм", "ширина": "50 мм",
"толщина": "10 мм"}`, which is a JSON object lifted out of an INSERT *inside*
an otherwise valid 2753-character reply. The gate validates the reply
structurally, parse-only, and returns a report that `generate_with_repair`
hands back to the agent as a repair turn.

The evidence has two sides, and both are pinned here:

* false positives — the replies a live run actually received, embedded verbatim
  below. Every one must pass, with no repair round spent: rejecting a usable
  schema costs a turn the method did not need, so the gate has to be right on
  the documents the agent really writes (`->>` operators, `NUMERIC(5,2)`,
  `REFERENCES sensor(id)`, comments between statements, non-ASCII literals, a
  trailing newline). The three embedded here carry the shapes the other eleven
  replies of the same run use; the full fourteen-reply audit is the harness-side
  evidence recorded in the comparison protocol.
* true positives — the JSON document the harness recorded, prose, and the
  structural defects (an unclosed parenthesis, literal, comment or dollar quote;
  a missing or duplicated `CREATE TABLE`; a relation used but never created).
  Each must be rejected, and by the defect it actually has, because that reason
  is the text the agent is asked to correct.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "digital_twin_builder"))

import sql_runner  # noqa: E402
from prompts import user as user_prompts  # noqa: E402


# --------------------------------------------------------------------------- #
# the replies a live run received, verbatim
# --------------------------------------------------------------------------- #
# 2026-09-21, `case_0001_serial_line` rep 0: six tables, dimension INSERTs, a
# view over `raw_ingest` and the two indexes the prompt asks for.
REAL_SERIAL_LINE = """\
CREATE TABLE machines (
    id TEXT PRIMARY KEY,
    processing_time_s DOUBLE PRECISION,
    availability_pct DOUBLE PRECISION,
    mttr_s DOUBLE PRECISION,
    power_working_kw DOUBLE PRECISION,
    power_idle_kw DOUBLE PRECISION
);

INSERT INTO machines (id, processing_time_s, availability_pct, mttr_s, power_working_kw, power_idle_kw)
VALUES ('M1', 150, 99.45, 793.67, 4.0, 0.4),
      ('M2', 120, 96.86, 1053.95, 5.0, 0.5),
      ('M3', 180, 99.03, 4200.65, 6.0, 0.6),
      ('M4', 120, 97.39, 1894.81, 5.0, 0.5),
      ('M5', 150, 99.56, 641.17, 4.0, 0.4);

CREATE TABLE buffers (
    id TEXT PRIMARY KEY,
    capacity INTEGER
);

INSERT INTO buffers (id, capacity)
VALUES ('B0', 20),
      ('B1', 8),
      ('B2', 8),
      ('B3', 8),
      ('B4', 8);

CREATE TABLE tag_map (
    tag_id TEXT PRIMARY KEY,
    machine_id TEXT,
    signal TEXT,
    unit TEXT,
    register TEXT,
    scale DOUBLE PRECISION
);

INSERT INTO tag_map (tag_id, machine_id, signal, unit, register, scale)
VALUES ('Avg_Time_per_part_s', 'M1', 'Avg_Time_per_part_s', 's', 'Avg_Time_per_part_s', 1.0),
      ('Availability_%', 'M1', 'Availability_%', '%', 'Availability_%', 1.0),
      ('MTTR_s', 'M1', 'MTTR_s', 's', 'MTTR_s', 1.0),
      ('EnergyIdling', 'M1', 'EnergyIdling', 'kW', 'EnergyIdling', 1.0),
      ('EnergyWorking', 'M1', 'EnergyWorking', 'kW', 'EnergyWorking', 1.0),
      ('Avg_Time_per_part_s', 'M2', 'Avg_Time_per_part_s', 's', 'Avg_Time_per_part_s', 1.0),
      ('Availability_%', 'M2', 'Availability_%', '%', 'Availability_%', 1.0),
      ('MTTR_s', 'M2', 'MTTR_s', 's', 'MTTR_s', 1.0),
      ('EnergyIdling', 'M2', 'EnergyIdling', 'kW', 'EnergyIdling', 1.0),
      ('EnergyWorking', 'M2', 'EnergyWorking', 'kW', 'EnergyWorking', 1.0),
      ('Avg_Time_per_part_s', 'M3', 'Avg_Time_per_part_s', 's', 'Avg_Time_per_part_s', 1.0),
      ('Availability_%', 'M3', 'Availability_%', '%', 'Availability_%', 1.0),
      ('MTTR_s', 'M3', 'MTTR_s', 's', 'MTTR_s', 1.0),
      ('EnergyIdling', 'M3', 'EnergyIdling', 'kW', 'EnergyIdling', 1.0),
      ('EnergyWorking', 'M3', 'EnergyWorking', 'kW', 'EnergyWorking', 1.0),
      ('Avg_Time_per_part_s', 'M4', 'Avg_Time_per_part_s', 's', 'Avg_Time_per_part_s', 1.0),
      ('Availability_%', 'M4', 'Availability_%', '%', 'Availability_%', 1.0),
      ('MTTR_s', 'M4', 'MTTR_s', 's', 'MTTR_s', 1.0),
      ('EnergyIdling', 'M4', 'EnergyIdling', 'kW', 'EnergyIdling', 1.0),
      ('EnergyWorking', 'M4', 'EnergyWorking', 'kW', 'EnergyWorking', 1.0),
      ('Avg_Time_per_part_s', 'M5', 'Avg_Time_per_part_s', 's', 'Avg_Time_per_part_s', 1.0),
      ('Availability_%', 'M5', 'Availability_%', '%', 'Availability_%', 1.0),
      ('MTTR_s', 'M5', 'MTTR_s', 's', 'MTTR_s', 1.0),
      ('EnergyIdling', 'M5', 'EnergyIdling', 'kW', 'EnergyIdling', 1.0),
      ('EnergyWorking', 'M5', 'EnergyWorking', 'kW', 'EnergyWorking', 1.0);

CREATE TABLE raw_ingest (
    ingested_at TIMESTAMPTZ,
    source TEXT,
    payload JSONB
);

CREATE TABLE events (
    ts TIMESTAMPTZ,
    machine_id TEXT,
    reason_code TEXT,
    duration_s DOUBLE PRECISION,
    energy_kwh DOUBLE PRECISION
);

CREATE TABLE samples (
    ts TIMESTAMPTZ,
    machine_id TEXT,
    tag TEXT,
    value DOUBLE PRECISION
);

CREATE VIEW ingest_watermark AS
SELECT DISTINCT source, MAX(ingested_at) AS max_event_ts FROM raw_ingest GROUP BY source;

CREATE INDEX idx_events_machine_id_ts ON events (machine_id, ts);
CREATE INDEX idx_samples_machine_id_ts ON samples (machine_id, ts);"""

# 2026-09-21, `case_0005_high_rate_line` rep 2: the shortest of the fourteen.
# Two views whose `WHERE` uses `payload->>'type'`, and `--` comments between the
# statements — the two constructs most likely to break a naive scanner.
REAL_HIGH_RATE = """\
CREATE TABLE machines (
    id TEXT PRIMARY KEY,
    processing_time_s INTEGER,
    availability DOUBLE PRECISION,
    mttr_s INTEGER,
    work_power_kw DOUBLE PRECISION,
    idle_power_kw DOUBLE PRECISION
);

CREATE TABLE buffers (
    id TEXT PRIMARY KEY,
    capacity INTEGER,
    before TEXT,
    after TEXT
);

CREATE TABLE stations (
    id TEXT PRIMARY KEY,
    processing_time_s INTEGER,
    availability DOUBLE PRECISION,
    mttr_s INTEGER,
    work_power_kw DOUBLE PRECISION,
    idle_power_kw DOUBLE PRECISION
);

CREATE TABLE tag_map (
    tag_id TEXT PRIMARY KEY,
    machine_id TEXT,
    signal TEXT,
    unit TEXT,
    register TEXT,
    scale DOUBLE PRECISION
);

CREATE TABLE raw_ingest (
    ingested_at TIMESTAMPTZ,
    source TEXT,
    payload JSONB
);

CREATE TABLE ingest_watermark (
    source TEXT PRIMARY KEY,
    max_event_ts TIMESTAMPTZ
);

-- Insert dimension data from requirements
INSERT INTO machines (id, processing_time_s, availability, mttr_s, work_power_kw, idle_power_kw) VALUES
('M1', 60, 0.995, 300, 3.0, 0.3),
('M2', 80, 0.99, 600, 5.0, 0.5),
('M3', 70, 0.99, 600, 4.5, 0.45),
('M4', 75, 0.995, 300, 4.0, 0.4);

INSERT INTO buffers (id, capacity, before, after) VALUES
('B0', 25, 'source', 'M1'),
('B1', 10, 'M1', 'M2'),
('B2', 10, 'M2', 'M3'),
('B3', 10, 'M3', 'M4');

INSERT INTO tag_map (tag_id, machine_id, signal, unit, register, scale) VALUES
('T1', 'M1', 'temperature', 'C', 'temp1', 1.0),
('T2', 'M2', 'vibration', 'mm/s', 'vib1', 1.0),
('T3', 'M3', 'pressure', 'bar', 'pres1', 1.0),
('T4', 'M4', 'flow', 'L/min', 'flow1', 1.0);

-- Create fact tables with time dimension
CREATE TABLE events (
    ts TIMESTAMPTZ,
    machine_id TEXT,
    reason_code TEXT,
    duration_s DOUBLE PRECISION,
    energy_kwh DOUBLE PRECISION
);

CREATE TABLE samples (
    ts TIMESTAMPTZ,
    machine_id TEXT,
    tag TEXT,
    value DOUBLE PRECISION
);

-- Add indexes for performance
CREATE INDEX idx_events_machine_time ON events(machine_id, ts);
CREATE INDEX idx_samples_machine_time ON samples(machine_id, ts);

-- Create views over raw_ingest for typed data
CREATE VIEW raw_events AS SELECT ts, machine_id, reason_code, duration_s, energy_kwh FROM raw_ingest WHERE payload->>'type' = 'event';
CREATE VIEW raw_samples AS SELECT ts, machine_id, tag, value FROM raw_ingest WHERE payload->>'type' = 'sample';"""

# 2026-09-17, `case_0001_serial_line` rep 0: the reply whose embedded JSON the
# harness recorded as the schema. `SERIAL PRIMARY KEY`, `VARCHAR(255)`,
# `NUMERIC(5,2)`, `REFERENCES sensor(id)` and Cyrillic string literals.
REAL_EARLIER = """\
CREATE TABLE production_type (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL
);

INSERT INTO production_type (name) VALUES ('производство автомобильных комплектующих');

CREATE TABLE process (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL
);

INSERT INTO process (name) VALUES ('обработка металлов'), ('прокат'), ('покрашивание'), ('тестирование');

CREATE TABLE equipment (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL
);

INSERT INTO equipment (name) VALUES ('гравировальные станки'), ('покрашальные машины'), ('тестовые системы');

CREATE TABLE sensor (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL
);

INSERT INTO sensor (name) VALUES ('датчик температуры'), ('датчик влажности'), ('датчик давления'), ('датчик скорости');

CREATE TABLE critical_parameter (
    id SERIAL PRIMARY KEY,
    parameter_name VARCHAR(255) UNIQUE NOT NULL,
    target_value VARCHAR(50) NOT NULL
);

INSERT INTO critical_parameter (parameter_name, target_value) VALUES ('температура', '40°C'), ('давление', '0.5 МПа'), ('скорость', '100 км/ч');

CREATE TABLE part_specification (
    id SERIAL PRIMARY KEY,
    part_type VARCHAR(255) UNIQUE NOT NULL,
    specifications JSONB
);

INSERT INTO part_specification (part_type, specifications) VALUES ('деталь 1', '{"длина": "100 мм", "ширина": "50 мм", "толщина": "10 мм"}'), ('деталь 2', '{"длина": "150 мм", "ширина": "75 мм", "толщина": "15 мм"}'), ('деталь 3', '{"длина": "200 мм", "ширина": "100 мм", "толщина": "20 мм"}'), ('деталь 4', '{"длина": "250 мм", "ширина": "125 мм", "толщина": "25 мм"}'), ('деталь 5', '{"длина": "300 мм", "ширина": "150 мм", "толщина": "30 мм"}'), ('деталь 6', '{"длина": "350 мм", "ширина": "175 мм", "толщина": "35 мм"}'), ('деталь 7', '{"длина": "400 мм", "ширина": "200 мм", "толщина": "40 мм"}'), ('деталь 8', '{"длина": "450 мм", "ширина": "225 мм", "толщина": "45 мм"}'), ('деталь 9', '{"длина": "500 мм", "ширина": "250 мм", "толщина": "50 мм"}'), ('деталь 10', '{"длина": "550 мм", "ширина": "275 мм", "толщина": "55 мм"}'), ('деталь 11', '{"длина": "600 мм", "ширина": "300 мм", "толщина": "60 мм"}'), ('деталь 12', '{"длина": "650 мм", "ширина": "325 мм", "толщина": "65 мм"}'), ('деталь 13', '{"длина": "700 мм", "ширина": "350 мм", "толщина": "70 мм"}'), ('деталь 14', '{"длина": "750 мм", "ширина": "375 мм", "толщина": "75 мм"}'), ('деталь 15', '{"длина": "800 мм", "ширина": "400 мм", "толщина": "80 мм"}');

CREATE TABLE sensor_data (
    id SERIAL PRIMARY KEY,
    sensor_id INTEGER REFERENCES sensor(id),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    temperature NUMERIC(5,2),
    humidity NUMERIC(5,2),
    pressure NUMERIC(5,2),
    speed NUMERIC(5,2),
    data_source VARCHAR(255)
);"""

# The document `artifacts/dtb_schema.json` actually held for that reply.
RECORDED_JSON = '{"длина": "100 мм", "ширина": "50 мм", "толщина": "10 мм"}'

REAL_REPLIES = {
    "20260921_serial_line_rep0": (
        REAL_SERIAL_LINE,
        {"statements": 12, "tables": 6, "views": 1, "indexes": 2, "inserts": 3}),
    "20260921_high_rate_line_rep2": (
        REAL_HIGH_RATE,
        {"statements": 15, "tables": 8, "views": 2, "indexes": 2, "inserts": 3}),
    "20260917_serial_line_rep0": (
        REAL_EARLIER,
        {"statements": 13, "tables": 7, "views": 0, "indexes": 0, "inserts": 6}),
}
# The recorded length of each reply, so a fixture that gets re-wrapped or
# trimmed in an edit fails here rather than quietly weakening the evidence.
REAL_REPLY_CHARS = {
    "20260921_serial_line_rep0": 3472,
    "20260921_high_rate_line_rep2": 2338,
    "20260917_serial_line_rep0": 2753,
}


@pytest.mark.parametrize("name", sorted(REAL_REPLIES))
def test_the_fixtures_are_the_recorded_replies_verbatim(name):
    assert len(REAL_REPLIES[name][0]) == REAL_REPLY_CHARS[name]


@pytest.mark.parametrize("name", sorted(REAL_REPLIES))
def test_a_reply_a_live_run_received_passes_the_gate(name):
    """No false positive, and not one repair round spent on a usable schema."""
    reply, counts = REAL_REPLIES[name]
    assert sql_runner.check(reply) is None
    verdict = sql_runner.verify(reply)
    assert verdict["ok"] is True
    assert verdict["report"] == ""
    summary = verdict["summary"]
    for field, want in counts.items():
        assert summary[field] == want, field
    assert summary["problems"] == []
    assert summary["non_sql"] == []
    assert summary["undefined"] == []


def test_the_json_the_harness_recorded_came_from_inside_a_valid_reply():
    """The recorded artefact was not the agent's answer.

    It is the value of the `specifications` column of `part_specification`,
    lifted out of the reply by a `json.loads`-style extraction. This is the
    incident the gate's JSON branch exists for: the reply is accepted as SQL,
    and the document the harness stored is rejected as not SQL.
    """
    assert RECORDED_JSON in REAL_EARLIER
    assert sql_runner.check(REAL_EARLIER) is None
    reason = sql_runner.check(RECORDED_JSON)
    assert reason is not None and "JSON document" in reason


# --------------------------------------------------------------------------- #
# false positives: constructs the fourteen replies use, and their neighbours
# --------------------------------------------------------------------------- #
# Each of these is SQL the DB agent legitimately writes. None may be rejected:
# every rejection here would be a repair round spent on work that was already
# right, which is the failure mode the bounds of `check` are ordered to avoid.
ACCEPTED = {
    # A function body quoted with dollars: the `;` characters inside it do not
    # end the statement, and the INSERT it contains resolves to the table above.
    "dollar_quoted_function": (
        "CREATE TABLE events (ts timestamptz, machine_id text);\n"
        "CREATE FUNCTION touch() RETURNS trigger AS $body$\n"
        "BEGIN\n"
        "    INSERT INTO events (ts, machine_id) VALUES (now(), 'M1');\n"
        "    RETURN NEW;\n"
        "END;\n"
        "$body$ LANGUAGE plpgsql;\n"),
    # A COMMENT whose *string* names a table that is not in the schema. String
    # literals are blanked before the uses are read, so `maintenance_log` is
    # prose, not a reference.
    "materialized_view_and_a_comment_naming_a_stranger": (
        "CREATE TABLE events (ts timestamptz, machine_id text);\n"
        "CREATE MATERIALIZED VIEW v_events AS SELECT ts, machine_id FROM events;\n"
        "COMMENT ON COLUMN events.machine_id IS 'join key into maintenance_log';\n"),
    # `ADD CONSTRAINT ... REFERENCES` and `IF NOT EXISTS` in all three forms.
    "constraint_and_if_not_exists": (
        "CREATE TABLE IF NOT EXISTS sensor (id integer PRIMARY KEY);\n"
        "CREATE TABLE readings (id integer PRIMARY KEY, sensor_id integer);\n"
        "ALTER TABLE readings ADD CONSTRAINT readings_sensor_fk\n"
        "    FOREIGN KEY (sensor_id) REFERENCES sensor (id);\n"
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_readings ON readings (sensor_id);\n"),
    # `INSERT ... ON CONFLICT`, which the prompt asks for on dimension rows.
    "insert_on_conflict": (
        "CREATE TABLE machines (id text PRIMARY KEY);\n"
        "INSERT INTO machines (id) VALUES ('M1') ON CONFLICT (id) DO NOTHING;\n"),
    # A CTE name is not a relation the schema has to create.
    "cte": (
        "CREATE TABLE events (ts timestamptz);\n"
        "CREATE VIEW v AS WITH recent AS (SELECT ts FROM events)\n"
        "    SELECT ts FROM recent;\n"),
    # A set-returning function in FROM position is not a relation either.
    "set_returning_function_in_from": (
        "CREATE TABLE events (ts timestamptz);\n"
        "CREATE VIEW v AS SELECT n FROM generate_series(1, 10) AS n;\n"),
    # A leading comment, and a `;` inside a trailing comment that must not end
    # a statement.
    "comment_before_and_after": (
        "-- schema for case 1; five tables\n"
        "CREATE TABLE events (ts timestamptz); -- done; really;\n"),
    # A dollar-quoted block is not required to reference anything.
    "do_block": (
        "CREATE TABLE events (ts timestamptz);\n"
        "DO $$ BEGIN PERFORM 1; END $$;\n"),
    # A schema-qualified creation, used by its bare name. Both spellings name the
    # same relation, so `events` in the view is not a relation that was never
    # created.
    "schema_qualified_create_used_bare": (
        "CREATE TABLE public.events (ts timestamptz, machine_id text);\n"
        "CREATE VIEW v AS SELECT ts FROM events;\n"),
    # ... and the same with the qualification kept on both sides.
    "schema_qualified_create_used_qualified": (
        "CREATE TABLE public.events (ts timestamptz);\n"
        "CREATE VIEW v AS SELECT ts FROM public.events;\n"),
    # The qualifier on a use, with the creation bare.
    "bare_create_used_qualified": (
        "CREATE TABLE events (ts timestamptz);\n"
        "CREATE VIEW v AS SELECT ts FROM public.events;\n"),
    # A quoted `"Machines"` and a bare `machines` are two different relations in
    # PostgreSQL, so creating both defines two tables, not one twice.
    "quoted_and_bare_are_two_relations": (
        'CREATE TABLE "Machines" (id text PRIMARY KEY);\n'
        "CREATE TABLE machines (id text PRIMARY KEY);\n"),
    # The same relation name in two schemas is two relations.
    "same_name_in_two_schemas": (
        "CREATE TABLE s1.events (ts timestamptz);\n"
        "CREATE TABLE s2.events (ts timestamptz);\n"),
}


@pytest.mark.parametrize("name", sorted(ACCEPTED))
def test_sql_the_agent_legitimately_writes_is_accepted(name):
    reason = sql_runner.check(ACCEPTED[name])
    assert reason is None, reason


def test_unquoted_names_are_folded_to_lower_case():
    """PostgreSQL folds an unquoted identifier to lower case, so `CREATE TABLE
    Machines` and `FROM machines` are the same relation and must compare equal.
    """
    assert sql_runner.check(
        "CREATE TABLE Machines (id text PRIMARY KEY);\n"
        "CREATE VIEW v AS SELECT id FROM machines;\n") is None
    assert sql_runner._relation_key("Machines") == sql_runner._relation_key("machines")


def test_a_quoted_name_is_folded_too_and_that_is_the_stated_bias():
    """A quoted `"Machines"` and a bare `machines` are *not* the same relation in
    PostgreSQL, but the check folds both, so this pair is accepted. The
    over-acceptance is deliberate and documented in `_relation_key`: quoting is
    cosmetic in nearly every reply the agent writes, and a false rejection costs
    a repair round on a schema that already works.
    """
    assert sql_runner.check(
        'CREATE TABLE "Machines" (id text PRIMARY KEY);\n'
        "CREATE VIEW v AS SELECT id FROM machines;\n") is None
    assert sql_runner._relation_key('"Machines"') == "machines"


def test_a_schema_qualifier_is_dropped_when_a_relation_is_matched():
    """`CREATE TABLE public.events` followed by `FROM events` is the same relation,
    so the use must not be reported as one that was never created. The qualifier
    is dropped on both sides: which schema the search path resolves the bare name
    to is the server's question, not the text's.
    """
    assert sql_runner.check(
        "CREATE TABLE public.events (ts timestamptz);\n"
        "CREATE VIEW v AS SELECT ts FROM events;\n") is None
    assert sql_runner._relation_key("public.events") == "events"
    assert sql_runner._relation_key("public.events") == sql_runner._relation_key("events")
    # and the schema is dropped on a use too, so `public.events` in a FROM reads
    # as `events` whatever schema name carries it
    assert sql_runner._relation_key("public.events") == sql_runner._relation_key(
        "other.events")


def test_the_duplicate_check_keeps_the_case_a_quoted_name_preserves():
    """The quote marks are not part of the name; the case a quoted name preserves
    is. So `"Machines"` and bare `machines` are two relations — PostgreSQL leaves
    the first alone and folds the second — and creating both is not a collision;
    but the quoting has to be resolved before the comparison, or `"machines"` and
    bare `machines` — which PostgreSQL resolves to the one name `machines` — would
    read as two and a real duplicate would go unreported.
    """
    assert sql_runner._definition_key('"Machines"') != sql_runner._definition_key("machines")
    assert sql_runner._definition_key('"Machines"') == "Machines"
    assert sql_runner._definition_key('"machines"') == sql_runner._definition_key("machines")
    assert sql_runner._definition_key('"machines"') == "machines"
    assert sql_runner.check(
        'CREATE TABLE "Machines" (id text PRIMARY KEY);\n'
        "CREATE TABLE machines (id text PRIMARY KEY);\n") is None
    # the bare pair is still a collision, so the check did not go blind
    assert sql_runner.check(
        "CREATE TABLE Machines (id text PRIMARY KEY);\n"
        "CREATE TABLE machines (id text PRIMARY KEY);\n") is not None
    # ... and so is a lowercase quoted name against the bare one it resolves to
    assert sql_runner.check(
        'CREATE TABLE "machines" (id text PRIMARY KEY);\n'
        "CREATE TABLE machines (id text PRIMARY KEY);\n") is not None


def test_the_duplicate_check_keeps_the_schema_qualifier():
    """`s1.events` and `s2.events` are two relations, so creating both is not a
    collision. A qualifier against a bare name may or may not collide, depending
    on the search path, and is taken to be distinct — the same direction as the
    rest of the gate: a missed rejection, never a round spent on working SQL.
    """
    assert sql_runner._definition_key("s1.events") != sql_runner._definition_key("s2.events")
    assert sql_runner.check(
        "CREATE TABLE s1.events (ts timestamptz);\n"
        "CREATE TABLE s2.events (ts timestamptz);\n") is None
    assert sql_runner._definition_key("public.events") != sql_runner._definition_key("events")


def test_a_quoted_name_with_a_dot_is_one_part():
    """The split is on the qualifier's `.`, not on a dot inside a quoted
    identifier, so `"my.table"` is a single relation and not a schema `my`."""
    assert sql_runner._parts('"my.table"') == ['"my.table"']
    assert sql_runner._relation_key('"my.table"') == "my.table"
    assert sql_runner._parts("public.events") == ["public", "events"]


# --------------------------------------------------------------------------- #
# true positives: the JSON document, and every structural defect
# --------------------------------------------------------------------------- #
# reply -> the phrase the report must contain, so the agent is told which defect
# it has rather than a generic rejection.
REJECTED = {
    # The document the harness recorded as the schema.
    "the_recorded_json": (RECORDED_JSON, "JSON document"),
    "a_json_array": ('[{"длина": "100 мм"}]', "JSON document"),
    "prose": ("Here is your PostgreSQL schema.\nNothing else.",
              "no statement begins with a SQL keyword"),
    "no_statement_at_all": (";;", "the reply contains no SQL statement"),
    "unclosed_parenthesis": ("CREATE TABLE events (ts timestamptz, machine_id text",
                            "parenthesis that are never closed"),
    "unclosed_string_literal": ("CREATE TABLE t (a text);\n"
                                "INSERT INTO t (a) VALUES ('oops);",
                                "string literal is never closed"),
    "unclosed_quoted_identifier": ('CREATE TABLE t ("a int);', "never closed"),
    "unclosed_block_comment": ("/* everything is fine", "block comment is never closed"),
    "unclosed_dollar_quote": ("CREATE TABLE t (a int);\nDO $$ BEGIN PERFORM 1; END",
                              "dollar-quoted block is never closed"),
    "stray_closing_parenthesis": ("CREATE TABLE t (a int));",
                                  "closing parenthesis that opens nothing"),
    "no_create_table": ("CREATE VIEW v AS SELECT 1 AS one;\n"
                        "INSERT INTO nowhere (a) VALUES (1);",
                        "no `CREATE TABLE` statement"),
    "table_created_twice": ("CREATE TABLE t (a int);\nCREATE TABLE t (b int);",
                            "`t` more than once"),
    # A quoted lowercase name resolves to the same relation as the bare name, so
    # this is one table created twice even though the two spellings differ.
    "quoted_lower_case_name_created_twice":
        ('CREATE TABLE "machines" (a int);\nCREATE TABLE machines (b int);',
         "`machines` more than once"),
    "view_over_a_relation_that_is_never_created":
        ("CREATE TABLE events (ts timestamptz);\n"
         "CREATE VIEW v AS SELECT * FROM samples;",
         "uses `samples` but never creates it"),
    "insert_into_a_relation_that_is_never_created":
        ("CREATE TABLE samples (ts timestamptz);\n"
         "INSERT INTO events (ts) VALUES (now());",
         "uses `events` but never creates it"),
    "index_on_a_relation_that_is_never_created":
        ("CREATE TABLE events (ts timestamptz);\n"
         "CREATE INDEX ix ON samples (ts);",
         "uses `samples` but never creates it"),
    "empty_reply": ("", "returned nothing"),
}


@pytest.mark.parametrize("name", sorted(REJECTED))
def test_a_bad_reply_is_rejected_by_the_defect_it_has(name):
    reply, phrase = REJECTED[name]
    reason = sql_runner.check(reply)
    assert reason is not None, f"{name} should not pass"
    assert phrase in reason, reason
    verdict = sql_runner.verify(reply)
    assert verdict["ok"] is False
    # the report is the reason, then the reply itself, bounded
    assert verdict["report"].startswith(reason + ".")
    assert "The SQL that was returned (last 4000 characters):" in verdict["report"]


def test_a_reply_of_none_is_an_empty_reply_not_a_crash():
    assert sql_runner.check(None) == sql_runner.check("")
    assert sql_runner.verify(None)["ok"] is False


def test_a_rejected_reply_is_quoted_back_past_the_report_bound():
    """The quote is the *last* 4000 characters, so a defect at the head of a
    long reply is named by the reason but is not in the quoted text. The reason
    has to be readable on its own, which is why every branch spells the defect
    out rather than saying "invalid schema".
    """
    reply = ("CREATE TABLE events (ts timestamptz);\n"
             "CREATE VIEW v AS SELECT * FROM missing_relation;\n"
             + "-- padding\n" * 400)
    verdict = sql_runner.verify(reply)
    reason, marker, quoted = verdict["report"].partition("\n\n")
    assert marker == "\n\n"
    assert quoted.startswith("The SQL that was returned (last 4000 characters):\n")
    tail = quoted.split("characters):\n", 1)[1]
    body = sql_runner.strip_code_fence(reply).strip()
    assert len(body) > sql_runner.REPORT_CHARS
    assert "`missing_relation`" in reason
    assert "missing_relation" not in tail
    assert tail == body[-sql_runner.REPORT_CHARS:]


# --------------------------------------------------------------------------- #
# the splitter: where a statement ends, and what is dropped
# --------------------------------------------------------------------------- #
def test_a_semicolon_in_a_literal_does_not_end_a_statement():
    statements, problems = sql_runner.split_statements(
        "INSERT INTO t (a) VALUES ('x;y');")
    assert statements == ["INSERT INTO t (a) VALUES ('x;y')"]
    assert problems == []


def test_a_semicolon_in_a_quoted_identifier_does_not_end_a_statement():
    statements, problems = sql_runner.split_statements(
        'CREATE TABLE "a;b" (x int);')
    assert statements == ['CREATE TABLE "a;b" (x int)']
    assert problems == []


def test_a_semicolon_in_a_dollar_quoted_block_does_not_end_a_statement():
    statements, problems = sql_runner.split_statements(
        "DO $$ BEGIN PERFORM 1; END $$;")
    assert statements == ["DO $$ BEGIN PERFORM 1; END $$"]
    assert problems == []


def test_a_semicolon_in_a_comment_does_not_end_a_statement():
    statements, problems = sql_runner.split_statements(
        "CREATE TABLE t (a int); -- done; really;\n")
    assert statements == ["CREATE TABLE t (a int)"]
    assert problems == []


def test_comments_are_dropped_from_the_statements():
    statements, problems = sql_runner.split_statements(
        "CREATE TABLE t (a int); /* a; b */\n"
        "-- a note\n"
        "CREATE TABLE u (b int);")
    assert statements == ["CREATE TABLE t (a int)", "CREATE TABLE u (b int)"]
    assert problems == []


def test_a_doubled_quote_is_an_escape_not_the_end_of_the_literal():
    statements, problems = sql_runner.split_statements(
        "INSERT INTO t (a) VALUES ('it''s; fine');")
    assert statements == ["INSERT INTO t (a) VALUES ('it''s; fine')"]
    assert problems == []


def test_nested_parentheses_are_balanced_not_counted():
    statements, problems = sql_runner.split_statements(
        "CREATE TABLE t (a numeric(5,2), b text);")
    assert len(statements) == 1 and problems == []


def test_each_unterminated_construct_is_reported():
    for sql, phrase in [
        ("CREATE TABLE t (a int", "never closed"),
        ("CREATE TABLE t (a text); INSERT INTO t VALUES ('x", "never closed"),
        ("/* nope", "never closed"),
        ("SELECT $tag$ not closed", "never closed"),
    ]:
        _, problems = sql_runner.split_statements(sql)
        assert any(phrase in p for p in problems), (sql, problems)


def test_a_reply_is_read_through_a_code_fence():
    fenced = "```sql\n" + REAL_SERIAL_LINE + "\n```"
    assert sql_runner.check(fenced) is None
    assert sql_runner.strip_code_fence(fenced) == REAL_SERIAL_LINE.strip("\n")
    # prose around the fence is dropped with it: the first block is the reply
    assert sql_runner.strip_code_fence(
        "Here you go:\n```sql\nCREATE TABLE t (a int);\n```\nDone."
    ) == "CREATE TABLE t (a int);"


def test_a_reply_with_no_fence_is_returned_unchanged():
    """A trailing newline is not a defect, and not a fence."""
    assert sql_runner.strip_code_fence(REAL_SERIAL_LINE + "\n") == REAL_SERIAL_LINE + "\n"
    assert sql_runner.check(REAL_SERIAL_LINE + "\n") is None
    assert sql_runner.strip_code_fence(None) == ""


# --------------------------------------------------------------------------- #
# the repair loop
# --------------------------------------------------------------------------- #
# Two rejections that violate different rules, so the loop is exercised on a
# reply whose defect moves between turns.
BAD_UNCLOSED = "CREATE TABLE events (ts timestamptz, machine_id text"
BAD_UNDEFINED = ("CREATE TABLE samples (ts timestamptz);\n"
                 "CREATE VIEW v AS SELECT * FROM events;")
GOOD = ("CREATE TABLE events (ts timestamptz, machine_id text);\n"
        "CREATE VIEW v AS SELECT ts, machine_id FROM events;\n"
        "CREATE INDEX ix ON events (machine_id, ts);")


class _Agent:
    """A stand-in for `streamlit-app.py`'s `submit(prompt, attempt)`.

    Records every turn it was asked for, including the prompt it was given —
    `None` on the first turn, a repair message after that.
    """

    def __init__(self, replies):
        self.replies = list(replies)
        self.turns = []

    def __call__(self, prompt, attempt):
        self.turns.append((prompt, attempt))
        assert self.replies, "the loop asked for more replies than the agent has"
        return self.replies.pop(0)


@pytest.mark.parametrize("total", [0, 1, 2, 3])
def test_a_total_of_n_is_n_repairs_and_n_plus_one_replies(total):
    expected = [BAD_UNCLOSED] + [BAD_UNDEFINED] * total
    agent = _Agent(list(expected))
    out = sql_runner.generate_with_repair(agent, attempts=total)

    assert len(agent.turns) == total + 1
    assert out["attempts"] == total + 1
    assert out["repaired"] == total
    assert out["ok"] is False
    assert out["sqls"] == expected
    # the last reply is kept, rejected, rather than discarded
    assert out["sql"] == expected[-1]
    assert out["report"] == sql_runner.verify(expected[-1])["report"]
    assert agent.turns[0] == (None, 0)
    assert [a for _, a in agent.turns] == list(range(total + 1))
    if total:
        assert "never creates it" in out["report"]


def test_the_loop_stops_at_the_first_reply_that_reads_as_sql():
    agent = _Agent([BAD_UNCLOSED, GOOD])
    out = sql_runner.generate_with_repair(agent, attempts=3)
    assert len(agent.turns) == 2
    assert out["ok"] is True and out["repaired"] == 1
    assert out["sql"] == GOOD and out["sqls"] == [BAD_UNCLOSED, GOOD]
    assert out["report"] == ""
    assert out["summary"]["tables"] == 1


def test_a_clean_first_reply_costs_one_turn_and_no_repair():
    agent = _Agent([GOOD])
    out = sql_runner.generate_with_repair(agent, attempts=3)
    assert agent.turns == [(None, 0)]
    assert out["ok"] is True and out["attempts"] == 1 and out["repaired"] == 0


def test_the_repair_prompt_gets_the_reply_the_report_and_the_counters():
    seen = []

    def repair_prompt(sql, report, attempt, total):
        seen.append((sql, report, attempt, total))
        return f"fix this ({attempt}/{total})"

    agent = _Agent([BAD_UNCLOSED, BAD_UNDEFINED, GOOD])
    out = sql_runner.generate_with_repair(agent, attempts=2,
                                          repair_prompt=repair_prompt)
    assert seen == [
        (BAD_UNCLOSED, sql_runner.verify(BAD_UNCLOSED)["report"], 1, 2),
        (BAD_UNDEFINED, sql_runner.verify(BAD_UNDEFINED)["report"], 2, 2),
    ]
    assert [prompt for prompt, _ in agent.turns] == [None, "fix this (1/2)", "fix this (2/2)"]
    assert out["ok"] is True and out["attempts"] == 3


def test_without_a_repair_prompt_the_report_itself_is_the_next_turn():
    agent = _Agent([BAD_UNCLOSED, GOOD])
    sql_runner.generate_with_repair(agent, attempts=1)
    assert agent.turns[1][0] == sql_runner.verify(BAD_UNCLOSED)["report"]


def test_a_fenced_reply_is_validated_and_returned_without_its_fence():
    agent = _Agent(["```sql\n" + GOOD + "\n```"])
    out = sql_runner.generate_with_repair(agent, attempts=0)
    assert out["ok"] is True
    assert out["sql"] == GOOD
    assert out["sqls"] == [GOOD]


def test_a_first_turn_with_no_reply_stops_before_validating_anything():
    """`submit` returns None when the task failed or timed out: there is nothing
    to validate and nothing to correct, so no repair turn is asked for."""
    agent = _Agent([None])
    out = sql_runner.generate_with_repair(agent, attempts=3)
    assert len(agent.turns) == 1
    assert out["sql"] is None and out["sqls"] == []
    assert out["attempts"] == 0 and out["repaired"] == 0
    assert out["ok"] is False and out["summary"] == {}
    assert "returned no schema for this turn" in out["report"]


def test_a_repair_turn_with_no_reply_keeps_the_last_schema_and_stops():
    agent = _Agent([BAD_UNCLOSED, None])
    out = sql_runner.generate_with_repair(agent, attempts=3)
    assert len(agent.turns) == 2
    assert out["sql"] == BAD_UNCLOSED and out["sqls"] == [BAD_UNCLOSED]
    assert out["attempts"] == 1 and out["repaired"] == 0
    assert out["ok"] is False
    # the last turn is the one that failed, and it is the verdict reported
    assert "returned no schema for this turn" in out["report"]


def test_every_turn_is_reported_to_the_caller_including_the_missing_one():
    seen = []
    agent = _Agent([BAD_UNCLOSED, None])
    sql_runner.generate_with_repair(
        agent, attempts=3,
        on_attempt=lambda i, sql, verdict: seen.append((i, sql, verdict["ok"])))
    assert seen == [(0, BAD_UNCLOSED, False), (1, None, False)]


def test_the_default_attempt_count_is_the_configured_module_constant(monkeypatch):
    monkeypatch.setattr(sql_runner, "DB_REPAIR_ATTEMPTS", 2)
    agent = _Agent([BAD_UNCLOSED, BAD_UNDEFINED, BAD_UNDEFINED])
    out = sql_runner.generate_with_repair(agent)
    assert len(agent.turns) == 3 and out["repaired"] == 2


# --------------------------------------------------------------------------- #
# the prompts ask for what the gate enforces
# --------------------------------------------------------------------------- #
REQUIREMENTS = {"production_type": "serial", "equipment": ["M1"],
                "line": {"stations": [{"id": "M1", "processing_time_s": 150.0}]}}


def test_the_db_prompt_asks_for_the_statements_the_gate_requires():
    prompt = user_prompts.make_db_prompt(REQUIREMENTS)
    assert "PostgreSQL" in prompt
    assert "CREATE TABLE" in prompt
    assert "CREATE VIEW" in prompt


def test_the_repair_prompt_carries_the_defect_and_the_reply_it_is_about():
    report = sql_runner.verify(RECORDED_JSON)["report"]
    prompt = user_prompts.make_db_repair(REQUIREMENTS, RECORDED_JSON, report, 2, 3)
    assert report in prompt
    assert RECORDED_JSON in prompt
    assert "not a usable PostgreSQL schema" in prompt
    # the repair turn asks for the same contract the gate checks
    assert "CREATE TABLE" in prompt
    flat = re.sub(r"\s+", " ", prompt)
    # the two ways out that would make the defect go away without fixing it
    assert "Do not drop a table to make the error go away" in flat
    assert "do not replace the schema with a JSON description" in flat
    assert "Return only the SQL code" in flat
    assert flat.endswith("This is repair attempt 2 of 3.")
