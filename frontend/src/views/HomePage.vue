<template>
  <div class="home-page">
    <div class="hero-section">
      <div class="hero-content">
        <h1 class="hero-title">Claw Access-View Compliance</h1>
        <p class="hero-subtitle">透视访问行为意图 · 校验合规性</p>
        <p class="hero-desc">
          ClawAVC 是一套面向 AI Agent 的行为合规审计系统。通过实时监控 Agent 的工具调用行为，
          与预定义的权限策略（IR）进行多维度一致性比对，识别越权访问、参数篡改、路径逃逸等异常行为。
        </p>
      </div>
      <div class="hero-graphic">
        <svg width="200" height="200" viewBox="0 0 200 200" fill="none">
          <circle cx="100" cy="100" r="90" stroke="#0052D9" stroke-width="2" opacity="0.2"/>
          <circle cx="100" cy="100" r="70" stroke="#0052D9" stroke-width="2" opacity="0.3"/>
          <circle cx="100" cy="100" r="50" stroke="#0052D9" stroke-width="3" opacity="0.5"/>
          <path d="M70 100L90 120L130 80" stroke="#0052D9" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
    </div>

    <div class="features-grid">
      <div class="feature-card">
        <div class="feature-icon blue">
          <t-icon name="view-module" size="28px" />
        </div>
        <h3>三维检测</h3>
        <p>工具调用一致性、参数匹配、资源访问权限——三个维度全面评估 Agent 行为合规性</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon orange">
          <t-icon name="time" size="28px" />
        </div>
        <h3>实时审计</h3>
        <p>WebSocket 实时推送，每一轮 Agent 交互完成后即刻呈现合规判定结果，零延迟感知风险</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon green">
          <t-icon name="secured" size="28px" />
        </div>
        <h3>IR 策略引擎</h3>
        <p>基于 subject/objects 策略模型，结合 LLM 翻译用户意图为标准化权限规则，精准描述允许范围</p>
      </div>
    </div>

    <div class="threshold-card">
      <h3>异常检测标准</h3>
      <div class="threshold-content">
        <div class="threshold-item">
          <div class="threshold-bar">
            <div class="bar-fill normal" style="width: 100%"></div>
            <div class="bar-marker" style="left: 50%">
              <span class="marker-label">0.5 阈值</span>
            </div>
          </div>
          <div class="threshold-labels">
            <span class="label-left danger">≤ 0.5 异常</span>
            <span class="label-right success">&gt; 0.5 正常</span>
          </div>
        </div>
        <div class="criteria-list">
          <div class="criteria-item">
            <t-tag theme="primary" variant="outline" size="small">工具调用</t-tag>
            <span>Agent 调用的工具是否在 IR 允许的范围内</span>
          </div>

          <div class="criteria-item">
            <t-tag theme="primary" variant="outline" size="small">参数一致</t-tag>
            <span>工具调用的参数键值是否与 IR 中约束的一致</span>
          </div>
          <div class="criteria-item">
            <t-tag theme="primary" variant="outline" size="small">资源访问</t-tag>
            <span>访问的文件路径和操作类型是否在允许范围内</span>
          </div>
        </div>
      </div>
    </div>
      <div class="credits">
     本平台Vibe Coding生成
    </div>
</div>
</template>

<script setup>
</script>

<style scoped>
.home-page {
  max-width: 1000px;
  margin: 0 auto;
}
.hero-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(135deg, #f0f5ff 0%, #fff 100%);
  border-radius: 16px;
  padding: 48px;
  margin-bottom: 32px;
  border: 1px solid #e3edff;
}
.hero-title {
  font-size: 28px;
  font-weight: 700;
  color: #0052D9;
  margin-bottom: 8px;
}
.hero-subtitle {
  font-size: 16px;
  color: #666;
  margin-bottom: 16px;
  font-weight: 500;
}
.hero-desc {
  font-size: 14px;
  color: #888;
  line-height: 1.8;
  max-width: 500px;
}
.features-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  margin-bottom: 32px;
}
.feature-card {
  background: #fff;
  border-radius: 12px;
  padding: 28px;
  border: 1px solid #eee;
  transition: all 0.2s;
}
.feature-card:hover {
  box-shadow: 0 4px 20px rgba(0, 82, 217, 0.08);
  border-color: #d4e3ff;
}
.feature-card h3 {
  font-size: 16px;
  margin: 14px 0 8px;
  color: #333;
}
.feature-card p {
  font-size: 13px;
  color: #888;
  line-height: 1.6;
}
.feature-icon {
  width: 48px; height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}
.feature-icon.blue { background: #0052D9; }
.feature-icon.orange { background: #ED7B2F; }
.feature-icon.green { background: #00a870; }
.threshold-card {
  background: #fff;
  border-radius: 12px;
  padding: 28px;
  border: 1px solid #eee;
}
.threshold-card h3 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 20px;
  color: #333;
}
.threshold-bar {
  position: relative;
  height: 8px;
  background: linear-gradient(to right, #ff5252 0%, #ff5252 50%, #00a870 50%, #00a870 100%);
  border-radius: 4px;
  margin-bottom: 8px;
}
.bar-marker {
  position: absolute;
  top: -6px;
  transform: translateX(-50%);
}
.marker-label {
  position: absolute;
  top: -20px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 11px;
  color: #666;
  white-space: nowrap;
  background: #fff;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid #ddd;
}
.bar-marker::after {
  content: '';
  display: block;
  width: 2px;
  height: 20px;
  background: #333;
  margin: 0 auto;
}
.threshold-labels {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  margin-bottom: 20px;
}
.label-left.danger { color: #ff5252; }
.label-right.success { color: #00a870; }
.criteria-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.criteria-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: #666;
}
.credits {
  text-align: center;
  font-size: 12px;
  color: #000;
  margin-top: 48px;
  padding-bottom: 24px;
}
</style>