<template>
  <div class="api-docs-page">
    <div class="page-layout">
      <!-- Left: Docs -->
      <div class="docs-panel">
        
        <p class="page-desc">以下为 ClawAVC 平台对外开放的 API 接口（建议开放，其他接口不开放），可供第三方系统集成调用。</p>

        <div v-if="loading" class="loading-state"><t-loading size="small" /> 加载中...</div>
        <div v-else-if="grouped.length === 0" class="empty-state">
          <t-icon name="file-unknown" size="48px" style="color: #ccc;" />
          <p>暂无对外公开的接口</p>
        </div>

        <div v-else class="docs-content">
          <div v-for="group in grouped" :key="group.category" class="category-section">
            <div class="category-header">
              <t-icon name="folder-open" size="18px" />
              <span>{{ group.category }}</span>
              <t-tag size="small" theme="primary" variant="light">{{ group.endpoints.length }}</t-tag>
            </div>

            <div v-for="ep in group.endpoints" :key="ep.key" class="endpoint-card" :class="{ selected: testReq.key === ep.key }">
              <div class="ep-header" @click="toggle(ep.key)">
                <span class="method-badge" :class="ep.method.toLowerCase()">{{ ep.method }}</span>
                <code class="ep-path">{{ ep.path }}</code>
                <span class="ep-summary">{{ ep.summary }}</span>
                <t-button size="small" variant="text" theme="primary" @click.stop="fillTest(ep)" title="填入测试面板">
                  <t-icon name="play-circle" size="14px" />
                </t-button>
                <t-icon :name="expandedKey === ep.key ? 'chevron-up' : 'chevron-down'" size="16px" class="ep-toggle" />
              </div>

              <div v-if="expandedKey === ep.key" class="ep-body">
                <div v-if="ep.description && ep.description !== ep.summary" class="ep-desc">{{ ep.description }}</div>
                <div v-if="ep.params && ep.params.length" class="ep-section">
                  <div class="section-label">请求参数</div>
                  <table class="params-table">
                    <thead><tr><th>参数名</th><th>类型</th><th>默认值</th><th>说明</th></tr></thead>
                    <tbody>
                      <tr v-for="p in ep.params" :key="p.name">
                        <td><code>{{ p.name }}</code></td>
                        <td>{{ p.type || '-' }}</td>
                        <td>{{ p.default || '-' }}</td>
                        <td>{{ p.desc || '-' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div v-if="ep.response" class="ep-section">
                  <div class="section-label">返回示例</div>
                  <pre class="response-block">{{ JSON.stringify(ep.response, null, 2) }}</pre>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Test Panel (floating) -->
      <div class="test-panel" :class="{ collapsed: testCollapsed }">
        <div class="test-header" @click="testCollapsed = !testCollapsed">
          <t-icon name="code" size="18px" />
          <span>API 测试</span>
          <t-icon :name="testCollapsed ? 'chevron-left' : 'chevron-right'" size="16px" style="margin-left: auto;" />
        </div>
        <div v-if="!testCollapsed" class="test-body">
          <div class="test-field">
            <label>请求地址</label>
            <t-input v-model="testReq.baseUrl" size="small" placeholder="http://..." />
          </div>
          <div class="test-field">
            <label>方法</label>
            <t-select v-model="testReq.method" size="small" :options="[{label:'GET',value:'GET'},{label:'POST',value:'POST'},{label:'PUT',value:'PUT'},{label:'DELETE',value:'DELETE'}]" />
          </div>
          <div class="test-field">
            <label>路径</label>
            <t-input v-model="testReq.path" size="small" placeholder="/api/..." />
          </div>
          <div class="test-field">
            <label>Query 参数</label>
            <t-textarea v-model="testReq.queryParams" size="small" placeholder="key=value（每行一个）" :autosize="{ minRows: 2, maxRows: 4 }" />
          </div>
          <div class="test-field" v-if="testReq.method !== 'GET'">
            <label>Body (JSON)</label>
            <t-textarea v-model="testReq.body" size="small" placeholder='{"key": "value"}' :autosize="{ minRows: 3, maxRows: 8 }" />
          </div>
          <div class="test-field">
            <label>Headers</label>
            <t-textarea v-model="testReq.headers" size="small" placeholder="Key: Value（每行一个）" :autosize="{ minRows: 1, maxRows: 3 }" />
          </div>
          <t-button theme="primary" block @click="sendTest" :loading="testLoading" size="small">
            发送请求
          </t-button>

          <div v-if="testResp !== null" class="test-response">
            <div class="resp-status" :class="testRespOk ? 'ok' : 'err'">
              {{ testRespStatus }}
            </div>
            <pre class="resp-body">{{ testResp }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"

const endpoints = ref([])
const loading = ref(true)
const expandedKey = ref(null)
const testCollapsed = ref(false)

// Determine default base URL from browser
const defaultBaseUrl = (() => {
  if (typeof window !== "undefined" && window.location) {
    const loc = window.location
    // Use current host but backend port 15100
    return loc.protocol + "//" + loc.hostname + ":15100"
  }
  return "http://127.0.0.1:15100"
})()

const testReq = ref({
  key: "",
  baseUrl: defaultBaseUrl,
  method: "GET",
  path: "/api/stats",
  queryParams: "",
  body: "",
  headers: "",
})
const testLoading = ref(false)
const testResp = ref(null)
const testRespOk = ref(true)
const testRespStatus = ref("")

onMounted(async () => {
  try {
    const r = await fetch("/api/docs/public")
    const j = await r.json()
    if (j.ok) endpoints.value = j.data
  } catch {}
  loading.value = false
})

const grouped = computed(() => {
  const map = {}
  for (const ep of endpoints.value) {
    if (!map[ep.category]) map[ep.category] = []
    map[ep.category].push(ep)
  }
  return Object.entries(map).map(([category, eps]) => ({ category, endpoints: eps }))
})

function toggle(key) { expandedKey.value = expandedKey.value === key ? null : key }

function fillTest(ep) {
  testReq.value.key = ep.key
  testReq.value.method = ep.method
  testReq.value.path = ep.path
  testResp.value = null

  // Fill query params from ep.params (for GET)
  if (ep.method === "GET" && ep.params && ep.params.length) {
    const lines = ep.params
      .filter(p => p.type !== "header")
      .map(p => p.name + "=" + (p.default || ""))
      .join("\n")
    testReq.value.queryParams = lines
    testReq.value.body = ""
  } else if (ep.params && ep.params.length) {
    // For POST/PUT, build body JSON
    const obj = {}
    ep.params.filter(p => p.type !== "header").forEach(p => { obj[p.name] = p.default || "" })
    testReq.value.body = JSON.stringify(obj, null, 2)
    testReq.value.queryParams = ""
  } else {
    testReq.value.queryParams = ""
    testReq.value.body = ""
  }

  // Fill headers from header-type params
  const headerParams = (ep.params || []).filter(p => p.type === "header")
  testReq.value.headers = headerParams.map(p => p.name + ": ").join("\n")
}

async function sendTest() {
  testLoading.value = true
  testResp.value = null

  let url = testReq.value.baseUrl.replace(/\/$/, "") + testReq.value.path

  // Append query params
  if (testReq.value.queryParams.trim()) {
    const pairs = testReq.value.queryParams.trim().split("\n").filter(l => l.includes("="))
    const qs = pairs.map(l => l.trim()).join("&")
    url += (url.includes("?") ? "&" : "?") + qs
  }

  // Parse headers
  const headers = { "Content-Type": "application/json" }
  if (testReq.value.headers.trim()) {
    testReq.value.headers.trim().split("\n").forEach(line => {
      const idx = line.indexOf(":")
      if (idx > 0) headers[line.slice(0, idx).trim()] = line.slice(idx + 1).trim()
    })
  }

  const opts = { method: testReq.value.method, headers }
  if (testReq.value.method !== "GET" && testReq.value.body.trim()) {
    opts.body = testReq.value.body
  }

  try {
    const resp = await fetch(url, opts)
    testRespStatus.value = resp.status + " " + resp.statusText
    testRespOk.value = resp.ok
    const text = await resp.text()
    try { testResp.value = JSON.stringify(JSON.parse(text), null, 2) }
    catch { testResp.value = text }
  } catch (e) {
    testRespOk.value = false
    testRespStatus.value = "Network Error"
    testResp.value = e.message
  }
  testLoading.value = false
}
</script>

<style scoped>
.api-docs-page { height: 100%; padding: 24px 8px 0; }
.page-layout { display: flex; gap: 16px; height: 100%; padding: 0 4px; }
.docs-panel { flex: 1; min-width: 0; overflow-y: auto; max-height: calc(100vh - 100px); padding: 16px 16px; }
.docs-panel h2 { font-size: 20px; font-weight: 600; color: #333; margin-bottom: 6px; }
.page-desc { font-size: 13px; color: #999; margin-bottom: 24px; }
.loading-state { text-align: center; padding: 60px 0; color: #999; }
.empty-state { text-align: center; padding: 80px 0; color: #999; }
.docs-content { display: flex; flex-direction: column; gap: 24px; padding-bottom: 40px; }
.category-header { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 600; color: #333; margin-bottom: 12px; }
.endpoint-card { background: #fff; border: 1px solid #e8ecf0; border-radius: 10px; overflow: hidden; transition: all 0.2s; margin-bottom: 8px; }
.endpoint-card:hover { box-shadow: 0 2px 12px rgba(0,82,217,0.06); }
.endpoint-card.selected { border-color: #0052D9; box-shadow: 0 0 0 2px rgba(0,82,217,0.1); }
.ep-header { display: flex; align-items: center; gap: 10px; padding: 12px 16px; cursor: pointer; }
.method-badge { font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 3px; color: #fff; text-transform: uppercase; font-family: monospace; }
.method-badge.get { background: #00a870; }
.method-badge.post { background: #0052D9; }
.method-badge.put { background: #ED7B2F; }
.method-badge.delete { background: #e34d59; }
.ep-path { font-size: 12px; font-family: "SF Mono", "Fira Code", monospace; color: #333; font-weight: 500; }
.ep-summary { flex: 1; font-size: 12px; color: #666; }
.ep-toggle { color: #999; flex-shrink: 0; }
.ep-body { padding: 0 16px 16px; border-top: 1px solid #f0f0f0; background: #fafbfc; }
.ep-desc { font-size: 12px; color: #666; padding: 10px 0 6px; line-height: 1.6; }
.ep-section { margin-top: 12px; }
.section-label { font-size: 11px; font-weight: 600; color: #333; margin-bottom: 6px; }
.params-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.params-table th { text-align: left; padding: 5px 8px; background: #f0f2f5; color: #666; font-weight: 500; }
.params-table td { padding: 5px 8px; border-bottom: 1px solid #f0f0f0; }
.params-table code { background: #f0f5ff; color: #0052D9; padding: 1px 3px; border-radius: 2px; font-size: 10px; }
.response-block { background: #1a1a2e; color: #a0e0a0; padding: 12px 14px; border-radius: 6px; font-size: 10px; line-height: 1.5; overflow-x: auto; font-family: "SF Mono", monospace; max-height: 200px; overflow-y: auto; }

/* Test Panel */
.test-panel { width: 340px; flex-shrink: 0; background: #fff; border: 1px solid #e8ecf0; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.06); position: sticky; top: 0; max-height: calc(100vh - 100px); overflow-y: auto; transition: width 0.2s; }
.test-panel.collapsed { width: 44px; overflow: hidden; }
.test-header { display: flex; align-items: center; gap: 8px; padding: 14px 16px; font-size: 14px; font-weight: 600; color: #333; cursor: pointer; border-bottom: 1px solid #f0f0f0; user-select: none; }
.test-body { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
.test-field label { display: block; font-size: 11px; font-weight: 500; color: #666; margin-bottom: 4px; }
.test-response { margin-top: 12px; }
.resp-status { font-size: 12px; font-weight: 600; margin-bottom: 6px; padding: 4px 8px; border-radius: 4px; display: inline-block; }
.resp-status.ok { background: #e6f7f0; color: #00a870; }
.resp-status.err { background: #fff0ed; color: #e34d59; }
.resp-body { background: #1a1a2e; color: #e0e0e0; padding: 12px 14px; border-radius: 6px; font-size: 10px; line-height: 1.5; overflow-x: auto; font-family: "SF Mono", monospace; max-height: 300px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
</style>
