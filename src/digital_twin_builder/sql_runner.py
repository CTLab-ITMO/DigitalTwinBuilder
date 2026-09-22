"""Validate a generated PostgreSQL schema and judge whether the DB stage worked.

The DB agent returns SQL; nothing in the pipeline ever reads it as SQL, so a
reply that is a JSON blob, or that is not SQL at all, or that creates a view over
a table nobody created, reaches the user as if it were a schema. This module
closes that gap the way `des_runner` closes it for the DES stage: it validates
the reply, returns a report that can be fed back to the agent for a correction,
and runs the same submit/repair loop.

Validation is parse-only. No database server is contacted and no SQL is
executed: every check is structural, so it runs wherever the app runs and needs
no dependency beyond the standard library.

The contract the prompt asks for is `CREATE TABLE` plus `CREATE VIEW`; the hard
requirement enforced here is at least one `CREATE TABLE`. A view is counted and
reported but not demanded, because the DB agent legitimately omits views on
schemas that need none and a validator that rejects them would reject work that
is right.
"""
from __future__ import annotations

import re
import sys

try:  # the app imports this as a top-level module; tests may import it as a package
    from config import DB_REPAIR_ATTEMPTS
except ImportError:  # pragma: no cover - fallback for a bare `python sql_runner.py`
    DB_REPAIR_ATTEMPTS = 3

FENCE_RE = re.compile(r"```[A-Za-z0-9_+-]*[ \t]*\r?\n(.*?)```", re.DOTALL)

# How much of the reply is fed back to the agent with the verdict. Enough for the
# statements the report names, short enough not to crowd out the repair prompt.
REPORT_CHARS = 4000

# A dollar-quoted block: `$$ ... $$` or `$tag$ ... $tag$`. A bare `$1` is a
# parameter placeholder, not a quote, so the tag must be absent or a word.
DOLLAR_QUOTE_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")

# The first word of a statement, if it is one SQL knows. A reply whose every
# statement starts outside this set is prose or data, not a schema.
STATEMENT_HEADS = frozenset({
    "select", "insert", "update", "delete", "create", "alter", "drop",
    "truncate", "comment", "grant", "revoke", "with", "do", "begin", "commit",
    "rollback", "set", "analyze", "vacuum", "explain", "copy", "call", "values",
    "declare", "refresh", "reindex", "cluster", "listen", "notify", "prepare",
})

# A relation name: a bare identifier or a double-quoted one (`"my table"`), which
# PostgreSQL allows wherever an identifier is allowed.
NAME = r'(?:"(?:[^"]|"")*"|[A-Za-z_][A-Za-z0-9_$]*)'

# A relation name that may carry a schema qualifier (`public.events`), which the
# agent writes on some replies instead of creating in the search path. Captured
# as one name so the qualifier is not read as the relation and the bare spelling
# is not reported as a relation that was never created.
QUALIFIED = NAME + r"(?:\s*\.\s*" + NAME + r")?"

# `CREATE TABLE [IF NOT EXISTS] name`, and the same for the other relation kinds.
CREATE_RELATION_RE = re.compile(
    r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?"
    r"(?:GLOBAL\s+|LOCAL\s+)?(?:TEMPORARY\s+|TEMP\s+|UNLOGGED\s+)?"
    r"(TABLE|VIEW|MATERIALIZED\s+VIEW)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(" + QUALIFIED + r")",
    re.IGNORECASE)

# Where a relation is *used*. `COMMENT ON COLUMN events.duration_s` and
# `CREATE INDEX ... ON events` are handled by their own pattern so a column
# reference is not read as a table.
#
# `FROM`/`JOIN` may name a set-returning function instead of a relation
# (`FROM generate_series(...)`), which this schema need not create, so there the
# name is only a use when no `(` follows it. The write positions cannot hold a
# function: the name after `INSERT INTO`/`UPDATE` is a relation even when
# `(column list)` follows it.
RELATION_SOURCE_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+(" + QUALIFIED + r")(\s*\()?", re.IGNORECASE)
RELATION_WRITE_RE = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|REFERENCES)\s+(" + QUALIFIED + r")",
    re.IGNORECASE)
INDEX_TARGET_RE = re.compile(
    r"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?"
    r"(?:IF\s+NOT\s+EXISTS\s+)?(?:\S+)\s+ON\s+(?:ONLY\s+)?"
    r"(" + QUALIFIED + r")",
    re.IGNORECASE)
CTE_RE = re.compile(
    r"\bWITH\s+(?:RECURSIVE\s+)?(" + NAME + r")\s+AS\s*\(",
    re.IGNORECASE)
STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")


_PART_RE = re.compile(r'"(?:[^"]|"")*"|[A-Za-z_][A-Za-z0-9_$]*')


def _parts(name: str) -> list[str]:
    """The dot-separated pieces of a relation name, quoting preserved.

    Splits on the `.` of a schema qualifier but not on a dot inside a quoted
    identifier, so `"my.schema".t` yields two parts rather than three.
    """
    return _PART_RE.findall(name or "")


def _unquote(part: str) -> str:
    """The text of one name part: the surrounding quotes removed, `""` unescaped."""
    if len(part) >= 2 and part[0] == '"' and part[-1] == '"':
        return part[1:-1].replace('""', '"')
    return part


def _relation_key(name: str) -> str:
    """A relation name folded to the form the *use* checks compare.

    PostgreSQL folds an unquoted identifier to lower case, so `CREATE TABLE
    Machines` and `FROM machines` name the same relation and have to compare
    equal. Quoting is a case-preserving escape, so in principle `"Machines"` and
    `machines` are two relations — but the fold is applied to quoted names too,
    which makes this comparison blind to case everywhere and accepts that pair.

    The over-acceptance is deliberate. Quoting is cosmetic in nearly every reply
    the DB agent writes, and a false rejection costs a repair round on a schema
    that already works, while a missed one leaves a reply that mostly works. The
    same reasoning drops the schema qualifier, in either direction:
    `CREATE TABLE public.events` used as `FROM events`, and `CREATE TABLE events`
    used as `FROM public.events`, are each taken to be one relation, because
    whether the search path resolves the bare name to that schema is a question
    about the server, not about the text.

    What this key deliberately does *not* decide is whether two creations
    collide: that is `_definition_key`, which keeps the distinction this one
    throws away.
    """
    parts = _parts(name)
    return _unquote(parts[-1] if parts else name).lower()


def _definition_key(name: str) -> str:
    """A relation name keyed for the duplicate check, where the distinctions
    `_relation_key` discards are the ones that matter.

    Two `CREATE TABLE` statements collide when they define the same relation, so
    each part is folded to the name PostgreSQL would resolve it to: a quoted part
    is unquoted and keeps its case, a bare part is lower-cased. The quote *marks*
    are not part of the name, so `"machines"` and bare `Machines` both resolve to
    `machines` and are one relation created twice, while `"Machines"` and bare
    `machines` resolve to `Machines` and `machines` — two relations, as in
    PostgreSQL, and creating both is not a collision. The schema qualifier is part
    of the definition, so `s1.events` and `s2.events` do not collide either.

    The over-acceptance this key keeps is a qualified name against a bare one, in
    either direction: `public.events` against `events` may or may not collide,
    depending on the search path, so the pair is taken to be distinct. That errs
    toward accepting a schema PostgreSQL might reject on its second statement,
    which costs a rejection the gate fails to make — the same direction as
    `_relation_key`, and never a repair round spent on a schema that already
    works.
    """
    parts = _parts(name)
    if not parts:
        return _unquote(name)
    return ".".join(_unquote(p) if p.startswith('"') else p.lower() for p in parts)


def strip_code_fence(text: str) -> str:
    """Drop a markdown fence the agent added despite being asked not to.

    Only unwraps when a fenced block exists; otherwise the text is returned
    unchanged, so a schema that legitimately contains no fence is not damaged.
    """
    m = FENCE_RE.search(text or "")
    return m.group(1).strip("\n") if m else (text or "")


def split_statements(sql: str) -> tuple[list[str], list[str]]:
    """Split a schema into statements on the `;` characters that end them.

    A `;` inside a string literal, a quoted identifier, a comment or a
    dollar-quoted block does not end a statement, and none of those constructs is
    damaged by the split. Returns the statements and a list of the structural
    defects found while scanning — an unterminated literal, comment or
    dollar-quote, an unbalanced parenthesis. Comments are dropped from the
    statements, so what comes back is the SQL the checks reason about.
    """
    text = sql or ""
    statements: list[str] = []
    problems: list[str] = []
    buf: list[str] = []
    depth = 0
    i, n = 0, len(text)

    def close_statement() -> None:
        nonlocal depth
        stmt = "".join(buf).strip()
        if stmt:
            statements.append(stmt)
        if depth > 0:
            problems.append(f"a statement has {depth} opening "
                            f"parenthes{'is' if depth == 1 else 'es'} that are "
                            f"never closed")
        elif depth < 0:
            problems.append("a statement has a closing parenthesis that opens "
                            "nothing")
        buf.clear()
        depth = 0

    while i < n:
        two = text[i:i + 2]
        ch = text[i]

        if two == "--":
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if two == "/*":
            j = text.find("*/", i + 2)
            if j == -1:
                problems.append("a block comment is never closed")
                i = n
                continue
            i = j + 2
            continue
        if ch in "'\"":
            j = i + 1
            while j < n:
                if text[j] == ch:
                    if j + 1 < n and text[j + 1] == ch:  # doubled quote escapes
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                problems.append(
                    "a string literal is never closed" if ch == "'" else
                    "a quoted identifier is never closed")
                i = n
                continue
            buf.append(text[i:j + 1])
            i = j + 1
            continue
        if ch == "$":
            m = DOLLAR_QUOTE_RE.match(text, i)
            if m:
                tag = m.group(0)
                j = text.find(tag, m.end())
                if j == -1:
                    problems.append(f"a {tag} dollar-quoted block is never closed")
                    i = n
                    continue
                buf.append(text[i:j + len(tag)])
                i = j + len(tag)
                continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ";":
            close_statement()
            i += 1
            continue

        buf.append(ch)
        i += 1

    close_statement()
    return statements, problems


def summarize(sql: str) -> dict:
    """The relations a schema creates, the ones it uses, and what it counts.

    Runs after `split_statements`, so comments are already gone; string literals
    are blanked here so a table name mentioned inside a COMMENT or an INSERT
    value is not read as a use of that table.
    """
    sql = strip_code_fence(sql or "")
    statements, problems = split_statements(sql)
    created: list[tuple[str, str]] = []
    non_sql: list[str] = []
    uses: list[str] = []
    ctes: set[str] = set()

    for stmt in statements:
        m = CREATE_RELATION_RE.match(stmt)
        if m:
            created.append((" ".join(m.group(1).split()).lower(), m.group(2)))
        head = re.match(r"\s*([A-Za-z_]+)", stmt)
        if not head or head.group(1).lower() not in STATEMENT_HEADS:
            non_sql.append(stmt)
            continue
        flat = STRING_LITERAL_RE.sub("''", stmt)
        ctes.update(_relation_key(n) for n in CTE_RE.findall(flat))
        for m in RELATION_SOURCE_RE.finditer(flat):
            if m.group(2):  # a set-returning function, not a relation
                continue
            uses.append(m.group(1))
        uses.extend(RELATION_WRITE_RE.findall(flat))
        m = INDEX_TARGET_RE.match(flat)
        if m:
            uses.append(m.group(1))

    counts: dict[str, int] = {}
    for kind, _ in created:
        counts[kind] = counts.get(kind, 0) + 1
    known = {_relation_key(name) for _, name in created} | ctes
    undefined = sorted({n for n in uses if _relation_key(n) not in known})

    return {
        "statements": len(statements),
        "problems": problems,
        "created": created,
        "tables": counts.get("table", 0),
        "views": counts.get("view", 0) + counts.get("materialized view", 0),
        "indexes": len(re.findall(r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b", sql or "",
                                  re.IGNORECASE)),
        "inserts": len(re.findall(r"\bINSERT\s+INTO\b", sql or "",
                                  re.IGNORECASE)),
        "non_sql": non_sql,
        "undefined": undefined,
    }


def check(sql: str) -> str | None:
    """Why the schema is not a usable schema, or None when it is.

    Each branch names the defect concretely enough for the DB agent to correct
    it: which literal was never closed, which table was created twice, which
    relation is used but never created.
    """
    text = strip_code_fence(sql or "")
    if not text.strip():
        return ("the DB agent returned nothing: the reply is empty, so there is "
                "no schema to run")
    if text.lstrip()[:1] in ("{", "["):
        return ("the reply is a JSON document, not SQL. The DB agent is asked "
                "for PostgreSQL `CREATE TABLE` / `CREATE VIEW` statements, and "
                "a JSON object is not one: nothing in it can be executed against "
                "a database")

    statements, problems = split_statements(text)
    if problems:
        return ("the SQL cannot be read: " + "; ".join(problems) +
                ". A schema is only executable once its statements, literals and "
                "parentheses are complete")
    if not statements:
        return ("the reply contains no SQL statement: it is text the database "
                "cannot run. Return the schema as `CREATE TABLE` (and, where "
                "useful, `CREATE VIEW`) statements")

    summary = summarize(text)
    if summary["non_sql"] and len(summary["non_sql"]) == summary["statements"]:
        sample = summary["non_sql"][0].splitlines()[0][:120]
        return (f"the reply is not SQL: no statement begins with a SQL keyword. "
                f"It begins with {sample!r}. Return PostgreSQL `CREATE TABLE` "
                f"statements")

    if summary["tables"] == 0:
        return ("the SQL contains no `CREATE TABLE` statement, so it defines no "
                "schema. The prompt asks for the tables that hold the twin's "
                "data, plus the views that expose them")

    seen: dict[str, int] = {}
    for _, name in summary["created"]:
        key = _definition_key(name)
        seen[key] = seen.get(key, 0) + 1
    duplicates = sorted(n for n, c in seen.items() if c > 1)
    if duplicates:
        return ("the SQL creates "
                + ", ".join(f"`{n}`" for n in duplicates)
                + " more than once: the second definition fails when the schema "
                  "is applied, so the whole file is unusable")

    if summary["undefined"]:
        names = summary["undefined"]
        return ("the SQL uses "
                + ", ".join(f"`{n}`" for n in names)
                + " but never creates it. Every relation a statement reads from "
                  "or writes to must be created earlier in the same schema (a "
                  "typo in a table name, or a table that was left out, fails "
                  "the whole file when it is applied)")
    return None


def verify(sql: str) -> dict:
    """Decide whether the DB stage produced a usable schema.

    Success needs a reply that is SQL and that holds together structurally (see
    `check`). `report` is the text handed back to the agent on failure — empty
    when `ok` is True.
    """
    reason = check(sql)
    body = strip_code_fence(sql).strip()
    summary = summarize(sql)
    if reason:
        reason = (reason + ".\n\nThe SQL that was returned "
                  f"(last {REPORT_CHARS} characters):\n"
                  f"{body[-REPORT_CHARS:] or '(empty reply)'}")
    return {"ok": reason is None, "report": reason or "", "summary": summary}


def generate_with_repair(submit, *, attempts: int | None = None,
                         repair_prompt=None, on_attempt=None) -> dict:
    """Ask `submit` for a schema, validate it, and ask again while it fails.

    `submit(prompt_text, attempt)` returns the agent's reply for one turn — or
    None if the turn produced no reply at all (task failed or timed out), which
    stops the loop because there is nothing to validate or to correct.
    `repair_prompt(previous_sql, report, attempt, total)` builds the follow-up
    message (normally `prompts.user.make_db_repair`). The loop validates the
    returned schema after every turn and stops at the first one that passes. It
    always returns the last schema, successful or not, together with the verdict,
    so a caller that runs out of attempts still has the schema and the reason it
    was rejected.
    """
    total = DB_REPAIR_ATTEMPTS if attempts is None else attempts
    # `total` counts repairs, so a total of 3 allows 4 schemas: the initial one
    # plus three corrections.
    sqls: list[str] = []
    verdict: dict | None = None
    prompt = None

    for i in range(total + 1):
        reply = submit(prompt, i)
        if reply is None:
            verdict = {"ok": False, "summary": {},
                       "report": ("The agent returned no schema for this turn "
                                  "(the task failed or did not complete in time), "
                                  "so there was nothing to validate.")}
            if callable(on_attempt):
                on_attempt(i, None, verdict)
            break
        sql = strip_code_fence(reply)
        sqls.append(sql)
        verdict = verify(sql)
        if callable(on_attempt):
            on_attempt(i, sql, verdict)
        if verdict["ok"] or i == total:
            break
        prompt = (repair_prompt(sql, verdict["report"], i + 1, total)
                  if callable(repair_prompt) else verdict["report"])

    return {"sql": sqls[-1] if sqls else None, "sqls": sqls,
            "ok": bool(verdict and verdict["ok"]),
            "report": (verdict or {}).get("report", ""),
            "summary": (verdict or {}).get("summary", {}) or {},
            "repaired": max(len(sqls) - 1, 0), "attempts": len(sqls)}
