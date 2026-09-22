<script setup lang="ts">
import { ref } from 'vue'
import { useAppStore } from '../stores/app'
import { api } from '../api/client'

const store = useAppStore()
const generatingConfig = ref(false)
const generatingSim = ref(false)
const generatingDes = ref(false)

const agentId = 2
const desConvIdx = 2

async function generateConfig() {
  if (!store.currentSessionId || !store.interviewResult) return
  generatingConfig.value = true
  try {
    const existing = store.conversations.find(c => c.agent_id === agentId && c.conv_idx === 0)
    let convId = existing?.id
    if (!convId) {
      const data = await api.createConversation(store.currentSessionId, agentId, 0)
      convId = data.conversation_id
    }

    const prompt = `На основе этих требований и схемы БД создай конфигурацию цифрового двойника:\nТребования: ${JSON.stringify(store.interviewResult)}\nСхема БД: ${store.dbSchema}`
    await store.sendMessage(agentId, 0, convId, prompt, { max_tokens: 3000 })
  } finally {
    generatingConfig.value = false
  }
}

async function generateSim() {
  if (!store.currentSessionId || !store.interviewResult) return
  generatingSim.value = true
  try {
    const existing = store.conversations.find(c => c.agent_id === agentId && c.conv_idx === 1)
    let convId = existing?.id
    if (!convId) {
      const data = await api.createConversation(store.currentSessionId, agentId, 1)
      convId = data.conversation_id
    }

    const prompt = `На основе требований и конфигурации создай код симуляции PyChrono:\nТребования: ${JSON.stringify(store.interviewResult)}\nСхема БД: ${store.dbSchema}`
    await store.sendMessage(agentId, 1, convId, prompt, { max_tokens: 4000 })
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
      store.error = 'Не удалось создать conversation — проверьте API'
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
    <h2>Конфигурация цифрового двойника</h2>

    <div v-if="!store.dbSchema" class="card warning">
      ⚠️ Пожалуйста, завершите настройку базы данных
    </div>

    <template v-if="store.dbSchema">
      <div class="card">
        <h3>SQL код для БД</h3>
        <details>
          <summary>Просмотр SQL</summary>
          <pre class="code-block"><code>{{ store.dbSchema }}</code></pre>
        </details>
        <button class="btn btn-secondary" style="margin-top:8px" @click="download('schema.sql', store.dbSchema!)">
          Скачать SQL
        </button>
      </div>

      <div v-if="!store.twinConfig" class="card">
        <button class="btn btn-primary" :disabled="generatingConfig" @click="generateConfig">
          {{ generatingConfig ? 'Generating...' : 'Сгенерировать конфигурацию' }}
        </button>
      </div>

      <div v-if="store.twinConfig" class="card">
        <h3>Конфигурация цифрового двойника</h3>
        <details open>
          <summary>Посмотреть конфигурацию ЦД</summary>
          <pre class="code-block"><code>{{ JSON.stringify(store.twinConfig, null, 2) }}</code></pre>
        </details>
      </div>

      <div v-if="store.twinConfig" class="card">
        <h3>Код симуляции PyChrono</h3>
        <div v-if="!store.simulationCode">
          <button class="btn btn-primary" :disabled="generatingSim" @click="generateSim">
            {{ generatingSim ? 'Generating...' : 'Сгенерировать код' }}
          </button>
        </div>
        <div v-if="store.simulationCode">
          <details open>
            <summary>Просмотр кода PyChrono</summary>
            <pre class="code-block"><code>{{ store.simulationCode }}</code></pre>
          </details>
          <div style="display:flex;gap:8px;margin-top:8px">
            <button class="btn btn-secondary" @click="download('simulation.py', store.simulationCode!)">
              Скачать код
            </button>
            <button class="btn btn-secondary" @click="regenSim">
              Перегенерировать
            </button>
          </div>
        </div>
      </div>

      <div v-if="store.twinConfig" class="card">
        <h3>DES-модель (SimPy)</h3>

        <div v-if="!store.desCode">
          <button class="btn btn-primary" :disabled="generatingDes" @click="generateDes">
            {{ generatingDes ? 'Generating...' : 'Сгенерировать DES-модель' }}
          </button>
        </div>

        <p v-if="generatingDes" class="hint">
          Модель генерируется, запускается и при ошибке отправляется на
          исправление — до тех пор, пока не завершится и не напечатает KPI.
        </p>

        <div v-if="store.pipelineJob && store.pipelineJob.slot === 'des' && store.pipelineJob.attempts.length" class="attempts">
          <div
            v-for="a in store.pipelineJob.attempts"
            :key="a.attempt"
            :class="['attempt', a.ok ? 'ok' : 'bad']"
          >
            Попытка {{ a.attempt + 1 }}:
            {{ a.attempt === 0 ? 'генерация' : 'исправление' }} —
            {{ a.chars }} симв.
            {{ a.ok ? '— запускается и печатает KPI' : `— не прошла (${a.status || 'no_reply'})` }}
          </div>
        </div>

        <div v-if="store.desVerdict && !generatingDes" :class="['verdict', store.desVerdict.ok ? 'ok' : 'bad']">
          {{ store.desVerdict.ok ? 'Модель запускается и сообщает KPI' : 'Модель не прошла проверку' }}:
          попыток {{ store.desVerdict.attempts }}, исправлений {{ store.desVerdict.repaired }}.
        </div>

        <div v-if="store.desVerdict?.ok" class="kpis">
          <div class="kpi">
            <span class="kpi-label">Throughput</span>
            <span class="kpi-value">{{ fmt(store.desVerdict.kpis.throughput_per_hour) }} parts/hour</span>
          </div>
          <div class="kpi">
            <span class="kpi-label">WIP</span>
            <span class="kpi-value">{{ fmt(store.desVerdict.kpis.wip_parts) }} parts</span>
          </div>
          <div class="kpi">
            <span class="kpi-label">Energy / part</span>
            <span class="kpi-value">{{ fmt(store.desVerdict.kpis.energy_per_part_kwh, 3) }} kWh/part</span>
          </div>
        </div>

        <pre v-if="store.desVerdict && !store.desVerdict.ok && store.desVerdict.report" class="code-block report">{{ store.desVerdict.report }}</pre>

        <div v-if="store.desCode">
          <details open>
            <summary>Просмотр кода SimPy</summary>
            <pre class="code-block"><code>{{ store.desCode }}</code></pre>
          </details>
          <div style="display:flex;gap:8px;margin-top:8px">
            <button class="btn btn-secondary" @click="download('des_model.py', store.desCode!)">
              Скачать код
            </button>
            <button class="btn btn-primary" :disabled="generatingDes" @click="generateDes">
              Перегенерировать
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
</style>
