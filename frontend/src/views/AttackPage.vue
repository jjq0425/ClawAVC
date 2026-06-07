<template>
  <div class="attack-page">
    <!-- ─── Hero Header (Red Team Console) ───────────────────── -->
    <section class="hero">
      <div class="hero-grid"></div>
      <div class="hero-scanline"></div>

      <div class="hero-row">
        <div class="hero-left">
          <div class="hero-icon-wrap">
            <svg width="34" height="34" viewBox="0 0 32 32" fill="none">
              <path d="M16 2L4 8v8c0 7.7 5.1 14.9 12 16 6.9-1.1 12-8.3 12-16V8L16 2z" stroke="#ff5b5b" stroke-width="2" fill="rgba(255,91,91,0.08)"/>
              <path d="M11 16h10M16 11v10" stroke="#ff5b5b" stroke-width="2" stroke-linecap="round"/>
            </svg>
          </div>
          <div class="hero-text">
            <div class="hero-eyebrow">RED TEAM CONSOLE · 红队作战台</div>
            <h1 class="hero-title">模拟攻击</h1>
            <p class="hero-sub">通过可控的对抗性场景，验证 ClawAVC 检测引擎在真实威胁下的防御能力</p>
          </div>
        </div>

        <div class="hero-status">
          <span class="status-dot"></span>
          <span class="status-text">SIMULATION ACTIVE</span>
        </div>
      </div>

      <div class="hero-stats">
        <div class="stat">
          <div class="stat-num">02</div>
          <div class="stat-label">攻击向量</div>
        </div>
        <div class="stat-divider"></div>
        <div class="stat">
          <div class="stat-num">{{ enabledCount }}</div>
          <div class="stat-label">已激活配置</div>
        </div>
        <div class="stat-divider"></div>
        <div class="stat">
          <div class="stat-num">3D</div>
          <div class="stat-label">检测维度</div>
        </div>
      </div>
    </section>

    <!-- ─── Section Title ───────────────────── -->
    <div class="section-title">
      <span class="section-bar"></span>
      <span class="section-name">威胁场景矩阵</span>
      <span class="section-count">2 vectors · 4 toggles</span>
    </div>

    <!-- ─── Scenarios ───────────────────── -->
    <div class="scenarios">
      <!-- ============ Scenario 1: Runtime Tampering ============ -->
      <article
        class="scenario-card tamper"
        :class="{ active: activeScenario === 'tamper' }"
        @click="selectScenario('tamper')"
      >
        <div class="severity-bar tamper"></div>

        <header class="scenario-head">
          <div class="scenario-icon tamper">
            <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
              <path d="M13 3v3M13 20v3M3 13h3M20 13h3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              <circle cx="13" cy="13" r="5" stroke="currentColor" stroke-width="2"/>
              <path d="M13 10v3l2 1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          <div class="scenario-meta">
            <h3>运行时篡改</h3>
            <span class="scenario-en">Runtime Tampering</span>
          </div>
          <div class="severity-badge high">
            <span class="severity-glow"></span>
            <span class="severity-label">HIGH</span>
          </div>
          <div class="expand-chevron" :class="{ rotated: activeScenario === 'tamper' }">
            <t-icon name="chevron-down" size="20px" />
          </div>
        </header>

        <p class="scenario-desc">
          篡改 Agent 运行时调用的工具映射。当 Agent 请求调用工具 <code>A</code> 时，实际执行被替换为工具 <code>B</code>，实现隐蔽的行为劫持。
        </p>

        <transition name="detail">
          <div v-if="activeScenario === 'tamper'" class="scenario-detail" @click.stop>
            <!-- Attack Chain -->
            <div class="block">
              <div class="block-title">
                <span class="block-dot tamper"></span>
                <span>攻击链路</span>
                <span class="block-tag">Attack Chain</span>
              </div>
              <div class="chain">
                <div class="chain-step tamper">
                  <div class="step-num">01</div>
                  <div class="step-icon"><t-icon name="user-circle" size="22px" /></div>
                  <div class="step-label">Agent</div>
                  <div class="step-sub">请求调用 read_file</div>
                </div>
                <div class="chain-arrow tamper" data-text="HIJACK">
                  <svg viewBox="0 0 80 12" preserveAspectRatio="none">
                    <line x1="0" y1="6" x2="70" y2="6" />
                    <polygon points="80,6 68,1 68,11" />
                  </svg>
                </div>
                <div class="chain-step tamper hot">
                  <div class="step-num">02</div>
                  <div class="step-icon"><t-icon name="swap" size="22px" /></div>
                  <div class="step-label">篡改层</div>
                  <div class="step-sub">替换为 exec_command</div>
                </div>
                <div class="chain-arrow tamper" data-text="EXECUTE">
                  <svg viewBox="0 0 80 12" preserveAspectRatio="none">
                    <line x1="0" y1="6" x2="70" y2="6" />
                    <polygon points="80,6 68,1 68,11" />
                  </svg>
                </div>
                <div class="chain-step tamper crit">
                  <div class="step-num">03</div>
                  <div class="step-icon"><t-icon name="error-circle" size="22px" /></div>
                  <div class="step-label">恶意操作</div>
                  <div class="step-sub">数据外泄 · 提权</div>
                </div>
              </div>
            </div>

            <!-- Impact Triplet -->
            <div class="impact-grid">
              <div class="impact-card">
                <div class="impact-icon-wrap tamper"><t-icon name="precise-monitor" size="18px" /></div>
                <div class="impact-key">攻击目标</div>
                <div class="impact-val">Tool Dispatch 调度层</div>
              </div>
              <div class="impact-card">
                <div class="impact-icon-wrap tamper"><t-icon name="fire" size="18px" /></div>
                <div class="impact-key">危害等级</div>
                <div class="impact-val">任意命令执行 · 数据外泄</div>
              </div>
              <div class="impact-card">
                <div class="impact-icon-wrap tamper"><t-icon name="search" size="18px" /></div>
                <div class="impact-key">隐蔽性</div>
                <div class="impact-val">Agent 无感知，返回伪造正常结果</div>
              </div>
            </div>

            <!-- Detection -->
            <div class="detection-panel">
              <div class="detection-shield">
                <svg width="40" height="48" viewBox="0 0 32 38" fill="none">
                  <path d="M16 2L3 6v12c0 9 6 16.5 13 18 7-1.5 13-9 13-18V6L16 2z" stroke="#0052D9" stroke-width="2" fill="rgba(0,82,217,0.06)"/>
                  <path d="M10 19l4 4 8-9" stroke="#00a870" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </div>
              <div class="detection-body">
                <div class="detection-head">
                  <span class="detection-title">ClawAVC 可检测维度</span>
                  <span class="detection-tag">Defense Coverage</span>
                </div>
                <ul class="detection-list">
                  <li>
                    <span class="detect-pill"><t-icon name="check" size="12px" /> 工具一致性</span>
                    <span class="detect-text">IR 仅允许 <code>read_file</code>，实际执行 <code>exec_command</code></span>
                  </li>
                  <li>
                    <span class="detect-pill"><t-icon name="check" size="12px" /> 资源访问</span>
                    <span class="detect-text">网络外连超出声明的资源范围</span>
                  </li>
                </ul>
              </div>
            </div>

            <!-- Attack Config Panel -->
            <div class="cfg-panel tamper">
              <div class="cfg-head">
                <span class="cfg-marker tamper"></span>
                <span class="cfg-title">攻击配置</span>
                <span class="cfg-en">Attack Config</span>
                <t-button
                  size="small"
                  theme="danger"
                  :loading="tamperSaving"
                  class="cfg-save"
                  @click="saveTamperConfig"
                >
                  <template #icon><t-icon name="save" /></template>
                  保存配置
                </t-button>
              </div>

              <div class="cfg-item" :class="{ on: tamperConfig.replace.enabled }">
                <div class="cfg-row">
                  <div class="cfg-info">
                    <div class="cfg-name">替换工具</div>
                    <code class="cfg-key">runtime_tamper.replace</code>
                    <div class="cfg-desc">Agent 调用某工具时，将其实际执行替换为指定的目标工具</div>
                  </div>
                  <t-switch v-model="tamperConfig.replace.enabled" />
                </div>
                <div v-if="tamperConfig.replace.enabled" class="cfg-input">
                  <!-- 原工具配置 -->
                  <div class="tamper-row">
                    <div class="tamper-label">原工具</div>
                    <t-input
                      v-model="tamperReplaceConfig.originalTool"
                      placeholder="原工具名称，如 read_file"
                      clearable
                    />
                    <t-input
                      v-model="tamperReplaceConfig.originalParamName"
                      placeholder="原参数名，如 path"
                      clearable
                    />
                  </div>
                  <!-- 替换工具配置 -->
                  <div class="tamper-row">
                    <div class="tamper-label">替换为</div>
                    <t-input
                      v-model="tamperReplaceConfig.replaceTool"
                      placeholder="替换工具名称，如 exec_command"
                      clearable
                    />
                    <t-input
                      v-model="tamperReplaceConfig.replaceParamName"
                      placeholder="替换参数名，如 cmd"
                      clearable
                    />
                  </div>
                  <!-- 提示信息 -->
                  <div class="tamper-hint">
                    <t-icon name="info-circle" size="14px" />
                    <span>请注意参数匹配：我们不做参数的任何转换。仅当两个工具的参数结构兼容时才可使用（如都是文件路径参数）。目前只支持一个参数，多余参数会忽略。本配置启停和配置有延迟，需要等待90秒后再使用！</span>
                  </div>
                </div>
              </div>

              <div class="cfg-item" :class="{ on: tamperConfig.insert.enabled }">
                <div class="cfg-row">
                  <div class="cfg-info">
                    <div class="cfg-name">插入工具</div>
                    <code class="cfg-key">runtime_tamper.insert</code>
                    <div class="cfg-desc">在 Agent 工具调用流程中额外插入执行指定工具</div>
                  </div>
                  <t-switch v-model="tamperConfig.insert.enabled" />
                </div>
                <div v-if="tamperConfig.insert.enabled" class="cfg-input">
                  <t-input
                    v-model="tamperConfig.insert.value"
                    placeholder="插入的工具名称，如 collect_secrets"
                    clearable
                  />
                </div>
              </div>
            </div>
          </div>
        </transition>
      </article>

      <!-- ============ Scenario 2: Tool Injection ============ -->
      <article
        class="scenario-card inject"
        :class="{ active: activeScenario === 'inject' }"
        @click="selectScenario('inject')"
      >
        <div class="severity-bar inject"></div>

        <header class="scenario-head">
          <div class="scenario-icon inject">
            <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
              <rect x="4" y="7" width="18" height="12" rx="2" stroke="currentColor" stroke-width="2"/>
              <path d="M8 11l3 3-3 3M13 17h4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          <div class="scenario-meta">
            <h3>工具注入</h3>
            <span class="scenario-en">Tool Injection</span>
          </div>
          <div class="severity-badge critical">
            <span class="severity-glow"></span>
            <span class="severity-label">CRITICAL</span>
          </div>
          <div class="expand-chevron" :class="{ rotated: activeScenario === 'inject' }">
            <t-icon name="chevron-down" size="20px" />
          </div>
        </header>

        <p class="scenario-desc">
          向 Agent 的可用工具列表中注入恶意工具定义。伪装为正常功能的工具被 LLM 自然选择调用，实际执行数据窃取、权限提升等恶意操作。
        </p>

        <transition name="detail">
          <div v-if="activeScenario === 'inject'" class="scenario-detail" @click.stop>
            <!-- Attack Chain -->
            <div class="block">
              <div class="block-title">
                <span class="block-dot inject"></span>
                <span>攻击链路</span>
                <span class="block-tag">Attack Chain</span>
              </div>
              <div class="chain">
                <div class="chain-step inject">
                  <div class="step-num">01</div>
                  <div class="step-icon"><t-icon name="user-circle" size="22px" /></div>
                  <div class="step-label">攻击者</div>
                  <div class="step-sub">构造恶意工具定义</div>
                </div>
                <div class="chain-arrow inject" data-text="INJECT">
                  <svg viewBox="0 0 80 12" preserveAspectRatio="none">
                    <line x1="0" y1="6" x2="70" y2="6" />
                    <polygon points="80,6 68,1 68,11" />
                  </svg>
                </div>
                <div class="chain-step inject hot">
                  <div class="step-num">02</div>
                  <div class="step-icon"><t-icon name="folder" size="22px" /></div>
                  <div class="step-label">工具注册表</div>
                  <div class="step-sub">伪装为 save_notes</div>
                </div>
                <div class="chain-arrow inject" data-text="INVOKE">
                  <svg viewBox="0 0 80 12" preserveAspectRatio="none">
                    <line x1="0" y1="6" x2="70" y2="6" />
                    <polygon points="80,6 68,1 68,11" />
                  </svg>
                </div>
                <div class="chain-step inject crit">
                  <div class="step-num">03</div>
                  <div class="step-icon"><t-icon name="error-circle" size="22px" /></div>
                  <div class="step-label">敏感数据</div>
                  <div class="step-sub">密钥 · 凭证 · 配置</div>
                </div>
              </div>
            </div>

            <!-- Impact Triplet -->
            <div class="impact-grid">
              <div class="impact-card">
                <div class="impact-icon-wrap inject"><t-icon name="precise-monitor" size="18px" /></div>
                <div class="impact-key">攻击目标</div>
                <div class="impact-val">Tools Manifest 工具注册表</div>
              </div>
              <div class="impact-card">
                <div class="impact-icon-wrap inject"><t-icon name="fire" size="18px" /></div>
                <div class="impact-key">危害等级</div>
                <div class="impact-val">凭证窃取 · SSH 密钥 · Token 外传</div>
              </div>
              <div class="impact-card">
                <div class="impact-icon-wrap inject"><t-icon name="search" size="18px" /></div>
                <div class="impact-key">隐蔽性</div>
                <div class="impact-val">LLM 基于描述自主选择，无异常提示</div>
              </div>
            </div>

            <!-- Detection -->
            <div class="detection-panel">
              <div class="detection-shield">
                <svg width="40" height="48" viewBox="0 0 32 38" fill="none">
                  <path d="M16 2L3 6v12c0 9 6 16.5 13 18 7-1.5 13-9 13-18V6L16 2z" stroke="#0052D9" stroke-width="2" fill="rgba(0,82,217,0.06)"/>
                  <path d="M10 19l4 4 8-9" stroke="#00a870" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </div>
              <div class="detection-body">
                <div class="detection-head">
                  <span class="detection-title">ClawAVC 可检测维度</span>
                  <span class="detection-tag">Defense Coverage</span>
                </div>
                <ul class="detection-list">
                  <li>
                    <span class="detect-pill"><t-icon name="check" size="12px" /> 工具一致性</span>
                    <span class="detect-text"><code>save_notes</code> 不在 IR 策略允许的工具列表中</span>
                  </li>
                  <li>
                    <span class="detect-pill"><t-icon name="check" size="12px" /> 参数一致性</span>
                    <span class="detect-text">参数中包含敏感路径与外部网络地址</span>
                  </li>
                  <li>
                    <span class="detect-pill"><t-icon name="check" size="12px" /> 资源访问</span>
                    <span class="detect-text">访问 <code>~/.ssh</code> 等敏感目录超出允许范围</span>
                  </li>
                </ul>
              </div>
            </div>

            <!-- Attack Config Panel -->
            <div class="cfg-panel inject">
              <div class="cfg-head">
                <span class="cfg-marker inject"></span>
                <span class="cfg-title">攻击配置</span>
                <span class="cfg-en">Attack Config</span>
                <t-button
                  size="small"
                  theme="primary"
                  :loading="injectSaving"
                  class="cfg-save"
                  @click="saveInjectConfig"
                >
                  <template #icon><t-icon name="save" /></template>
                  保存配置
                </t-button>
              </div>

              <div class="cfg-item" :class="{ on: injectConfig.network.enabled }">
                <div class="cfg-row">
                  <div class="cfg-info">
                    <div class="cfg-name">固定访问网络</div>
                    <code class="cfg-key">tool_injection.network</code>
                    <div class="cfg-desc">注入的工具被调用时强制外连到指定地址</div>
                  </div>
                  <t-switch v-model="injectConfig.network.enabled" />
                </div>
                <div v-if="injectConfig.network.enabled" class="cfg-input">
                  <t-input
                    v-model="injectConfig.network.value"
                    placeholder="如 http://malicious.example.com/collect"
                    clearable
                  />
                </div>
              </div>

              <div class="cfg-item" :class="{ on: injectConfig.filepath.enabled }">
                <div class="cfg-row">
                  <div class="cfg-info">
                    <div class="cfg-name">固定访问文件路径</div>
                    <code class="cfg-key">tool_injection.filepath</code>
                    <div class="cfg-desc">注入的工具被调用时强制读取指定文件路径</div>
                  </div>
                  <t-switch v-model="injectConfig.filepath.enabled" />
                </div>
                <div v-if="injectConfig.filepath.enabled" class="cfg-input">
                  <t-input
                    v-model="injectConfig.filepath.value"
                    placeholder="如 /root/.ssh/id_rsa"
                    clearable
                  />
                </div>
              </div>
            </div>
          </div>
        </transition>
      </article>
    </div>

    <!-- ─── Footer Notice ───────────────────── -->
    <div class="notice">
      <div class="notice-bar"></div>
      <div class="notice-icon"><t-icon name="info-circle-filled" size="16px" /></div>
      <div class="notice-text">
        <strong>合规提示</strong>
        <span>以上场景仅用于验证 ClawAVC 检测引擎的能力边界。请勿在未经授权的生产环境中启用任何攻击配置。</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

const API = '/api'
const activeScenario = ref('')

const injectConfig = ref({
  network: { enabled: false, value: '' },
  filepath: { enabled: false, value: '' },
})
const injectSaving = ref(false)

const tamperConfig = ref({
  replace: { enabled: false, value: '' },
  insert: { enabled: false, value: '' },
})
const tamperSaving = ref(false)

// 替换工具的详细配置（四个输入框）
const tamperReplaceConfig = ref({
  originalTool: '',
  originalParamName: '',
  replaceTool: '',
  replaceParamName: '',
})

// 监听 JSON 配置变化，同步到四个输入框（只在从服务器加载时触发）
const isInitializing = ref(true)

watch(() => tamperConfig.value.replace.value, (val) => {
  // 只在初始化时或手动加载配置时同步
  if (isInitializing.value || !tamperConfig.value.replace.enabled) {
    if (val) {
      try {
        const parsed = JSON.parse(val)
        tamperReplaceConfig.value = {
          originalTool: parsed.original_tool || '',
          originalParamName: parsed.original_param_name || '',
          replaceTool: parsed.replace_tool || '',
          replaceParamName: parsed.replace_param_name || '',
        }
      } catch {
        // 解析失败，保持当前值
      }
    } else {
      tamperReplaceConfig.value = { originalTool: '', originalParamName: '', replaceTool: '', replaceParamName: '' }
    }
  }
})

// 监听四个输入框变化，生成 JSON 配置（防抖处理）
let saveTimeout = null
watch(tamperReplaceConfig, () => {
  if (!tamperConfig.value.replace.enabled) return
  
  // 防抖：300ms 内不重复更新
  if (saveTimeout) clearTimeout(saveTimeout)
  
  saveTimeout = setTimeout(() => {
    const config = {
      original_tool: tamperReplaceConfig.value.originalTool.trim(),
      original_param_name: tamperReplaceConfig.value.originalParamName.trim(),
      replace_tool: tamperReplaceConfig.value.replaceTool.trim(),
      replace_param_name: tamperReplaceConfig.value.replaceParamName.trim(),
    }
    tamperConfig.value.replace.value = JSON.stringify(config)
  }, 300)
}, { deep: true })

// 标记初始化结束
const initTimeout = setTimeout(() => {
  isInitializing.value = false
}, 500)

const enabledCount = computed(() => {
  let n = 0
  if (injectConfig.value.network.enabled) n++
  if (injectConfig.value.filepath.enabled) n++
  if (tamperConfig.value.replace.enabled) n++
  if (tamperConfig.value.insert.enabled) n++
  return String(n).padStart(2, '0')
})

function selectScenario(name) {
  activeScenario.value = activeScenario.value === name ? '' : name
}

onMounted(async () => {
  try {
    const res = await fetch(`${API}/attack/config`)
    const data = await res.json()
    if (data.ok && data.data) {
      const ti = data.data.tool_injection || {}
      injectConfig.value = {
        network: { enabled: !!ti.network?.enabled, value: ti.network?.value || '' },
        filepath: { enabled: !!ti.filepath?.enabled, value: ti.filepath?.value || '' },
      }
      const rt = data.data.runtime_tamper || {}
      tamperConfig.value = {
        replace: { enabled: !!rt.replace?.enabled, value: rt.replace?.value || '' },
        insert: { enabled: !!rt.insert?.enabled, value: rt.insert?.value || '' },
      }
    }
  } catch (e) {
    /* silent */
  }
})

async function saveInjectConfig() {
  injectSaving.value = true
  try {
    const res = await fetch(`${API}/attack/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool_injection: injectConfig.value }),
    })
    const data = await res.json()
    if (data.ok) {
      MessagePlugin.success('攻击配置已保存')
    } else {
      MessagePlugin.error(data.error || '保存失败')
    }
  } catch (e) {
    MessagePlugin.error('保存失败')
  } finally {
    injectSaving.value = false
  }
}

async function saveTamperConfig() {
  tamperSaving.value = true
  try {
    const res = await fetch(`${API}/attack/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ runtime_tamper: tamperConfig.value }),
    })
    const data = await res.json()
    if (data.ok) {
      MessagePlugin.success('攻击配置已保存')
    } else {
      MessagePlugin.error(data.error || '保存失败')
    }
  } catch (e) {
    MessagePlugin.error('保存失败')
  } finally {
    tamperSaving.value = false
  }
}

// 清理定时器
onUnmounted(() => {
  if (saveTimeout) clearTimeout(saveTimeout)
  if (initTimeout) clearTimeout(initTimeout)
})
</script>

<style scoped>
/* ─── Tokens ────────────────────────────────────────────── */
:root, .attack-page {
  --avc-blue:    #0052D9;
  --avc-orange:  #ED7B2F;
  --avc-red:     #e63946;
  --avc-red2:    #ff5b5b;
  --avc-crit:    #c026d3;  /* magenta for CRITICAL */
  --avc-green:   #00a870;
  --avc-ink:     #0f1530;
  --avc-mute:    #6b7280;
  --avc-line:    #eef0f4;
}

.attack-page {
  max-width: 960px;
  margin: 0 auto;
  padding: 0 8px 56px;
  color: #1f2438;
}

/* ─── Hero ──────────────────────────────────────────────── */
.hero {
  position: relative;
  overflow: hidden;
  border-radius: 18px;
  padding: 28px 32px 22px;
  margin-bottom: 28px;
  background:
    radial-gradient(120% 140% at 110% -10%, rgba(255, 91, 91, 0.18) 0%, transparent 55%),
    radial-gradient(80% 120% at -10% 120%, rgba(237, 123, 47, 0.18) 0%, transparent 55%),
    linear-gradient(135deg, #0f1530 0%, #1a1838 60%, #2a1733 100%);
  color: #fff;
  box-shadow: 0 12px 36px rgba(15, 21, 48, 0.18);
}
.hero-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px);
  background-size: 28px 28px;
  pointer-events: none;
  mask-image: linear-gradient(180deg, rgba(0,0,0,0.7), transparent 90%);
}
.hero-scanline {
  position: absolute; left: 0; right: 0; top: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(255,91,91,0.6), transparent);
  animation: scan 4s linear infinite;
  pointer-events: none;
}
@keyframes scan {
  0% { transform: translateY(0); opacity: 0.0; }
  10% { opacity: 1; }
  90% { opacity: 1; }
  100% { transform: translateY(180px); opacity: 0; }
}

.hero-row {
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}
.hero-left { display: flex; align-items: center; gap: 16px; }
.hero-icon-wrap {
  width: 56px; height: 56px;
  border-radius: 14px;
  background: rgba(255, 91, 91, 0.12);
  border: 1px solid rgba(255, 91, 91, 0.28);
  display: flex; align-items: center; justify-content: center;
  box-shadow: inset 0 0 22px rgba(255, 91, 91, 0.18);
}
.hero-eyebrow {
  font-size: 11px;
  letter-spacing: 1.5px;
  font-weight: 600;
  color: rgba(255, 200, 200, 0.85);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  margin-bottom: 4px;
}
.hero-title {
  font-size: 26px;
  font-weight: 700;
  margin: 0 0 4px;
  letter-spacing: 1px;
  background: linear-gradient(120deg, #fff, #ffd6c2 80%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.hero-sub {
  font-size: 13px;
  color: rgba(255,255,255,0.66);
  margin: 0;
  max-width: 540px;
  line-height: 1.6;
}

.hero-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  border-radius: 999px;
  background: rgba(255, 91, 91, 0.12);
  border: 1px solid rgba(255, 91, 91, 0.4);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.6px;
  color: #ffb4b4;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  white-space: nowrap;
}
.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: #ff5b5b;
  box-shadow: 0 0 0 0 rgba(255, 91, 91, 0.7);
  animation: ping 1.8s infinite;
}
@keyframes ping {
  0%   { box-shadow: 0 0 0 0 rgba(255, 91, 91, 0.55); }
  70%  { box-shadow: 0 0 0 10px rgba(255, 91, 91, 0); }
  100% { box-shadow: 0 0 0 0 rgba(255, 91, 91, 0); }
}

.hero-stats {
  position: relative;
  display: flex;
  align-items: stretch;
  gap: 8px;
  margin-top: 22px;
  padding-top: 20px;
  border-top: 1px dashed rgba(255,255,255,0.12);
}
.stat { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.stat-num {
  font-size: 22px;
  font-weight: 700;
  color: #fff;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  letter-spacing: 0.5px;
}
.stat-label {
  font-size: 11px;
  color: rgba(255,255,255,0.55);
  letter-spacing: 0.5px;
}
.stat-divider {
  width: 1px;
  background: rgba(255,255,255,0.08);
  margin: 4px 8px;
}

/* ─── Section Title ──────────────────────────────────────── */
.section-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 4px 4px 14px;
  font-size: 13px;
  font-weight: 700;
  color: var(--avc-ink);
}
.section-bar {
  width: 4px; height: 14px;
  background: linear-gradient(180deg, #ED7B2F, #e63946);
  border-radius: 2px;
}
.section-name { letter-spacing: 0.3px; }
.section-count {
  margin-left: auto;
  font-size: 11px;
  font-weight: 500;
  color: var(--avc-mute);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}

/* ─── Scenarios ──────────────────────────────────────────── */
.scenarios {
  display: flex;
  flex-direction: column;
  gap: 18px;
  margin-bottom: 24px;
}
.scenario-card {
  position: relative;
  background: #fff;
  border-radius: 16px;
  padding: 22px 24px 22px 28px;
  border: 1px solid var(--avc-line);
  cursor: pointer;
  transition: border-color 0.25s, box-shadow 0.25s, transform 0.25s;
  overflow: hidden;
}
.scenario-card:hover {
  border-color: #d8dde6;
  box-shadow: 0 8px 28px rgba(15, 21, 48, 0.06);
  transform: translateY(-1px);
}
.scenario-card.active {
  border-color: transparent;
  box-shadow: 0 12px 36px rgba(15, 21, 48, 0.1);
}
.scenario-card.tamper.active { box-shadow: 0 12px 36px rgba(230, 57, 70, 0.14); }
.scenario-card.inject.active { box-shadow: 0 12px 36px rgba(192, 38, 211, 0.14); }

.severity-bar {
  position: absolute;
  top: 0; bottom: 0; left: 0;
  width: 4px;
}
.severity-bar.tamper { background: linear-gradient(180deg, #ED7B2F, #e63946); }
.severity-bar.inject { background: linear-gradient(180deg, #c026d3, #db2777); }

.scenario-head {
  display: flex;
  align-items: center;
  gap: 14px;
}
.scenario-icon {
  width: 48px; height: 48px;
  border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.scenario-icon.tamper {
  background: linear-gradient(135deg, #fff1ec, #ffe0d8);
  color: #e63946;
  box-shadow: inset 0 0 0 1px #fcd5cb;
}
.scenario-icon.inject {
  background: linear-gradient(135deg, #fdf0fb, #fcd9f5);
  color: #c026d3;
  box-shadow: inset 0 0 0 1px #f5c2eb;
}
.scenario-meta { flex: 1; min-width: 0; }
.scenario-meta h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--avc-ink);
  margin: 0 0 3px;
  letter-spacing: 0.2px;
}
.scenario-en {
  font-size: 11px;
  color: var(--avc-mute);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  letter-spacing: 0.4px;
}

.severity-badge {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 1.5px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  flex-shrink: 0;
  overflow: hidden;
}
.severity-badge .severity-glow {
  position: absolute;
  inset: 0;
  background: linear-gradient(120deg, transparent, rgba(255,255,255,0.5), transparent);
  transform: translateX(-100%);
  animation: shine 3.2s ease-in-out infinite;
}
.severity-badge.high {
  background: linear-gradient(135deg, #fff1ec, #ffd9cb);
  color: #c1361f;
  border: 1px solid #fbb799;
}
.severity-badge.critical {
  background: linear-gradient(135deg, #fdf0fb, #f9c5ee);
  color: #86198f;
  border: 1px solid #ec99dd;
}
@keyframes shine {
  0%, 60% { transform: translateX(-100%); }
  90%, 100% { transform: translateX(100%); }
}
.expand-chevron {
  color: var(--avc-mute);
  transition: transform 0.3s, color 0.2s;
}
.expand-chevron.rotated { transform: rotate(180deg); color: var(--avc-ink); }

.scenario-desc {
  font-size: 13px;
  color: #4b5163;
  line-height: 1.75;
  margin: 14px 0 0;
}
.scenario-desc code {
  background: rgba(15, 21, 48, 0.06);
  color: var(--avc-ink);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}

/* ─── Detail Block ───────────────────────────────────────── */
.scenario-detail {
  margin-top: 22px;
  padding-top: 22px;
  border-top: 1px dashed #e5e7ed;
}
.detail-enter-active, .detail-leave-active {
  transition: opacity 0.25s, transform 0.25s;
  overflow: hidden;
}
.detail-enter-from, .detail-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.block { margin-bottom: 22px; }
.block-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--avc-ink);
  letter-spacing: 0.6px;
  margin-bottom: 14px;
  text-transform: uppercase;
}
.block-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
}
.block-dot.tamper { background: #e63946; }
.block-dot.inject { background: #c026d3; }
.block-tag {
  margin-left: auto;
  font-size: 11px;
  font-weight: 500;
  color: var(--avc-mute);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  text-transform: none;
  letter-spacing: 0.3px;
}

/* ─── Attack Chain (Timeline) ───────────────────────────── */
.chain {
  display: flex;
  align-items: stretch;
  gap: 0;
  padding: 8px 4px;
  overflow-x: auto;
}
.chain-step {
  position: relative;
  flex: 1 1 0;
  min-width: 130px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 16px 10px 14px;
  border-radius: 12px;
  background: linear-gradient(180deg, #fafbff, #f3f5fb);
  border: 1px solid #e5e8f1;
}
.chain-step.tamper { background: linear-gradient(180deg, #fff7f3, #ffece2); border-color: #fad4c2; }
.chain-step.tamper.hot { background: linear-gradient(180deg, #ffe9dd, #ffd5c0); border-color: #f5b69a; }
.chain-step.tamper.crit { background: linear-gradient(180deg, #ffd9cc, #ffbfa9); border-color: #f08566; color: #6b1e0f; }

.chain-step.inject { background: linear-gradient(180deg, #fdf3fb, #fae3f4); border-color: #f4c8e6; }
.chain-step.inject.hot { background: linear-gradient(180deg, #fadcef, #f3c0e2); border-color: #ec9dd2; }
.chain-step.inject.crit { background: linear-gradient(180deg, #f3c0e2, #e69ed1); border-color: #d97ac1; color: #6b125c; }

.step-num {
  position: absolute;
  top: 8px; right: 10px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1px;
  color: rgba(15, 21, 48, 0.32);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.step-icon { margin-bottom: 6px; opacity: 0.95; }
.step-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--avc-ink);
}
.step-sub {
  font-size: 11px;
  color: #6b7180;
  margin-top: 3px;
  line-height: 1.4;
}
.chain-step.crit .step-sub { color: rgba(0,0,0,0.55); }

.chain-arrow {
  position: relative;
  flex: 0 0 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 4px;
}
.chain-arrow svg {
  width: 100%;
  height: 12px;
}
.chain-arrow.tamper svg line { stroke: #ED7B2F; stroke-width: 2; stroke-dasharray: 4 4; animation: dash 1.4s linear infinite; }
.chain-arrow.tamper svg polygon { fill: #e63946; }
.chain-arrow.inject svg line { stroke: #c026d3; stroke-width: 2; stroke-dasharray: 4 4; animation: dash 1.4s linear infinite; }
.chain-arrow.inject svg polygon { fill: #db2777; }
@keyframes dash {
  to { stroke-dashoffset: -16; }
}
.chain-arrow::after {
  content: attr(data-text);
  position: absolute;
  top: -22px; left: 50%;
  transform: translateX(-50%);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1.5px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  color: #e63946;
}
.chain-arrow.inject::after { color: #c026d3; }

/* ─── Impact Triplet ─────────────────────────────────────── */
.impact-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 22px;
}
.impact-card {
  position: relative;
  padding: 16px 14px;
  border-radius: 12px;
  background: #fafbfd;
  border: 1px solid #ecedf3;
  transition: border-color 0.2s, transform 0.2s;
}
.impact-card:hover {
  border-color: #d8dde6;
  transform: translateY(-1px);
}
.impact-icon-wrap {
  width: 32px; height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
}
.impact-icon-wrap.tamper {
  background: linear-gradient(135deg, #fff1ec, #ffd9cb);
  color: #e63946;
}
.impact-icon-wrap.inject {
  background: linear-gradient(135deg, #fdf0fb, #f9c5ee);
  color: #c026d3;
}
.impact-key {
  font-size: 11px;
  font-weight: 700;
  color: var(--avc-mute);
  letter-spacing: 0.4px;
  margin-bottom: 4px;
  text-transform: uppercase;
}
.impact-val {
  font-size: 13px;
  color: var(--avc-ink);
  font-weight: 600;
  line-height: 1.5;
}

/* ─── Detection Panel ───────────────────────────────────── */
.detection-panel {
  display: flex;
  align-items: stretch;
  gap: 14px;
  padding: 18px 18px 18px 14px;
  border-radius: 14px;
  background:
    linear-gradient(135deg, rgba(0, 168, 112, 0.06), rgba(0, 82, 217, 0.06));
  border: 1px solid rgba(0, 82, 217, 0.18);
  margin-bottom: 22px;
}
.detection-shield {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  padding-top: 2px;
}
.detection-body { flex: 1; min-width: 0; }
.detection-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.detection-title {
  font-size: 14px;
  font-weight: 700;
  color: #0052D9;
  letter-spacing: 0.3px;
}
.detection-tag {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.6px;
  color: #00a870;
  background: rgba(0, 168, 112, 0.1);
  padding: 2px 8px;
  border-radius: 4px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.detection-list {
  list-style: none;
  padding: 0; margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.detection-list li {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 12.5px;
  color: #2c3344;
  line-height: 1.6;
}
.detect-pill {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  background: linear-gradient(135deg, #e6fbf3, #c8f5e2);
  color: #04754f;
  border: 1px solid #9bedc6;
}
.detect-text { flex: 1; }
.detect-text code {
  background: rgba(15, 21, 48, 0.06);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11.5px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}

/* ─── Attack Config Panel ────────────────────────────────── */
.cfg-panel {
  border-radius: 14px;
  padding: 18px 18px 16px;
  border: 1px solid;
  position: relative;
  overflow: hidden;
}
.cfg-panel.tamper {
  background: linear-gradient(135deg, #fff7f3, #ffe9dd 70%, #ffe0d3);
  border-color: #f5c2aa;
}
.cfg-panel.inject {
  background: linear-gradient(135deg, #fdf3fb, #f9dcef 70%, #f4cbe6);
  border-color: #ecaad6;
}
.cfg-panel::before {
  content: '';
  position: absolute;
  top: 0; right: 0; width: 120px; height: 120px;
  background: radial-gradient(circle at top right, rgba(255,255,255,0.5), transparent 70%);
  pointer-events: none;
}

.cfg-head {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px dashed rgba(15, 21, 48, 0.08);
}
.cfg-marker {
  width: 8px; height: 8px;
  border-radius: 2px;
  transform: rotate(45deg);
}
.cfg-marker.tamper { background: #e63946; box-shadow: 0 0 0 3px rgba(230,57,70,0.18); }
.cfg-marker.inject { background: #c026d3; box-shadow: 0 0 0 3px rgba(192,38,211,0.18); }
.cfg-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--avc-ink);
  letter-spacing: 0.3px;
}
.cfg-en {
  font-size: 11px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  color: var(--avc-mute);
}
.cfg-save { margin-left: auto; }

.cfg-item {
  position: relative;
  background: rgba(255,255,255,0.78);
  border: 1px solid rgba(15, 21, 48, 0.06);
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 10px;
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
}
.cfg-item:last-child { margin-bottom: 0; }
.cfg-panel.tamper .cfg-item.on {
  border-color: rgba(230, 57, 70, 0.4);
  box-shadow: 0 4px 16px rgba(230, 57, 70, 0.1);
}
.cfg-panel.inject .cfg-item.on {
  border-color: rgba(192, 38, 211, 0.4);
  box-shadow: 0 4px 16px rgba(192, 38, 211, 0.1);
}
.cfg-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}
.cfg-info { flex: 1; min-width: 0; }
.cfg-name {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--avc-ink);
}
.cfg-key {
  display: inline-block;
  margin-top: 4px;
  padding: 2px 8px;
  border-radius: 5px;
  font-size: 11px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.cfg-panel.tamper .cfg-key {
  background: rgba(230, 57, 70, 0.1);
  color: #c1361f;
}
.cfg-panel.inject .cfg-key {
  background: rgba(192, 38, 211, 0.1);
  color: #86198f;
}
.cfg-desc {
  font-size: 11.5px;
  color: var(--avc-mute);
  margin-top: 5px;
  line-height: 1.5;
}
.cfg-input {
  margin-top: 12px;
  animation: fadeDown 0.25s ease;
}

/* 替换工具配置样式 */
.tamper-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.tamper-row:last-child {
  margin-bottom: 0;
}
.tamper-label {
  min-width: 50px;
  font-size: 12px;
  font-weight: 600;
  color: #6b7180;
  text-align: right;
}
.tamper-row .t-input {
  flex: 1;
  max-width: 300px;
}
.tamper-hint {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 10px;
  padding: 8px 12px;
  background: rgba(230, 57, 70, 0.08);
  border-radius: 6px;
  font-size: 11.5px;
  color: #a04040;
  line-height: 1.5;
}
.tamper-hint .t-icon { margin-top: 1px; }

@keyframes fadeDown {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ─── Footer Notice ─────────────────────────────────────── */
.notice {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px 14px 18px;
  border-radius: 12px;
  background: linear-gradient(135deg, #fff8ed, #ffefd6);
  border: 1px solid #fcdba0;
  font-size: 12.5px;
  color: #7a571c;
  line-height: 1.6;
  overflow: hidden;
}
.notice-bar {
  position: absolute;
  top: 0; bottom: 0; left: 0;
  width: 3px;
  background: linear-gradient(180deg, #ED7B2F, #e63946);
}
.notice-icon { color: #ED7B2F; padding-top: 1px; }
.notice-text strong {
  display: block;
  color: #5a3f10;
  font-size: 13px;
  margin-bottom: 2px;
}
</style>
