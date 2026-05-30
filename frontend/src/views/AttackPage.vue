<template>
  <div class="attack-page">
    <div class="coming-soon-card">
      <div class="icon-area">
        <svg width="80" height="80" viewBox="0 0 80 80" fill="none">
          <rect width="80" height="80" rx="20" fill="#FFF3E8"/>
          <path d="M25 55L40 25L55 55H25Z" stroke="#ED7B2F" stroke-width="3" stroke-linejoin="round"/>
          <circle cx="40" cy="47" r="2" fill="#ED7B2F"/>
          <line x1="40" y1="35" x2="40" y2="43" stroke="#ED7B2F" stroke-width="3" stroke-linecap="round"/>
        </svg>
      </div>
      <h2>模拟攻击</h2>
      <p class="desc">通过预设的恶意工具场景，验证 ClawAVC 审计引擎的检测能力</p>
      <div class="status-badge">
        <t-tag theme="warning" variant="light" size="large">
          灰度中，暂不开放
        </t-tag>
      </div>
      <div class="roadmap">
        <div class="roadmap-item">
          <t-icon name="check-circle-filled" size="16px" style="color: #00a870;" />
          <span>路径穿越检测（zip-slip）</span>
        </div>
        <div class="roadmap-item">
          <t-icon name="check-circle-filled" size="16px" style="color: #00a870;" />
          <span>未授权工具调用检测</span>
        </div>
        <div class="roadmap-item pending">
          <t-icon name="time-filled" size="16px" style="color: #ED7B2F;" />
          <span>参数注入攻击模拟</span>
        </div>
        <div class="roadmap-item pending">
          <t-icon name="time-filled" size="16px" style="color: #ED7B2F;" />
          <span>提权逃逸模拟</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.attack-page {
  display: flex;
  justify-content: center;
  padding-top: 60px;
}
.coming-soon-card {
  background: #fff;
  border-radius: 16px;
  padding: 48px;
  text-align: center;
  max-width: 480px;
  border: 1px solid #eee;
}
.icon-area {
  margin-bottom: 20px;
}
.coming-soon-card h2 {
  font-size: 22px;
  font-weight: 600;
  color: #333;
  margin-bottom: 8px;
}
.desc {
  font-size: 14px;
  color: #888;
  margin-bottom: 24px;
  line-height: 1.6;
}
.status-badge {
  margin-bottom: 28px;
}
.roadmap {
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.roadmap-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #333;
}
.roadmap-item.pending {
  color: #999;
}
</style>
