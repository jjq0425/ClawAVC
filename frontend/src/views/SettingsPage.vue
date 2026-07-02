<template>
  <div class="settings-page">
    <h2>平台管理</h2>

    <!-- Session Info -->
    <div class="mgmt-card">
      <div class="card-title">会话状态</div>
      <div class="setting-row">
        <div class="setting-label">
          <span>登录状态</span>
          <span class="setting-desc">清除后需重新输入入门口令</span>
        </div>
        <div class="setting-value">
          <t-tag theme="success" variant="light" size="small">已登录</t-tag>
          <t-button theme="danger" variant="text" size="small" @click="clearLogin">清除</t-button>
        </div>
      </div>
      <div class="setting-row">
        <div class="setting-label">
          <span>特权状态</span>
          <span class="setting-desc">特权会话有效期内免重复验证</span>
        </div>
        <div class="setting-value">
          <PrivilegeStatus hint="未验证" @unlock="showPrivDialog = true" />
          <t-button v-if="adminValid" theme="danger" variant="text" size="small" @click="clearAdmin">清除</t-button>
        </div>
      </div>
    </div>

    <!-- Privileged Settings -->
    <div class="mgmt-card">
      <div class="card-title">系统配置</div>

      <!-- Secret Key -->
      <div class="setting-row" :class="{ locked: !adminValid }">
        <div class="setting-left">
          <div v-if="!adminValid" class="lock-icon">
            <t-icon name="lock-on" size="16px" />
          </div>
          <div class="setting-label">
            <span>入门口令</span>
            <span class="setting-desc">用户访问系统时需要输入的密钥</span>
          </div>
        </div>
        <div class="setting-value">
          <t-input
            v-model="secretKey"
            :type="showSecret ? 'text' : 'password'"
            size="medium"
            style="width: 180px;"
            :disabled="!adminValid"
            placeholder="输入新口令"
          >
            <template #suffix-icon>
              <t-icon :name="showSecret ? 'browse' : 'browse-off'" style="cursor:pointer;" @click="showSecret = !showSecret" />
            </template>
          </t-input>
          <t-button theme="primary" size="small" :disabled="!adminValid || !secretKey.trim()" @click="saveSecretKey" :loading="saving">
            保存
          </t-button>
        </div>
      </div>

      <!-- Round Update Time Limit -->
      <div class="setting-row" :class="{ locked: !adminValid }">
        <div class="setting-left">
          <div v-if="!adminValid" class="lock-icon">
            <t-icon name="lock-on" size="16px" />
          </div>
          <div class="setting-label">
            <span>Round更新时间限制</span>
            <span class="setting-desc">开启后，API修改Round数据将限制在15分钟内，超过15分钟需前往数据运维页面修改</span>
          </div>
        </div>
        <div class="setting-value">
          <t-switch v-model="roundUpdateTimeLimitEnabled" :disabled="!adminValid" @change="saveRoundUpdateTimeLimit" />
          <span class="switch-label">{{ roundUpdateTimeLimitEnabled ? '已启用' : '已禁用' }}</span>
        </div>
      </div>

      <!-- Intercept Non-IR Tools 开关已迁移至「安全拦截」页面 -->

      <!-- 清空 API Trace -->
      <div class="setting-row" :class="{ locked: !adminValid }">
        <div class="setting-left">
          <div v-if="!adminValid" class="lock-icon">
            <t-icon name="lock-on" size="16px" />
          </div>
          <div class="setting-label">
            <span>清空 API 追踪记录</span>
            <span class="setting-desc">清空 api_trace 表的所有请求记录</span>
          </div>
        </div>
        <div class="setting-value">
          <t-popconfirm content="确定要清空所有 API 追踪记录吗？此操作不可撤销。" @confirm="clearApiTrace">
            <t-button theme="danger" size="small" :disabled="!adminValid" :loading="clearingTrace">
              清空
            </t-button>
          </t-popconfirm>
        </div>
      </div>

      <!-- 清空后端日志 -->
      <div class="setting-row" :class="{ locked: !adminValid }">
        <div class="setting-left">
          <div v-if="!adminValid" class="lock-icon">
            <t-icon name="lock-on" size="16px" />
          </div>
          <div class="setting-label">
            <span>清空后端日志</span>
            <span class="setting-desc">清空 logs/backend.log 文件内容</span>
          </div>
        </div>
        <div class="setting-value">
          <t-popconfirm content="确定要清空后端日志吗？此操作不可撤销。" @confirm="clearBackendLog">
            <t-button theme="danger" size="small" :disabled="!adminValid" :loading="clearingBackendLog">
              清空
            </t-button>
          </t-popconfirm>
        </div>
      </div>

      <!-- 清空前端日志 -->
      <div class="setting-row" :class="{ locked: !adminValid }">
        <div class="setting-left">
          <div v-if="!adminValid" class="lock-icon">
            <t-icon name="lock-on" size="16px" />
          </div>
          <div class="setting-label">
            <span>清空前端日志</span>
            <span class="setting-desc">清空 logs/frontend.log 文件内容</span>
          </div>
        </div>
        <div class="setting-value">
          <t-popconfirm content="确定要清空前端日志吗？此操作不可撤销。" @confirm="clearFrontendLog">
            <t-button theme="danger" size="small" :disabled="!adminValid" :loading="clearingFrontendLog">
              清空
            </t-button>
          </t-popconfirm>
        </div>
      </div>

      <!-- Unlock hint -->
      <div v-if="!adminValid" style="margin-top: 12px;">
        <PrivilegeStatus hint="以上配置项需要特权密钥" @unlock="showPrivDialog = true" />
      </div>
    </div>

    <!-- Info -->
    <div class="mgmt-card info">
      <div class="card-title">说明</div>
      <div class="info-list">
        <div class="info-item">
          <t-icon name="info-circle" size="16px" style="color: #0052D9;" />
          <span>入门口令由特权用户配置，修改后已登录用户需重新验证</span>
        </div>
        <div class="info-item">
          <t-icon name="info-circle" size="16px" style="color: #ED7B2F;" />
          <span>特权密钥不可通过界面修改，会话默认 20 分钟有效</span>
        </div>
        <div class="info-item">
          <t-icon name="info-circle" size="16px" style="color: #ED7B2F;" />
          <span>部分操作（如修改入门口令、数据库写入、模型配置变更）需要特权验证，以防误操作。如有需要请联系平台管理员</span>
        </div>
      </div>
    </div>

    <!-- Privilege Dialog -->
    <PrivilegeDialog v-model="showPrivDialog" @success="onPrivSuccess" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue"
import { useRouter } from "vue-router"
import { MessagePlugin } from "tdesign-vue-next"
import PrivilegeDialog from "../components/PrivilegeDialog.vue"
import PrivilegeStatus from "../components/PrivilegeStatus.vue"

const router = useRouter()
const showPrivDialog = ref(false)
const secretKey = ref("")
const showSecret = ref(false)
const saving = ref(false)
const roundUpdateTimeLimitEnabled = ref(true)

const adminSession = ref("")
const adminExpiry = ref(0)
const tick = ref(0)
let _timer = null
const clearingTrace = ref(false)

const adminValid = computed(() => {
  void tick.value
  const s = sessionStorage.getItem("clawavc_admin_session")
  const e = Number(sessionStorage.getItem("clawavc_admin_expiry") || 0)
  return !!s && Date.now() < e
})

const clearingBackendLog = ref(false)
const clearingFrontendLog = ref(false)

onMounted(() => {
  const saved = sessionStorage.getItem("clawavc_admin_session")
  const savedExpiry = sessionStorage.getItem("clawavc_admin_expiry")
  if (saved && savedExpiry && Date.now() < Number(savedExpiry)) {
    adminSession.value = saved
    adminExpiry.value = Number(savedExpiry)
  }
  _timer = setInterval(() => { tick.value++ }, 1000)
  
  // 加载Round更新时间限制开关状态
  loadRoundUpdateTimeLimit()
})

onUnmounted(() => { clearInterval(_timer) })

function onPrivSuccess(token) {
  adminSession.value = token
  adminExpiry.value = Number(sessionStorage.getItem("clawavc_admin_expiry"))
}

function clearLogin() {
  sessionStorage.removeItem("clawavc_verified_key")
  MessagePlugin.success("登录状态已清除")
  router.replace("/login")
}

function clearAdmin() {
  adminSession.value = ""
  adminExpiry.value = 0
  sessionStorage.removeItem("clawavc_admin_session")
  sessionStorage.removeItem("clawavc_admin_expiry")
  MessagePlugin.success("特权状态已清除")
}

async function saveSecretKey() {
  saving.value = true
  try {
    const res = await fetch("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Admin-Session": adminSession.value },
      body: JSON.stringify({ secret_key: secretKey.value.trim() }),
    })
    const json = await res.json()
    if (json.ok) {
      MessagePlugin.success("入门口令已更新")
      sessionStorage.setItem("clawavc_verified_key", secretKey.value.trim())
    } else MessagePlugin.error(json.error || "保存失败")
  } catch (e) { MessagePlugin.error("连接失败") }
  saving.value = false
}

async function loadRoundUpdateTimeLimit() {
  try {
    const res = await fetch("/api/config/round_update_time_limit")
    const json = await res.json()
    if (json.ok) {
      roundUpdateTimeLimitEnabled.value = json.data.enabled
    }
  } catch (e) { console.error("加载Round更新时间限制状态失败:", e) }
}

async function saveRoundUpdateTimeLimit() {
  try {
    const res = await fetch("/api/config/round_update_time_limit", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Admin-Session": adminSession.value },
      body: JSON.stringify({ enabled: roundUpdateTimeLimitEnabled.value }),
    })
    const json = await res.json()
    if (json.ok) {
      MessagePlugin.success(`Round更新时间限制已${roundUpdateTimeLimitEnabled.value ? '启用' : '禁用'}`)
    } else {
      MessagePlugin.error(json.error || "保存失败")
      // 恢复原状态
      roundUpdateTimeLimitEnabled.value = !roundUpdateTimeLimitEnabled.value
    }
  } catch (e) {
    MessagePlugin.error("连接失败")
    roundUpdateTimeLimitEnabled.value = !roundUpdateTimeLimitEnabled.value
  }
}

async function clearApiTrace() {
  clearingTrace.value = true
  try {
    const res = await fetch("/api/trace/clear", {
      method: "DELETE",
      headers: { "Content-Type": "application/json", "X-Admin-Session": adminSession.value },
    })
    const json = await res.json()
    if (json.ok) {
      const deleted = json.data?.deleted || 0
      MessagePlugin.success(`已清空 ${deleted} 条 API 追踪记录`)
    } else {
      MessagePlugin.error(json.error || "清空失败")
    }
  } catch (e) {
    MessagePlugin.error("连接失败")
  }
  clearingTrace.value = false
}

async function clearBackendLog() {
  clearingBackendLog.value = true
  try {
    const res = await fetch("/api/logs/clear-backend", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Admin-Session": adminSession.value },
    })
    const json = await res.json()
    if (json.ok) {
      MessagePlugin.success("后端日志已清空")
    } else {
      MessagePlugin.error(json.error || "清空失败")
    }
  } catch (e) {
    MessagePlugin.error("连接失败")
  }
  clearingBackendLog.value = false
}

async function clearFrontendLog() {
  clearingFrontendLog.value = true
  try {
    const res = await fetch("/api/logs/clear-frontend", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Admin-Session": adminSession.value },
    })
    const json = await res.json()
    if (json.ok) {
      MessagePlugin.success("前端日志已清空")
    } else {
      MessagePlugin.error(json.error || "清空失败")
    }
  } catch (e) {
    MessagePlugin.error("连接失败")
  }
  clearingFrontendLog.value = false
}
</script>

<style scoped>
.settings-page { max-width: 700px; margin: 0 auto; }
.settings-page h2 { font-size: 20px; font-weight: 600; margin-bottom: 24px; color: #333; }
.mgmt-card { background: #fff; border-radius: 12px; padding: 22px 24px; border: 1px solid #eee; margin-bottom: 16px; }
.mgmt-card.info { background: #f9fafb; }
.card-title { font-size: 14px; font-weight: 600; color: #333; margin-bottom: 14px; }
.setting-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 0; border-top: 1px solid #f5f5f5;
  transition: opacity 0.2s;
}
.setting-row.locked { opacity: 0.5; }
.setting-left { display: flex; align-items: center; gap: 10px; }
.lock-icon { color: #ED7B2F; display: flex; }
.setting-label span { display: block; }
.setting-label span:first-child { font-size: 14px; color: #333; font-weight: 500; }
.setting-desc { font-size: 12px; color: #999; margin-top: 2px; }
.setting-value { display: flex; align-items: center; gap: 8px; }
.unlock-hint {
  display: flex; align-items: center; gap: 6px;
  margin-top: 12px; padding: 10px 14px;
  background: #fffbf5; border: 1px dashed #ffe0c2; border-radius: 8px;
  font-size: 13px; color: #ED7B2F; cursor: pointer;
  transition: background 0.2s;
}
.unlock-hint:hover { background: #fff5ea; }
.info-list { display: flex; flex-direction: column; gap: 8px; }
.info-item { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #666; }
.switch-label { font-size: 13px; color: #666; }
</style>
