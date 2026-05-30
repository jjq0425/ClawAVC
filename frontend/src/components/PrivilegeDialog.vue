<template>
  <t-dialog
    v-model:visible="visible"
    header="特权验证"
    :confirm-btn="{ content: '验证', theme: 'warning', loading: loading }"
    :cancel-btn="{ content: '取消' }"
    @confirm="handleVerify"
    @cancel="visible = false"
    width="380px"
  >
    <div class="privilege-dialog">
      <div class="dialog-icon">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
          <rect width="48" height="48" rx="12" fill="#FFF3E8"/>
          <path d="M24 14C20.134 14 17 17.134 17 21V23H15V35H33V23H31V21C31 17.134 27.866 14 24 14ZM20 21C20 18.791 21.791 17 24 17C26.209 17 28 18.791 28 21V23H20V21Z" fill="#ED7B2F"/>
        </svg>
      </div>
      <p class="dialog-desc">此操作需要特权密钥验证</p>
      <t-input
        v-model="key"
        type="password"
        placeholder="输入特权密钥"
        size="large"
        @enter="handleVerify"
        :status="error ? 'error' : 'default'"
        :tips="error"
      />
    </div>
  </t-dialog>
</template>

<script setup>
import { ref, computed, watch } from "vue"
import { MessagePlugin } from "tdesign-vue-next"

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})

const emit = defineEmits(["update:modelValue", "success"])

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit("update:modelValue", val),
})

const key = ref("")
const error = ref("")
const loading = ref(false)

watch(visible, (val) => {
  if (val) { key.value = ""; error.value = "" }
})

async function handleVerify() {
  if (!key.value.trim()) { error.value = "请输入特权密钥"; return }
  loading.value = true
  error.value = ""
  try {
    const res = await fetch("/api/admin/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ admin_key: key.value }),
    })
    const json = await res.json()
    if (json.ok) {
      sessionStorage.setItem("clawavc_admin_session", json.session_token)
      sessionStorage.setItem("clawavc_admin_expiry", String(Date.now() + (json.ttl || 1200) * 1000))
      MessagePlugin.success("特权验证成功")
      visible.value = false
      emit("success", json.session_token)
    } else {
      error.value = "特权密钥错误"
    }
  } catch (e) { error.value = "连接失败" }
  loading.value = false
}
</script>

<style scoped>
.privilege-dialog { text-align: center; }
.dialog-icon { margin-bottom: 12px; }
.dialog-desc { font-size: 14px; color: #666; margin-bottom: 16px; }
</style>
