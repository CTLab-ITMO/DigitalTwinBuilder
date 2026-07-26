<script setup lang="ts">
import { onMounted } from 'vue'
import { useAppStore } from './stores/app'
import SessionSidebar from './components/SessionSidebar.vue'
import InterviewTab from './components/InterviewTab.vue'
import DatabaseTab from './components/DatabaseTab.vue'
import TwinTab from './components/TwinTab.vue'
import SettingsTab from './components/SettingsTab.vue'

const store = useAppStore()

const tabs = ['Интервью', 'База данных', 'Цифровой двойник', 'Настройки']

onMounted(() => {
  store.loadSessions()
  setInterval(() => store.loadAgentStatuses(), 5000)
})
</script>

<template>
  <div class="app-layout">
    <SessionSidebar />

    <main class="main-area">
      <header class="top-bar">
        <h1>Digital Twin Builder</h1>
      </header>

      <div class="tabs">
        <button
          v-for="(tab, i) in tabs"
          :key="i"
          :class="['tab', { active: store.activeTab === i }]"
          @click="store.activeTab = i"
        >
          {{ tab }}
        </button>
      </div>

      <div class="tab-content">
        <InterviewTab v-if="store.activeTab === 0" />
        <DatabaseTab v-if="store.activeTab === 1" />
        <TwinTab v-if="store.activeTab === 2" />
        <SettingsTab v-if="store.activeTab === 3" />
      </div>

      <div v-if="store.error" class="error-bar">
        {{ store.error }}
        <button @click="store.error = null" class="error-close">&times;</button>
      </div>
    </main>
  </div>
</template>

<style>
*,
*::before,
*::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

:root {
  --bg: #0f1419;
  --surface: #1a1f2e;
  --surface2: #242b3d;
  --border: #2d3548;
  --text: #e2e8f0;
  --text-muted: #8892a4;
  --accent: #3b82f6;
  --accent-hover: #2563eb;
  --green: #22c55e;
  --yellow: #eab308;
  --red: #ef4444;
  --radius: 8px;
}

html, body, #app {
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
}

.app-layout {
  display: flex;
  height: 100%;
}

.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.top-bar {
  padding: 16px 24px;
  border-bottom: 1px solid var(--border);
}

.top-bar h1 {
  font-size: 20px;
  font-weight: 600;
}

.tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
  background: var(--surface);
}

.tab {
  padding: 12px 20px;
  border: none;
  background: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 14px;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
}

.tab:hover {
  color: var(--text);
  background: var(--surface2);
}

.tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.tab-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.error-bar {
  position: fixed;
  bottom: 16px;
  right: 16px;
  background: var(--red);
  color: white;
  padding: 12px 16px;
  border-radius: var(--radius);
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
  z-index: 100;
}

.error-close {
  background: none;
  border: none;
  color: white;
  font-size: 18px;
  cursor: pointer;
}

/* Shared component styles */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  margin-bottom: 16px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  border-radius: var(--radius);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-primary {
  background: var(--accent);
  color: white;
}
.btn-primary:hover { background: var(--accent-hover); }

.btn-secondary {
  background: var(--surface2);
  color: var(--text);
  border: 1px solid var(--border);
}
.btn-secondary:hover { background: var(--border); }

input, textarea, select {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text);
  padding: 8px 12px;
  font-size: 14px;
  outline: none;
}

input:focus, textarea:focus {
  border-color: var(--accent);
}

pre, code {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 13px;
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
