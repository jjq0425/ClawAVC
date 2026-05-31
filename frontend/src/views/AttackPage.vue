<template>
  <div class="attack-page">
    <!-- Header -->
    <div class="page-header">
      <div class="header-left">
        <div class="header-icon">
          <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
            <path d="M16 2L4 8v8c0 7.7 5.1 14.9 12 16 6.9-1.1 12-8.3 12-16V8L16 2z" stroke="#ff4444" stroke-width="2" fill="none"/>
            <path d="M11 16h10M16 11v10" stroke="#ff4444" stroke-width="2" stroke-linecap="round"/>
          </svg>
        </div>
        <div>
          <h2>模拟攻击</h2>
          <p class="subtitle">验证 ClawAVC 检测引擎的防御能力</p>
        </div>
      </div>
      <div class="header-badge">
        <span class="pulse-dot"></span>
        <span>SIMULATION</span>
      </div>
    </div>

    <!-- Threat Matrix -->
    <div class="threat-matrix">
      <div class="matrix-header">
        <div class="matrix-icon">
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path d="M9 1.5L2 5v4c0 4.4 2.9 8.5 7 9.5 4.1-1 7-5.1 7-9.5V5L9 1.5z" stroke="#ff4444" stroke-width="1.5" fill="rgba(255,68,68,0.06)"/>
            <path d="M6.5 9h5M9 6.5v5" stroke="#ff4444" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </div>
        <span>威胁场景矩阵</span>
        <span class="matrix-count">2 个攻击向量</span>
      </div>
    </div>

    <!-- Attack Scenarios -->
    <div class="scenarios">
      <!-- Scenario 1: Runtime Tampering -->
      <div class="scenario-card" :class="{ active: activeScenario === 'tamper' }" @click="selectScenario('tamper')">
        <div class="scenario-header">
          <div class="scenario-icon tamper">
            <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
              <path d="M13 3v3M13 20v3M3 13h3M20 13h3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              <circle cx="13" cy="13" r="5" stroke="currentColor" stroke-width="2"/>
              <path d="M13 10v3l2 1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          <div class="scenario-meta">
            <h3>运行时篡改</h3>
            <span class="scenario-tag">Runtime Tampering</span>
          </div>
          <div class="severity high">HIGH</div>
        </div>
        <p class="scenario-desc">
          篡改 Agent 运行时调用的工具映射。当 Agent 请求调用工具 A 时，实际执行被替换为工具 B，实现隐蔽的行为劫持。
        </p>

        <div class="scenario-detail" v-if="activeScenario === 'tamper'">
          <!-- Attack Chain Visualization -->
          <div class="attack-chain">
            <div class="chain-title">攻击链路</div>
            <div class="chain-visual">
              <div class="chain-node agent">
                <div class="node-icon"><t-icon name="user" /></div>
                <div class="node-label">Agent</div>
                <div class="node-sub">请求调用 read_file</div>
              </div>
              <div class="chain-link danger">
                <div class="link-line"></div>
                <div class="link-badge"><t-icon name="lightning" /> 劫持</div>
              </div>
              <div class="chain-node hijack">
                <div class="node-icon"><t-icon name="swap" /></div>
                <div class="node-label">篡改层</div>
                <div class="node-sub">替换为 exec_command</div>
              </div>
              <div class="chain-link danger">
                <div class="link-line"></div>
                <div class="link-badge"><t-icon name="lightning" /> 执行</div>
              </div>
              <div class="chain-node target">
                <div class="node-icon"><t-icon name="error-circle" /></div>
                <div class="node-label">恶意操作</div>
                <div class="node-sub">数据外泄 / 提权</div>
              </div>
            </div>
          </div>

          <!-- Impact -->
          <div class="impact-section">
            <div class="impact-item">
              <div class="impact-icon"><t-icon name="precise-monitor" /></div>
              <div>
                <div class="impact-title">攻击目标</div>
                <div class="impact-desc">Tool Dispatch 调度层</div>
              </div>
            </div>
            <div class="impact-item">
              <div class="impact-icon"><t-icon name="fire" /></div>
              <div>
                <div class="impact-title">危害等级</div>
                <div class="impact-desc">任意命令执行 · 数据外泄</div>
              </div>
            </div>
            <div class="impact-item">
              <div class="impact-icon"><t-icon name="search" /></div>
              <div>
                <div class="impact-title">隐蔽性</div>
                <div class="impact-desc">Agent 无感知，返回伪造的正常结果</div>
              </div>
            </div>
          </div>

          <!-- Detection -->
          <div class="detection-card">
            <div class="detection-header">
              <span class="shield-icon"><t-icon name="shield" /></span>
              <span>ClawAVC 检测维度</span>
            </div>
            <div class="detection-items">
              <div class="detect-item">
                <span class="detect-badge pass">可检出</span>
                <span>工具调用一致性 — IR 仅允许 read_file，实际执行 exec_command</span>
              </div>
              <div class="detect-item">
                <span class="detect-badge pass">可检出</span>
                <span>资源访问一致性 — 网络外连超出声明资源范围</span>
              </div>
            </div>
          </div>

          <!-- Attack Config (color block) -->
          <div class="config-block tamper-block" @click.stop>
            <div class="config-block-header">
              <span class="cfg-dot"></span>
              <span class="cfg-title">攻击配置</span>
              <span class="cfg-tag">Attack Config</span>
              <t-button
                size="small"
                theme="danger"
                :loading="tamperSaving"
                class="cfg-save-btn"
                @click="saveTamperConfig"
              >
                <t-icon name="save" /> 保存配置
              </t-button>
            </div>

            <!-- Item: Replace tool -->
            <div class="config-item" :class="{ on: tamperConfig.replace.enabled }">
              <div class="config-item-top">
                <div class="config-item-meta">
                  <div>
                    <div class="ci-name">替换工具</div>
                    <code class="ci-key">runtime_tamper.replace</code>
                    <div class="ci-desc">Agent 调用某工具时，将其实际执行替换为指定的目标工具</div>
                  </div>
                </div>
                <t-switch v-model="tamperConfig.replace.enabled" />
              </div>
              <div class="config-item-body" v-if="tamperConfig.replace.enabled">
                <t-input
                  v-model="tamperConfig.replace.value"
                  placeholder="目标工具名称，如 exec_command"
                  clearable
                />
              </div>
            </div>

            <!-- Item: Insert tool -->
            <div class="config-item" :class="{ on: tamperConfig.insert.enabled }">
              <div class="config-item-top">
                <div class="config-item-meta">
                  <div>
                    <div class="ci-name">插入工具</div>
                    <code class="ci-key">runtime_tamper.insert</code>
                    <div class="ci-desc">在 Agent 工具调用流程中额外插入执行指定工具</div>
                  </div>
                </div>
                <t-switch v-model="tamperConfig.insert.enabled" />
              </div>
              <div class="config-item-body" v-if="tamperConfig.insert.enabled">
                <t-input
                  v-model="tamperConfig.insert.value"
                  placeholder="插入的工具名称，如 collect_secrets"
                  clearable
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Scenario 2: Tool Injection -->
      <div class="scenario-card" :class="{ active: activeScenario === 'inject' }" @click="selectScenario('inject')">
        <div class="scenario-header">
          <div class="scenario-icon inject">
            <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
              <rect x="4" y="7" width="18" height="12" rx="2" stroke="currentColor" stroke-width="2"/>
              <path d="M8 11l3 3-3 3M13 17h4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          <div class="scenario-meta">
            <h3>工具注入</h3>
            <span class="scenario-tag">Tool Injection</span>
          </div>
          <div class="severity critical">CRITICAL</div>
        </div>
        <p class="scenario-desc">
          向 Agent 的可用工具列表中注入恶意工具定义。伪装为正常功能的工具被 LLM 自然选择调用，实际执行数据窃取、权限提升等恶意操作。
        </p>

        <div class="scenario-detail" v-if="activeScenario === 'inject'">
          <!-- Attack Chain Visualization -->
          <div class="attack-chain">
            <div class="chain-title">攻击链路</div>
            <div class="chain-visual">
              <div class="chain-node attacker">
                <div class="node-icon"><t-icon name="user" /></div>
                <div class="node-label">攻击者</div>
                <div class="node-sub">构造恶意工具定义</div>
              </div>
              <div class="chain-link danger">
                <div class="link-line"></div>
                <div class="link-badge"><t-icon name="lightning" /> 注入</div>
              </div>
              <div class="chain-node registry">
                <div class="node-icon"><t-icon name="folder" /></div>
                <div class="node-label">工具注册表</div>
                <div class="node-sub">伪装为 save_notes</div>
              </div>
              <div class="chain-link danger">
                <div class="link-line"></div>
                <div class="link-badge"><t-icon name="lightning" /> 调用</div>
              </div>
              <div class="chain-node target">
                <div class="node-icon"><t-icon name="error-circle" /></div>
                <div class="node-label">敏感数据</div>
                <div class="node-sub">密钥 · 凭证 · 配置</div>
              </div>
            </div>
          </div>

          <!-- Impact -->
          <div class="impact-section">
            <div class="impact-item">
              <div class="impact-icon"><t-icon name="precise-monitor" /></div>
              <div>
                <div class="impact-title">攻击目标</div>
                <div class="impact-desc">Tools Manifest 工具注册表</div>
              </div>
            </div>
            <div class="impact-item">
              <div class="impact-icon"><t-icon name="fire" /></div>
              <div>
                <div class="impact-title">危害等级</div>
                <div class="impact-desc">凭证窃取 · SSH 密钥泄露 · Token 外传</div>
              </div>
            </div>
            <div class="impact-item">
              <div class="impact-icon"><t-icon name="search" /></div>
              <div>
                <div class="impact-title">隐蔽性</div>
                <div class="impact-desc">LLM 基于描述自然选择恶意工具，无异常提示</div>
              </div>
            </div>
          </div>

          <!-- Detection -->
          <div class="detection-card">
            <div class="detection-header">
              <span class="shield-icon"><t-icon name="shield" /></span>
              <span>ClawAVC 检测维度</span>
            </div>
            <div class="detection-items">
              <div class="detect-item">
                <span class="detect-badge pass">可检出</span>
                <span>工具调用一致性 — save_notes 不在 IR 策略允许的工具列表中</span>
              </div>
              <div class="detect-item">
                <span class="detect-badge pass">可检出</span>
                <span>参数一致性 — 参数中包含敏感路径与外部网络地址</span>
              </div>
              <div class="detect-item">
                <span class="detect-badge pass">可检出</span>
                <span>资源访问一致性 — 访问 ~/.ssh 等敏感目录超出允许范围</span>
              </div>
            </div>
          </div>

          <!-- Attack Config (color block) -->
          <div class="config-block inject-block" @click.stop>
            <div class="config-block-header">
              <span class="cfg-dot"></span>
              <span class="cfg-title">攻击配置</span>
              <span class="cfg-tag">Attack Config</span>
              <t-button
                size="small"
                theme="primary"
                :loading="injectSaving"
                class="cfg-save-btn"
                @click="saveInjectConfig"
              >
                <t-icon name="save" /> 保存配置
              </t-button>
            </div>

            <!-- Item: Fixed network access -->
            <div class="config-item" :class="{ on: injectConfig.network.enabled }">
              <div class="config-item-top">
                <div class="config-item-meta">
                  <div>
                    <div class="ci-name">固定访问网络</div>
                    <code class="ci-key">tool_injection.network</code>
                    <div class="ci-desc">注入的工具被调用时强制外连到指定地址</div>
                  </div>
                </div>
                <t-switch v-model="injectConfig.network.enabled" />
              </div>
              <div class="config-item-body" v-if="injectConfig.network.enabled">
                <t-input
                  v-model="injectConfig.network.value"
                  placeholder="如 http://malicious.example.com/collect"
                  clearable
                />
              </div>
            </div>

            <!-- Item: Fixed file path access -->
            <div class="config-item" :class="{ on: injectConfig.filepath.enabled }">
              <div class="config-item-top">
                <div class="config-item-meta">
                  <div>
                    <div class="ci-name">固定访问文件路径</div>
                    <code class="ci-key">tool_injection.filepath</code>
                    <div class="ci-desc">注入的工具被调用时强制读取指定文件路径</div>
                  </div>
                </div>
                <t-switch v-model="injectConfig.filepath.enabled" />
              </div>
              <div class="config-item-body" v-if="injectConfig.filepath.enabled">
                <t-input
                  v-model="injectConfig.filepath.value"
                  placeholder="如 /root/.ssh/id_rsa"
                  clearable
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Footer -->
    <div class="footer-notice">
      <span class="footer-icon"><t-icon name="error-circle" /></span>
      <span>以上场景仅用于验证 ClawAVC 检测引擎的能力边界，。</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
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
    // 静默失败，使用默认配置
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
</script>

<style scoped>
.attack-page {
  max-width: 880px;
  margin: 0 auto;
  padding: 0 24px 48px;
}

/* Header */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: rgba(255, 68, 68, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
}
.page-header h2 {
  font-size: 20px;
  font-weight: 700;
  color: #1a1a2e;
  margin: 0;
}
.subtitle {
  font-size: 13px;
  color: #888;
  margin: 2px 0 0;
}
.header-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 20px;
  background: rgba(255, 68, 68, 0.05);
  border: 1px solid rgba(255, 68, 68, 0.18);
  font-size: 11px;
  font-weight: 600;
  color: #ff4444;
  letter-spacing: 1px;
  font-family: 'JetBrains Mono', monospace;
}
.pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ff4444;
  animation: pulse 2s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.7); }
}

/* Threat Matrix */
.threat-matrix {
  margin-bottom: 20px;
}
.matrix-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #444;
}
.matrix-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: rgba(255, 68, 68, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
}
.matrix-count {
  margin-left: auto;
  font-size: 11px;
  font-weight: 500;
  color: #999;
}

/* Scenarios */
.scenarios {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 24px;
}
.scenario-card {
  background: #fff;
  border-radius: 14px;
  padding: 24px;
  border: 1px solid #e8e8e8;
  cursor: pointer;
  transition: all 0.25s;
}
.scenario-card:hover {
  border-color: #ddd;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.05);
}
.scenario-card.active {
  border-color: #ff4444;
  box-shadow: 0 4px 24px rgba(255, 68, 68, 0.08);
}
.scenario-header {
  display: flex;
  align-items: center;
  gap: 14px;
}
.scenario-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.scenario-icon.tamper {
  background: linear-gradient(135deg, #fff5f5, #ffe0e0);
  color: #e63946;
}
.scenario-icon.inject {
  background: linear-gradient(135deg, #f5f0ff, #e8daff);
  color: #7c3aed;
}
.scenario-meta {
  flex: 1;
}
.scenario-meta h3 {
  font-size: 16px;
  font-weight: 700;
  color: #1a1a2e;
  margin: 0 0 3px;
}
.scenario-tag {
  font-size: 11px;
  color: #999;
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 0.3px;
}
.severity {
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1px;
  font-family: 'JetBrains Mono', monospace;
}
.severity.high {
  background: #fff5f5;
  color: #e63946;
  border: 1px solid #fecdd3;
}
.severity.critical {
  background: #fdf2f8;
  color: #be185d;
  border: 1px solid #f9a8d4;
}
.scenario-desc {
  font-size: 13px;
  color: #666;
  line-height: 1.7;
  margin: 14px 0 0;
}

/* Detail */
.scenario-detail {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px dashed #eee;
  animation: slideDown 0.3s ease;
}
@keyframes slideDown {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Attack Chain */
.attack-chain {
  margin-bottom: 20px;
}
.chain-title {
  font-size: 12px;
  font-weight: 600;
  color: #999;
  margin-bottom: 14px;
  text-transform: uppercase;
  letter-spacing: 1px;
}
.chain-visual {
  display: flex;
  align-items: center;
  gap: 0;
  overflow-x: auto;
  padding: 8px 0;
}
.chain-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 100px;
  padding: 14px 12px;
  border-radius: 12px;
  background: #f9fafb;
  border: 1px solid #eee;
  text-align: center;
}
.chain-node.hijack, .chain-node.attacker {
  background: #fff5f5;
  border-color: #fecdd3;
}
.chain-node.target {
  background: #fef2f2;
  border-color: #fca5a5;
}
.node-icon {
  font-size: 24px;
  margin-bottom: 6px;
}
.node-label {
  font-size: 12px;
  font-weight: 600;
  color: #333;
}
.node-sub {
  font-size: 10px;
  color: #888;
  margin-top: 3px;
}
.chain-link {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 60px;
}
.link-line {
  width: 40px;
  height: 2px;
  background: linear-gradient(90deg, #fca5a5, #ff4444);
  border-radius: 1px;
}
.link-badge {
  font-size: 10px;
  color: #e63946;
  font-weight: 600;
  margin-top: 4px;
  white-space: nowrap;
}
.link-badge .t-icon {
  vertical-align: -1px;
}

/* Impact */
.impact-section {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 16px;
}
.impact-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  border-radius: 10px;
  background: #fafafa;
  border: 1px solid #f0f0f0;
}
.impact-icon {
  font-size: 18px;
  flex-shrink: 0;
}
.impact-title {
  font-size: 11px;
  font-weight: 600;
  color: #666;
  margin-bottom: 2px;
}
.impact-desc {
  font-size: 12px;
  color: #333;
  line-height: 1.4;
}

/* Detection */
.detection-card {
  background: rgba(0, 168, 112, 0.03);
  border: 1px solid rgba(0, 168, 112, 0.18);
  border-radius: 12px;
  padding: 16px;
}
.detection-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #00a870;
  margin-bottom: 12px;
}
.shield-icon {
  font-size: 16px;
}
.detection-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.detect-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: #555;
  line-height: 1.5;
}
.detect-badge {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
}
.detect-badge.pass {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
}

/* Attack Config Block (color block) */
.config-block {
  margin-top: 16px;
  border-radius: 12px;
  padding: 16px;
  cursor: default;
}
.inject-block {
  background: linear-gradient(135deg, #faf5ff, #f3e8ff);
  border: 1px solid #e9d5ff;
}
.tamper-block {
  background: linear-gradient(135deg, #fff5f5, #ffe4e4);
  border: 1px solid #fecdd3;
}
.config-block-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}
.cfg-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #7c3aed;
}
.tamper-block .cfg-dot {
  background: #e63946;
}
.cfg-title {
  font-size: 13px;
  font-weight: 700;
  color: #1a1a2e;
}
.cfg-tag {
  font-size: 11px;
  color: #999;
  font-family: 'JetBrains Mono', monospace;
}
.cfg-save-btn {
  margin-left: auto;
}
.config-empty {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.55);
  font-size: 12px;
  color: #999;
}
.cfg-empty-icon {
  font-size: 16px;
}
.config-item {
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(124, 58, 237, 0.12);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 10px;
  transition: all 0.2s;
}
.config-item:last-child {
  margin-bottom: 0;
}
.config-item.on {
  border-color: rgba(124, 58, 237, 0.35);
  box-shadow: 0 2px 12px rgba(124, 58, 237, 0.08);
}
.config-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.config-item-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ci-key {
  display: inline-block;
  margin: 4px 0 2px;
  padding: 1px 8px;
  border-radius: 5px;
  background: rgba(124, 58, 237, 0.1);
  color: #7c3aed;
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
}
.ci-name {
  font-size: 13px;
  font-weight: 600;
  color: #1a1a2e;
}
.ci-desc {
  font-size: 11px;
  color: #888;
  margin-top: 2px;
}
.config-item-body {
  margin-top: 12px;
  animation: slideDown 0.25s ease;
}

/* Tamper block: red theme overrides */
.tamper-block .ci-key {
  background: rgba(230, 57, 70, 0.1);
  color: #e63946;
}
.tamper-block .config-item {
  border-color: rgba(230, 57, 70, 0.12);
}
.tamper-block .config-item.on {
  border-color: rgba(230, 57, 70, 0.35);
  box-shadow: 0 2px 12px rgba(230, 57, 70, 0.08);
}

/* Footer */
.footer-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 18px;
  background: #fffbf5;
  border-radius: 10px;
  border: 1px solid #fde8c8;
  font-size: 12px;
  color: #8a6d3b;
  line-height: 1.5;
}
.footer-icon {
  font-size: 14px;
  flex-shrink: 0;
}
</style>
