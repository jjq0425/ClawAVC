<template>
  <div v-if="error" class="registry-warning">
    <t-icon name="error-circle-filled" size="18px" />
    <div class="warning-content">
      <span class="warning-title">策略库异常</span>
      <span class="warning-detail">{{ error }}</span>
    </div>
    <router-link to="/policy" class="warning-link" @click.stop>
      前往「策略库」配置 →
    </router-link>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"

const error = ref("")

onMounted(async () => {
  try {
    const res = await fetch("/api/translator/registry-health")
    const json = await res.json()
    if (!json.ok) error.value = json.error
  } catch (e) {
    error.value = "无法连接后端服务"
  }
})
</script>

<style scoped>
.registry-warning {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: linear-gradient(135deg, #fff8f0 0%, #fff5f5 100%);
  border: 1px solid #ffe0c2;
  border-radius: 10px;
  margin-bottom: 16px;
  color: #ED7B2F;
}
.warning-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.warning-title {
  font-size: 13px;
  font-weight: 600;
}
.warning-detail {
  font-size: 12px;
  color: #999;
}
.warning-link {
  font-size: 12px;
  color: #0052D9;
  text-decoration: none;
  white-space: nowrap;
}
.warning-link:hover {
  text-decoration: underline;
}
</style>
