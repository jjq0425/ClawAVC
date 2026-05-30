<template>
  <div class="default-tab">
    <div class="default-card">
      <div class="card-title">通用兜底策略</div>
      <p class="card-desc">当 Level-1 未匹配到任何场景时，使用此默认策略作为兜底。保存时会经过 normalize + validate 校验。</p>
      <textarea v-model="policyText" class="policy-textarea" rows="12" placeholder="加载中..."></textarea>
      <div class="default-actions">
        <t-button theme="primary" @click="save" :loading="saving">保存策略</t-button>
        <t-button variant="outline" @click="load">重新加载</t-button>
      </div>
      <div v-if="validation" class="validation-result" :class="{ ok: validation.ok }">
        <t-icon :name="validation.ok ? 'check-circle' : 'error-circle'" size="16px" />
        <span v-if="validation.ok">校验通过</span>
        <div v-else>
          <span>校验失败</span>
          <ul class="val-errors"><li v-for="(e, i) in validation.errors" :key="i">{{ e }}</li></ul>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { MessagePlugin } from "tdesign-vue-next"

const policyText = ref("")
const saving = ref(false)
const validation = ref(null)

async function load() {
  try { const r = await fetch("/api/translator/default-policy"); const j = await r.json(); if (j.ok) policyText.value = JSON.stringify(j.data, null, 2) } catch {}
}

async function save() {
  saving.value = true; validation.value = null
  try {
    const policy = JSON.parse(policyText.value)
    const r = await fetch("/api/translator/default-policy", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ policy }) })
    const j = await r.json()
    if (j.ok) { MessagePlugin.success("默认策略已保存"); validation.value = j.validation }
    else validation.value = j.validation || { ok: false, errors: [j.error] }
  } catch (e) { validation.value = { ok: false, errors: ["JSON 格式错误"] } }
  saving.value = false
}

onMounted(load)
</script>

<style scoped>
.default-card { background: #fff; border-radius: 12px; padding: 24px; border: 1px solid #eee; }
.card-title { font-size: 15px; font-weight: 600; margin-bottom: 8px; }
.card-desc { font-size: 13px; color: #999; margin-bottom: 14px; }
.policy-textarea { width: 100%; border: 1px solid #ddd; border-radius: 8px; padding: 12px; font-family: "SF Mono", monospace; font-size: 12px; line-height: 1.6; resize: vertical; outline: none; }
.policy-textarea:focus { border-color: #0052D9; }
.default-actions { display: flex; gap: 8px; margin-top: 12px; }
.validation-result { display: flex; align-items: flex-start; gap: 6px; margin-top: 10px; padding: 8px 12px; border-radius: 6px; font-size: 12px; background: #fff5f5; color: #ff5252; }
.validation-result.ok { background: #f0fff8; color: #00a870; }
.val-errors { margin: 4px 0 0 16px; padding: 0; font-size: 11px; }
</style>
