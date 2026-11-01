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
      <p class="section-desc">配置监控数据来源。启动监控前需填写 OpenClaw 根文件夹路径。</p>
      
      <div v-if="monitorRunning" class="readonly-hint">
        <t-icon name="info-circle" size="14px" />
        <span>安全监控运行期间，数据源配置将被锁定，无法修改。请先终止监控后再进行配置调整。</span>
      </div>

      <div class="form-group">
        <label class="form-label">OpenClaw 根文件夹 <t-tag size="small" theme="danger" variant="light">必填</t-tag></label>
        <p class="form-hint">指定 OpenClaw 的根文件夹路径，系统将访问其下的 agents/sessions 等日志文件来检测 Round 事件。</p>
        <div class="input-row">
          <t-input
            v-model="openclaw_root"
            placeholder="请输入 OpenClaw 根文件夹的绝对路径"
            clearable
            size="large"
            :disabled="monitorRunning"
          />
          <t-button theme="primary" @click="saveSingle('openclaw_root')" :loading="saving === 'openclaw_root'" :disabled="monitorRunning">
            保存
          </t-button>
        </div>
        <div v-if="pathStatus.openclaw_root" class="path-status">
          <t-tag :theme="pathStatus.openclaw_root === 'ok' ? 'success' : 'warning'" variant="light" size="small">
            {{ pathStatus.openclaw_root === 'ok' ? '路径有效' : '路径不存在或不可读' }}
          </t-tag>
        </div>
      </div>

      <t-divider />

      <div class="form-group">
        <label class="form-label">交互数据来源</label>
        <p class="form-hint">选择从何处获取 Agent 的工具调用和请求/响应数据。默认从 OpenClaw 日志直接解析，也可选择从网关日志获取。</p>
        <t-switch v-model="use_gateway" @change="saveSingle('use_gateway')" :disabled="monitorRunning"><template #label>{{ use_gateway ? '从网关获取' : '从 OpenClaw 日志获取' }}</template></t-switch>
      </div>

      <div v-if="use_gateway">
        <t-divider />
        <div class="form-group">
          <label class="form-label">网关日志路径</label>
          <p class="form-hint">Portkey 网关日志目录路径，系统将从中读取请求/响应数据并解析 action。</p>
          <div class="input-row">
            <t-input
              v-model="gateway_log_path"
              placeholder="请输入网关日志目录的绝对路径"
              clearable
              size="large"
              :disabled="monitorRunning"
            />
            <t-button theme="primary" @click="saveSingle('gateway_log_path')" :loading="saving === 'gateway_log_path'" :disabled="monitorRunning">
              保存
            </t-button>
          </div>
          <div v-if="pathStatus.gateway_log_path" class="path-status">
            <t-tag :theme="pathStatus.gateway_log_path === 'ok' ? 'success' : 'warning'" variant="light" size="small">
              {{ pathStatus.gateway_log_path === 'ok' ? '路径有效' : '路径不存在或不可读' }}
            </t-tag>
          </div>
        </div>
      </div>

      <t-divider />

      <div class="form-group">
        <label class="form-label">工具调用追踪 <t-tag size="small" theme="primary" variant="light">调试</t-tag></label>
        <p class="form-hint">启用后，每次 Agent 调用工具时会将工具名、参数等信息写入 /tmp/openclaw-tool-trace.jsonl 文件，便于调试监控逻辑。</p>
        <t-switch v-model="tool_trace_enabled" @change="saveSingle('tool_trace_enabled')" :disabled="monitorRunning">
          <template #label>{{ tool_trace_enabled ? '已启用' : '已禁用' }}</template>
        </t-switch>
      </div>

    </div>

    <!-- Detection Config -->
    <div class="section-card">
      <div class="section-header">
        <t-icon name="search" size="20px" />
        <span>检测配置</span>
      </div>
      <p class="section-desc">配置运行监测时的安全检测策略。</p>

      <div v-if="monitorRunning" class="readonly-hint">
        <t-icon name="info-circle" size="14px" />
        <span>安全监控运行期间，检测配置将被锁定，无法修改。请先终止监控后再进行调整。</span>
      </div>

      <div class="form-group">
        <label class="form-label">工具返回结果提示注入监测关键词</label>
        <p class="form-hint">每行填写一个关键词（不区分大小写）。运行监测时将检查外部工具返回结果中是否包含这些关键词，以识别提示词注入攻击，例如：IMPORTANT、SYSTEM INSTRUCT。</p>
        <t-textarea
          v-model="tool_result_injection_keywords"
          :autosize="{ minRows: 4, maxRows: 10 }"
          placeholder="IMPORTANT&#10;SYSTEM INSTRUCT&#10;IGNORE PREVIOUS INSTRUCTIONS"
          :disabled="monitorRunning"
        />
        <div class="input-row save-row">
          <t-button theme="primary" @click="saveSingle('tool_result_injection_keywords')" :loading="saving === 'tool_result_injection_keywords'" :disabled="monitorRunning">
            保存
          </t-button>
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">参数内容检测规则（含各规则严重级）</label>
        <p class="form-hint">
          配置输入参数中哪些形态应被视为异常、以及各自的严重级。关闭开关表示使用系统内置默认规则；
          开启后以下拉选择各规则严重级，保存时自动序列化为配置。
        </p>

        <t-switch v-model="paramRulesEnabled" :disabled="monitorRunning">
          <template #label>{{ paramRulesEnabled ? '使用自定义规则' : '使用内置默认规则' }}</template>
        </t-switch>

        <div v-if="paramRulesEnabled" class="rules-form">
          <div class="rules-block">
            <div class="rules-title">路径类参数规则（path）</div>
            <div class="rule-row" v-for="r in PATH_RULES" :key="r.key">
              <div class="rule-info">
                <span class="rule-name">{{ r.label }}</span>
                <span class="rule-code">{{ r.key }}</span>
              </div>
              <t-select v-model="paramForm.path[r.key]" :options="SEVERITY_OPTIONS" :disabled="monitorRunning" style="width: 140px" />
            </div>
          </div>

          <div class="rules-block">
            <div class="rules-title">内容类参数规则（content）</div>
            <div class="rule-row">
              <div class="rule-info">
                <span class="rule-name">编码载荷块（Base64 可解码产物）</span>
                <span class="rule-code">encoded_blob</span>
              </div>
              <div class="rule-ctl">
                <t-select v-model="paramForm.content.encoded_blob_severity" :options="SEVERITY_OPTIONS" :disabled="monitorRunning" style="width: 120px" />
                <span class="ctl-label">最短 token</span>
                <t-input-number v-model="paramForm.content.encoded_blob_min_token" :min="8" :max="4096" :disabled="monitorRunning" style="width: 120px" />
              </div>
            </div>
            <div class="rule-row">
              <div class="rule-info">
                <span class="rule-name">危险命令特征共现（类数达标即升级）</span>
                <span class="rule-code">cmd_co_occurrence</span>
              </div>
              <div class="rule-ctl">
                <t-select v-model="paramForm.content.cmd_severity" :options="SEVERITY_OPTIONS" :disabled="monitorRunning" style="width: 120px" />
                <span class="ctl-label">共现类数</span>
                <t-input-number v-model="paramForm.content.cmd_classes" :min="1" :max="6" :disabled="monitorRunning" style="width: 110px" />
              </div>
            </div>
            <div class="rule-row">
              <div class="rule-info">
                <span class="rule-name">单类危险命令（低置信提示）</span>
                <span class="rule-code">cmd_severity_single</span>
              </div>
              <t-select v-model="paramForm.content.cmd_severity_single" :options="SEVERITY_OPTIONS" :disabled="monitorRunning" style="width: 140px" />
            </div>
            <div class="rule-row">
              <div class="rule-info">
                <span class="rule-name">注入标记投递（参数内容含注入标记）</span>
                <span class="rule-code">inject_markers</span>
              </div>
              <t-select v-model="paramForm.content.inject_severity" :options="SEVERITY_OPTIONS" :disabled="monitorRunning" style="width: 140px" />
            </div>
            <div class="rule-row">
              <div class="rule-info">
                <span class="rule-name">混淆特征（零宽/不可见字符）</span>
                <span class="rule-code">obfuscation</span>
              </div>
              <t-select v-model="paramForm.content.obfuscation" :options="SEVERITY_OPTIONS" :disabled="monitorRunning" style="width: 140px" />
            </div>
            <div class="rule-row">
              <div class="rule-info">
                <span class="rule-name">攻击语义标记（脚本头 + 隐藏持久化等）</span>
                <span class="rule-code">semantic_severity</span>
              </div>
              <t-select v-model="paramForm.content.semantic_severity" :options="SEVERITY_OPTIONS" :disabled="monitorRunning" style="width: 140px" />
            </div>
            <div class="rule-row col">
              <div class="rule-info">
                <span class="rule-name">注入标记词表</span>
                <span class="rule-code">inject_markers（每行一个）</span>
              </div>
              <t-textarea v-model="paramForm.content.injectMarkersText" :autosize="{ minRows: 3, maxRows: 8 }"
                placeholder="[SYSTEM NOTICE]&#10;remember-rule&#10;ignore all previous" :disabled="monitorRunning" />
            </div>
          </div>
        </div>

        <p v-if="paramRulesError" class="form-hint err-hint">{{ paramRulesError }}</p>
        <div class="input-row save-row">
          <t-button theme="primary" @click="saveSingle('param_content_rules')" :loading="saving === 'param_content_rules'" :disabled="monitorRunning">
            保存
          </t-button>
          <t-button variant="outline" @click="loadDefaultParamRules" :loading="loadingDefault" :disabled="monitorRunning">
            载入默认值
          </t-button>
          <t-button variant="outline" @click="resetParamRulesToDefault" :disabled="monitorRunning">
            恢复内置默认
          </t-button>
          <t-button variant="outline" @click="showParamRulesJson = !showParamRulesJson" :disabled="monitorRunning">
            {{ showParamRulesJson ? '隐藏' : '查看' }} JSON
          </t-button>
        </div>
        <pre v-if="showParamRulesJson" class="json-preview">{{ paramRulesJsonText }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"

const gateway_log_path = ref("")
const openclaw_root = ref("")
const use_gateway = ref(false)
const tool_trace_enabled = ref(false)
const tool_result_injection_keywords = ref("")
const paramRulesError = ref("")
const loadingDefault = ref(false)
const paramRulesEnabled = ref(false)
const showParamRulesJson = ref(false)

const SEVERITY_OPTIONS = [
  { label: "critical 严重", value: "critical" },
  { label: "high 高", value: "high" },
  { label: "medium 中", value: "medium" },
  { label: "low 低", value: "low" },
]
const PATH_RULES = [
  { key: "traversal_escape", label: "路径穿越逃逸（规范化后脱出原目录锚）" },
  { key: "traversal_attempt", label: "穿越未遂（含 ../ 但未脱出）" },
  { key: "home_expand", label: "Home 目录展开（~/ 开头）" },
  { key: "encoded_variant", label: "编码变体（URL 解码后路径变化）" },
  { key: "proc_sys_dev", label: "特殊路径（/proc /sys /dev）" },
  { key: "tmp_write", label: "临时目录写入（/tmp）" },
  { key: "dotfile_write", label: "点文件写入（隐藏文件）" },
  { key: "nul_control", label: "NUL / 控制字符注入" },
]

const emptyParamForm = () => ({
  path: PATH_RULES.reduce((acc, r) => { acc[r.key] = "medium"; return acc }, {}),
  content: {
    encoded_blob_severity: "high",
    encoded_blob_min_token: 40,
    cmd_severity: "critical",
    cmd_classes: 2,
    cmd_severity_single: "medium",
    inject_severity: "critical",
    obfuscation: "high",
    semantic_severity: "high",
    injectMarkersText: "",
  },
})
const paramForm = ref(emptyParamForm())

// 表单 → 配置 JSON（保存时提交）
const param_content_rules = computed(() => {
  if (!paramRulesEnabled.value) return ""
  const f = paramForm.value
  const markers = (f.content.injectMarkersText || "")
    .split("\n").map(s => s.trim()).filter(Boolean)
  return JSON.stringify({
    path: { ...f.path },
    content: {
      traversal_escape: undefined,
      encoded_blob: { severity: f.content.encoded_blob_severity, min_token: Number(f.content.encoded_blob_min_token) || 40, escalate: "critical" },
      cmd_co_occurrence: { classes: Number(f.content.cmd_classes) || 2, severity: f.content.cmd_severity, severity_single: f.content.cmd_severity_single },
      inject_severity: f.content.inject_severity,
      obfuscation: f.content.obfuscation,
      semantic_severity: f.content.semantic_severity,
      ...(markers.length ? { inject_markers: markers } : {}),
    },
  }, (k, v) => (v === undefined ? undefined : v))
})
const paramRulesJsonText = computed(() => param_content_rules.value || "（当前使用内置默认规则）")

function applyParamRulesToForm(rules) {
  const f = emptyParamForm()
  const p = (rules && rules.path) || {}
  for (const r of PATH_RULES) if (p[r.key]) f.path[r.key] = p[r.key]
  const c = (rules && rules.content) || {}
  const eb = c.encoded_blob || {}
  const co = c.cmd_co_occurrence || {}
  if (eb.severity) f.content.encoded_blob_severity = eb.severity
  if (eb.min_token) f.content.encoded_blob_min_token = eb.min_token
  if (co.severity) f.content.cmd_severity = co.severity
  if (co.classes) f.content.cmd_classes = co.classes
  if (co.severity_single) f.content.cmd_severity_single = co.severity_single
  if (c.inject_severity) f.content.inject_severity = c.inject_severity
  if (c.obfuscation) f.content.obfuscation = c.obfuscation
  if (c.semantic_severity) f.content.semantic_severity = c.semantic_severity
  if (Array.isArray(c.inject_markers)) f.content.injectMarkersText = c.inject_markers.join("\n")
  paramForm.value = f
}
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
      use_gateway.value = d.use_gateway === "true"
      tool_trace_enabled.value = d.tool_trace_enabled === "true"
      tool_result_injection_keywords.value = d.tool_result_injection_keywords || ""
      const raw = d.param_content_rules || ""
      paramRulesError.value = ""
      if (raw.trim()) {
        try {
          applyParamRulesToForm(JSON.parse(raw))
          paramRulesEnabled.value = true
        } catch {
          paramRulesEnabled.value = false
          paramRulesError.value = "已保存的规则无法解析，当前回退为内置默认；可点“载入默认值”后重新保存。"
        }
      } else {
        paramRulesEnabled.value = false
      }
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

async function loadDefaultParamRules() {
  loadingDefault.value = true
  try {
    const r = await fetch("/api/monitor/param-content-rules/default")
    const j = await r.json()
    if (j.ok) {
      applyParamRulesToForm(j.data)
      paramRulesEnabled.value = true
      paramRulesError.value = ""
      MessagePlugin.success("已载入内置默认规则，可逐项修改后保存")
    } else {
      MessagePlugin.error(j.error || "获取默认规则失败")
    }
  } catch { MessagePlugin.error("网络错误") }
  finally { loadingDefault.value = false }
}

function resetParamRulesToDefault() {
  paramRulesEnabled.value = false
  paramRulesError.value = ""
  MessagePlugin.success("已切换为内置默认规则，点击保存生效")
}

async function saveSingle(key) {
  saving.value = key
  const valueMap = {
    gateway_log_path: gateway_log_path.value,
    openclaw_root: openclaw_root.value,
    use_gateway: use_gateway.value ? "true" : "false",
    tool_trace_enabled: tool_trace_enabled.value ? "true" : "false",
    tool_result_injection_keywords: tool_result_injection_keywords.value,
    param_content_rules: param_content_rules.value,
  }
  if (key === "param_content_rules") {
    // 表单已约束严重级与数值范围，这里只保留解析兜底（正常不会触发）
    paramRulesError.value = ""
    const v = param_content_rules.value
    if (v) {
      try {
        const parsed = JSON.parse(v)
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          paramRulesError.value = "规则序列化异常"
          MessagePlugin.error("规则序列化异常")
          saving.value = ""
          return
        }
      } catch (e) {
        paramRulesError.value = `规则序列化失败: ${e.message}`
        MessagePlugin.error(`规则序列化失败: ${e.message}`)
        saving.value = ""
        return
      }
    }
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
.err-hint { color: #d54941; }
.rules-form { margin-top: 12px; border: 1px solid #e8ecf0; border-radius: 10px; background: #fff; overflow: hidden; }
.rules-block { padding: 12px 14px; }
.rules-block + .rules-block { border-top: 1px solid #eef2f7; }
.rules-title { font-size: 13px; font-weight: 600; color: #15303e; margin-bottom: 10px; }
.rule-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 7px 0; border-bottom: 1px dashed #f1f5f9; }
.rule-row:last-child { border-bottom: none; }
.rule-row.col { flex-direction: column; align-items: stretch; gap: 6px; }
.rule-info { min-width: 0; }
.rule-name { display: block; font-size: 12.5px; color: #334155; }
.rule-code { display: block; font-size: 11px; color: #94a3b8; font-family: ui-monospace, Consolas, monospace; }
.rule-ctl { display: flex; align-items: center; gap: 8px; }
.ctl-label { font-size: 12px; color: #64748b; }
.json-preview { background: #0f172a; color: #e2e8f0; border-radius: 8px; padding: 10px 14px; font-size: 11.5px; font-family: ui-monospace, Consolas, monospace; white-space: pre-wrap; word-break: break-all; margin-top: 8px; }
.input-row { display: flex; gap: 10px; align-items: center; }
.save-row { margin-top: 10px; }
.path-status { margin-top: 8px; }
.readonly-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 14px;
  background: #fff8e6;
  border: 1px solid #ffe58f;
  border-radius: 6px;
  font-size: 12px;
  color: #d48806;
  margin-bottom: 16px;
}
</style>
