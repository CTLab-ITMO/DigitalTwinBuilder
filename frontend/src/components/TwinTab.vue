<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAppStore } from '../stores/app'
import { apiBaseUrl } from '../api/client'
import { t } from '../i18n'

const store = useAppStore()
const generatingConfig = ref(false)
const generatingSim = ref(false)
const generatingDes = ref(false)

const agentId = 2
const desConvIdx = 2

// Anomaly detection: the stack is started by hand on the user's machine, so
// this card's job is to hand over one runnable command. The GPU overlay is a
// second compose file, which means the `up` *and* the `down` have to carry the
// same `-f` flags — a `down` that names only the base file would not tear down
// what the overlay started.
const anomalyMode = ref<'cpu' | 'gpu'>('cpu')
const anomalyCopied = ref(false)

const composeFiles = computed(() =>
  anomalyMode.value === 'gpu' ? ' -f docker-compose.yml -f docker-compose.gpu.yml' : ''
)

const anomalyCommand = computed(() =>
  `DTB_API_URL=${apiBaseUrl()} DTB_SESSION_ID=${store.currentSessionId} ` +
  `docker compose${composeFiles.value} --profile anomaly up -d --build`
)

const anomalyStopCommand = computed(
  () => `docker compose${composeFiles.value} --profile anomaly down`
)

async function prepareAnomaly() {
  await store.prepareAnomaly()
}

async function copyCommand() {
  try {
    await navigator.clipboard.writeText(anomalyCommand.value)
    anomalyCopied.value = true
    // Transient: the button goes back to its label on its own, so a second copy
    // reads as an action rather than as a state that never changes.
    window.setTimeout(() => { anomalyCopied.value = false }, 2000)
  } catch {
    // The clipboard API needs a secure context; say so rather than let the
    // button look like it worked.
    store.error = t('error.anomalyCopy')
  }
}

// Both twin slots go through the broker now: it seeds the conversation with the
// agent's system prompt and builds the engineered `make_gen_conf` /
// `make_gen_sim` text, then waits for the turn on this side's long poll. The
// client's own ad-hoc prompt and 60-second give-up are gone.
async function generateConfig() {
  if (!store.currentSessionId || !store.interviewResult) return
  generatingConfig.value = true
  try {
    const convId = await store.ensureConversation(agentId, 0)
    if (!convId) {
      store.error = t('error.createConversation')
      return
    }
    await store.generateTwinConfig(convId)
  } finally {
    generatingConfig.value = false
  }
}

async function generateSim() {
  if (!store.currentSessionId || !store.interviewResult) return
  generatingSim.value = true
  try {
    const convId = await store.ensureConversation(agentId, 1)
    if (!convId) {
      store.error = t('error.createConversation')
      return
    }
    await store.generateTwinSim(convId)
  } finally {
    generatingSim.value = false
  }
}

// The DES slot: the broker asks the agent for a SimPy program, runs it, and
// sends the program back with its traceback while it does not complete with
// its three KPIs. Nothing reaches this card that has not been executed.
async function generateDes() {
  if (!store.currentSessionId || !store.dbSchema) return
  generatingDes.value = true
  try {
    const convId = await store.ensureConversation(agentId, desConvIdx)
    if (!convId) {
      store.error = t('error.createConversation')
      return
    }
    await store.generateDesModel(convId)
  } finally {
    generatingDes.value = false
  }
}

function fmt(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? '—' : value.toFixed(digits)
}

function download(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/plain' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}

function regenSim() {
  store.simulationCode = null
}
</script>

<template>
  <div class="twin-tab">
    <h2>{{ t('twin.title') }}</h2>

    <div v-if="!store.dbSchema" class="card warning">
      {{ t('twin.needDb') }}
    </div>

    <template v-if="store.dbSchema">
      <div class="card">
        <h3>{{ t('twin.sqlHeading') }}</h3>
        <details>
          <summary>{{ t('twin.viewSql') }}</summary>
          <pre class="code-block"><code>{{ store.dbSchema }}</code></pre>
        </details>
        <button class="btn btn-secondary" style="margin-top:8px" @click="download('schema.sql', store.dbSchema!)">
          {{ t('twin.downloadSql') }}
        </button>
      </div>

      <div v-if="!store.twinConfig" class="card">
        <button class="btn btn-primary" :disabled="generatingConfig" @click="generateConfig">
          {{ generatingConfig ? t('common.generating') : t('twin.generateConfig') }}
        </button>
        <p v-if="!generatingConfig && store.twinVerdict?.slot === 'gen_conf' && !store.twinVerdict.ok" class="verdict bad">
          {{ store.twinVerdict.report || t('twin.noReply') }}
        </p>
      </div>

      <div v-if="store.twinConfig" class="card">
        <h3>{{ t('twin.configHeading') }}</h3>
        <details open>
          <summary>{{ t('twin.viewConfig') }}</summary>
          <pre class="code-block"><code>{{ JSON.stringify(store.twinConfig, null, 2) }}</code></pre>
        </details>
      </div>

      <div v-if="store.twinConfig" class="card">
        <h3>{{ t('twin.anomalyHeading') }}</h3>
        <p class="hint">{{ t('twin.anomalyHint') }}</p>

        <div v-if="!store.anomalyConfig" style="margin-top:8px">
          <button class="btn btn-primary" :disabled="store.anomalyBusy" @click="prepareAnomaly">
            {{ store.anomalyBusy ? t('common.generating') : t('twin.anomalyPrepare') }}
          </button>
          <p v-if="store.anomalyError" class="verdict bad">
            {{ t('error.anomalyConfig') }}
            <span class="error-detail">{{ store.anomalyError }}</span>
          </p>
        </div>

        <template v-if="store.anomalyConfig">
          <details>
            <summary>{{ t('twin.anomalyViewConfig') }}</summary>
            <pre class="code-block"><code>{{ JSON.stringify(store.anomalyConfig, null, 2) }}</code></pre>
          </details>

          <div class="anomaly-mode">
            <label>
              <input v-model="anomalyMode" type="radio" value="cpu" />
              {{ t('twin.anomalyCpu') }}
            </label>
            <label>
              <input v-model="anomalyMode" type="radio" value="gpu" />
              {{ t('twin.anomalyGpu') }}
            </label>
          </div>

          <p class="hint">{{ t('twin.anomalyCommand') }}</p>
          <div class="command">
            <pre class="code-block"><code>{{ anomalyCommand }}</code></pre>
            <button class="btn btn-secondary" @click="copyCommand">
              {{ anomalyCopied ? t('twin.anomalyCopied') : t('twin.anomalyCopy') }}
            </button>
          </div>

          <h4 class="endpoints-heading">{{ t('twin.anomalyAccess') }}</h4>
          <ul class="endpoints">
            <li>
              {{ t('twin.anomalyGrafana') }}: <code>http://localhost:3000</code>
              <span class="hint">({{ t('twin.anomalyGrafanaAuth') }})</span>
            </li>
            <li>
              {{ t('twin.anomalyDetector') }}: <code>http://localhost:9100/status</code>
            </li>
            <li>
              {{ t('twin.anomalyApi') }}: <code>http://localhost:8001</code>
            </li>
          </ul>

          <p class="hint">{{ t('twin.anomalyStop', { cmd: anomalyStopCommand }) }}</p>
          <p class="hint">{{ t('twin.anomalyTrainHint') }}</p>
        </template>
      </div>

      <div v-if="store.twinConfig" class="card">
        <h3>{{ t('twin.simHeading') }}</h3>
        <div v-if="!store.simulationCode">
          <button class="btn btn-primary" :disabled="generatingSim" @click="generateSim">
            {{ generatingSim ? t('common.generating') : t('twin.generateCode') }}
          </button>
          <p v-if="!generatingSim && store.twinVerdict?.slot === 'gen_sim' && !store.twinVerdict.ok" class="verdict bad">
            {{ store.twinVerdict.report || t('twin.noReply') }}
          </p>
        </div>
        <div v-if="store.simulationCode">
          <details open>
            <summary>{{ t('twin.viewChrono') }}</summary>
            <pre class="code-block"><code>{{ store.simulationCode }}</code></pre>
          </details>
          <div style="display:flex;gap:8px;margin-top:8px">
            <button class="btn btn-secondary" @click="download('simulation.py', store.simulationCode!)">
              {{ t('twin.downloadCode') }}
            </button>
            <button class="btn btn-secondary" @click="regenSim">
              {{ t('twin.regenerate') }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="store.twinConfig" class="card">
        <h3>{{ t('twin.desHeading') }}</h3>

        <div v-if="!store.desCode">
          <button class="btn btn-primary" :disabled="generatingDes" @click="generateDes">
            {{ generatingDes ? t('common.generating') : t('twin.generateDes') }}
          </button>
        </div>

        <p v-if="generatingDes" class="hint">
          {{ t('twin.desRunning') }}
        </p>

        <div v-if="store.pipelineJob && store.pipelineJob.slot === 'des' && store.pipelineJob.attempts.length" class="attempts">
          <div
            v-for="a in store.pipelineJob.attempts"
            :key="a.attempt"
            :class="['attempt', a.ok ? 'ok' : 'bad']"
          >
            {{ t('twin.attempt', { n: a.attempt + 1 }) }}
            {{ a.attempt === 0 ? t('twin.attemptGen') : t('twin.attemptRepair') }} —
            {{ t('twin.chars', { n: a.chars }) }}
            {{ a.ok ? t('twin.attemptOk') : t('twin.attemptBad', { status: a.status || 'no_reply' }) }}
          </div>
        </div>

        <div v-if="store.desVerdict && !generatingDes" :class="['verdict', store.desVerdict.ok ? 'ok' : 'bad']">
          {{ store.desVerdict.ok ? t('twin.desOk') : t('twin.desBad') }}:
          {{ t('twin.attemptsRepairs', { attempts: store.desVerdict.attempts, repaired: store.desVerdict.repaired }) }}
        </div>

        <div v-if="store.desVerdict?.ok" class="kpis">
          <div class="kpi">
            <span class="kpi-label">{{ t('kpi.throughput') }}</span>
            <span class="kpi-value">{{ fmt(store.desVerdict.kpis.throughput_per_hour) }} {{ t('unit.partsPerHour') }}</span>
          </div>
          <div class="kpi">
            <span class="kpi-label">{{ t('kpi.wip') }}</span>
            <span class="kpi-value">{{ fmt(store.desVerdict.kpis.wip_parts) }} {{ t('unit.parts') }}</span>
          </div>
          <div class="kpi">
            <span class="kpi-label">{{ t('kpi.energy') }}</span>
            <span class="kpi-value">{{ fmt(store.desVerdict.kpis.energy_per_part_kwh, 3) }} {{ t('unit.kwhPerPart') }}</span>
          </div>
        </div>

        <pre v-if="store.desVerdict && !store.desVerdict.ok && store.desVerdict.report" class="code-block report">{{ store.desVerdict.report }}</pre>

        <div v-if="store.desCode">
          <details open>
            <summary>{{ t('twin.viewSimpy') }}</summary>
            <pre class="code-block"><code>{{ store.desCode }}</code></pre>
          </details>
          <div style="display:flex;gap:8px;margin-top:8px">
            <button class="btn btn-secondary" @click="download('des_model.py', store.desCode!)">
              {{ t('twin.downloadCode') }}
            </button>
            <button class="btn btn-primary" :disabled="generatingDes" @click="generateDes">
              {{ t('twin.regenerate') }}
            </button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.twin-tab {
  max-width: 800px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.twin-tab h2 { font-size: 18px; font-weight: 600; }
.twin-tab h3 { font-size: 14px; font-weight: 600; margin-bottom: 8px; }

.warning { border-color: var(--yellow); color: var(--yellow); }

.code-block {
  background: var(--bg);
  padding: 16px;
  border-radius: var(--radius);
  overflow-x: auto;
  margin-top: 8px;
  max-height: 400px;
  font-size: 13px;
}

details {
  cursor: pointer;
}

details summary {
  font-size: 13px;
  color: var(--accent);
}

.hint { font-size: 13px; color: var(--text-muted); margin-top: 8px; }

.attempts {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 12px 0;
  font-size: 12px;
}
.attempt { color: var(--text-muted); }
.attempt.ok { color: var(--green); }
.attempt.bad { color: var(--red); }

.verdict { font-size: 13px; margin-top: 8px; }
.verdict.ok { color: var(--green); }
.verdict.bad { color: var(--red); }

/* The store keeps the API's own `"<status>: <detail>"`, and the sentence above
   cannot tell a 404 (wrong API) from a 400 (an interview with no devices) —
   showing it is what makes the failure actionable instead of a dead end. */
.error-detail {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}

.kpis {
  display: flex;
  gap: 24px;
  margin: 12px 0;
  flex-wrap: wrap;
}
.kpi { display: flex; flex-direction: column; gap: 2px; }
.kpi-label { font-size: 11px; text-transform: uppercase; color: var(--text-muted); }
.kpi-value { font-size: 15px; font-weight: 600; }

.report {
  white-space: pre-wrap;
  max-height: 240px;
  font-size: 12px;
}

.anomaly-mode {
  display: flex;
  gap: 16px;
  margin-top: 12px;
  font-size: 13px;
}
.anomaly-mode label { display: flex; align-items: center; gap: 6px; cursor: pointer; }

.command {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.command .code-block {
  flex: 1;
  min-width: 0;
  margin-top: 0;
  max-height: none;
  white-space: pre-wrap;
  word-break: break-all;
}
.command .btn { flex-shrink: 0; }

.endpoints-heading {
  font-size: 13px;
  font-weight: 600;
  margin: 16px 0 4px;
}
.endpoints {
  list-style: none;
  font-size: 13px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.endpoints code {
  background: var(--bg);
  padding: 1px 4px;
  border-radius: 4px;
}
</style>
