<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAppStore } from '../stores/app'
import { t, tAgentStatus } from '../i18n'

const store = useAppStore()
const health = ref<any>(null)

onMounted(async () => {
  try {
    const { api } = await import('../api/client')
    health.value = await api.checkHealth()
  } catch { /* ignore */ }
})
</script>

<template>
  <div class="settings-tab">
    <h2>{{ t('settings.title') }}</h2>

    <div class="card">
      <h3>{{ t('settings.agentStatus') }}</h3>
      <div class="agent-grid">
        <div
          v-for="(status, i) in store.agentStatuses"
          :key="i"
          class="agent-card"
        >
          <div class="agent-header">
            <span :class="['dot', {
              green: status?.status === 'idle',
              yellow: status?.status === 'busy',
              red: !status || status?.status === 'offline'
            }]" />
            <strong>{{ t('sidebar.agent', { i }) }}</strong>
          </div>
          <div class="agent-info">
            <span>{{ t('settings.status') }} <strong>{{ tAgentStatus(status?.status) }}</strong></span>
            <span v-if="status?.last_heartbeat">
              {{ t('settings.lastHeartbeat', { t: new Date(status.last_heartbeat).toLocaleTimeString() }) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <h3>{{ t('settings.queues') }}</h3>
      <div class="queue-grid">
        <div v-for="(q, i) in store.queueStatuses" :key="i" class="queue-item">
          <strong>{{ t('sidebar.agent', { i }) }}</strong>
          <span>{{ t('settings.pending', { n: q.pending_count }) }}</span>
          <span>{{ t('settings.active', { v: q.active_task ? t('settings.yes') : t('settings.no') }) }}</span>
        </div>
      </div>
    </div>

    <div class="card" v-if="health">
      <h3>{{ t('settings.apiHealth') }}</h3>
      <div class="health-info">
        <span>{{ t('settings.status') }} <strong :style="{color: health.status === 'healthy' ? 'var(--green)' : 'var(--red)'}">{{ health.status }}</strong></span>
        <span>{{ t('settings.database', { v: health.database }) }}</span>
        <span>{{ t('settings.pool', { v: health.pool }) }}</span>
        <span>{{ health.timestamp }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-tab {
  max-width: 800px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.settings-tab h2 { font-size: 18px; font-weight: 600; }
.settings-tab h3 { font-size: 14px; font-weight: 600; margin-bottom: 12px; }

.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.agent-card {
  background: var(--surface2);
  border-radius: var(--radius);
  padding: 12px;
}

.agent-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.dot {
  width: 10px; height: 10px;
  border-radius: 50%;
}
.dot.green { background: var(--green); }
.dot.yellow { background: var(--yellow); }
.dot.red { background: var(--red); }

.agent-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted);
}

.queue-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.queue-item {
  display: flex;
  gap: 16px;
  font-size: 13px;
}

.health-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--text-muted);
}
</style>
