<template>
  <div class="replay-page">
    <div class="page-header">
      <h1>流量回放</h1>
      <p class="page-desc">选择历史 Round，以 WSS 推送方式回放，便于调试客户端或演示。</p>
    </div>

    <!-- 回放配置 -->
    <div class="section-card">
      <div class="section-header">
        <t-icon name="play-circle" size="20px" />
        <span>回放配置</span>
      </div>

      <template v-if="selectedRound">
        <div class="replay-info">
          <div class="info-item">
            <span class="info-label">Round ID</span>
            <span class="info-value mono">{{ selectedRound.round_id }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">用户查询</span>
            <span class="info-value">{{ selectedRound.user_query || '-' }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">开始时间</span>
            <span class="info-value">{{ selectedRound.time_start }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">结束时间</span>
            <span class="info-value">{{ selectedRound.time_end }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">合规得分</span>
            <t-tag :theme="selectedRound.overall_score >= 0.5 ? 'success' : 'danger'" variant="light">
              {{ selectedRound.overall_score?.toFixed(2) }}
            </t-tag>
          </div>
        </div>

        <div class="replay-options">
          <div class="option-item">
            <label>回放速度</label>
            <t-slider v-model="replaySpeed" :min="0.1" :max="2" :step="0.1" />
            <span class="option-value">{{ replaySpeed === 0.1 ? '最慢' : replaySpeed + 'x' }}</span>
          </div>
          
          <div class="option-item">
            <label>推送顺序</label>
            <t-select v-model="pushOrder" style="width: 260px">
              <t-option value="start_ir_end_kernel" label="start → ir → end → kernel" />
              <t-option value="start_end_ir_kernel" label="start → end → ir → kernel" />
              <t-option value="start_end_kernel_ir" label="start → end → kernel → ir" />
              <t-option value="start_ir_kernel_end" label="start → ir → kernel → end" />
              <t-option value="start_kernel_ir_end" label="start → kernel → ir → end" />
              <t-option value="start_kernel_end_ir" label="start → kernel → end → ir" />
              <t-option value="random" label="随机顺序" />
            </t-select>
            <span class="option-hint">start 一定最先，ir/end/kernel 可自由排列</span>
          </div>
        </div>

        <div class="replay-actions">
          <div class="action-buttons">
            <t-tooltip :content="!wsConnected ? '请先点击下方「连接」按钮，建立 WebSocket 连接' : ''" :disabled="wsConnected">
              <t-button theme="primary" size="large" @click="startReplay" :loading="replaying" :disabled="!wsConnected">
                <t-icon name="play-circle" />
                开始回放
              </t-button>
            </t-tooltip>
            <t-button v-if="replaying" theme="danger" variant="outline" size="large" @click="cancelReplay">
              <t-icon name="stop-circle" />
              停止
            </t-button>
          </div>
        </div>

        <!-- 回放进度 -->
        <div v-if="replaying" class="replay-progress">
          <t-progress :percentage="replayProgress" :status="replayStatus" :stroke-width="12" />
          <div class="progress-info">
            <span>当前阶段: {{ currentStage }}</span>
          </div>
        </div>
      </template>

      <div v-else class="empty-replay">
        <t-icon name="play-circle" size="56px" class="empty-icon" />
        <p class="empty-title">请选择要回放的 Round</p>
        <p class="empty-desc">在下方 Round 列表中点击「选择回放」，然后回到这里点击「开始回放」即可</p>
      </div>
    </div>

    <!-- WSS 连接 -->
    <div class="section-card">
      <div class="section-header">
        <t-icon name="wifi" size="20px" />
        <span>WSS 连接</span>
        <span class="conn-status" :class="{ online: wsConnected }">
          <span class="status-dot"></span>
          {{ wsConnected ? '已连接' : '未连接' }}
        </span>
      </div>
      <div class="ws-config">
        <div class="config-item">
          <label>WSS 地址</label>
          <t-input v-model="wsUrl" :disabled="wsConnected" placeholder="ws://host:15100/wss/monitor" />
        </div>
        <t-button v-if="!wsConnected" theme="primary" @click="connectWs" :loading="wsConnecting">连接</t-button>
        <t-button v-else theme="danger" variant="outline" @click="disconnectWs">断开</t-button>
      </div>
      <div v-if="wsConnected" class="ws-received">
        <div class="received-header">
          <span>收到的消息 <t-tag size="small" variant="light">{{ receivedMessages.length }}</t-tag></span>
          <t-button size="small" variant="text" @click="receivedMessages = []" v-if="receivedMessages.length">清空</t-button>
        </div>
        <div class="received-list">
          <div v-for="(msg, i) in receivedMessages" :key="i" class="received-item" :class="msg.push_type">
            <span class="msg-type">{{ msg.push_type }}</span>
            <span class="msg-time">{{ msg.time }}</span>
            <pre class="msg-body">{{ formatJson(msg) }}</pre>
          </div>
          <div v-if="receivedMessages.length === 0" class="msg-empty">等待推送...</div>
        </div>
      </div>
    </div>

    <!-- Round 选择 -->
    <div class="section-card">
      <div class="section-header">
        <t-icon name="search" size="20px" />
        <span>Round 列表</span>
        <t-button theme="default" size="small" @click="loadRounds">
          <t-icon name="refresh" />
        </t-button>
      </div>
      
      <div class="filter-row">
        <t-input
          v-model="searchQuery"
          placeholder="搜索 round_id 或用户查询"
          clearable
          style="width: 280px"
        >
          <template #prefix-icon><t-icon name="search" /></template>
        </t-input>
      </div>

      <t-table
        :data="roundList"
        :columns="columns"
        :loading="loading"
        row-key="round_id"
        hover
        stripe
        :pagination="pagination"
        @page-change="onPageChange"
      >
        <template #overall_score="{ row }">
          <t-tag :theme="row.overall_score >= 0.5 ? 'success' : 'danger'" variant="light">
            {{ row.overall_score?.toFixed(2) }}
          </t-tag>
        </template>
        <template #is_abnormal="{ row }">
          <t-tag v-if="row.is_abnormal" theme="danger" size="small">异常</t-tag>
          <span v-else class="normal-tag">正常</span>
        </template>
        <template #action="{ row }">
          <t-button 
            theme="primary" 
            variant="text" 
            size="small" 
            @click="handleSelectRound(row)"
            :disabled="replaying && selectedRound?.round_id !== row.round_id"
          >
            选择回放
          </t-button>
        </template>
      </t-table>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted, computed, onUnmounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"
import { io } from "socket.io-client"

const browserHost = typeof window !== "undefined" ? window.location.hostname : "127.0.0.1"
const defaultWsBase = (typeof window !== "undefined" ? (window.location.protocol === "https:" ? "wss://" : "ws://") + window.location.hostname + ":15100" : "ws://127.0.0.1:15100")

// WSS 连接
const wsUrl = ref(defaultWsBase + "/wss/monitor")
const wsConnected = ref(false)
const wsConnecting = ref(false)
const receivedMessages = ref([])
let socket = null

function connectWs() {
  wsConnecting.value = true
  socket = io(wsUrl.value, { path: "/wss", transports: ["websocket"] })
  socket.on("connect", () => { wsConnected.value = true; wsConnecting.value = false })
  socket.on("disconnect", () => { wsConnected.value = false })
  socket.on("connect_error", () => { wsConnecting.value = false })
  socket.on("push", (data) => {
    receivedMessages.value.unshift({
      push_type: data.push_type || "unknown",
      time: new Date().toLocaleTimeString(),
      ...data
    })
    if (receivedMessages.value.length > 50) receivedMessages.value.pop()
  })
}

function disconnectWs() {
  if (socket) { socket.disconnect(); socket = null }
  wsConnected.value = false
}

function formatJson(obj) {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

// Round 选择
const searchQuery = ref("")
const roundList = ref([])
const loading = ref(false)
const selectedRound = ref(null)
const replaying = ref(false)
const replaySpeed = ref(1)
const replayProgress = ref(0)
const currentStage = ref("")
const pushOrder = ref("sequential")  // 推送顺序: sequential | random | ir_first | end_first

const columns = [
  { colKey: "round_id", title: "Round ID", width: 180, ellipsis: true },
  { colKey: "user_query", title: "用户查询", width: 200, ellipsis: true },
  { colKey: "time_start", title: "开始时间", width: 180 },
  { colKey: "overall_score", title: "合规得分", width: 100 },
  { colKey: "is_abnormal", title: "状态", width: 80 },
  { colKey: "action", title: "操作", width: 100 },
]

const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
})

const replayStatus = computed(() => {
  if (replayProgress.value >= 100) return "success"
  return "active"
})

onMounted(() => {
  loadRounds()
})

onUnmounted(() => {
  disconnectWs()
})

async function loadRounds() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      limit: pagination.value.pageSize,
      offset: (pagination.value.current - 1) * pagination.value.pageSize,
    })
    if (searchQuery.value) {
      params.append("query", searchQuery.value)
    }
    const r = await fetch(`/api/rounds?${params}`)
    const j = await r.json()
    if (j.ok) {
      roundList.value = j.data
      pagination.value.total = j.total
    }
  } catch (e) {
    console.error("加载失败:", e)
  } finally {
    loading.value = false
  }
}

function onPageChange(pageInfo) {
  pagination.value.current = pageInfo.current
  pagination.value.pageSize = pageInfo.pageSize
  loadRounds()
}

async function selectRound(round) {
  selectedRound.value = round
  replayProgress.value = 0
  
  const r = await fetch(`/api/rounds/query?round_id=${round.round_id}`)
  const j = await r.json()
  if (j.ok) {
    selectedRound.value = { ...round, ...j.data }
  }
}

function handleSelectRound(round) {
  if (replaying.value && selectedRound.value?.round_id !== round.round_id) {
    MessagePlugin.warning("回放过程中不允许切换 Round，请等待当前回放完成或停止回放后再操作。")
    return
  }
  MessagePlugin.info("请前往上方「回放配置」区域进行参数设置，然后点击「开始回放」进行调试。")
  selectRound(round)
}

async function startReplay() {
  if (!selectedRound.value || !wsConnected.value) return
  
  replaying.value = true
  replayProgress.value = 0
  
  const round = selectedRound.value
  const order = pushOrder.value
  
  console.log("开始回放", round.round_id, "推送顺序:", order)
  
  let delay_ir = 0
  let delay_end = 0
  
  if (round.time_start && round.time_end) {
    const start = new Date(round.time_start.replace('+0800', '+08:00'))
    const end = new Date(round.time_end.replace('+0800', '+08:00'))
    delay_end = (end - start) / 1000
    delay_ir = delay_end / 3
  }
  
  const speed = replaySpeed.value
  const actual_delay_ir = delay_ir / speed
  const actual_delay_end = delay_end / speed
  
  let action_json = round.action_json || "[]"
  let ir_json = round.ir_json || "{}"
  if (typeof action_json === 'string') {
    try { action_json = JSON.parse(action_json) } catch {}
  }
  if (typeof ir_json === 'string') {
    try { ir_json = JSON.parse(ir_json) } catch {}
  }
  
  let overall_score = round.overall_score || 1.0
  if (typeof round.judge_result === 'string' && round.judge_result.includes('整体得分')) {
    const match = round.judge_result.match(/整体得分[：:]\s*([\d.]+)/)
    if (match) overall_score = parseFloat(match[1])
  }
  
  // 检查是否有 kernel 数据
  const hasKernel = !!(round.kernel_syscall_seq || round.kernel_lsm_hook_result || round.kernel_resource_facts)
  
  // 根据推送顺序决定执行顺序
  // start 一定最先，ir/end/kernel 可自由排列
  const pushOrderMap = {
    start_ir_end_kernel: ['start', 'ir', 'end', 'kernel'],
    start_end_ir_kernel: ['start', 'end', 'ir', 'kernel'],
    start_end_kernel_ir: ['start', 'end', 'kernel', 'ir'],
    start_ir_kernel_end: ['start', 'ir', 'kernel', 'end'],
    start_kernel_ir_end: ['start', 'kernel', 'ir', 'end'],
    start_kernel_end_ir: ['start', 'kernel', 'end', 'ir'],
    random: null, // 随机顺序
  }
  
  let pushSequence
  if (order === 'random') {
    // 随机顺序：start 一定最先，ir/end/kernel 随机
    pushSequence = ['start', ...shuffle(['ir', 'end', 'kernel'])]
  } else {
    pushSequence = pushOrderMap[order] || ['start', 'ir', 'end', 'kernel']
  }
  
  // 推送函数映射
  const pushFunctions = {
    start: () => pushRoundStart(round, action_json, ir_json, overall_score),
    ir: () => pushRoundIrReady(round, action_json, ir_json, overall_score),
    end: () => pushRoundEnd(round, action_json, ir_json, overall_score),
    kernel: async () => {
      currentStage.value = "round_kernel"
      console.log("推送", "round_kernel")
      
      const kernel_syscall_seq = round.kernel_syscall_seq || ""
      const kernel_lsm_hook_result = round.kernel_lsm_hook_result || ""
      const kernel_resource_facts = round.kernel_resource_facts || ""
      
      await fetch("/api/monitor/send-test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          push_type: "round_kernel",
          round_id: round.round_id,
          kernel_syscall_seq: kernel_syscall_seq,
          kernel_lsm_hook_result: kernel_lsm_hook_result,
          kernel_resource_facts: kernel_resource_facts,
        })
      })
    },
  }
  
  // 按顺序推送
  for (const item of pushSequence) {
    // 如果没有 kernel 数据，跳过 kernel
    if (item === 'kernel' && !hasKernel) continue
    
    const fn = pushFunctions[item]
    if (fn) {
      await fn()
    }
  }
  
  replayProgress.value = 100
  
  currentStage.value = "完成"
  console.log("回放完成", round.round_id)
  replaying.value = false
}

// 推送 round_start
async function pushRoundStart(round, action_json, ir_json, overall_score) {
  currentStage.value = "round_start"
  console.log("推送", "round_start")
  
  await fetch("/api/monitor/send-test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      push_type: "round_start",
      round_id: round.round_id,
      time_start: round.time_start,
      session_key: round.session_key,
    })
  })
  
  replayProgress.value = 10
  await sleep(0.5)
}

// 推送 round_ir_ready
async function pushRoundIrReady(round, action_json, ir_json, overall_score) {
  currentStage.value = "round_ir_ready"
  console.log("推送", "round_ir_ready")
  
  await fetch("/api/monitor/send-test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      push_type: "round_ir_ready",
      round_id: round.round_id,
      ir_json: JSON.stringify(ir_json),
    })
  })
  
  replayProgress.value = 50
  await sleep(0.5)
}

// 推送 round_end
async function pushRoundEnd(round, action_json, ir_json, overall_score) {
  currentStage.value = "round_end"
  console.log("推送", "round_end")
  
  await fetch("/api/monitor/send-test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      push_type: "round_end",
      round_id: round.round_id,
      time_start: round.time_start,
      time_end: round.time_end,
      action_json: JSON.stringify(action_json),
      ir_json: JSON.stringify(ir_json),
      overall_score: overall_score,
      judge_result: round.judge_result || "",
    })
  })
  
  replayProgress.value = 90
  await sleep(0.5)
}

// 随机打乱数组
function shuffle(arr) {
  const result = [...arr]
  for (let i = result.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]]
  }
  return result
}

function cancelReplay() {
  replaying.value = false
  console.log("回放已停止")
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms * 1000))
}
</script>

<style scoped>
.replay-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
}

.page-header {
  margin-bottom: 24px;
}

.page-header h1 {
  font-size: 24px;
  font-weight: 600;
  color: #333;
  margin: 0 0 8px;
}

.page-desc {
  font-size: 14px;
  color: #999;
  margin: 0;
}

.section-card {
  background: #fff;
  border-radius: 14px;
  border: 1px solid #e8ecf0;
  padding: 24px;
  margin-bottom: 20px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.03);
}

.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  color: #333;
  margin-bottom: 16px;
}

.conn-status {
  margin-left: auto;
  font-size: 12px;
  color: #999;
  display: flex;
  align-items: center;
  gap: 6px;
}

.conn-status.online {
  color: #00a870;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ddd;
}

.conn-status.online .status-dot {
  background: #00a870;
  box-shadow: 0 0 6px #00a870;
}

.ws-config {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
}

.ws-config .config-item {
  flex: 1;
}

.ws-config .config-item label {
  display: block;
  font-size: 12px;
  color: #999;
  margin-bottom: 4px;
}

.ws-received {
  border: 1px solid #e8ecf0;
  border-radius: 8px;
  overflow: hidden;
}

.received-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: #f8f9fa;
  font-size: 12px;
  color: #666;
}

.received-list {
  max-height: 200px;
  overflow-y: auto;
  padding: 8px;
}

.received-item {
  border-radius: 6px;
  margin-bottom: 6px;
  border: 1px solid #e8ecf0;
  overflow: hidden;
  background: #fafbfc;
}

.received-item.round_start { border-left: 3px solid #0052D9; }
.received-item.round_ir_ready { border-left: 3px solid #00a870; }
.received-item.round_end { border-left: 3px solid #ED7B2F; }

.msg-type {
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  padding: 3px 6px;
  border-radius: 3px;
  color: #fff;
  background: #0052D9;
}

.received-item.round_ir_ready .msg-type { background: #00a870; }
.received-item.round_end .msg-type { background: #ED7B2F; }

.msg-time {
  font-size: 10px;
  color: #999;
  margin-left: 8px;
}

.msg-body {
  margin: 0;
  padding: 8px 10px;
  font-size: 10px;
  background: #fff;
  color: #333;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: "SF Mono", monospace;
  max-height: 80px;
  overflow-y: auto;
}

.msg-empty {
  text-align: center;
  padding: 24px;
  font-size: 12px;
  color: #ccc;
  font-style: italic;
}

.filter-row {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.replay-info {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  padding: 16px;
  background: #f8f9fa;
  border-radius: 8px;
  margin-bottom: 20px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-label {
  font-size: 12px;
  color: #999;
}

.info-value {
  font-size: 13px;
  color: #333;
  word-break: break-all;
}

.info-value.mono {
  font-family: "SF Mono", monospace;
  font-size: 11px;
}

.replay-options {
  padding: 16px;
  background: #f8f9fa;
  border-radius: 8px;
  margin-bottom: 20px;
}

.option-item {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.option-item:last-child {
  margin-bottom: 0;
}

.option-item label {
  min-width: 80px;
  font-size: 13px;
  color: #666;
}

.option-hint {
  font-size: 11px;
  color: #999;
  margin-left: 8px;
}

.option-item {
  display: flex;
  align-items: center;
  gap: 12px;
}

.option-item label {
  width: 80px;
  font-size: 13px;
  color: #666;
}

.option-value {
  min-width: 40px;
  font-size: 13px;
  color: #333;
}

.replay-actions {
  margin-bottom: 20px;
}

.action-buttons {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: flex-start;
}

.replay-progress {
  margin-top: 16px;
}

.progress-info {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #999;
  margin-top: 8px;
}

.empty-replay {
  text-align: center;
  padding: 56px 20px;
}

.empty-icon {
  color: #ddd;
  margin-bottom: 16px;
}

.empty-title {
  font-size: 16px;
  font-weight: 600;
  color: #666;
  margin: 0 0 8px;
}

.empty-desc {
  font-size: 13px;
  color: #999;
  margin: 0;
  max-width: 360px;
  margin-left: auto;
  margin-right: auto;
  line-height: 1.6;
}

.normal-tag {
  color: #00a870;
}
</style>
