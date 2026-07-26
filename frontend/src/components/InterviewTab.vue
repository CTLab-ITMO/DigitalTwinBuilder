<script setup lang="ts">
import { ref, computed } from 'vue'
import { useAppStore } from '../stores/app'
import { api } from '../api/client'

const store = useAppStore()
const input = ref('')
const temperature = ref(0.7)
const maxTokens = ref(1000)

const agentId = 0
const convIdx = 0

const agentMessages = computed(() => store.messages)

const isWaiting = computed(() => {
  // Check pending tasks in memory
  if (Object.values(store.pendingTasks).some(v => v)) return true
  // Check if last message is from user (no response yet)
  const msgs = store.messages
  if (msgs.length === 0) return false
  return msgs[msgs.length - 1].role === 'user'
})

async function getOrCreateConv(): Promise<string | null> {
  const existing = store.conversations.find(c => c.agent_id === agentId && c.conv_idx === convIdx)
  if (existing) return existing.id
  if (!store.currentSessionId) return null
  const data = await api.createConversation(store.currentSessionId, agentId, convIdx)
  return data.conversation_id
}

async function send() {
  const msg = input.value.trim()
  if (!msg) return

  // Clear input immediately
  input.value = ''

  // Auto-create session if none selected
  if (!store.currentSessionId) {
    const sid = await store.createSession()
    if (!sid) return
  }

  const convId = await getOrCreateConv()
  if (!convId) return

  // Add user message to local state
  store.messages.push({
    id: crypto.randomUUID(),
    role: 'user',
    content: msg,
  })

  await store.sendMessage(agentId, convIdx, convId, msg, {
    temperature: temperature.value,
    max_tokens: maxTokens.value,
  })
}
</script>

<template>
  <div class="interview-tab">
    <div class="scroll-area">
      <h2>Создание цифрового двойника производства</h2>

      <div v-if="store.interviewResult" class="card completed">
        <strong>✓ Интервью завершено</strong>
        <p class="hint">Перейдите на вкладку «База данных»</p>
      </div>

      <div class="messages">
        <div
          v-for="msg in agentMessages"
          :key="msg.id"
          :class="['message', msg.role]"
        >
          <div class="msg-content">{{ msg.content }}</div>
        </div>
        <div v-if="isWaiting" class="message assistant">
          <div class="msg-content">
            <span class="spinner" style="display:inline-block;vertical-align:middle" />
            Processing...
          </div>
        </div>
      </div>
    </div>

    <div class="bottom-bar">
      <div class="card params-card">
        <div class="param-row">
          <label>Temperature</label>
          <input type="range" min="0" max="2" step="0.1" v-model.number="temperature" />
          <span class="param-value">{{ temperature }}</span>
        </div>
        <div class="param-row">
          <label>Max Tokens</label>
          <input type="number" v-model.number="maxTokens" min="100" max="10000" />
        </div>
      </div>

      <div class="input-area">
        <input
          v-model="input"
          type="text"
          placeholder="Введите информацию о вашем производстве..."
          :disabled="!!store.interviewResult || isWaiting"
          @keydown.enter="send"
        />
        <button class="btn btn-primary" @click="send" :disabled="!input.trim() || isWaiting">
          Send
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.interview-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.scroll-area {
  flex: 1;
  overflow-y: auto;
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
}

.scroll-area h2 { font-size: 18px; font-weight: 600; margin-bottom: 16px; }

.completed { border-color: var(--green); }
.completed strong { color: var(--green); }
.hint { margin-top: 8px; color: var(--text-muted); font-size: 13px; }

.messages {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-bottom: 16px;
}

.message {
  padding: 12px 16px;
  border-radius: var(--radius);
  max-width: 80%;
}
.message.user { background: var(--accent); color: white; align-self: flex-end; }
.message.assistant { background: var(--surface2); align-self: flex-start; }
.message.system { display: none; }

.msg-content { white-space: pre-wrap; word-break: break-word; font-size: 14px; line-height: 1.5; }

.param-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.param-row:last-child { margin-bottom: 0; }
.param-row label { font-size: 13px; color: var(--text-muted); min-width: 100px; }
.param-row input[type="range"] { flex: 1; }
.param-value { font-size: 13px; min-width: 30px; text-align: right; }
.param-row input[type="number"] { width: 100px; }

.bottom-bar {
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
  padding-top: 8px;
}

.params-card {
  margin-bottom: 8px !important;
}

.input-area { display: flex; gap: 8px; }
.input-area input { flex: 1; }
</style>
