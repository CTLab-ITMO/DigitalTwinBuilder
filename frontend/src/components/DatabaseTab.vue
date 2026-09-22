<script setup lang="ts">
import { ref } from 'vue'
import { useAppStore } from '../stores/app'

const store = useAppStore()
const generating = ref(false)

const agentId = 1
const convIdx = 0

// The prompt, the validation and the repair loop live in the broker now: it
// asks the DB agent for a schema, checks the reply is a usable PostgreSQL
// schema, and sends a correction back until it is (or the attempts run out).
async function generateSchema() {
  if (!store.currentSessionId || !store.interviewResult) return

  generating.value = true
  try {
    const convId = await store.ensureConversation(agentId, convIdx)
    if (!convId) {
      store.error = 'Не удалось создать conversation — проверьте API'
      return
    }
    await store.generateDbSchema(convId)
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

      <div v-if="generating" class="card">
        <h3>Проверка схемы</h3>
        <p class="hint">
          Агент генерирует схему, она проверяется как PostgreSQL, и при ошибке
          запрашивается исправление. Это может занять несколько минут.
        </p>
      </div>

      <div v-if="store.dbVerdict && !generating" class="card" :class="{ ok: store.dbVerdict.ok, bad: !store.dbVerdict.ok }">
        <h3>{{ store.dbVerdict.ok ? 'Схема проверена' : 'Схема не прошла проверку' }}</h3>
        <p class="verdict">
          Попыток: {{ store.dbVerdict.attempts }}, исправлений:
          {{ store.dbVerdict.repaired }}
          <template v-if="store.dbVerdict.summary?.tables !== undefined">
            — таблиц: {{ store.dbVerdict.summary.tables }},
            представлений: {{ store.dbVerdict.summary.views ?? 0 }}
          </template>
        </p>
        <pre v-if="!store.dbVerdict.ok && store.dbVerdict.report" class="report">{{ store.dbVerdict.report }}</pre>
      </div>

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

.card.ok { border-color: var(--green); }
.card.ok h3 { color: var(--green); }
.card.bad { border-color: var(--red); }
.card.bad h3 { color: var(--red); }

.verdict { font-size: 13px; color: var(--text-muted); }

.hint { font-size: 13px; color: var(--text-muted); }

.report {
  background: var(--bg);
  border-radius: var(--radius);
  padding: 12px;
  margin-top: 8px;
  font-size: 12px;
  white-space: pre-wrap;
  max-height: 240px;
  overflow: auto;
}
</style>
