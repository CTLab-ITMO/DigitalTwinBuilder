<script setup lang="ts">
import { ref } from 'vue'
import { useAppStore } from '../stores/app'
import { api } from '../api/client'

const store = useAppStore()
const generatingConfig = ref(false)
const generatingSim = ref(false)

const agentId = 2

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
</style>
