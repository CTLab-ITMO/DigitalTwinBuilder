<script setup lang="ts">
import { ref } from 'vue'
import { useAppStore } from '../stores/app'
import type { Session } from '../types'

const store = useAppStore()

/** The row whose title is being edited, if any. */
const editingId = ref<string | null>(null)
const draftTitle = ref('')

function onNewChat() {
  store.createSession().then(sid => {
    if (!sid) return
    store.createSession() // triggers UI to create a conversation
  })
}

function selectSession(id: string) {
  store.loadSession(id)
}

function displayTitle(s: Session) {
  return s.title || `Chat ${s.id.substring(0, 8)}`
}

function startRename(s: Session) {
  editingId.value = s.id
  draftTitle.value = s.title || ''
}

/** The input only exists while its row is being edited, so mounting is the cue
 *  to take focus and select the text. */
function focusTitleInput(el: any) {
  if (el instanceof HTMLInputElement) {
    el.focus()
    el.select()
  }
}

function cancelRename() {
  editingId.value = null
  draftTitle.value = ''
}

async function commitRename(s: Session) {
  // Enter unmounts the input, which fires blur on the way out — the editing
  // check keeps that blur from saving a second time.
  if (editingId.value !== s.id) return
  const title = draftTitle.value.trim()
  if (!title || title === s.title) {
    cancelRename()
    return
  }
  editingId.value = null
  draftTitle.value = ''
  await store.renameSession(s.id, title)
}

async function onDelete(s: Session) {
  const ok = confirm(
    `Удалить сессию «${displayTitle(s)}»? Вместе с ней удалятся все её диалоги и сообщения.`
  )
  if (!ok) return
  await store.deleteSession(s.id)
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
      <div
        v-for="s in store.sessions"
        :key="s.id"
        :class="['session-item', { active: s.id === store.currentSessionId }]"
      >
        <input
          v-if="editingId === s.id"
          :ref="focusTitleInput"
          v-model="draftTitle"
          class="session-title-input"
          maxlength="255"
          @keydown.enter.prevent="commitRename(s)"
          @keydown.esc.prevent="cancelRename"
          @blur="commitRename(s)"
        />

        <template v-else>
          <button class="session-title" :title="displayTitle(s)" @click="selectSession(s.id)">
            {{ displayTitle(s) }}
          </button>

          <span class="session-actions">
            <button class="icon-btn" title="Переименовать" @click="startRename(s)">
              <svg
                viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
              >
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z" />
              </svg>
            </button>
            <button class="icon-btn danger" title="Удалить" @click="onDelete(s)">
              <svg
                viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
                stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
              >
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                <path d="M10 11v6M14 11v6" />
                <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
              </svg>
            </button>
          </span>
        </template>
      </div>

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
  display: flex;
  align-items: center;
  border-radius: var(--radius);
  transition: background 0.15s;
}

.session-item:hover {
  background: var(--surface2);
}

.session-item.active {
  background: var(--accent);
}

.session-title {
  flex: 1;
  min-width: 0;
  padding: 10px 12px;
  border: none;
  background: none;
  color: var(--text);
  text-align: left;
  border-radius: var(--radius);
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-item.active .session-title {
  color: white;
}

.session-title-input {
  flex: 1;
  min-width: 0;
  margin: 4px 0 4px 6px;
  padding: 6px 8px;
  font-size: 13px;
}

/* The row actions stay hidden until the row is hovered or open, so the list
   reads as a list rather than as a wall of icons. */
.session-actions {
  display: flex;
  gap: 2px;
  padding-right: 4px;
  opacity: 0;
  transition: opacity 0.15s;
}

.session-item:hover .session-actions,
.session-item.active .session-actions {
  opacity: 1;
}

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  background: none;
  color: var(--text-muted);
  border-radius: 6px;
  cursor: pointer;
}

.icon-btn:hover {
  background: var(--surface);
  color: var(--text);
}

.icon-btn.danger:hover {
  color: var(--red);
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
