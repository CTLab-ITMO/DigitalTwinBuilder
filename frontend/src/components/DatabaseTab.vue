<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAppStore } from '../stores/app'
import { api } from '../api/client'

const store = useAppStore()
const generating = ref(false)

const agentId = 1
const convIdx = 0

async function generateSchema() {
  if (!store.currentSessionId || !store.interviewResult) return

  generating.value = true
  try {
    const existing = store.conversations.find(c => c.agent_id === agentId && c.conv_idx === convIdx)
    let convId = existing?.id

    if (!convId) {
      const data = await api.createConversation(store.currentSessionId, agentId, convIdx)
      convId = data.conversation_id
    }

    const prompt = `На основе следующих требований создай схему базы данных:\n${JSON.stringify(store.interviewResult, null, 2)}`

    await store.sendMessage(agentId, convIdx, convId, prompt, { max_tokens: 3000 })
  } finally {
    generating.value = false
  }
}
</script>

<template>
  <div class="db-tab">
    <h2>Настройка базы данных</h2>

    <div v-if="!store.interviewResult" class="card warning">
      Пожалуйста, завершите интервью на вкладке «Интервью»
    </div>

    <template v-if="store.interviewResult">
      <div class="card">
        <h3>Результат интервью</h3>
        <pre class="json-display">{{ JSON.stringify(store.interviewResult, null, 2) }}</pre>
      </div>

      <button
        v-if="!store.dbSchema"
        class="btn btn-primary"
        :disabled="generating"
        @click="generateSchema"
      >
        {{ generating ? 'Generating...' : 'Сгенерировать схему БД' }}
      </button>

      <div v-if="store.dbSchema" class="card">
        <h3>Схема базы данных</h3>
        <pre class="sql-display"><code>{{ store.dbSchema }}</code></pre>
      </div>
    </template>
  </div>
</template>

<style scoped>
.db-tab {
  max-width: 800px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.db-tab h2 { font-size: 18px; font-weight: 600; }
.db-tab h3 { font-size: 14px; font-weight: 600; margin-bottom: 12px; }

.warning {
  border-color: var(--yellow);
  color: var(--yellow);
}

.json-display {
  background: var(--bg);
  padding: 12px;
  border-radius: var(--radius);
  font-size: 13px;
  overflow-x: auto;
  max-height: 300px;
}

.sql-display {
  background: var(--bg);
  padding: 16px;
  border-radius: var(--radius);
  overflow-x: auto;
}
</style>
