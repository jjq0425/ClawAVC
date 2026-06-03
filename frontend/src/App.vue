<template>
  <div v-if="isAuthRoute" class="app-container">
    <aside class="sidebar">
      <div class="logo-area">
        <img src="/logo-long.png" alt="ClawAVC" class="logo-img" />
      </div>
      <nav class="nav-list">
        <router-link v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item" active-class="active" :exact="item.exact">
          <t-icon :name="item.icon" size="20px" />
          <span>{{ item.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <div class="conn-dot" :class="{ online: connected }"></div>
        <span class="conn-text">{{ connected ? 'Connected' : 'Offline' }}</span>
      </div>
    </aside>
    <main class="main-area"><router-view /></main>
  </div>
  <router-view v-else />
</template>

<script setup>
import { computed } from "vue"
import { useRoute } from "vue-router"
import { connected } from "./utils/socket.js"

const route = useRoute()
const isAuthRoute = computed(() => route.name !== "Login")

const navItems = [
  { path: "/", icon: "home", label: "首页", exact: true },
  { path: "/monitor", icon: "dashboard", label: "运行监控" },
  { path: "/attack", icon: "bug", label: "模拟攻击" },
  { path: "/policy", icon: "file-setting", label: "策略翻译" },
  { path: "/database", icon: "server", label: "数据运维" },
  { path: "/replay", icon: "play-circle", label: "Round 回放" },
  { path: "/api-docs", icon: "code", label: "对外接口" },
  { path: "/navigator", icon: "link", label: "快捷导航" },
  { path: "/settings", icon: "setting", label: "平台管理" },
]
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f7fa; color: #333; }
.app-container { display: flex; min-height: 100vh; }
.sidebar { width: 220px; background: #fff; border-right: 1px solid #e8e8e8; display: flex; flex-direction: column; padding: 24px 0; position: fixed; height: 100vh; z-index: 10; }
.logo-area { display: flex; align-items: center; gap: 10px; padding: 0 24px; margin-bottom: 16px; }
.logo-text { font-size: 20px; font-weight: 700; color: #0052D9; letter-spacing: -0.5px; }
.logo-img { height: 60px; width: auto; object-fit: contain; }
.nav-list { flex: 1; }
.nav-item { display: flex; align-items: center; gap: 10px; padding: 12px 24px; cursor: pointer; color: #666; font-size: 14px; transition: all 0.2s; border-left: 3px solid transparent; text-decoration: none; }
.nav-item:hover { background: #f0f5ff; color: #0052D9; }
.nav-item.active { background: #f0f5ff; color: #0052D9; font-weight: 600; border-left-color: #0052D9; }
.sidebar-footer { padding: 16px 24px; display: flex; align-items: center; gap: 8px; }
.conn-dot { width: 8px; height: 8px; border-radius: 50%; background: #ddd; }
.conn-dot.online { background: #00a870; box-shadow: 0 0 6px #00a870; }
.conn-text { font-size: 12px; color: #999; }
.main-area { flex: 1; margin-left: 220px; padding: 32px; }
</style>
