<template>
  <div class="wss-tab">
    <div class="page-layout">
      <!-- Left: WSS Docs -->
      <div class="docs-panel">
        <p class="page-desc">WebSocket 长连接接口，按消息组订阅，实时接收 Agent 行为审计推送。</p>

        <div class="connect-info">
          <div class="section-label">连接方式</div>
          <div class="info-row">
            <span class="info-key">协议</span>
            <span class="info-val">Socket.IO (WebSocket transport)</span>
          </div>
          <div class="info-row">
            <span class="info-key">完整路径格式</span>
            <code class="ws-url">ws://{{ browserHost }}:15100/wss/&lt;namespace&gt;</code>
          </div>
          <p class="hint">客户端通过 Socket.IO 连接对应消息组 namespace，监听统一事件 <code>push</code>，通过 <code>push_type</code> 区分消息类型。</p>
          <div class="code-example">
            <div class="section-label">接入示例</div>
            <div class="code-tabs">
              <span class="code-tab" :class="{ active: codeLang === 'js' }" @click="codeLang = 'js'">JavaScript</span>
              <span class="code-tab" :class="{ active: codeLang === 'py' }" @click="codeLang = 'py'">Python</span>
            </div>
            <pre v-if="codeLang === 'js'" class="code-block"><code class="lang-js"><span class="kw">import</span> { io } <span class="kw">from</span> <span class="str">"socket.io-client"</span>

<span class="kw">const</span> socket = io(<span class="str">"ws://{{ browserHost }}:15100/wss/monitor"</span>, {
  <span class="key">path</span>: <span class="str">"/wss"</span>,
  <span class="key">transports</span>: [<span class="str">"websocket"</span>]
})

socket.on(<span class="str">"push"</span>, (data) => {
  <span class="kw">switch</span> (data.push_type) {
    <span class="kw">case</span> <span class="str">"round_start"</span>:
      console.log(<span class="str">"Round started:"</span>, data.round_id, data.time_start)
      <span class="kw">break</span>
    <span class="kw">case</span> <span class="str">"round_ir_ready"</span>:
      console.log(<span class="str">"IR ready:"</span>, data.round_id)
      <span class="kw">break</span>
    <span class="kw">case</span> <span class="str">"round_end"</span>:
      console.log(<span class="str">"Round ended:"</span>, data.round_id, <span class="str">"score:"</span>, data.overall_score)
      <span class="kw">break</span>
  }
})</code></pre>
            <pre v-if="codeLang === 'py'" class="code-block"><code class="lang-py"><span class="kw">import</span> socketio

sio = socketio.Client()

<span class="dec">@sio.on</span>(<span class="str">"push"</span>, namespace=<span class="str">"/wss/monitor"</span>)
<span class="kw">def</span> <span class="fn">on_push</span>(data):
    push_type = data.get(<span class="str">"push_type"</span>)
    <span class="kw">if</span> push_type == <span class="str">"round_start"</span>:
        print(<span class="str">f"Round started: {data['round_id']}"</span>)
    <span class="kw">elif</span> push_type == <span class="str">"round_ir_ready"</span>:
        print(<span class="str">f"IR ready: {data['round_id']}"</span>)
    <span class="kw">elif</span> push_type == <span class="str">"round_end"</span>:
        print(<span class="str">f"Round ended: {data['round_id']} score={data['overall_score']}"</span>)

sio.connect(
    <span class="str">"ws://{{ browserHost }}:15100"</span>,
    socketio_path=<span class="str">"/wss"</span>,
    namespaces=[<span class="str">"/wss/monitor"</span>],
    transports=[<span class="str">"websocket"</span>]
)
sio.wait()</code></pre>
          </div>
        </div>

        <!-- 运行消息组 -->
        <div class="category-header">
          <t-icon name="wifi" size="18px" />
          <span>运行消息组</span>
          <code class="ns-badge">ws://{{ browserHost }}:15100/wss/monitor</code>
          <t-button size="small" variant="text" theme="primary" @click="fillWsUrl('/wss/monitor')" title="填入调试面板">
            <t-icon name="play-circle" size="14px" />
          </t-button>
        </div>

        <!-- Unified push event -->
        <div class="endpoint-card">
          <div class="ep-header" @click="expandedEvent = expandedEvent === 'push' ? null : 'push'">
            <span class="type-badge event">PUSH</span>
            <code class="ep-path">event: "push"</code>
            <span class="ep-summary">统一推送事件（通过 push_type 区分）</span>
            <t-icon :name="expandedEvent === 'push' ? 'chevron-up' : 'chevron-down'" size="16px" class="ep-toggle" />
          </div>
          <div v-if="expandedEvent === 'push'" class="ep-body">
            <div class="ep-desc">所有消息通过统一的 <code>push</code> 事件推送，消息体中 <code>push_type</code> 字段标识具体类型。</div>

            <!-- push_type: round_start -->
            <div class="push-type-section">
              <div class="push-type-header start">
                <span class="push-type-badge">push_type: "round_start"</span>
                <span class="push-type-desc">Round 开始</span>
              </div>
              <div class="push-type-body">
                <p class="type-explain">检测到新 Round 开始时推送，标志一轮 Agent 交互开始。</p>
                <pre class="response-block">{
  "push_type": "round_start",
  "round_id": "abc12345",
  "time_start": "2026-05-30 21:20:00.123+0800",
  "session_key": "agent:main:main",
  "push_time": "2026-05-30 21:20:00.123+0800",
  "is_mock": false
}</pre>
                <table class="params-table">
                  <thead><tr><th>字段</th><th>类型</th><th>说明</th></tr></thead>
                  <tbody>
                    <tr><td><code>push_type</code></td><td>string</td><td>固定 "round_start"</td></tr>
                    <tr><td><code>round_id</code></td><td>string</td><td>本轮唯一标识</td></tr>
                    <tr><td><code>time_start</code></td><td>string</td><td>Round 开始时间</td></tr>
                    <tr><td><code>session_key</code></td><td>string</td><td>Agent 会话标识</td></tr>
                    <tr><td><code>push_time</code></td><td>string</td><td>消息推送时间</td></tr>
                    <tr><td><code>is_mock</code></td><td>boolean</td><td>是否模拟发送（测试消息自动设为 true）</td></tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- push_type: round_ir_ready -->
            <div class="push-type-section">
              <div class="push-type-header ir">
                <span class="push-type-badge">push_type: "round_ir_ready"</span>
                <span class="push-type-desc">IR 策略就绪</span>
              </div>
              <div class="push-type-body">
                <p class="type-explain">IR 翻译管线完成后推送，在 round_start 之后、round_end 之前触发。</p>
                <pre class="response-block">{
  "push_type": "round_ir_ready",
  "round_id": "abc12345",
  "ir_json": "{\"level1\":[\"file_ops\"],\"level2\":{\"policies\":[...]}}",
  "push_time": "2026-05-30 21:20:05.456+0800",
  "is_mock": false
}</pre>
                <table class="params-table">
                  <thead><tr><th>字段</th><th>类型</th><th>说明</th></tr></thead>
                  <tbody>
                    <tr><td><code>push_type</code></td><td>string</td><td>固定 "round_ir_ready"</td></tr>
                    <tr><td><code>round_id</code></td><td>string</td><td>关联 Round ID</td></tr>
                    <tr><td><code>ir_json</code></td><td>string</td><td>结构化权限策略 JSON</td></tr>
                    <tr><td><code>push_time</code></td><td>string</td><td>推送时间</td></tr>
                    <tr><td><code>is_mock</code></td><td>boolean</td><td>是否模拟发送（测试消息自动设为 true）</td></tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- push_type: round_end -->
            <div class="push-type-section">
              <div class="push-type-header end">
                <span class="push-type-badge">push_type: "round_end"</span>
                <span class="push-type-desc">Round 结束（含完整判定）</span>
              </div>
              <div class="push-type-body">
                <p class="type-explain">Round 结束时推送完整审计结果：行为轨迹 + IR + 判定得分。</p>
                <pre class="response-block">{
  "push_type": "round_end",
  "round_id": "abc12345",
  "time_start": "2026-05-30 21:20:00.123+0800",
  "time_end": "2026-05-30 21:20:15.789+0800",
  "action_json": "[{\"tool\":\"read\",\"arguments\":{...}}]",
  "ir_json": "{...}",
  "overall_score": 0.85,
  "judge_result": "【判定结果】行为一致...",
  "push_time": "2026-05-30 21:20:15.789+0800",
  "is_mock": false
}</pre>
                <table class="params-table">
                  <thead><tr><th>字段</th><th>类型</th><th>说明</th></tr></thead>
                  <tbody>
                    <tr><td><code>push_type</code></td><td>string</td><td>固定 "round_end"</td></tr>
                    <tr><td><code>round_id</code></td><td>string</td><td>本轮标识</td></tr>
                    <tr><td><code>time_start</code></td><td>string</td><td>开始时间</td></tr>
                    <tr><td><code>time_end</code></td><td>string</td><td>结束时间</td></tr>
                    <tr><td><code>action_json</code></td><td>string</td><td>用户态行为 JSON</td></tr>
                    <tr><td><code>ir_json</code></td><td>string</td><td>IR 策略 JSON</td></tr>
                    <tr><td><code>overall_score</code></td><td>float</td><td>得分 (>0.5 合规)</td></tr>
                    <tr><td><code>judge_result</code></td><td>string</td><td>判定文本</td></tr>
                    <tr><td><code>push_time</code></td><td>string</td><td>推送时间</td></tr>
                    <tr><td><code>is_mock</code></td><td>boolean</td><td>是否模拟发送（测试消息自动设为 true）</td></tr>
                  </tbody>
                </table>
                <div>
                  <p class="hint">注：除上述三种标准消息外，平台后续可能增加其他 push_type，或对字段进行调整，客户端请做好兼容处理。</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Debug Panel -->
      <div class="test-panel" :class="{ collapsed: testCollapsed }">
        <div class="test-header" @click="testCollapsed = !testCollapsed">
          <t-icon name="wifi" size="18px" />
          <span>WSS 调试</span>
          <t-icon :name="testCollapsed ? 'chevron-left' : 'chevron-right'" size="16px" style="margin-left: auto;" />
        </div>
        <div v-if="!testCollapsed" class="test-body">
          <div v-if="!monitorRunning" class="monitor-warn">
            <t-icon name="error-circle" size="16px" />
            <span>监控未启动，无法接收推送</span>
            <t-button size="small" theme="primary" variant="text" @click="$router.push('/monitor')">去启动</t-button>
          </div>

          <div class="test-field">
            <label>WSS 地址</label>
            <t-input v-model="wsUrl" size="small" placeholder="ws://host:15100/wss/monitor" :disabled="wsConnected" />
          </div>

          <div class="test-field">
            <label>连接状态</label>
            <div class="conn-status">
              <span class="status-dot" :class="wsConnected ? 'online' : 'offline'" />
              <span>{{ wsConnected ? '已连接' : '未连接' }}</span>
              <t-button v-if="!wsConnected" size="small" theme="primary" @click="connectWs" :loading="wsConnecting">连接</t-button>
              <t-button v-else size="small" theme="danger" variant="outline" @click="disconnectWs">断开</t-button>
            </div>
          </div>

          <div class="test-field msg-header">
            <label>接收消息 <t-tag size="small" variant="light">{{ messages.length }}</t-tag></label>
            <t-button size="small" variant="text" @click="messages = []" v-if="messages.length">清空</t-button>
          </div>

          <div class="msg-list">
            <div v-for="(msg, i) in messages" :key="i" class="msg-item" :class="msg.push_type">
              <div class="msg-head">
                <span class="msg-type" :class="msg.push_type">{{ msg.push_type }}</span>
                <span class="msg-time">{{ msg.recv_time }}</span>
              </div>
              <pre class="msg-body">{{ msg.data }}</pre>
            </div>
            <div v-if="messages.length === 0" class="msg-empty">
              {{ wsConnected ? '等待推送...' : '请先连接 WSS' }}
            </div>
          </div>

          <!-- 手动推送 -->
          <div class="mock-push-section">
            <div class="mock-push-header">
              <t-icon name="send" size="14px" />
              <span>手动推送（非 Agent 行为触发）</span>
            </div>
            <div class="mock-push-body">
              <div class="send-field">
                <label>push_type</label>
                <t-select v-model="sendType" size="small" style="width: 100%">
                  <t-option value="round_start" label="round_start (Round 开始)" />
                  <t-option value="round_ir_ready" label="round_ir_ready (IR 策略就绪)" />
                  <t-option value="round_end" label="round_end (Round 结束)" />
                </t-select>
              </div>
              <div class="send-field">
                <label>消息内容 (JSON)</label>
                <t-textarea v-model="sendPayload" size="small" :autosize="{ minRows: 4, maxRows: 8 }" placeholder='输入 JSON 格式消息，is_mock 字段会自动设为 true' />
                <div v-if="jsonError" class="json-error">{{ jsonError }}</div>
              </div>
              <div class="send-actions">
                <t-button theme="primary" @click="sendTestMessage" :loading="sending" :disabled="!wsConnected || !isJsonValid">
                  <t-icon name="send" size="14px" />
                  发送
                </t-button>
                <t-button variant="outline" @click="fillDefaultPayload" size="small">
                  填入默认
                </t-button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, watch } from "vue"
import { io } from "socket.io-client"

const browserHost = typeof window !== "undefined" ? window.location.hostname : "127.0.0.1"
const defaultWsBase = (typeof window !== "undefined" ? (window.location.protocol === "https:" ? "wss://" : "ws://") + window.location.hostname + ":15100" : "ws://127.0.0.1:15100")

const codeLang = ref('js')
const expandedEvent = ref(null)
const testCollapsed = ref(false)
const monitorRunning = ref(false)
const wsUrl = ref(defaultWsBase + "/wss/monitor")
const wsConnected = ref(false)
const wsConnecting = ref(false)
const messages = ref([])
let socket = null

onMounted(() => { checkMonitor() })
onUnmounted(() => { disconnectWs() })

async function checkMonitor() {
  try { const r = await fetch("/api/monitor/status"); const j = await r.json(); if (j.ok) monitorRunning.value = j.data.running } catch {}
}

function fillWsUrl(ns) {
  wsUrl.value = defaultWsBase + ns
}

function connectWs() {
  wsConnecting.value = true
  socket = io(wsUrl.value, { path: "/wss", transports: ["websocket"] })
  socket.on("connect", () => { wsConnected.value = true; wsConnecting.value = false })
  socket.on("disconnect", () => { wsConnected.value = false })
  socket.on("connect_error", () => { wsConnecting.value = false })
  socket.on("push", (data) => {
    messages.value.unshift({ push_type: data.push_type || "unknown", recv_time: new Date().toLocaleTimeString(), data: JSON.stringify(data, null, 2) })
    if (messages.value.length > 100) messages.value.pop()
  })
}

function disconnectWs() { if (socket) { socket.disconnect(); socket = null }; wsConnected.value = false }

// 测试发送相关
const sendType = ref('round_start')
const sendPayload = ref('')
const sending = ref(false)
const jsonError = ref('')

// JSON 校验
function validateJson() {
  if (!sendPayload.value.trim()) {
    jsonError.value = 'JSON 内容不能为空'
    return false
  }
  try {
    JSON.parse(sendPayload.value)
    jsonError.value = ''
    return true
  } catch (e) {
    jsonError.value = 'JSON 格式错误: ' + e.message
    return false
  }
}

// 监听输入变化进行校验
watch(sendPayload, () => {
  validateJson()
})

const isJsonValid = computed(() => validateJson())

function fillDefaultPayload() {
  const now = new Date().toISOString().replace('T', ' ').slice(0, 26) + '+0800'
  const roundId = 'mock_' + Date.now()
  
  let payload = ''
  switch (sendType.value) {
    case 'round_start':
      payload = JSON.stringify({
        push_type: 'round_start',
        round_id: roundId,
        time_start: now,
        session_key: 'agent:main:main',
        push_time: now
      }, null, 2)
      break
    case 'round_ir_ready':
      payload = JSON.stringify({
        push_type: 'round_ir_ready',
        round_id: roundId,
        ir_json: '{"level1":["file_ops"],"level2":{"policies":[{"scene":"file_ops","functions":["read_file"]}]}}',
        push_time: now
      }, null, 2)
      break
    case 'round_end':
      payload = JSON.stringify({
        push_type: 'round_end',
        round_id: roundId,
        time_start: now,
        time_end: now,
        action_json: '[{"tool":"read","arguments":{"path":"/tmp/test.txt"}}]',
        ir_json: '{"level1":["file_ops"],"level2":{"policies":[{"scene":"file_ops","functions":["read_file"]}]}}',
        overall_score: 0.85,
        judge_result: '【判定结果】行为一致，符合预期',
        push_time: now
      }, null, 2)
      break
  }
  sendPayload.value = payload
}

function sendTestMessage() {
  if (!wsConnected.value) return
  
  try {
    const payload = JSON.parse(sendPayload.value)
    payload.push_type = sendType.value
    
    sending.value = true
    
    fetch('/api/monitor/send-test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(async (res) => {
      const data = await res.json()
      if (!data.ok) {
        throw new Error(data.error || '发送失败')
      }
      // 不记录消息，等待 WebSocket push 事件自然收到
    }).catch((e) => {
      console.error('发送失败:', e)
    })
    
    sending.value = false
  } catch (e) {
    console.error('发送失败:', e)
  } finally {
    sending.value = false
  }
}
</script>

<style scoped>
.wss-tab { padding: 24px 8px; }
.page-layout { display: flex; gap: 20px; }
.docs-panel { flex: 1; min-width: 0; overflow-y: auto; max-height: calc(100vh - 160px); padding: 0 16px; }
.page-desc { font-size: 13px; color: #999; margin-bottom: 20px; }
.connect-info { background: #f8faff; border: 1px solid #e0e8f5; border-radius: 10px; padding: 18px 22px; margin-bottom: 24px; }
.connect-info .section-label { font-size: 12px; font-weight: 600; color: #333; margin-bottom: 10px; }
.info-row { display: flex; align-items: center; gap: 12px; padding: 5px 0; font-size: 12px; }
.info-key { color: #666; min-width: 100px; }
.info-val { color: #333; }
.ws-url { font-size: 12px; color: #0052D9; background: #fff; padding: 4px 10px; border-radius: 4px; border: 1px solid #e8ecf0; }
.hint { font-size: 11px; color: #999; margin: 12px 0 0; line-height: 1.6; }
.hint code { background: #f0f5ff; color: #0052D9; padding: 1px 4px; border-radius: 2px; }
.category-header { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 600; color: #333; margin-bottom: 14px; }
.ns-badge { font-size: 11px; background: #f0f5ff; color: #0052D9; padding: 3px 10px; border-radius: 4px; font-family: monospace; }
.endpoint-card { background: #fff; border: 1px solid #e8ecf0; border-radius: 10px; overflow: hidden; margin-bottom: 10px; }
.endpoint-card:hover { box-shadow: 0 2px 12px rgba(0,82,217,0.06); }
.ep-header { display: flex; align-items: center; gap: 10px; padding: 14px 18px; cursor: pointer; }
.type-badge { font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 3px; color: #fff; font-family: monospace; }
.type-badge.event { background: #722ed1; }
.ep-path { font-size: 12px; font-family: "SF Mono", monospace; color: #333; }
.ep-summary { flex: 1; font-size: 12px; color: #666; }
.ep-toggle { color: #999; }
.ep-body { padding: 4px 18px 18px; border-top: 1px solid #f0f0f0; background: #fafbfc; }
.ep-desc { font-size: 12px; color: #666; padding: 10px 0; line-height: 1.6; }
.ep-desc code { background: #f0f5ff; color: #0052D9; padding: 1px 4px; border-radius: 2px; }

/* Push type sections inside the expanded card */
.push-type-section { margin-top: 16px; border: 1px solid #e8ecf0; border-radius: 8px; overflow: hidden; }
.push-type-header { display: flex; align-items: center; gap: 10px; padding: 10px 14px; }
.push-type-header.start { background: linear-gradient(90deg, #f0f5ff, #fff); border-bottom: 1px solid #e0e8f5; }
.push-type-header.ir { background: linear-gradient(90deg, #f0fff8, #fff); border-bottom: 1px solid #d0f0e0; }
.push-type-header.end { background: linear-gradient(90deg, #fffbf5, #fff); border-bottom: 1px solid #ffe8d0; }
.push-type-badge { font-size: 11px; font-family: monospace; font-weight: 600; color: #333; }
.push-type-desc { font-size: 12px; color: #666; }
.push-type-body { padding: 12px 14px; }
.type-explain { font-size: 12px; color: #666; margin: 0 0 10px; }
.response-block { background: #1a1a2e; color: #a0e0a0; padding: 12px 14px; border-radius: 6px; font-size: 10px; line-height: 1.5; overflow-x: auto; font-family: "SF Mono", monospace; margin-bottom: 12px; }
.params-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.params-table th { text-align: left; padding: 5px 8px; background: #f0f2f5; color: #666; }
.params-table td { padding: 5px 8px; border-bottom: 1px solid #f0f0f0; }
.params-table code { background: #f0f5ff; color: #0052D9; padding: 1px 3px; border-radius: 2px; font-size: 10px; }

/* Test Panel */
.test-panel { width: 360px; flex-shrink: 0; background: #fff; border: 1px solid #e8ecf0; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.06); position: sticky; top: 0; max-height: calc(100vh - 160px); overflow-y: auto; }
.test-panel.collapsed { width: 44px; overflow: hidden; }
.test-header { display: flex; align-items: center; gap: 8px; padding: 14px 16px; font-size: 14px; font-weight: 600; color: #333; cursor: pointer; border-bottom: 1px solid #f0f0f0; }
.test-body { padding: 16px; display: flex; flex-direction: column; gap: 14px; }
.test-field label { display: block; font-size: 11px; font-weight: 500; color: #666; margin-bottom: 4px; }
.monitor-warn { background: #fff8e6; border: 1px solid #ffe58f; border-radius: 6px; padding: 10px 12px; display: flex; align-items: center; gap: 8px; font-size: 12px; color: #d48806; }
.conn-status { display: flex; align-items: center; gap: 8px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
.status-dot.online { background: #00a870; box-shadow: 0 0 4px #00a870; }
.status-dot.offline { background: #ccc; }
.msg-header { display: flex; align-items: center; justify-content: space-between; }
.msg-list { max-height: 350px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
.msg-item { border-radius: 6px; overflow: hidden; border: 1px solid #e8ecf0; }
.msg-item.round_start { border-left: 3px solid #0052D9; }
.msg-item.round_ir_ready { border-left: 3px solid #00a870; }
.msg-item.round_end { border-left: 3px solid #ED7B2F; }
.msg-head { display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: #f8f9fa; }
.msg-type { font-size: 10px; font-weight: 700; font-family: monospace; padding: 1px 6px; border-radius: 3px; color: #fff; }
.msg-type.round_start { background: #0052D9; }
.msg-type.round_ir_ready { background: #00a870; }
.msg-type.round_end { background: #ED7B2F; }
.msg-time { font-size: 10px; color: #999; }
.msg-body { margin: 0; padding: 8px 10px; font-size: 10px; line-height: 1.4; background: #fafbfc; color: #333; overflow-x: auto; white-space: pre-wrap; word-break: break-all; font-family: "SF Mono", monospace; max-height: 120px; overflow-y: auto; }
.msg-empty { text-align: center; padding: 24px; font-size: 12px; color: #ccc; font-style: italic; }

.code-example { margin-top: 16px; }
.code-tabs { display: flex; gap: 0; margin-bottom: 0; }
.code-tab { padding: 6px 16px; font-size: 12px; font-weight: 500; cursor: pointer; border: 1px solid #e8ecf0; border-bottom: none; border-radius: 6px 6px 0 0; background: #f5f7fa; color: #666; transition: all 0.2s; }
.code-tab.active { background: #1a1a2e; color: #a0e0a0; border-color: #1a1a2e; }
.code-block { background: #1a1a2e; color: #e0e0e0; padding: 16px 18px; border-radius: 0 6px 6px 6px; font-size: 12px; line-height: 1.7; overflow-x: auto; font-family: "SF Mono", "Fira Code", monospace; margin: 0; }
.code-block .kw { color: #c792ea; }
.code-block .str { color: #c3e88d; }
.code-block .key { color: #89ddff; }
.code-block .fn { color: #82aaff; }
.code-block .dec { color: #f78c6c; }

/* Test Send Section */
.mock-push-section { background: #f8faff; border: 1px solid #e0e8f5; border-radius: 8px; padding: 14px; }
.mock-push-header { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: #333; margin-bottom: 12px; }
.mock-push-body { display: flex; flex-direction: column; gap: 10px; }
.send-field label { display: block; font-size: 11px; font-weight: 500; color: #666; margin-bottom: 4px; }
.send-field .t-textarea, .send-field .t-select { width: 100%; }
.json-error { font-size: 11px; color: #e34d59; margin-top: 4px; padding: 4px 8px; background: #fff0ed; border-radius: 4px; }
.send-actions { display: flex; gap: 8px; justify-content: flex-end; }
</style>
