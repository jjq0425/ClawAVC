<template>
  <div class="export-page">
    <div class="coming-soon-card">
      <div class="icon-area">
        <svg width="80" height="80" viewBox="0 0 80 80" fill="none">
          <rect width="80" height="80" rx="20" fill="#F0F5FF"/>
          <path d="M28 50V54H52V50" stroke="#0052D9" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M40 26V46" stroke="#0052D9" stroke-width="3" stroke-linecap="round"/>
          <path d="M33 39L40 46L47 39" stroke="#0052D9" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
      <h2>数据导出</h2>
      <p class="desc">导出审计轮次数据用于模型训练与离线分析</p>
      <div class="status-badge">
        <t-tag theme="primary" variant="light" size="large">
          灰度中，暂未开放
        </t-tag>
      </div>
      <div class="roadmap">
        <div class="roadmap-item">
          <t-icon name="time-filled" size="16px" style="color: #0052D9;" />
          <span>JSONL 格式批量导出</span>
        </div>
        <div class="roadmap-item">
          <t-icon name="time-filled" size="16px" style="color: #0052D9;" />
          <span>按时间范围筛选导出</span>
        </div>
        <div class="roadmap-item">
          <t-icon name="time-filled" size="16px" style="color: #0052D9;" />
          <span>异常样本标注导出</span>
        </div>
        <div class="roadmap-item">
          <t-icon name="time-filled" size="16px" style="color: #0052D9;" />
          <span>SFT / DPO 训练格式适配</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.export-page {
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
.icon-area { margin-bottom: 20px; }
.coming-soon-card h2 { font-size: 22px; font-weight: 600; color: #333; margin-bottom: 8px; }
.desc { font-size: 14px; color: #888; margin-bottom: 24px; line-height: 1.6; }
.status-badge { margin-bottom: 28px; }
.roadmap { text-align: left; display: flex; flex-direction: column; gap: 10px; }
.roadmap-item { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #666; }
</style>
