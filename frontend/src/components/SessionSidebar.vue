<script setup lang="ts">
import { useAppStore } from '../stores/app'

const store = useAppStore()

function onNewChat() {
  store.createSession().then(sid => {
    if (!sid) return
    store.createSession() // triggers UI to create a conversation
  })
}

function selectSession(id: string) {
  store.loadSession(id)
}
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <h2>Sessions</h2>
      <button class="btn btn-primary" style="width:100%" @click="onNewChat">
        + New Chat
      </button>
    </div>

    <div class="session-list">
      <button
        v-for="s in store.sessions"
        :key="s.id"
        :class="['session-item', { active: s.id === store.currentSessionId }]"
        @click="selectSession(s.id)"
      >
        {{ s.title || `Chat ${s.id.substring(0, 8)}` }}
      </button>

      <div v-if="store.sessions.length === 0" class="empty">
        No sessions yet
      </div>
    </div>

    <div class="sidebar-footer">
      <div
        v-for="(status, i) in store.agentStatuses"
        :key="i"
        class="agent-status-item"
      >
        <span
          :class="['dot', {
            green: status?.status === 'idle',
            yellow: status?.status === 'busy',
            red: status?.status === 'offline' || !status
          }]"
        />
        <span class="agent-label">Agent {{ i }}</span>
        <span class="agent-state">{{ status?.status || 'offline' }}</span>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 260px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.sidebar-header h2 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.session-item {
  width: 100%;
  padding: 10px 12px;
  border: none;
  background: none;
  color: var(--text);
  text-align: left;
  border-radius: var(--radius);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s;
}

.session-item:hover {
  background: var(--surface2);
}

.session-item.active {
  background: var(--accent);
  color: white;
}

.empty {
  padding: 24px 12px;
  color: var(--text-muted);
  font-size: 13px;
  text-align: center;
}

.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.agent-status-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot.green { background: var(--green); }
.dot.yellow { background: var(--yellow); }
.dot.red { background: var(--red); }

.agent-label {
  color: var(--text-muted);
}

.agent-state {
  margin-left: auto;
  text-transform: capitalize;
}
</style>
