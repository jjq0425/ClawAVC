<template>
  <div class="config-tab">
    <!-- Monitor Control -->
    <div class="control-card" :class="{ active: monitorRunning }">
      <div class="control-bg">
        <div class="pulse-ring" v-if="monitorRunning"></div>
        <div class="shield-icon" :class="{ active: monitorRunning }">
          <t-icon :name="monitorRunning ? 'secured' : 'lock-on'" size="36px" />
        </div>
      </div>
      <div class="control-content">
        <div class="control-title">
          {{ monitorRunning ? '安全监控运行中' : '安全监控未启动' }}
        </div>
        <div class="control-desc">
          {{ monitorRunning ? '正在持续审计 Agent 行为，实时检测异常访问与合规违规' : '启动后将持续监听日志，实时检测 Agent 行为合规性' }}
        </div>
        <div class="control-actions">
          <t-button
            v-if="!monitorRunning"
            theme="primary"
            size="large"
            @click="startMonitor"
            :loading="controlling"
          >
            <template #icon><t-icon name="play-circle" /></template>
            启动安全监控
          </t-button>
          <t-button
            v-else
            theme="danger"
            size="large"
            @click="stopMonitor"
            :loading="controlling"
          >
            <template #icon><t-icon name="stop-circle" /></template>
            终止监控
          </t-button>
        </div>
      </div>
    </div>

    <!-- Config Form -->
    <div class="section-card">
      <div class="section-header">
        <t-icon name="setting" size="20px" />
        <span>数据源配置</span>
      </div>
      <p class="section-desc">配置监控数据来源路径。启动监控前需填写以下配置。</p>

      <div class="form-group">
        <label class="form-label">网关日志路径</label>
        <p class="form-hint">Portkey 网关日志目录路径，系统将从中读取请求/响应数据并解析 action。</p>
        <div class="input-row">
          <t-input
            v-model="gateway_log_path"
            placeholder="请输入网关日志目录的绝对路径"
            clearable
            size="large"
          />
          <t-button theme="primary" @click="saveSingle('gateway_log_path')" :loading="saving === 'gateway_log_path'">
            保存
          </t-button>
        </div>
        <div v-if="pathStatus.gateway_log_path" class="path-status">
          <t-tag :theme="pathStatus.gateway_log_path === 'ok' ? 'success' : 'warning'" variant="light" size="small">
            {{ pathStatus.gateway_log_path === 'ok' ? '路径有效' : '路径不存在或不可读' }}
          </t-tag>
        </div>
      </div>

      <t-divider />

      <div class="form-group">
        <label class="form-label">OpenClaw 根文件夹</label>
        <p class="form-hint">指定 OpenClaw 的根文件夹路径，系统将访问其下的 agents/sessions 等日志文件。</p>
        <div class="input-row">
          <t-input
            v-model="openclaw_root"
            placeholder="请输入 OpenClaw 根文件夹的绝对路径"
            clearable
            size="large"
          />
          <t-button theme="primary" @click="saveSingle('openclaw_root')" :loading="saving === 'openclaw_root'">
            保存
          </t-button>
        </div>
        <div v-if="pathStatus.openclaw_root" class="path-status">
          <t-tag :theme="pathStatus.openclaw_root === 'ok' ? 'success' : 'warning'" variant="light" size="small">
            {{ pathStatus.openclaw_root === 'ok' ? '路径有效' : '路径不存在或不可读' }}
          </t-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"

const gateway_log_path = ref("")
const openclaw_root = ref("")
const saving = ref("")
const pathStatus = ref({})
const monitorRunning = ref(false)
const controlling = ref(false)

onMounted(() => {
  loadConfig()
  checkStatus()
})

async function loadConfig() {
  try {
    const r = await fetch("/api/monitor/config")
    const j = await r.json()
    if (j.ok) {
      const d = j.data
      gateway_log_path.value = d.gateway_log_path || ""
      openclaw_root.value = d.openclaw_root || ""
      pathStatus.value = d._path_status || {}
    }
  } catch {}
}

async function checkStatus() {
  try {
    const r = await fetch("/api/monitor/status")
    const j = await r.json()
    if (j.ok) monitorRunning.value = j.data.running
  } catch {}
}

async function startMonitor() {
  controlling.value = true
  try {
    const r = await fetch("/api/monitor/start", { method: "POST" })
    const j = await r.json()
    if (j.ok) {
      MessagePlugin.success(j.message || "监控已启动")
      monitorRunning.value = true
    } else {
      MessagePlugin.error(j.error || "启动失败")
    }
  } catch { MessagePlugin.error("网络错误") }
  finally { controlling.value = false }
}

async function stopMonitor() {
  controlling.value = true
  try {
    const r = await fetch("/api/monitor/stop", { method: "POST" })
    const j = await r.json()
    if (j.ok) {
      MessagePlugin.success(j.message || "监控已停止")
      monitorRunning.value = false
    } else {
      MessagePlugin.error(j.error || "停止失败")
    }
  } catch { MessagePlugin.error("网络错误") }
  finally { controlling.value = false }
}

async function saveSingle(key) {
  saving.value = key
  const valueMap = {
    gateway_log_path: gateway_log_path.value,
    openclaw_root: openclaw_root.value,
  }
  try {
    const r = await fetch("/api/monitor/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, value: valueMap[key] })
    })
    const j = await r.json()
    if (j.ok) {
      MessagePlugin.success("已保存")
      if (j.data && j.data.path_valid !== undefined) {
        pathStatus.value[key] = j.data.path_valid ? "ok" : "invalid"
      }
    } else {
      MessagePlugin.error(j.error || "保存失败")
    }
  } catch { MessagePlugin.error("网络错误") }
  finally { saving.value = "" }
}
</script>

<style scoped>
.config-tab { max-width: 720px; margin: 0 auto; padding-top: 20px; }

/* Control Card */
.control-card {
  position: relative;
  border-radius: 16px;
  padding: 32px;
  margin-bottom: 24px;
  overflow: hidden;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
  border: 1px solid rgba(255,255,255,0.08);
  box-shadow: 0 8px 32px rgba(0,0,0,0.2);
  display: flex;
  align-items: center;
  gap: 28px;
  transition: all 0.4s ease;
}
.control-card.active {
  background: linear-gradient(135deg, #0a2e1a 0%, #0d3d23 50%, #0f5132 100%);
  border-color: rgba(0,200,143,0.2);
  box-shadow: 0 8px 32px rgba(0,168,112,0.15);
}
.control-bg {
  position: relative;
  flex-shrink: 0;
}
.shield-icon {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255,255,255,0.06);
  border: 2px solid rgba(255,255,255,0.12);
  color: rgba(255,255,255,0.5);
  transition: all 0.4s ease;
}
.shield-icon.active {
  background: rgba(0,200,143,0.15);
  border-color: rgba(0,200,143,0.4);
  color: #00c48f;
  box-shadow: 0 0 20px rgba(0,200,143,0.2);
}
.pulse-ring {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 72px;
  height: 72px;
  border-radius: 50%;
  border: 2px solid rgba(0,200,143,0.4);
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
  0% { transform: translate(-50%, -50%) scale(1); opacity: 1; }
  100% { transform: translate(-50%, -50%) scale(1.6); opacity: 0; }
}
.control-content { flex: 1; }
.control-title {
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 6px;
}
.control-desc {
  font-size: 13px;
  color: rgba(255,255,255,0.6);
  margin-bottom: 18px;
  line-height: 1.5;
}
.control-actions {
  display: flex;
  gap: 12px;
}

/* Section Card */
.section-card {
  background: #fff;
  border-radius: 14px;
  border: 1px solid #e8ecf0;
  padding: 28px 32px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.03);
  margin-bottom: 20px;
}
.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 600;
  color: #333;
  margin-bottom: 6px;
}
.section-desc {
  font-size: 13px;
  color: #999;
  margin-bottom: 20px;
}
.form-group { margin-bottom: 4px; }
.form-label { display: block; font-size: 14px; font-weight: 500; color: #333; margin-bottom: 4px; }
.form-hint { font-size: 12px; color: #999; margin-bottom: 10px; }
.input-row { display: flex; gap: 10px; align-items: center; }
.path-status { margin-top: 8px; }
</style>
