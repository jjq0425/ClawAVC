<template>
  <div class="privilege-status" :class="{ unlocked: isValid }">
    <div v-if="isValid" class="status-unlocked">
      <t-icon name="check-circle-filled" size="16px" style="color: #00a870;" />
      <span class="status-text">特权已解锁</span>
      <span class="countdown">{{ minutes }}:{{ seconds }}</span>
    </div>
    <div v-else class="status-locked" @click="$emit('unlock')">
      <t-icon name="lock-on" size="14px" />
      <span class="status-text">{{ hint || '需要特权验证' }}</span>
      <t-button theme="warning" variant="text" size="small">点击解锁</t-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue"

const props = defineProps({
  hint: { type: String, default: "" },
})

defineEmits(["unlock"])

const now = ref(Date.now())
let timer = null

onMounted(() => {
  timer = setInterval(() => { now.value = Date.now() }, 500)
})
onUnmounted(() => clearInterval(timer))

const isValid = computed(() => {
  void now.value  // force re-evaluation every tick
  const session = sessionStorage.getItem("clawavc_admin_session")
  const exp = Number(sessionStorage.getItem("clawavc_admin_expiry") || 0)
  return !!session && Date.now() < exp
})

const remaining = computed(() => {
  void now.value
  const exp = Number(sessionStorage.getItem("clawavc_admin_expiry") || 0)
  return Math.max(0, Math.floor((exp - Date.now()) / 1000))
})
const minutes = computed(() => String(Math.floor(remaining.value / 60)).padStart(2, "0"))
const seconds = computed(() => String(remaining.value % 60).padStart(2, "0"))
</script>

<style scoped>
.privilege-status {
  display: flex;
  align-items: center;
  padding: 10px 16px;
  border-radius: 8px;
  font-size: 13px;
  transition: all 0.2s;
}
.privilege-status.unlocked {
  background: #f0fff8;
  border: 1px solid #c2f0d8;
}
.privilege-status:not(.unlocked) {
  background: #fffbf5;
  border: 1px dashed #ffe0c2;
  cursor: pointer;
}
.privilege-status:not(.unlocked):hover {
  background: #fff5ea;
}
.status-unlocked, .status-locked {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.status-text { color: #333; flex: 1; }
.status-locked .status-text { color: #ED7B2F; }
.countdown {
  font-family: "SF Mono", "Fira Code", monospace;
  font-size: 12px;
  color: #999;
  background: #f0f0f0;
  padding: 2px 8px;
  border-radius: 4px;
}
</style>
