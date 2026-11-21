<template>
    <!-- 监控配置页：监控启停控制 + 数据源配置 + 检测配置（提示注入词表 / 参数深度检测规则） -->
  <div class="config-tab">
    <!-- 监控控制卡片：状态图标 + 运行中呼吸光环 + 启停按钮（loading 防连点） -->
    <!-- Monitor Control -->
    <!-- 监控启停卡片：运行状态可视化 + 启动/终止按钮（互斥切换） -->
    <div class="control-card" :class="{ active: monitorRunning }">
<!-- 控制卡左半：图标与光环容器 -->
<!-- 相对定位，光环以其为锚点居中 -->
      <div class="control-bg">
<!-- 运行中呼吸光环：无限脉冲动画 -->
        <div class="pulse-ring" v-if="monitorRunning"></div>
<!-- 盾形状态图标：未启动灰、运行中绿 -->
        <div class="shield-icon" :class="{ active: monitorRunning }">
          <t-icon :name="monitorRunning ? 'secured' : 'lock-on'" size="36px" />
        </div>
      </div>
<!-- 控制卡右半：标题/描述/动作 -->
      <div class="control-content">
<!-- 状态标题：运行中/未启动双态文案 -->
        <div class="control-title">
          {{ monitorRunning ? '安全监控运行中' : '安全监控未启动' }}
        </div>
<!-- 状态描述：双态文案 -->
        <div class="control-desc">
          {{ monitorRunning ? '正在持续审计 Agent 行为，实时检测异常访问与合规违规' : '启动后将持续监听日志，实时检测 Agent 行为合规性' }}
        </div>
<!-- 动作行：启动/终止按钮按状态二选一 -->
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

    <!-- 数据源配置卡片：OpenClaw 根路径（必填）、采集源切换、网关日志路径、工具追踪开关 -->
      <!-- 分节头：图标 + 标题（数据源 / 检测配置两卡片共用样式） -->
    <!-- Config Form -->
      <!-- 运行期间配置锁定：避免热改路径导致采集错位，启停与配置互斥 -->
    <div class="section-card">
      <div class="section-header">
        <t-icon name="setting" size="20px" />
      <!-- 只读提示：运行期间配置锁定的可视化说明 -->
<!-- 分节标题文字 -->
        <span>数据源配置</span>
      </div>
<!-- 分节说明：启动前需填 OpenClaw 根路径 -->
      <p class="section-desc">配置监控数据来源。启动监控前需填写 OpenClaw 根文件夹路径。</p>
      
      <div v-if="monitorRunning" class="readonly-hint">
      <!-- 配置项模板（本页通用）：label + 说明 + 输入行 + 保存按钮 + 有效性状态 -->
        <t-icon name="info-circle" size="14px" />
        <span>安全监控运行期间，数据源配置将被锁定，无法修改。请先终止监控后再进行配置调整。</span>
      </div>

      <div class="form-group">
<!-- 字段标签：带必填标记 -->
<!-- 必填标记 -->
        <label class="form-label">OpenClaw 根文件夹 <t-tag size="small" theme="danger" variant="light">必填</t-tag></label>
<!-- 字段说明：访问 agents/sessions 等日志以检测 Round -->
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
        <!-- 路径有效性回显：保存后立即校验，ok/不存在双态标签 -->
        <div v-if="pathStatus.openclaw_root" class="path-status">
          <t-tag :theme="pathStatus.openclaw_root === 'ok' ? 'success' : 'warning'" variant="light" size="small">
            {{ pathStatus.openclaw_root === 'ok' ? '路径有效' : '路径不存在或不可读' }}
          </t-tag>
        </div>
      </div>

      <t-divider />

      <!-- 采集源二选一：OpenClaw 会话日志直读 / Portkey 网关日志（切换后自动保存） -->
      <div class="form-group">
      <!-- 网关日志路径（仅从网关获取时显示）：独立保存与有效性校验 -->
<!-- 采集源标签 -->
        <label class="form-label">交互数据来源</label>
<!-- 采集源说明：OpenClaw 直读 / 网关日志 -->
        <p class="form-hint">选择从何处获取 Agent 的工具调用和请求/响应数据。默认从 OpenClaw 日志直接解析，也可选择从网关日志获取。</p>
<!-- 采集源开关：切换即保存（saveSingle） -->
        <t-switch v-model="use_gateway" @change="saveSingle('use_gateway')" :disabled="monitorRunning"><template #label>{{ use_gateway ? '从网关获取' : '从 OpenClaw 日志获取' }}</template></t-switch>
      </div>

<!-- 网关模式附加表单：仅从网关获取时显示 -->
      <div v-if="use_gateway">
        <t-divider />
        <div class="form-group">
<!-- 网关路径标签 -->
          <label class="form-label">网关日志路径</label>
<!-- 网关路径说明：读取请求/响应并解析 action -->
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
          <!-- 网关路径同样带有效性回显：与 OpenClaw 根路径一致的校验口径 -->
          <div v-if="pathStatus.gateway_log_path" class="path-status">
            <t-tag :theme="pathStatus.gateway_log_path === 'ok' ? 'success' : 'warning'" variant="light" size="small">
              {{ pathStatus.gateway_log_path === 'ok' ? '路径有效' : '路径不存在或不可读' }}
            </t-tag>
          </div>
        </div>
      </div>

      <t-divider />

      <!-- 工具调用追踪（调试用途）：落盘 /tmp/openclaw-tool-trace.jsonl，供监控逻辑排障 -->
      <div class="form-group">
    <!-- 检测配置卡片：运行期锁定提示与两组检测规则（词表 / 参数规则） -->
<!-- 工具追踪标签：带调试标记 -->
        <label class="form-label">工具调用追踪 <t-tag size="small" theme="primary" variant="light">调试</t-tag></label>
<!-- 追踪说明：写入 /tmp/openclaw-tool-trace.jsonl -->
        <p class="form-hint">启用后，每次 Agent 调用工具时会将工具名、参数等信息写入 /tmp/openclaw-tool-trace.jsonl 文件，便于调试监控逻辑。</p>
<!-- 追踪开关：切换即保存 -->
        <t-switch v-model="tool_trace_enabled" @change="saveSingle('tool_trace_enabled')" :disabled="monitorRunning">
<!-- 追踪开关状态文案 -->
          <template #label>{{ tool_trace_enabled ? '已启用' : '已禁用' }}</template>
        </t-switch>
      </div>

    </div>

    <!-- 检测配置卡片：提示注入关键词词表 + 参数内容深度检测规则组 -->
    <!-- Detection Config -->
      <!-- 检测配置同样在运行期间锁定 -->
      <!-- 注入词表文本域：autosize 自适应，占位示例即推荐词项 -->
    <div class="section-card">
      <div class="section-header">
        <t-icon name="search" size="20px" />
<!-- 检测配置分节标题 -->
        <span>检测配置</span>
      </div>
<!-- 检测配置说明 -->
      <p class="section-desc">配置运行监测时的安全检测策略。</p>

      <div v-if="monitorRunning" class="readonly-hint">
        <t-icon name="info-circle" size="14px" />
        <span>安全监控运行期间，检测配置将被锁定，无法修改。请先终止监控后再进行调整。</span>
      </div>

      <!-- 提示注入关键词：每行一个、大小写不敏感，命中即写入判定报告（OWASP LLM01 口径） -->
      <div class="form-group">
      <!-- 词表保存行：独立保存按钮（与数据源配置分开保存） -->
        <label class="form-label">工具返回结果提示注入监测关键词</label>
      <!-- 参数内容检测规则区：说明 + 总开关 + 自定义规则表单 + 操作按钮组 -->
<!-- 词表说明：每行一个，大小写不敏感 -->
<!-- 命中即写入判定报告（OWASP LLM01 口径） -->
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
      <!-- 自定义规则总开关：关闭=使用内置默认（后端免配置），开启=下方逐条编辑 -->

      <!-- 参数内容深度检测规则：path 组与 content 组，逐条独立启用/定级，
           词表与阈值（min_token/classes 等）均在此可调，保存时序列化为 monitor_conf.param_content_rules -->
      <div class="form-group">
<!-- 参数规则标签 -->
        <label class="form-label">参数内容检测规则（含各规则严重级）</label>
        <p class="form-hint">
<!-- 参数规则说明：形态→异常 + 严重级可调 -->
          配置输入参数中哪些形态应被视为异常、以及各自的严重级。关闭开关表示使用系统内置默认规则；
          开启后以下拉选择各规则严重级，保存时自动序列化为配置。
        </p>
                <!-- 参数控件区：按 params 元数据渲染 severity/int/bool 控件，
                     控件 disabled 联动规则开关状态 -->
          <!-- 规则行：标题/说明/规则键 + 启用开关 + 参数控件 + 词表文本域；
               disabled 状态下整行降透明度提示不可用 -->

<!-- 自定义规则总开关：关=内置默认，开=逐条编辑 -->
        <t-switch v-model="paramRulesEnabled" :disabled="monitorRunning">
<!-- 规则模式文案：自定义/内置 -->
          <template #label>{{ paramRulesEnabled ? '使用自定义规则' : '使用内置默认规则' }}</template>
        </t-switch>

        <!-- 自定义规则表单：由后端规则目录接口自动渲染（base.py Rule 元数据驱动），
             新增规则无需改本页代码 -->
        <!-- 控件按参数类型分派：severity 下拉 / int 数字框 / bool 开关 / list 词表文本域 -->
<!-- 自定义规则表单：目录驱动渲染 -->
<!-- 新增规则无需改本页代码 -->
        <div v-if="paramRulesEnabled" class="rules-form">
<!-- 目录加载中提示 -->
          <div v-if="!ruleGroups.length" class="form-hint">规则目录加载中…</div>
<!-- 规则组块：path 组 / content 组 -->
          <div class="rules-block" v-for="g in ruleGroups" :key="g.side">
<!-- 组标题 -->
            <div class="rules-title">{{ g.title }}</div>
<!-- 组说明 -->
            <p class="rules-desc">{{ g.description }}</p>
<!-- 规则行循环：禁用行降透明度 -->
            <div class="rule-row" v-for="r in g.rules" :key="g.side + '.' + r.key" :class="{ 'rule-off': !ruleState[g.side][r.key].enabled }">
<!-- 规则信息列：名称/说明/代码键 -->
              <div class="rule-info">
              <!-- 词表参数行：数量回显 + 文本域（每行一项） -->
<!-- 规则名：含「仅写类工具/默认关闭」徽标 -->
                <span class="rule-name">
                  {{ r.label }}
<!-- 徽标：仅对写类工具生效 -->
                  <span v-if="r.needs_write_tool" class="rule-badge">仅写类工具</span>
<!-- 徽标：默认关闭需手动启用 -->
                  <span v-if="!r.default_enabled" class="rule-badge">默认关闭</span>
                </span>
<!-- 规则说明 -->
                <span class="rule-desc">{{ r.description }}</span>
<!-- 规则键 + 复位链接 -->
                <span class="rule-code">{{ r.key }}
<!-- 单条规则复位链接 -->
                  <a class="rule-reset" @click="resetRuleToDefault(g.side, r)">复位</a>
                </span>
              </div>
<!-- 规则控件列：开关 + 参数控件 -->
              <div class="rule-ctl">
                <t-switch v-model="ruleState[g.side][r.key].enabled" size="small" :disabled="monitorRunning" />
                <template v-for="p in r.params" :key="p.name">
                  <template v-if="p.type === 'severity'">
                    <t-select v-model="ruleState[g.side][r.key][p.name]" :options="severityOptions"
                      :disabled="monitorRunning || !ruleState[g.side][r.key].enabled" style="width: 118px" />
              <!-- 词表参数：每行一项，编辑即时写回本地编辑态（保存时统一序列化） -->
                  </template>
                  <template v-else-if="p.type === 'int'">
                    <span class="ctl-label">{{ p.label }}</span>
      <!-- 操作按钮组：保存 / 载入默认值 / 恢复内置默认 / 查看 JSON 预览 -->
                    <t-input-number v-model="ruleState[g.side][r.key][p.name]" :min="p.min" :max="p.max" theme="normal"
                      :disabled="monitorRunning || !ruleState[g.side][r.key].enabled" style="width: 104px" />
                  </template>
<!-- 布尔参数：开关 -->
                  <template v-else-if="p.type === 'bool'">
                    <span class="ctl-label">{{ p.label }}</span>
                    <t-switch v-model="ruleState[g.side][r.key][p.name]" size="small"
                      :disabled="monitorRunning || !ruleState[g.side][r.key].enabled" />
                  </template>
                </template>
      <!-- 规则配置错误提示（如已存配置解析失败）与操作按钮组：保存/载入默认/恢复内置/查看 JSON -->
              </div>
<!-- 词表参数区：整行换行占满 -->
              <div v-if="listParams(r).length" class="rule-row-list">
<!-- 词表参数行：数量回显 + 文本域 -->
                <div v-for="p in listParams(r)" :key="p.name" class="list-param">
                  <span class="ctl-label">{{ p.label }}（每行一个，共 {{ (ruleState[g.side][r.key][p.name] || []).length }} 项）</span>
<!-- 词表文本域：编辑即时写回本地编辑态 -->
                  <t-textarea :value="(ruleState[g.side][r.key][p.name] || []).join('\n')"
                    :autosize="{ minRows: 2, maxRows: 6 }" :disabled="monitorRunning || !ruleState[g.side][r.key].enabled"
                    @change="(v) => setListParam(g.side, r.key, p.name, v)" />
                </div>
              </div>
            </div>
          </div>
        </div>

<!-- 规则配置错误提示（已存配置解析失败时） -->
        <p v-if="paramRulesError" class="form-hint err-hint">{{ paramRulesError }}</p>
        <div class="input-row save-row">
      <!-- JSON 预览：只读 <pre> 展示当前生效配置，核对用 -->
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
<!-- JSON 预览：只读展示当前生效配置 -->
        <pre v-if="showParamRulesJson" class="json-preview">{{ paramRulesJsonText }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
// 本页状态与动作：配置项逐项保存（saveSingle），规则目录加载与本地编辑态管理
import { ref, computed, onMounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"

// 数据源配置的响应式状态：三项后端配置键的本地镜像（saveSingle 按键回写）
// 网关日志路径本地镜像（saveSingle 按键回写）
const gateway_log_path = ref("")
// OpenClaw 根路径本地镜像
const openclaw_root = ref("")
// 采集源开关镜像（false=OpenClaw 直读）
const use_gateway = ref(false)
// 工具追踪开关镜像（调试用途）
const tool_trace_enabled = ref(false)
// 提示注入关键词词表（textarea 文本 ↔ 后端按行存储）与规则配置的 UI 状态
// 注入词表镜像（textarea 文本）
const tool_result_injection_keywords = ref("")
// 规则配置错误信息
const paramRulesError = ref("")
// 载入默认值按钮 loading
const loadingDefault = ref(false)
// 自定义规则开关（false=内置默认）
const paramRulesEnabled = ref(false)
// JSON 预览展开状态
const showParamRulesJson = ref(false)

// 规则目录（后端 /param-content-rules/catalog 下发）：新增规则无需改前端
// 规则目录（后端 catalog 接口）与本地编辑态：ruleState[side][key] = {enabled, severity, ...参数}
const ruleGroups = ref([])
// 规则编辑态：ruleState[side][key] = {enabled, ...参数}
const ruleState = ref({ path: {}, content: {} })
// 严重级下拉选项：critical/high/medium/low
const severityOptions = ref([
  { label: "critical 严重", value: "critical" },
  { label: "high 高", value: "high" },
  { label: "medium 中", value: "medium" },
  { label: "low 低", value: "low" },
])

// 目录数据 → 本地编辑态初始化：默认 enabled/severity 取规则元数据，词表参数展开为数组
function initRuleState(catalog) {
// 编辑态骨架：path/content 双组
  const state = { path: {}, content: {} }
  // 逐组逐规则展开：enabled 取 active（后端当前生效值）优先、缺省取默认；
  // 词表参数展开为数组副本，避免编辑时直接改到目录对象。
// 逐组逐规则展开
  for (const g of catalog.groups || []) {
    state[g.side] = state[g.side] || {}
    // 每条规则一个 item：{enabled, ...各参数}——与后端配置结构一一对应。
    for (const r of g.rules) {
// 单条规则编辑态：enabled 取 active 优先、缺省取默认
      const item = { enabled: r.active ? r.active.enabled : r.default_enabled }
      for (const p of r.params || []) {
    // 参数当前值三来源：active > 默认；list 型必须数组化（textarea 双向需要）。
        const cur = r.active && r.active[p.name] !== undefined && r.active[p.name] !== null
          ? r.active[p.name] : p.default
// 词表参数数组化：textarea 双向需要
        item[p.name] = p.type === "list" ? [...(cur || [])] : cur
      }
// 写入编辑态：与后端配置结构一一对应
      state[g.side][r.key] = item
    }
  }
  ruleState.value = state
}

/** 把某条规则重置为默认值（enabled / severity / 阈值 / 词表） */
// 单条规则复位：恢复该规则的出厂默认（severity 与 enabled），不整页重置
function resetRuleToDefault(side, rule) {
  // 复位项只带默认 enabled/severity 与各参数出厂值：一键回到「无本地修改」状态。
// 复位骨架：出厂 enabled/severity
  const item = { enabled: rule.default_enabled, severity: rule.default_severity }
  for (const p of rule.params || []) {
  // severity 参数特殊：跟规则默认级而非参数通用默认，保持展示一致。
    item[p.name] = p.type === "severity" ? rule.default_severity
      : p.type === "list" ? [...(p.default || [])] : p.default
  }
// 单条规则复位写入
  ruleState.value[side][rule.key] = item
}

// 取规则的词表类参数（list 型）：渲染为每行一项的 textarea
function listParams(rule) {
// 取词表类参数（list 型）
  return (rule.params || []).filter(p => p.type === "list")
}

// 词表编辑回写：按行拆分为数组写入 ruleState（空行过滤）
function setListParam(side, key, name, text) {
// 文本→数组：按行拆分并过滤空行
  ruleState.value[side][key][name] = String(text || "")
    .split("\n").map(s => s.trim()).filter(Boolean)
}

// 表单 → 配置 JSON（保存时提交；每条规则都是对象，含 enabled 开关）
// 编辑态 → 后端配置结构的计算属性：仅当启用自定义规则时序列化，
// 词表参数仅在有改动时输出，保持配置最小化；关闭开关则整体回退内置默认
const param_content_rules = computed(() => {
// 关闭自定义：不输出配置（后端走内置默认）
  if (!paramRulesEnabled.value) return ""
  // payload 双段结构 {path, content}：与后端 monitor_conf.param_content_rules 的
  // 配置契约一致，每条规则序列化为 {enabled, ...参数} 对象。
// 序列化骨架：path/content 双段
  const payload = { path: {}, content: {} }
  for (const g of ruleGroups.value) {
    for (const r of g.rules) {
  // 编辑态缺失的规则跳过：目录加载未完成时不输出半成品配置。
      const st = ruleState.value[g.side] && ruleState.value[g.side][r.key]
      if (!st) continue
  // enabled 恒输出（含 false）：与「关闭单条规则」的语义区分于「删除配置项」。
// enabled 恒输出（含 false）：区别于「删除配置项」
      const obj = { enabled: !!st.enabled }
      for (const p of r.params || []) {
        obj[p.name] = st[p.name]
      }
      payload[g.side][r.key] = obj
    }
  }
// 序列化为保存用 JSON 字符串
  return JSON.stringify(payload)
})
// JSON 预览文本：只读展示当前生效（或内置默认）的规则配置，便于核对
const paramRulesJsonText = computed(() => param_content_rules.value || "（当前使用内置默认规则）")

// 规则目录加载：catalog 接口返回 {groups, severities}，失败时提示并保持内置默认
// 目录加载实现：成功时初始化编辑态（active 值回填）；失败静默——
// 规则 UI 依赖后端，接口不可用时保持内置默认且不阻塞整页。
async function loadRuleCatalog() {
  try {
    const r = await fetch("/api/monitor/param-content-rules/catalog")
    const j = await r.json()
    if (j.ok) {
// loadRuleCatalog 实现：fetch → ok 校验 → groups/severities 回填 → initRuleState；
// severities 映射为中文标签选项（critical 严重 / high 高 / medium 中 / low 低）。
      ruleGroups.value = j.data.groups || []
// monitorRunning：启停互斥的状态源；运行中所有配置项 disabled（模板绑定）
// 严重级列表映射为中文标签选项
      if (j.data.severities) {
// 中文标签映射表
        const cn = { critical: "严重", high: "高", medium: "中", low: "低" }
// severities → 「critical 严重」等选项
        severityOptions.value = j.data.severities.map(s => ({ label: `${s} ${cn[s] || ""}`.trim(), value: s }))
      }
// 目录就绪后初始化编辑态（active 回填）
      initRuleState(j.data)
    }
  } catch {}
}
// 保存中状态（按键记录）：同一时刻只允许一个保存动作，避免并发覆盖
const saving = ref("")
// 路径有效性回显：按键存 ok/invalid
const pathStatus = ref({})
// 监控运行状态（驱动全部配置项 disabled）
const monitorRunning = ref(false)
// 启停请求进行中（按钮 loading 防连点）
const controlling = ref(false)

// checkStatus：挂载期查询监控进程状态（页面刷新后恢复运行中标记）
// 挂载即拉取配置与规则目录：与后端配置键一一对应回填本地状态
onMounted(async () => {
// 挂载：先载配置
  await loadConfig()
  await loadRuleCatalog()
// 再查运行状态
  checkStatus()
})

// 配置加载实现：逐键回填本地镜像；param_content_rules 非法时
// 显式降级（关闭自定义开关并提示），配置坏值不致整页不可用。
async function loadConfig() {
  try {
// 配置加载（GET 全量键值）
    const r = await fetch("/api/monitor/config")
    const j = await r.json()
// loadConfig 实现：逐键回填；规则配置的解析失败显式降级为内置默认并提示，
// 后端 _path_status 顺带回填（首次加载即显示路径有效性）。
    if (j.ok) {
// 配置数据解包
      const d = j.data
// 逐键回填本地镜像
      gateway_log_path.value = d.gateway_log_path || ""
// 键回填：OpenClaw 根路径
      openclaw_root.value = d.openclaw_root || ""
// 键回填：采集源开关（字符串转布尔）
      use_gateway.value = d.use_gateway === "true"
// 键回填：追踪开关
      tool_trace_enabled.value = d.tool_trace_enabled === "true"
// 键回填：注入词表
      tool_result_injection_keywords.value = d.tool_result_injection_keywords || ""
// 已存规则配置原文
      const raw = d.param_content_rules || ""
      paramRulesError.value = ""
// 三态判定：非空 → 尝试解析
      if (raw.trim()) {
        try {
// 可解析 → 自定义模式（取值由 catalog active 回填）
          JSON.parse(raw)
// 载入默认后开启自定义开关
          paramRulesEnabled.value = true  // 具体取值由 catalog 接口的 active 值回填
        } catch {
      // 规则配置三态：非空且可解析 → 自定义；非空但坏 → 降级+提示；空 → 内置默认。
          paramRulesEnabled.value = false
          paramRulesError.value = "已保存的规则无法解析，当前回退为内置默认；可点“载入默认值”后重新保存。"
        }
      } else {
        paramRulesEnabled.value = false
      }
// 路径有效性回显（首次加载即显示）
      pathStatus.value = d._path_status || {}
    }
  } catch {}
}

// 监控状态轮询：仅挂载时查询一次（启停由按钮驱动状态，不做后台轮询）。
async function checkStatus() {
  try {
// 状态查询（挂载时一次）
    const r = await fetch("/api/monitor/status")
    const j = await r.json()
// 运行状态回填（页面刷新后恢复标记）
    if (j.ok) monitorRunning.value = j.data.running
  } catch {}
}

// startMonitor/stopMonitor 的 controlling 标志：请求期间按钮 loading，
// 防止重复启停把监控进程置于中间状态。
// 启动监控：POST /api/monitor/start，成功后锁定全部配置项（运行期只读）。
async function startMonitor() {
  controlling.value = true
  try {
// 启动请求
    const r = await fetch("/api/monitor/start", { method: "POST" })
    const j = await r.json()
    if (j.ok) {
      MessagePlugin.success(j.message || "监控已启动")
// 启动成功：进入运行中态
      monitorRunning.value = true
    } else {
// 启动失败提示
      MessagePlugin.error(j.error || "启动失败")
    }
  } catch { MessagePlugin.error("网络错误") }
  finally { controlling.value = false }
}

// 终止监控：成功后解锁配置项；启停互斥由 controlling 状态防连点。
async function stopMonitor() {
  controlling.value = true
  try {
// 停止请求
    const r = await fetch("/api/monitor/stop", { method: "POST" })
    const j = await r.json()
    if (j.ok) {
// 停止成功：解锁配置项
      MessagePlugin.success(j.message || "监控已停止")
// 停止成功：退出运行中态
      monitorRunning.value = false
    } else {
      MessagePlugin.error(j.error || "停止失败")
// stopMonitor 之后配置项解锁：模板 disabled 绑定 monitorRunning，状态即 UI。
    }
// loadDefaultParamRules：以出厂默认为起点的「微调流」——复位所有规则并开启
// 自定义开关；与 resetParamRulesToDefault（整体放弃自定义）语义互补。
  } catch { MessagePlugin.error("网络错误") }
  finally { controlling.value = false }
}

// 载入默认值：把每条规则复位到出厂默认并开启自定义开关——
// 用于「以默认为起点微调」的场景，不落盘直到显式保存。
async function loadDefaultParamRules() {
  loadingDefault.value = true
  try {
// 目录未加载时先拉目录
    if (!ruleGroups.value.length) await loadRuleCatalog()
    for (const g of ruleGroups.value) {
      for (const r of g.rules) resetRuleToDefault(g.side, r)
    }
    paramRulesEnabled.value = true
    paramRulesError.value = ""
    MessagePlugin.success("已载入内置默认规则，可逐项修改后保存")
  } catch { MessagePlugin.error("载入默认规则失败") }
  finally { loadingDefault.value = false }
}

// 恢复内置默认：直接关闭自定义开关（后端按内置默认执行），
// 比载入默认值更彻底，适合放弃全部自定义的场景。
function resetParamRulesToDefault() {
  paramRulesEnabled.value = false
  paramRulesError.value = ""
  MessagePlugin.success("已切换为内置默认规则，点击保存生效")
}

// saveSingle：单键保存的统一入口——valueMap 聚合全部配置键的当前值，
// PUT /api/monitor/config 按键回写，保存中状态按键隔离防并发覆盖。
async function saveSingle(key) {
// 按键记录保存中状态
  saving.value = key
// 单键保存的取值聚合：按 key 提交对应值
  const valueMap = {
// 取值项：网关日志路径
    gateway_log_path: gateway_log_path.value,
// 取值项：OpenClaw 根路径
    openclaw_root: openclaw_root.value,
// 取值项：采集源开关（后端按字符串存）
    use_gateway: use_gateway.value ? "true" : "false",
// 取值项：工具追踪开关
    tool_trace_enabled: tool_trace_enabled.value ? "true" : "false",
// 取值项：注入词表
    tool_result_injection_keywords: tool_result_injection_keywords.value,
// 取值项：参数规则（computed 序列化）
    param_content_rules: param_content_rules.value,
  }
    // param_content_rules 的解析兜底：序列化产物必须是 JSON 对象，
    // 异常时阻断保存并提示（正常路径表单已约束，此处防御程序性错误）。
  if (key === "param_content_rules") {
    // 表单已约束严重级与数值范围，这里只保留解析兜底（正常不会触发）
    paramRulesError.value = ""
// 规则序列化产物校验
    const v = param_content_rules.value
    if (v) {
      try {
// 解析兜底：必须是 JSON 对象
        const parsed = JSON.parse(v)
// 非对象（数组/原始值）：阻断保存
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
// 提交保存请求（PUT 单键）
    const r = await fetch("/api/monitor/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
// 请求体：单键 + 对应值
      body: JSON.stringify({ key, value: valueMap[key] })
    })
    const j = await r.json()
    if (j.ok) {
// 保存成功提示
      MessagePlugin.success("已保存")
      // 路径类配置保存后回传有效性：pathStatus 即时回显 ok/invalid。
// 路径类配置：保存后回显有效性
      if (j.data && j.data.path_valid !== undefined) {
// 保存后路径有效性即时回显
        pathStatus.value[key] = j.data.path_valid ? "ok" : "invalid"
      }
    } else {
      MessagePlugin.error(j.error || "保存失败")
    }
  } catch { MessagePlugin.error("网络错误") }
// 复位保存状态
  finally { saving.value = "" }
}
</script>

<style scoped>
/* 本页样式：监控控制卡片 + 配置表单 + 规则编辑行的布局与状态反馈 */
.config-tab { max-width: 720px; margin: 0 auto; padding-top: 20px; }

/* 控制卡片：深色渐变底，运行中切换为绿色系并点亮边框 */
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
/* 运行中态：背景/边框/阴影整体转绿，与未启动态形成强对比 */
.control-card.active {
  background: linear-gradient(135deg, #0a2e1a 0%, #0d3d23 50%, #0f5132 100%);
  border-color: rgba(0,200,143,0.2);
  box-shadow: 0 8px 32px rgba(0,168,112,0.15);
}
/* 图标容器：72px 圆形托盘，半透明描边 */
/* 图标容器：相对定位（光环锚点） */
.control-bg {
  position: relative;
  flex-shrink: 0;
}
/* 盾形状态图标：未启动半透明灰、运行中绿色发光 */
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
/* 运行中图标态：绿色描边 + 呼吸光晕 */
.shield-icon.active {
  background: rgba(0,200,143,0.15);
  border-color: rgba(0,200,143,0.4);
  color: #00c48f;
  box-shadow: 0 0 20px rgba(0,200,143,0.2);
}
/* 呼吸光环：绝对定位居中 + 无限脉冲动画（仅运行中渲染） */
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
/* 脉冲关键帧：1→1.6 缩放并淡出，2s 循环 */
@keyframes pulse {
  0% { transform: translate(-50%, -50%) scale(1); opacity: 1; }
  100% { transform: translate(-50%, -50%) scale(1.6); opacity: 0; }
}
/* 卡片右半部：标题/描述/按钮纵排 */
/* 控制卡右半弹性填充 */
.control-content { flex: 1; }
/* 状态标题样式 */
.control-title {
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 6px;
}
/* 状态描述样式 */
.control-desc {
  font-size: 13px;
  color: rgba(255,255,255,0.6);
  margin-bottom: 18px;
  line-height: 1.5;
}
/* 动作行：启停按钮横排 */
/* 动作行：横排 */
.control-actions {
  display: flex;
  gap: 12px;
}

/* Section Card */
/* 分节卡片：白底圆角容器（数据源/检测配置共用） */
.section-card {
  background: #fff;
  border-radius: 14px;
  border: 1px solid #e8ecf0;
  padding: 28px 32px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.03);
  margin-bottom: 20px;
}
/* 分节头：图标 + 标题 */
.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 600;
  color: #333;
  margin-bottom: 6px;
}
/* 分节说明样式 */
.section-desc {
  font-size: 13px;
  color: #999;
  margin-bottom: 20px;
}
/* 表单元素：组/标签/提示/错误色 */
/* 表单组间距 */
.form-group { margin-bottom: 4px; }
/* 字段标签样式 */
.form-label { display: block; font-size: 14px; font-weight: 500; color: #333; margin-bottom: 4px; }
/* 字段说明样式 */
.form-hint { font-size: 12px; color: #999; margin-bottom: 10px; }
/* 错误色提示 */
.err-hint { color: #d54941; }
/* 规则编辑区：外框容器 + 规则组块 + 组标题与说明 */
.rules-form { margin-top: 12px; border: 1px solid #e8ecf0; border-radius: 10px; background: #fff; overflow: hidden; }
/* 规则组块内边距 */
.rules-block { padding: 12px 14px; }
/* 组块间分隔线 */
.rules-block + .rules-block { border-top: 1px solid #eef2f7; }
/* 组标题样式 */
.rules-title { font-size: 13px; font-weight: 600; color: #15303e; margin-bottom: 4px; }
/* 组说明样式 */
.rules-desc { font-size: 11.5px; color: #94a3b8; margin: 0 0 10px; }
/* 规则行：flex 两端布局，启用/禁用透明度反馈；纵向形态用于窄屏换行 */
.rule-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px dashed #f1f5f9; flex-wrap: wrap; }
/* 末行无分隔线 */
.rule-row:last-child { border-bottom: none; }
/* 禁用行降透明度 */
.rule-off { opacity: 0.5; }
/* 纵向规则行（窄屏） */
.rule-row.col { flex-direction: column; align-items: stretch; gap: 6px; }
/* 规则信息列弹性布局 */
.rule-info { min-width: 0; flex: 1 1 320px; }
/* 规则信息列：名称/说明/代码键与徽标 */
/* 规则名样式 */
.rule-name { display: block; font-size: 12.5px; color: #334155; }
/* 规则说明样式 */
.rule-desc { display: block; font-size: 11.5px; color: #94a3b8; margin-top: 2px; line-height: 1.45; }
/* 徽标：仅写类工具 / 默认关闭的灰底小标签 */
.rule-badge { display: inline-block; margin-left: 6px; padding: 0 6px; border-radius: 8px; background: #eef2f7; color: #64748b; font-size: 10.5px; vertical-align: middle; }
/* 规则键等宽小字 */
.rule-code { display: block; font-size: 11px; color: #94a3b8; font-family: ui-monospace, Consolas, monospace; margin-top: 3px; }
/* 复位链接：蓝色可点，hover 下划线 */
/* 复位链接样式 */
.rule-reset { margin-left: 8px; color: #2f6fed; cursor: pointer; }
/* 复位链接 hover 下划线 */
.rule-reset:hover { text-decoration: underline; }
/* 词表参数区：整行换行占满 + 文本域纵排 */
.rule-row-list { flex: 1 1 100%; display: flex; flex-direction: column; gap: 8px; margin-top: 4px; }
/* 词表参数行样式 */
.list-param { display: flex; flex-direction: column; gap: 4px; }
/* 控件列：开关/下拉/数字框横排 */
.rule-ctl { display: flex; align-items: center; gap: 8px; }
/* 控件前缀标签样式 */
.ctl-label { font-size: 12px; color: #64748b; }
/* JSON 预览：暗色代码块，white-space 保留换行 */
.json-preview { background: #0f172a; color: #e2e8f0; border-radius: 8px; padding: 10px 14px; font-size: 11.5px; font-family: ui-monospace, Consolas, monospace; white-space: pre-wrap; word-break: break-all; margin-top: 8px; }
/* 输入行与保存行、路径状态通用间距 */
/* 输入行样式 */
.input-row { display: flex; gap: 10px; align-items: center; }
/* 保存行间距 */
.save-row { margin-top: 10px; }
/* 路径状态回显间距 */
.path-status { margin-top: 8px; }
/* 只读提示条：黄色警示底（运行期锁定提示） */
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
