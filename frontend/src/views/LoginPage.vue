<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-logo">
        <svg width="48" height="48" viewBox="0 0 32 32" fill="none">
          <rect width="32" height="32" rx="8" fill="#0052D9"/>
          <path d="M8 16L14 22L24 10" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
      <h2>ClawAVC</h2>
      <p class="login-subtitle">Claw Access-View Compliance</p>
      <div class="login-form">
        <t-input
          v-model="secretKey"
          type="password"
          placeholder="请输入访问密钥"
          size="large"
          @enter="handleLogin"
          :status="error ? 'error' : 'default'"
          :tips="error"
        >
          <template #prefix-icon><t-icon name="lock-on" /></template>
        </t-input>
        <t-button
          theme="primary"
          size="large"
          block
          :loading="loading"
          @click="handleLogin"
        >
          验证访问
        </t-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { useRouter } from "vue-router"

const router = useRouter()
const secretKey = ref("")
const error = ref("")
const loading = ref(false)

onMounted(() => {
  
  // Auto-fill from subdomain if available
  const pending = localStorage.getItem("clawavc_pending_key")
  if (pending) {
    secretKey.value = pending
    localStorage.removeItem("clawavc_pending_key")
  }
})

async function handleLogin() {
  if (!secretKey.value.trim()) {
    error.value = "请输入密钥"
    return
  }
  loading.value = true
  error.value = ""
  try {
    const res = await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ secret: secretKey.value.trim() }),
    })
    const json = await res.json()
    if (json.ok) {
      sessionStorage.setItem("clawavc_verified_key", secretKey.value.trim())
      router.replace("/")
    } else {
      error.value = "密钥错误，请重试"
    }
  } catch (e) {
    error.value = "连接失败，请检查服务"
  }
  loading.value = false
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #f0f5ff 0%, #e8f4ff 50%, #fff 100%);
}
.login-card {
  background: #fff;
  border-radius: 16px;
  padding: 48px 40px;
  width: 380px;
  text-align: center;
  box-shadow: 0 8px 40px rgba(0, 82, 217, 0.08);
}
.login-logo { margin-bottom: 16px; }
.login-card h2 {
  font-size: 24px;
  font-weight: 700;
  color: #0052D9;
  margin-bottom: 4px;
}
.login-subtitle {
  font-size: 13px;
  color: #999;
  margin-bottom: 32px;
}
.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
