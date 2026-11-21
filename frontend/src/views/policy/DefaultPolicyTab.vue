<template>
<!-- 通用兜底策略页：L1 未命中场景时的默认 IR 策略 -->
  <div class="default-tab">
<!-- 策略卡片容器 -->
    <div class="default-card">
<!-- 卡片标题 -->
      <div class="card-title">通用兜底策略</div>
<!-- 说明：保存前经 normalize + validate 校验 -->
      <p class="card-desc">当 Level-1 未匹配到任何场景时，使用此默认策略作为兜底。保存时会经过 normalize + validate 校验。</p>
<!-- 策略 JSON 编辑文本域 -->
      <textarea v-model="policyText" class="policy-textarea" rows="12" placeholder="加载中..."></textarea>
<!-- 操作行：保存/重载 -->
      <div class="default-actions">
<!-- 保存按钮：校验失败给错误列表 -->
        <t-button theme="primary" @click="save" :loading="saving">保存策略</t-button>
<!-- 重新加载按钮 -->
        <t-button variant="outline" @click="load">重新加载</t-button>
      </div>
<!-- 校验结果条：通过/失败双态 -->
      <div v-if="validation" class="validation-result" :class="{ ok: validation.ok }">
        <t-icon :name="validation.ok ? 'check-circle' : 'error-circle'" size="16px" />
        <span v-if="validation.ok">校验通过</span>
        <div v-else>
<!-- 失败标题 -->
          <span>校验失败</span>
<!-- 错误列表 -->
          <ul class="val-errors"><li v-for="(e, i) in validation.errors" :key="i">{{ e }}</li></ul>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// Vue API
import { ref, onMounted } from "vue"
// TDesign 全局消息插件
import { MessagePlugin } from "tdesign-vue-next"

// 兜底策略 JSON 文本
const policyText = ref("")
// 保存中标志
const saving = ref(false)
// 校验结果（通过/错误列表）
const validation = ref(null)

// 加载服务端兜底策略
async function load() {
  try { const r = await fetch("/api/translator/default-policy"); const j = await r.json(); if (j.ok) policyText.value = JSON.stringify(j.data, null, 2) } catch {}
}

// 保存：JSON 解析 + 服务端校验
async function save() {
  saving.value = true; validation.value = null
  try {
// 文本转对象：解析失败按格式错误处理
    const policy = JSON.parse(policyText.value)
    const r = await fetch("/api/translator/default-policy", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ policy }) })
    const j = await r.json()
// 成功：回写校验结果
    if (j.ok) { MessagePlugin.success("默认策略已保存"); validation.value = j.validation }
    else validation.value = j.validation || { ok: false, errors: [j.error] }
// 异常兜底：JSON 格式错误
  } catch (e) { validation.value = { ok: false, errors: ["JSON 格式错误"] } }
  saving.value = false
}

// 挂载即加载
onMounted(load)
</script>

<style scoped>
/* 卡片容器样式 */
.default-card { background: #fff; border-radius: 12px; padding: 24px; border: 1px solid #eee; }
/* 标题样式 */
.card-title { font-size: 15px; font-weight: 600; margin-bottom: 8px; }
/* 说明文字样式 */
.card-desc { font-size: 13px; color: #999; margin-bottom: 14px; }
/* 策略编辑文本域：等宽 */
.policy-textarea { width: 100%; border: 1px solid #ddd; border-radius: 8px; padding: 12px; font-family: "SF Mono", monospace; font-size: 12px; line-height: 1.6; resize: vertical; outline: none; }
/* 文本域聚焦态 */
.policy-textarea:focus { border-color: #0052D9; }
/* 操作行布局 */
.default-actions { display: flex; gap: 8px; margin-top: 12px; }
/* 校验结果条样式 */
.validation-result { display: flex; align-items: flex-start; gap: 6px; margin-top: 10px; padding: 8px 12px; border-radius: 6px; font-size: 12px; background: #fff5f5; color: #ff5252; }
/* 通过态绿色 */
.validation-result.ok { background: #f0fff8; color: #00a870; }
/* 错误列表样式 */
.val-errors { margin: 4px 0 0 16px; padding: 0; font-size: 11px; }
</style>
