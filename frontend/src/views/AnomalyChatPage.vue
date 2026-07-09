<template>
  <div class="xy-page">
    <!-- 左侧：会话历史 -->
    <aside class="xy-side">
      <div class="xy-side__head">
        <div class="xy-side__brand">
          <t-icon name="cpu" />
          <span>异常分析 · 小异</span>
        </div>
        <t-button theme="primary" size="small" block @click="createNew">
          <template #icon><t-icon name="add" /></template>
          新建对话
        </t-button>
      </div>
      <div class="xy-side__list">
        <div
          v-for="s in sessions"
          :key="s.session_id"
          class="xy-session"
          :class="{ active: s.session_id === activeId }"
          @click="selectSession(s.session_id)"
        >
          <div class="xy-session__icon"><t-icon name="chat" /></div>
          <div class="xy-session__body">
            <div class="xy-session__title">{{ s.title || "新对话" }}</div>
            <div class="xy-session__meta">
              <span class="xy-session__time">{{ fmtTime(s.updated_at) }}</span>
              <span v-if="s.preview" class="xy-session__preview">{{ s.preview }}</span>
            </div>
          </div>
          <span
            class="xy-session__del"
            @click.stop="deleteSession(s.session_id)"
          >
            <t-icon name="delete" />
          </span>
        </div>
        <div v-if="!sessions.length" class="xy-side__empty">暂无对话，点击「新建对话」开始</div>
      </div>
    </aside>

    <!-- 右侧：聊天区 -->
    <section class="xy-main">
      <div class="xy-main__bar">
        <div class="xy-main__title">
          <t-icon name="chat" />
          <span>{{ activeTitle || "新对话" }}</span>
        </div>
        <div class="xy-main__actions">
          <t-tag v-if="configured" theme="success" variant="light" size="small">已配置模型</t-tag>
          <t-tag v-else theme="warning" variant="light" size="small">未配置模型</t-tag>
          <t-button theme="default" variant="outline" size="small" @click="openSettings">
            <template #icon><t-icon name="setting" /></template>
            设置
          </t-button>
        </div>
      </div>
      <div class="xy-main__chat">
        <XiaoYiChat :session-id="activeId" :seed="activeMessages" @persist="onPersist" />
      </div>
    </section>

    <!-- 设置对话框：二阶段异常判断大模型请求地址 -->
    <t-dialog
      v-model:visible="settingsVisible"
      header="异常判断大模型（二阶段）设置"
      :confirm-btn="{ content: '保存', loading: settingsSaving }"
      @confirm="saveSettings"
      width="560px"
    >
      <p class="xy-set__desc">
        该地址即「小异」所连接的服务端（OpenAI 兼容的 <code>chat/completions</code>）。
        对话与运行监控的二阶段异常判断共用此配置。
      </p>
      <t-textarea
        v-model="settingsUrl"
        placeholder="如 http://127.0.0.1:8000/v1/chat/completions"
        :autosize="{ minRows: 2, maxRows: 4 }"
      />
      <t-alert v-if="settingsMsg" :theme="settingsOk ? 'success' : 'error'" class="xy-set__alert">
        {{ settingsMsg }}
      </t-alert>
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import { useRoute } from "vue-router"
import { MessagePlugin } from "tdesign-vue-next"
import XiaoYiChat from "../components/XiaoYiChat.vue"

const route = useRoute()
const sessions = ref([])
const activeId = ref("")

const configured = ref(false)
const settingsVisible = ref(false)
const settingsUrl = ref("")
const settingsSaving = ref(false)
const settingsMsg = ref("")
const settingsOk = ref(true)

const activeSession = computed(() => sessions.value.find((s) => s.session_id === activeId.value) || null)
const activeTitle = computed(() => activeSession.value?.title || "")
const activeMessages = computed(() => activeSession.value?.messages || [])

onMounted(async () => {
  await loadConfigStatus()
  await loadSessions()
  const target = route.query.session
  if (target && sessions.value.find((s) => s.session_id === target)) {
    activeId.value = target
  } else if (!sessions.value.length) {
    await createNew()
  } else {
    activeId.value = sessions.value[0].session_id
  }
})

async function loadConfigStatus() {
  try {
    const r = await fetch("/api/monitor/config")
    const j = await r.json()
    if (j.ok && j.data) configured.value = !!(j.data.anomaly_llm_url_v2 || "")
  } catch {}
}

async function loadSessions(keepActive = false) {
  try {
    const r = await fetch("/api/monitor/anomaly-chats")
    const j = await r.json()
    if (j.ok && Array.isArray(j.data)) {
      sessions.value = j.data
      if (!keepActive || !sessions.value.find((s) => s.session_id === activeId.value)) {
        activeId.value = sessions.value.length ? sessions.value[0].session_id : ""
      }
    }
  } catch {}
}

async function createNew() {
  // 清理当前没有任何用户消息的空会话，避免堆积
  const cur = activeSession.value
  if (cur && (!cur.messages || cur.messages.filter((m) => m.role === "user").length === 0)) {
    await fetch(`/api/monitor/anomaly-chats/${cur.session_id}`, { method: "DELETE" })
    sessions.value = sessions.value.filter((s) => s.session_id !== cur.session_id)
  }
  try {
    const r = await fetch("/api/monitor/anomaly-chats", { method: "POST" })
    const j = await r.json()
    if (j.ok && j.data?.session_id) {
      const sid = j.data.session_id
      sessions.value.unshift({ session_id: sid, title: "新对话", preview: "", messages: [], updated_at: "" })
      activeId.value = sid
    } else {
      MessagePlugin.error("新建对话失败")
    }
  } catch {
    MessagePlugin.error("网络错误")
  }
}

function selectSession(id) {
  activeId.value = id
}

async function deleteSession(id) {
  try {
    const r = await fetch(`/api/monitor/anomaly-chats/${id}`, { method: "DELETE" })
    const j = await r.json()
    if (!j.ok) {
      MessagePlugin.error(j.error || "删除失败")
      return
    }
  } catch {
    MessagePlugin.error("网络错误")
    return
  }
  // 删除成功后从数据库重新加载，确保与后端一致（后端会一并清除 round 关联）
  if (activeId.value === id) {
    await loadSessions()
    if (!sessions.value.length) {
      await createNew()
    }
  } else {
    await loadSessions(true)
  }
}

async function onPersist({ sessionId, title, messages }) {
  if (!sessionId) return
  try {
    const r = await fetch(`/api/monitor/anomaly-chats/${sessionId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, messages }),
    })
    const j = await r.json()
    if (j.ok) {
      await loadSessions(true) // 刷新标题/预览/时间，保留当前会话
    } else {
      MessagePlugin.error(j.error || "保存对话失败")
    }
  } catch {
    MessagePlugin.error("网络错误")
  }
}

async function openSettings() {
  settingsMsg.value = ""
  try {
    const r = await fetch("/api/monitor/config")
    const j = await r.json()
    if (j.ok && j.data) {
      settingsUrl.value = j.data.anomaly_llm_url_v2 || ""
      configured.value = !!settingsUrl.value
    }
  } catch {}
  settingsVisible.value = true
}

async function saveSettings() {
  settingsSaving.value = true
  settingsMsg.value = ""
  try {
    const r = await fetch("/api/monitor/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: "anomaly_llm_url_v2", value: settingsUrl.value }),
    })
    const j = await r.json()
    if (j.ok) {
      settingsOk.value = true
      settingsMsg.value = "已保存"
      configured.value = !!settingsUrl.value.trim()
      MessagePlugin.success("已保存")
    } else {
      settingsOk.value = false
      settingsMsg.value = j.error || "保存失败"
    }
  } catch {
    settingsOk.value = false
    settingsMsg.value = "网络错误"
  } finally {
    settingsSaving.value = false
  }
}

function fmtTime(t) {
  if (!t) return ""
  return String(t).replace("T", " ").slice(0, 16)
}
</script>

<style scoped>
.xy-page {
  display: flex;
  height: calc(100vh - 64px);
  gap: 16px;
  padding: 16px;
  box-sizing: border-box;
  background: #f5f7fb;
  overflow: hidden;
}

/* 侧边栏 */
.xy-side {
  width: 280px;
  flex: 0 0 280px;
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid #e8ecf0;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}
.xy-side__head {
  padding: 16px;
  border-bottom: 1px solid #eef1f5;
  background: linear-gradient(135deg, #0b1f4d 0%, #143a8f 100%);
}
.xy-side__brand {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #fff;
  font-weight: 700;
  font-size: 15px;
  margin-bottom: 14px;
}
.xy-side__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px;
}
.xy-session {
  position: relative;
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s;
}
.xy-session:hover { background: #f2f6ff; }
.xy-session.active { background: #e8f0ff; box-shadow: inset 0 0 0 1px #c5d8ff; }
.xy-session__icon {
  flex: 0 0 32px;
  width: 32px;
  height: 32px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #4f8bff, #2b6fff);
  color: #fff;
  font-size: 18px;
}
.xy-session__body { flex: 1; min-width: 0; }
.xy-session__title {
  font-size: 14px;
  font-weight: 600;
  color: #1c2b3a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.xy-session__meta { display: flex; gap: 8px; align-items: center; margin-top: 3px; }
.xy-session__time { font-size: 11px; color: #9aa4b5; flex: 0 0 auto; }
.xy-session__preview {
  font-size: 12px;
  color: #99a2b3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.xy-session__del {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  padding: 2px;
  color: #c0c6d0;
  opacity: 0;
  transition: opacity 0.15s, color 0.15s;
}
.xy-session:hover .xy-session__del { opacity: 1; }
.xy-session__del:hover { color: #e34d59; }
.xy-side__empty { padding: 24px 12px; text-align: center; font-size: 12px; color: #99a2b3; }

/* 右侧主区 */
.xy-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid #e8ecf0;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}
.xy-main__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid #eef1f5;
}
.xy-main__title { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: #1c2b3a; }
.xy-main__actions { display: flex; align-items: center; gap: 10px; }
.xy-main__chat {
  flex: 1;
  min-height: 0;
  min-width: 0;
  padding: 14px;
  overflow: hidden;
}

/* 设置对话框 */
.xy-set__desc { font-size: 13px; color: #5e6675; margin: 0 0 12px; line-height: 1.6; }
.xy-set__desc code { background: #f0f3f8; padding: 1px 6px; border-radius: 4px; font-size: 12px; }
.xy-set__alert { margin-top: 12px; }
</style>
