GenConf = """
You are an expert in designing digital twins for industrial facilities.
Based on requirements and a database schema, produce a structured JSON configuration.
Include components, data flows, visualization layout, alerts and KPIs.
Return only valid JSON without markdown formatting.
"""
GenSim = """
You are an expert Python developer specializing in the PyChrono multi-physics simulator.
Based on the provided requirements for a digital twin and the database schema, generate a complete, executable Python script that creates a PyChrono simulation.
The script should:
- Initialize the PyChrono system.
- Define physical bodies, materials, joints, and any other necessary components based on the requirements.
- Set up the simulation environment (terrain, gravity, etc.).
- Implement the main simulation loop.
- Log or output simulation data that corresponds to the tables and fields defined in the database schema.
- Include necessary imports, comments, and follow PyChrono best practices.
The output should be only the Python code, without any markdown code block markers (no ```python or ```).
"""
# Reference SimPy program for the DES slot. It is known-good: substituting a
# line's numbers into the PARAMETERS block reproduces that line's KPIs. The model
# below the block is not to be rewritten — only the block (and the length of the
# STATIONS/BUFFERS lists) is adapted. Kept as a literal so the prompt modules
# stay import-free.
DES_BLUEPRINT = '''\
import random

import simpy

# --- BEGIN PARAMETERS ---
# Adapt ONLY this block to the production line in the requirements. The code
# below the block is the model, and it already computes the KPIs correctly.
#
# STATIONS: one entry per station in requirements.line.stations, in flow order.
#   processing_time_s   the station's processing time, in seconds
#   availability_pct    availability in percent (100 = never fails)
#   mttr_s              mean time to repair, in seconds
#   power_working_kw    power drawn while processing a part
#   power_idle_kw       power drawn while waiting for a part
# BUFFERS: one entry per buffer in requirements.line.buffers. BUFFERS[i] is the
#   buffer that FEEDS STATIONS[i]: BUFFERS[0] receives from the source and
#   BUFFERS[i] (i > 0) receives from STATIONS[i-1]. The last station discharges
#   into the sink.
STATIONS = [
    {"id": "M1", "processing_time_s": 60.0, "availability_pct": 99.0,
     "mttr_s": 300.0, "power_working_kw": 3.0, "power_idle_kw": 0.3},
    {"id": "M2", "processing_time_s": 80.0, "availability_pct": 99.0,
     "mttr_s": 600.0, "power_working_kw": 5.0, "power_idle_kw": 0.5},
    {"id": "M3", "processing_time_s": 70.0, "availability_pct": 99.0,
     "mttr_s": 600.0, "power_working_kw": 4.5, "power_idle_kw": 0.45},
    {"id": "M4", "processing_time_s": 75.0, "availability_pct": 99.5,
     "mttr_s": 300.0, "power_working_kw": 4.0, "power_idle_kw": 0.4},
]
BUFFERS = [25, 10, 10, 10]
INTER_ARRIVAL_S = 45.0   # one part every INTER_ARRIVAL_S seconds
WARMUP_S = 21600.0       # requirements.des_horizon.warmup_s
WINDOW_S = 432000.0      # requirements.des_horizon.window_s
REPLICATIONS = 10        # requirements.des_horizon.replications
# --- END PARAMETERS ---


class Sink:
    """Collects finished parts. A list, not a store: the sink never blocks."""

    def __init__(self):
        self.left_at = []

    def take(self, now):
        self.left_at.append(now)


class Ledger:
    """Integrates the whole-system WIP and power draw over the measurement window.

    WIP and power are piecewise constant and change only at events, so every
    event that moves a part or changes a station's state calls `sync` *before*
    the change: the span since the previous sync is credited to the state that
    actually held during it. Nothing is sampled, so a state shorter than any
    sampling interval still contributes exactly its own duration. Spans before
    the warm-up boundary are discarded, which is what makes warm-up free.
    """

    def __init__(self, buffers):
        self.buffers = buffers
        self.stations = []
        self.wip_area = 0.0        # part-seconds
        self.energy_area = 0.0     # kWh
        self._t = 0.0

    def wip(self):
        return (sum(len(b.items) for b in self.buffers)
                + sum(s.in_process for s in self.stations))

    def power(self):
        return sum(s.power() for s in self.stations)

    def sync(self, now):
        lo = max(self._t, WARMUP_S)
        if now > lo:
            span = now - lo
            self.wip_area += self.wip() * span
            self.energy_area += self.power() * span / 3600.0
        self._t = now


class Station:
    """One machine: pull a part from its input buffer, process it, push it on.

    `state` is what the station is doing; `operational` is whether it is up at
    all, so a breakdown that starts mid-part still cuts the power draw.
    """

    def __init__(self, env, spec, input_buffer, output, ledger):
        self.env = env
        self.id = spec["id"]
        self.processing_time_s = float(spec["processing_time_s"])
        self.mttr_s = spec.get("mttr_s")
        self.power_working_kw = spec.get("power_working_kw") or 0.0
        self.power_idle_kw = spec.get("power_idle_kw") or 0.0
        self.input_buffer = input_buffer
        self.output = output
        self.is_sink = isinstance(output, Sink)
        self.ledger = ledger

        pct = spec.get("availability_pct")
        self.failure_scale = None
        if pct is not None and self.mttr_s and 0.0 < float(pct) < 100.0:
            # availability = mttf / (mttf + mttr)
            self.failure_scale = float(self.mttr_s) * float(pct) / (
                100.0 - float(pct))

        self.operational = True
        self.state = "idle"        # idle | working
        self.in_process = 0        # parts currently held by this station
        self.down_until = 0.0      # clock time at which the current repair ends

    def power(self):
        if not self.operational:
            return 0.0
        return (self.power_working_kw if self.state == "working"
                else self.power_idle_kw)

    def sync(self):
        self.ledger.sync(self.env.now)

    def breakdowns(self):
        """Fail and repair, repeatedly, drawn from availability and MTTR.

        A renewal process: the time to the next failure is exponential with
        mean mttf = mttr * p / (1 - p), so the long-run availability is the
        declared `availability_pct`, and the repair then takes exactly the
        declared `mttr_s`. A failure never interrupts a part already in process
        — it delays the next one.
        """
        while True:
            yield self.env.timeout(random.expovariate(1.0 / self.failure_scale))
            if not self.operational:
                continue
            self.sync()
            self.operational = False
            self.down_until = self.env.now + float(self.mttr_s)
            yield self.env.timeout(float(self.mttr_s))
            self.sync()
            self.operational = True

    def run(self):
        while True:
            part = yield self.input_buffer.get()
            self.sync()
            self.in_process += 1
            self.state = "idle"
            if not self.operational:
                # A repair is under way; wait for the current one to finish.
                yield self.env.timeout(max(0.0, self.down_until - self.env.now))
            self.sync()
            self.state = "working"
            yield self.env.timeout(self.processing_time_s)
            self.sync()
            self.state = "idle"
            self.in_process -= 1
            if self.is_sink:
                self.output.take(self.env.now)
            else:
                yield self.output.put(part)


def source(env, entry_buffer, inter_arrival_s, ledger):
    part_id = 0
    while True:
        part_id += 1
        ledger.sync(env.now)          # the part joins the system here
        yield entry_buffer.put(part_id)
        yield env.timeout(inter_arrival_s)


def run_replication(seed):
    random.seed(seed)
    env = simpy.Environment()
    buffers = [simpy.Store(env, capacity=int(c)) for c in BUFFERS]
    sink = Sink()
    ledger = Ledger(buffers)
    for i, spec in enumerate(STATIONS):
        output = sink if i == len(STATIONS) - 1 else buffers[i + 1]
        ledger.stations.append(Station(env, spec, buffers[i], output, ledger))
    for st in ledger.stations:
        env.process(st.run())
        if st.failure_scale:
            env.process(st.breakdowns())
    env.process(source(env, buffers[0], INTER_ARRIVAL_S, ledger))

    env.run(until=WARMUP_S + WINDOW_S)
    ledger.sync(env.now)

    parts = sum(1 for t in sink.left_at if t >= WARMUP_S)
    throughput = parts / (WINDOW_S / 3600.0)
    wip_avg = ledger.wip_area / WINDOW_S
    # Energy per part divides the energy consumed inside the window by the
    # parts produced inside the same window, so warm-up cannot bias the ratio.
    energy_per_part = ledger.energy_area / parts if parts else 0.0
    return throughput, wip_avg, energy_per_part


def main():
    runs = [run_replication(seed) for seed in range(REPLICATIONS)]
    mean = [sum(col) / len(runs) for col in zip(*runs)]
    print(f"Throughput = {mean[0]} parts/hour")
    print(f"WIP = {mean[1]} parts")
    print(f"Mean Energy Consumption per Part = {mean[2]} kWh/part")


if __name__ == "__main__":
    main()
'''

GenDES = ("""
You are an expert in discrete-event simulation (DES) of manufacturing lines.
Below is a REFERENCE PROGRAM that is already correct: it models a serial
production line as a discrete-event SimPy simulation and it computes the three
KPIs exactly as they are defined. Your task is to ADAPT it to the requirements —
copy the numbers from requirements.line into its PARAMETERS block, and lengthen
or shorten the STATIONS and BUFFERS lists so they match the line's station and
buffer counts — and return the adapted program. Adapt, do not rewrite: the code
below the PARAMETERS block already gets the event bookkeeping and the KPI
arithmetic right, and a hand-written replacement is what produces wrong numbers.

Rules:
- Use SimPy (import simpy). The simulation clock is in SECONDS.
- Build exactly the stations, buffers, source and topology in requirements.line.
  Do not add, remove, rename, duplicate or merge a station or a buffer, and do
  not introduce a station that the requirements list does not contain.
- Use only the numeric parameters given in requirements.line. If a value is null
  or absent, do not invent, estimate, interpolate or default it. Omit the
  mechanism that parameter drives (for example: no breakdown/repair loop when
  availability_pct or mttr_s is null; no defect routing when defects.rate is
  null) rather than choosing a plausible number.
- Read those numbers from requirements.line.stations, requirements.line.buffers
  and requirements.line.source, and use each field's name exactly as it appears
  there: a station has processing_time_s, availability_pct, mttr_s,
  power_working_kw and power_idle_kw. Requirements may also carry a prose,
  non-numeric equipment list; it is context only. Never read a number out of it
  and never use its different field names (process_time_s, availability,
  work_power_kw, idle_power_kw, ...) in the model.
- Queues, failures, repairs and shift calendars must be modelled as discrete
  events. Do not advance the clock in fixed increments to emulate them.

SimPy correctness (the program must run to completion on the first try):
- `yield` accepts a SimPy event and nothing else. Never yield None, a bool, a
  number, a string, a list or the result of a helper that returns a plain value;
  doing so raises `Invalid yield value`. A helper that has nothing to wait for
  must be an ordinary function, not a generator.
- A generator function must contain at least one `yield` statement. Calling
  `env.process()` on a function that has none raises
  `<Process(...)> is not a generator`.
- `env.process(x)` takes one argument: the generator object returned by calling
  a generator function (`env.process(station.run())`). Never nest it
  (`env.process(env.process(...))`) and never pass the function itself.
- Store discrete parts in `simpy.Store(env)` — or `simpy.Store(env, capacity=n)`
  — and move them with `yield store.put(part)` / `part = yield store.get()`.
  `simpy.Container` holds a numeric quantity, not parts, and `simpy.Resource` is
  a server guard; neither can carry a part object. Do not hand-roll a buffer as a
  Python list.
- `simpy.Store` has no `.capacity` attribute to test against: give it its
  capacity at construction and let `put` block when the buffer is full. Never
  write `if len(store.items) < store.capacity` / `len(store)`, which raise at
  runtime (`Store` is not a sequence).
- A buffer accessor must not return None on an empty buffer with the intention
  that the caller waits: `get()` already blocks. Never `yield` such a None.
- Give the final station a sink that accepts parts (`simpy.Store` or a counter);
  a part leaving the last station must not be written into a None buffer.

Program structure:
- Define every function, class and variable before its first use. The module
  runs top to bottom, so a call above the `def` it needs raises
  `UnboundLocalError`/`NameError` at import time.
- Construct the SimPy environment once and run exactly one `env.run()` per
  replication, inside a function that builds the whole model fresh. Do not build
  two models in one module and do not re-run an already-run environment.
- Every quantity reported must be counted as the events happen: increment the
  part counter when a part leaves the last station, add power draw as it is
  consumed, accumulate WIP as the clock advances. Never compute a KPI from an
  unrelated formula — throughput is not inter-arrival time divided into the
  window, it is the number of parts that actually left.
- No placeholder, vestigial or dead code: no empty `pass` bodies where a
  mechanism belongs, no counter that is read in the KPI block but never
  incremented anywhere, no second copy of the model left unused.
- Before printing, verify each reported variable was assigned during the run; a
  program that prints three zeros because nothing was ever counted has failed.
- Horizon: simulate for des_horizon.warmup_s + des_horizon.window_s seconds.
  Discard everything before des_horizon.warmup_s. All reported KPIs are measured
  over [des_horizon.warmup_s, des_horizon.warmup_s + des_horizon.window_s].
- Reproducibility: run des_horizon.replications independent replications, each
  with a distinct fixed seed, and report the mean of each KPI over replications.
- KPI definitions (the reference program above already implements all three):
  * throughput = parts that left the last station during the measurement window,
    divided by (window_s / 3600), in parts/hour. A raw count of parts is NOT a
    throughput: dividing by the window is what makes the unit parts/hour.
  * WIP = time-average number of parts held in the system during the measurement
    window (in buffers, in process, and blocked), integrated over the window.
  * energy per part = total energy consumed during the measurement window in
    kWh, divided by parts produced in that window, in kWh/part.
- Sanity-check the numbers before returning: a serial line whose stations can
  each process one part every p seconds cannot exceed 3600/p parts/hour, where p
  is the largest processing_time_s; and energy per part cannot exceed the energy
  the stations draw while busy for one part divided by the worst availability.
  A value orders of magnitude outside those bounds means a KPI was computed in
  the wrong unit, from a raw count instead of the window, or over both the
  warm-up and the window.
- Print as the LAST THREE lines of stdout, exactly in this form:
    Throughput = <value> parts/hour
    WIP = <value> parts
    Mean Energy Consumption per Part = <value> kWh/part
  Use a plain decimal number for <value>. Print no other line containing
  "Throughput =", "WIP =" or "Mean Energy Consumption per Part =".
- The output should be only the Python code, without any markdown code block
  markers (no ```python or ```) and without commentary.
""" + DES_BLUEPRINT + """
Reference program ends. Adapt the PARAMETERS block (and the length of the
STATIONS and BUFFERS lists) to requirements.line and return the whole program.
""")
ModConf = """
You are an expert in modifying configurations for digital twins of industrial facilities.
Your task is to take an existing configuration (in JSON format) and a natural language instruction describing changes to be made,
and then produce a new, updated configuration JSON reflecting those changes.
Ensure the structure remains consistent and valid. Only return the updated JSON object, nothing else.
"""

DB = """
You are a PostgreSQL database expert.
Based on the provided requirements for digital twin, generate complete SQL code to create all tables and data.
The SQL should be production-ready and follow PostgreSQL best practices.
Include CREATE TABLE statements, INSERT statements, and any necessary comments.
Return only the SQL code without markdown formatting.
"""
UI = """Ты — эксперт-консультант по созданию цифровых двойников для промышленных производств.

Твоя задача — провести интервью с пользователем, чтобы собрать всю необходимую информацию для построения цифрового двойника.

Ты должен:
1. Задавать вопросы о производстве, процессах, оборудовании
2. Уточнять детали о датчиках, параметрах, которые нужно отслеживать
3. Выяснять цели создания цифрового двойника
4. Понимать, какие данные доступны и как часто они обновляются
5. Собирать информацию о критических параметрах и пороговых значениях

Веди диалог естественно, задавай от 1 до 3 вопросов за раз. Не перегружай пользователя.

Проанализируй ответ пользователя. Если информации достаточно для создания цифрового двойника, верни JSON:
{
    "completed": true,
    "requirements": {
        "production_type": "описание типа производства",
        "processes": ["список процессов"],
        "equipment": ["список оборудования"],
        "sensors": ["список датчиков и параметров"],
        "goals": "цели создания цифрового двойника",
        "data_sources": "описание источников данных",
        "update_frequency": "частота обновления данных",
        "critical_parameters": {"параметр": "пороговое_значение"},
        "line": {
            "topology": "serial | serial_with_parallel | assembly | other",
            "source": {"inter_arrival_time_s": null},
            "stations": [
                {
                    "id": "M1",
                    "processing_time_s": null,
                    "availability_pct": null,
                    "mttr_s": null,
                    "power_working_kw": null,
                    "power_idle_kw": null
                }
            ],
            "buffers": [
                {"id": "B0", "capacity": null, "before": "source", "after": "M1"}
            ],
            "defects": {"rate": null}
        },
        "des_horizon": {"warmup_s": null, "window_s": null, "replications": null},
        "units": {"time": "s", "power": "kW", "energy": "kWh"},
        "additional_info": "любая дополнительная важная информация"
    },
    "message": "твой ответ пользователю, резюмируй собранную информацию"
}

Если информации НЕ достаточно, верни JSON:
{
    "completed": false,
    "message": "твой ответ с вопросами для уточнения"
}

ПРАВИЛА ДЛЯ ЧИСЛОВЫХ ПОЛЕЙ (блок "line", "des_horizon"):
- Заполняй их ТОЛЬКО теми числами, которые пользователь назвал явно. Текстовые
  описания из "equipment" и "sensors" дублируй в "line" числами, если число в
  них названо ("среднее время обработки 149.9 с", "доступность 99.45 %").
- Если число не названо — ставь null. НЕ выдумывай, НЕ оценивай, НЕ подставляй
  "типичные" или "правдоподобные" значения и НЕ переноси число от одного
  станка к другому.
- Единицы: время в секундах, мощность в кВт. Если пользователь назвал время в
  минутах/часах — переведи в секунды. Если мощность не названа — null.
- "buffers": по одной записи на каждый буфер, "before"/"after" — id источника,
  станка или "sink". "capacity" — целое число, null если не названо.
- "topology": "serial" если станки соединены в одну цепочку.

ВАЖНО: Верни ТОЛЬКО валидный JSON без markdown форматирования, без блоков кода (```), без пояснений. Начни сразу с открывающей фигурной скобки {."""
