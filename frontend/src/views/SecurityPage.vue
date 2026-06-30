<template>
  <div class="security-page">
    <h2>安全拦截</h2>

    <!-- 开关卡片 -->
    <div class="mgmt-card">
      <div class="card-title">
        <span>拦截策略</span>
        <span class="card-sub">portkey 网关将依据 IR 翻译结果，对本轮 user_query 的 tool_calls 进行白名单校验</span>
      </div>

      <div class="setting-row" :class="{ locked: !adminValid }">
        <div class="setting-left">
          <div v-if="!adminValid" class="lock-icon">
            <t-icon name="lock-on" size="16px" />
          </div>
          <div class="setting-label">
            <span>拦截 IR 外工具</span>
            <span class="setting-desc">
              开启后，portkey 网关在收到上游 LLM 返回的 tool_calls 时，会同步等待本轮 IR 翻译完成，
              并仅放行 IR 白名单内的工具；非白名单工具会被替换为系统提示，并将拦截事件上报至此页面。
              同一 turn（user_query）共享同一份 IR。
            </span>
          </div>
        </div>
        <div class="setting-value">
          <t-switch v-model="interceptEnabled" :disabled="!adminValid" @change="saveInterceptSwitch" />
          <span class="switch-label">{{ interceptEnabled ? '已启用' : '已禁用' }}</span>
        </div>
      </div>

      <div class="setting-row" :class="{ locked: !adminValid }">
        <div class="setting-left">
          <div v-if="!adminValid" class="lock-icon">
            <t-icon name="lock-on" size="16px" />
          </div>
          <div class="setting-label">
            <span>死循环熔断</span>
            <span class="setting-desc">
              开启后，当同一 turn 内对同名同参 tool_call 累计调用达到阈值（默认 3 次，含本次）时，
              portkey 网关将跳过 retry，直接合成"loop break"拒绝文本流，强制 Agent 改用自然语言
              回答用户原始问题。用于防御"白名单工具反复无效返回"场景。
            </span>
          </div>
        </div>
        <div class="setting-value loop-breaker-value">
          <t-switch v-model="loopBreakerEnabled" :disabled="!adminValid" @change="saveLoopBreakerSwitch" />
          <span class="switch-label">{{ loopBreakerEnabled ? '已启用' : '已禁用' }}</span>
          <t-input-number
            v-model="loopBreakerThreshold"
            :min="2"
            :max="50"
            :step="1"
            size="small"
            :disabled="!adminValid || !loopBreakerEnabled"
            style="width: 96px; margin-left: 12px;"
            @blur="saveLoopBreakerThreshold"
            @change="onLoopBreakerThresholdChange"
          />
          <span class="switch-label">次熔断</span>
        </div>
      </div>

      <div class="setting-row" :class="{ locked: !adminValid }">
        <div class="setting-left">
          <div v-if="!adminValid" class="lock-icon">
            <t-icon name="lock-on" size="16px" />
          </div>
          <div class="setting-label">
            <span>IR 长轮询超时</span>
            <span class="setting-desc">
              portkey 网关每次请求 <code>/api/translator/turn-ir</code> 时，clawAVC 会先等待 watcher
              异步翻译完成；若 watcher 漏触发或耗时过长，等到本超时后会本端 fallback 调一次 translate
              作为兜底，仍失败则放行 + 上报 ir_timeout 事件。范围 5 ~ 1800 秒，默认 300 秒（5 分钟）。
            </span>
          </div>
        </div>
        <div class="setting-value loop-breaker-value">
          <t-input-number
            v-model="turnIrWaitSec"
            :min="5"
            :max="1800"
            :step="10"
            size="small"
            :disabled="!adminValid"
            style="width: 120px;"
            @blur="saveTurnIrWaitSec"
            @change="onTurnIrWaitSecChange"
          />
          <span class="switch-label">秒</span>
        </div>
      </div>

      <div v-if="!adminValid" style="margin-top: 12px;">
        <PrivilegeStatus hint="切换开关需要特权密钥" @unlock="showPrivDialog = true" />
      </div>
    </div>

    <!-- 数据流说明 -->
    <div class="mgmt-card info">
      <div class="card-title"><span>拦截链路</span></div>
      <ol class="flow-list">
        <li>Agent 请求经 portkey 网关转发至上游 LLM</li>
        <li>LLM 返回含 <code>tool_calls</code>/<code>tool_use</code> 时，网关同步请求 clawAVC 的 <code>/api/translator/turn-ir</code></li>
        <li>clawAVC 按 <code>turn_key</code> 缓存翻译结果（同一 turn 复用），返回 <code>allowed_tools</code> 白名单</li>
        <li>网关重写非白名单工具调用为系统提示，并 POST 上报至 <code>/api/intercept/events</code></li>
        <li>本页通过 SocketIO 实时刷新拦截事件</li>
      </ol>
    </div>

    <!-- 事件流 -->
    <div class="mgmt-card">
      <div class="card-title row-between">
        <div class="title-left">
          <span>拦截事件</span>
          <t-tag theme="primary" variant="light" size="small">{{ totalCount }}</t-tag>
          <t-tag v-if="liveDot" theme="success" variant="light" size="small">实时</t-tag>
        </div>
        <div class="title-actions">
          <t-input v-model="filterTool" placeholder="按工具名过滤" size="small" style="width: 160px;" clearable />
          <t-button size="small" variant="outline" @click="refresh">刷新</t-button>
          <t-button size="small" theme="danger" variant="outline" :disabled="!adminValid || items.length === 0" @click="clearAll">清空</t-button>
        </div>
      </div>

      <t-table
        :data="filteredItems"
        :columns="columns"
        row-key="id"
        size="small"
        :pagination="pagination"
        :hover="true"
        :empty="emptyText"
      >
        <template #received_at="{ row }">
          <span class="mono">{{ row ? formatTime(row.received_at) : '' }}</span>
        </template>
        <template #event_type="{ row }">
          <t-tag
            v-if="row"
            :theme="row.event_type === 'ir_loop_break' ? 'danger' : (row.event_type === 'ir_tool_block' ? 'warning' : 'default')"
            variant="light"
            size="small"
          >
            {{ row.event_type }}
          </t-tag>
        </template>
        <template #protocol="{ row }">
          <t-tag v-if="row" theme="primary" variant="outline" size="small">{{ row.protocol || '-' }}</t-tag>
        </template>
        <template #violations="{ row }">
          <div v-if="row" class="tag-row">
            <t-tag
              v-for="(v, i) in (row.violations || [])"
              :key="i"
              theme="danger"
              variant="light"
              size="small"
            >{{ v }}</t-tag>
          </div>
        </template>
        <template #allowed_tools="{ row }">
          <div v-if="row" class="tag-row">
            <t-tag
              v-for="(v, i) in (row.allowed_tools || []).slice(0, 6)"
              :key="i"
              theme="success"
              variant="light"
              size="small"
            >{{ v }}</t-tag>
            <span v-if="(row.allowed_tools || []).length > 6" class="more-hint">+{{ row.allowed_tools.length - 6 }}</span>
          </div>
        </template>
        <template #user_query="{ row }">
          <div v-if="row" class="query-cell" :title="row.user_query || ''">{{ row.user_query || '-' }}</div>
        </template>
        <template #turn_key="{ row }">
          <code v-if="row" class="mono small">{{ row.turn_key || '-' }}</code>
        </template>
        <template #note="{ row }">
          <div v-if="row" class="note-cell" :title="row.note || ''">{{ row.note || '-' }}</div>
        </template>
      </t-table>
    </div>

    <PrivilegeDialog v-model="showPrivDialog" @success="onPrivSuccess" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue"
import { MessagePlugin, DialogPlugin } from "tdesign-vue-next"
import PrivilegeDialog from "../components/PrivilegeDialog.vue"
import PrivilegeStatus from "../components/PrivilegeStatus.vue"
import { socket } from "../utils/socket.js"

// ─── 开关 ───────────────────────────────────────────────
const interceptEnabled = ref(false)
// 监控数据源是否为"从网关获取"（拦截 IR 外工具依赖此条件）
const useGatewayDataSource = ref(false)
// 死循环熔断
const loopBreakerEnabled = ref(true)
const loopBreakerThreshold = ref(3)
let _loopBreakerSavedThreshold = 3
// IR 长轮询超时（秒；DB 配置存毫秒，前端展示秒）
const turnIrWaitSec = ref(300)
let _turnIrWaitSecSaved = 300
const showPrivDialog = ref(false)
const adminSession = ref("")
const tick = ref(0)
let _timer = null

const adminValid = computed(() => {
  void tick.value
  const s = sessionStorage.getItem("clawavc_admin_session")
  const e = Number(sessionStorage.getItem("clawavc_admin_expiry") || 0)
  return !!s && Date.now() < e
})

function onPrivSuccess(token) {
  adminSession.value = token
}

async function loadSwitch() {
  try {
    const res = await fetch("/api/config/intercept_non_ir_tools")
    const json = await res.json()
    if (json.ok) interceptEnabled.value = !!json.data.enabled
  } catch (e) { console.error("加载开关状态失败:", e) }
}

async function loadDataSource() {
  try {
    const r = await fetch("/api/monitor/config")
    const j = await r.json()
    if (j.ok) {
      useGatewayDataSource.value = j.data?.use_gateway === "true"
    }
  } catch (e) { console.error("加载监控数据源失败:", e) }
}

async function saveInterceptSwitch() {
  // 开启拦截前刷新一次数据源状态；若非"从网关获取"则提示但不阻断
  if (interceptEnabled.value) {
    await loadDataSource()
    if (!useGatewayDataSource.value) {
      const dlg = DialogPlugin.alert({
        header: "提示：拦截依赖网关数据源",
        body: '当前"交互数据来源"未选择"从网关获取"，IR 外工具拦截功能依赖 portkey 网关链路才能生效。\n\n开关仍可启用，但实际不会拦截任何工具调用。建议前往「运行监控 → 配置」将数据源切换为"从网关获取"后再启用。',
        confirmBtn: "我知道了",
        theme: "warning",
        onConfirm: () => { dlg.destroy() },
        onClose: () => { dlg.destroy() },
      })
    }
  }
  try {
    const res = await fetch("/api/config/intercept_non_ir_tools", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Admin-Session": adminSession.value },
      body: JSON.stringify({ enabled: interceptEnabled.value }),
    })
    const json = await res.json()
    if (json.ok) {
      MessagePlugin.success(`IR 外工具拦截已${interceptEnabled.value ? '启用' : '禁用'}`)
    } else {
      MessagePlugin.error(json.error || "保存失败")
      interceptEnabled.value = !interceptEnabled.value
    }
  } catch (e) {
    MessagePlugin.error("连接失败")
    interceptEnabled.value = !interceptEnabled.value
  }
}

// ─── 死循环熔断开关 ─────────────────────────────────────
async function loadLoopBreaker() {
  try {
    const res = await fetch("/api/config/loop_breaker")
    const json = await res.json()
    if (json.ok) {
      loopBreakerEnabled.value = !!json.data.enabled
      const t = Number(json.data.threshold) || 3
      loopBreakerThreshold.value = t
      _loopBreakerSavedThreshold = t
    }
  } catch (e) { console.error("加载熔断配置失败:", e) }
}

async function _putLoopBreaker(enabled, threshold) {
  const res = await fetch("/api/config/loop_breaker", {
    method: "PUT",
    headers: { "Content-Type": "application/json", "X-Admin-Session": adminSession.value },
    body: JSON.stringify({ enabled, threshold }),
  })
  const json = await res.json()
  if (json.ok) {
    loopBreakerEnabled.value = !!json.data.enabled
    loopBreakerThreshold.value = Number(json.data.threshold) || 3
    _loopBreakerSavedThreshold = loopBreakerThreshold.value
    return true
  }
  MessagePlugin.error(json.error || "保存失败")
  return false
}

async function saveLoopBreakerSwitch() {
  const prev = !loopBreakerEnabled.value
  try {
    const ok = await _putLoopBreaker(loopBreakerEnabled.value, loopBreakerThreshold.value)
    if (ok) {
      MessagePlugin.success(`死循环熔断已${loopBreakerEnabled.value ? '启用' : '禁用'}`)
    } else {
      loopBreakerEnabled.value = prev
    }
  } catch (e) {
    MessagePlugin.error("连接失败")
    loopBreakerEnabled.value = prev
  }
}

function onLoopBreakerThresholdChange(v) {
  // t-input-number @change 在每次步进都触发，避免单次按下连发多次后端写入：
  // 仅当变化值与已保存值不同时记入 pending，真正落库在 blur 触发
  if (typeof v === "number" && !Number.isNaN(v)) {
    loopBreakerThreshold.value = Math.max(2, Math.min(50, Math.round(v)))
  }
}

async function saveLoopBreakerThreshold() {
  if (!adminValid.value) return
  if (!loopBreakerEnabled.value) return
  const t = Math.max(2, Math.min(50, Math.round(Number(loopBreakerThreshold.value) || 3)))
  if (t === _loopBreakerSavedThreshold) return
  try {
    const ok = await _putLoopBreaker(loopBreakerEnabled.value, t)
    if (ok) {
      MessagePlugin.success(`熔断阈值已更新为 ${t} 次`)
    } else {
      loopBreakerThreshold.value = _loopBreakerSavedThreshold
    }
  } catch (e) {
    MessagePlugin.error("连接失败")
    loopBreakerThreshold.value = _loopBreakerSavedThreshold
  }
}

// ─── IR 长轮询超时配置 ─────────────────────────────────
async function loadTurnIrWaitMs() {
  try {
    const res = await fetch("/api/config/turn_ir_wait_ms")
    const json = await res.json()
    if (json.ok && json.data) {
      const sec = Math.max(5, Math.min(1800, Math.round((Number(json.data.wait_ms) || 300000) / 1000)))
      turnIrWaitSec.value = sec
      _turnIrWaitSecSaved = sec
    }
  } catch (e) { console.error("加载长轮询超时配置失败:", e) }
}

function onTurnIrWaitSecChange(v) {
  if (typeof v === "number" && !Number.isNaN(v)) {
    turnIrWaitSec.value = Math.max(5, Math.min(1800, Math.round(v)))
  }
}

async function saveTurnIrWaitSec() {
  if (!adminValid.value) return
  const sec = Math.max(5, Math.min(1800, Math.round(Number(turnIrWaitSec.value) || 300)))
  if (sec === _turnIrWaitSecSaved) return
  try {
    const res = await fetch("/api/config/turn_ir_wait_ms", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Admin-Session": adminSession.value },
      body: JSON.stringify({ wait_ms: sec * 1000 }),
    })
    const json = await res.json()
    if (json.ok) {
      const newSec = Math.round((Number(json.data.wait_ms) || sec * 1000) / 1000)
      turnIrWaitSec.value = newSec
      _turnIrWaitSecSaved = newSec
      MessagePlugin.success(`IR 长轮询超时已更新为 ${newSec} 秒`)
    } else {
      MessagePlugin.error(json.error || "保存失败")
      turnIrWaitSec.value = _turnIrWaitSecSaved
    }
  } catch (e) {
    MessagePlugin.error("连接失败")
    turnIrWaitSec.value = _turnIrWaitSecSaved
  }
}

// ─── 事件流 ────────────────────────────────────────────
const items = ref([])
const totalCount = ref(0)
const filterTool = ref("")
const liveDot = ref(false)
let _liveTimer = null

const pagination = {
  defaultCurrent: 1,
  defaultPageSize: 20,
  pageSizeOptions: [10, 20, 50, 100],
  showJumper: true,
}

const columns = [
  { colKey: "received_at", title: "时间", width: 170, ellipsis: true },
  { colKey: "event_type", title: "类型", width: 130 },
  { colKey: "protocol", title: "协议", width: 90 },
  { colKey: "violations", title: "被拦截工具", width: 200 },
  { colKey: "allowed_tools", title: "本轮白名单", width: 260 },
  { colKey: "user_query", title: "user_query", minWidth: 220, ellipsis: true },
  { colKey: "turn_key", title: "turn_key", width: 110 },
  { colKey: "note", title: "备注", minWidth: 200, ellipsis: true },
]

const filteredItems = computed(() => {
  const kw = filterTool.value.trim().toLowerCase()
  if (!kw) return items.value
  return items.value.filter(it => {
    const v = (it.violations || []).some(x => String(x).toLowerCase().includes(kw))
    const a = (it.allowed_tools || []).some(x => String(x).toLowerCase().includes(kw))
    return v || a
  })
})

const emptyText = computed(() =>
  interceptEnabled.value
    ? "暂无拦截事件，等待网关上报…"
    : "拦截开关未启用，开启后将在此显示被网关拒绝的工具调用"
)

function formatTime(s) {
  if (!s) return "-"
  // 后端返回 sqlite CURRENT_TIMESTAMP（UTC，无时区），补 Z 让浏览器按本地时区显示
  const ts = /Z|[+-]\d{2}:?\d{2}$/.test(s) ? s : s.replace(" ", "T") + "Z"
  const d = new Date(ts)
  if (isNaN(d.getTime())) return s
  return d.toLocaleString()
}

async function fetchEvents() {
  try {
    const res = await fetch("/api/intercept/events?limit=200")
    const json = await res.json()
    if (json.ok) {
      items.value = json.data.items || []
      totalCount.value = json.data.total || items.value.length
    }
  } catch (e) {
    console.error("加载拦截事件失败:", e)
  }
}

async function refresh() {
  await fetchEvents()
  MessagePlugin.success("已刷新")
}

async function clearAll() {
  if (!adminValid.value) { MessagePlugin.warning("需要特权验证"); return }
  if (!confirm("确认清空所有拦截事件？此操作不可恢复")) return
  try {
    const res = await fetch("/api/intercept/events", {
      method: "DELETE",
      headers: { "X-Admin-Session": adminSession.value },
    })
    const json = await res.json()
    if (json.ok) {
      items.value = []
      totalCount.value = 0
      MessagePlugin.success("已清空")
    } else {
      MessagePlugin.error(json.error || "清空失败")
    }
  } catch (e) {
    MessagePlugin.error("连接失败")
  }
}

function onInterceptEvent(payload) {
  if (!payload || !payload.id) return
  // 去重：可能因刷新顺序短时间内重复
  if (items.value.find(it => it.id === payload.id)) return
  items.value.unshift(payload)
  totalCount.value += 1
  // 实时标识闪一下
  liveDot.value = true
  if (_liveTimer) clearTimeout(_liveTimer)
  _liveTimer = setTimeout(() => { liveDot.value = false }, 1500)
}

onMounted(() => {
  const saved = sessionStorage.getItem("clawavc_admin_session")
  const savedExpiry = sessionStorage.getItem("clawavc_admin_expiry")
  if (saved && savedExpiry && Date.now() < Number(savedExpiry)) {
    adminSession.value = saved
  }
  _timer = setInterval(() => { tick.value++ }, 1000)

  loadSwitch()
  loadLoopBreaker()
  loadTurnIrWaitMs()
  loadDataSource()
  fetchEvents()
  socket.on("intercept_event", onInterceptEvent)
})

onUnmounted(() => {
  clearInterval(_timer)
  if (_liveTimer) clearTimeout(_liveTimer)
  socket.off("intercept_event", onInterceptEvent)
})
</script>

<style scoped>
.security-page { max-width: 1100px; margin: 0 auto; }
.security-page h2 { font-size: 20px; font-weight: 600; margin-bottom: 24px; color: #333; }

.mgmt-card { background: #fff; border-radius: 12px; padding: 22px 24px; border: 1px solid #eee; margin-bottom: 16px; }
.mgmt-card.info { background: #f9fafb; }
.card-title { font-size: 14px; font-weight: 600; color: #333; margin-bottom: 14px; display: flex; align-items: center; gap: 10px; }
.card-title.row-between { justify-content: space-between; }
.card-sub { font-size: 12px; color: #999; font-weight: 400; }
.title-left { display: flex; align-items: center; gap: 8px; }
.title-actions { display: flex; align-items: center; gap: 8px; }

.setting-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 0; border-top: 1px solid #f5f5f5;
  transition: opacity 0.2s;
}
.setting-row.locked { opacity: 0.5; }
.setting-left { display: flex; align-items: flex-start; gap: 10px; }
.lock-icon { color: #ED7B2F; display: flex; padding-top: 2px; }
.setting-label span { display: block; }
.setting-label span:first-child { font-size: 14px; color: #333; font-weight: 500; }
.setting-desc { font-size: 12px; color: #999; margin-top: 4px; max-width: 640px; line-height: 1.6; }
.setting-value { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.switch-label { font-size: 13px; color: #666; }

.flow-list { padding-left: 22px; margin: 0; }
.flow-list li { font-size: 13px; color: #555; line-height: 2; }
.flow-list code { background: #eef2f7; padding: 1px 6px; border-radius: 4px; font-size: 12px; color: #0052D9; }

.tag-row { display: flex; flex-wrap: wrap; gap: 4px; }
.more-hint { font-size: 12px; color: #999; align-self: center; }
.query-cell { max-width: 380px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #555; font-size: 13px; }
.note-cell { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #666; font-size: 12px; }
.mono { font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace; font-size: 12px; color: #555; }
.mono.small { font-size: 11px; color: #888; }
</style>
