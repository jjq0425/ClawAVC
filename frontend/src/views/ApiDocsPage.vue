<template>
  <div class="api-docs-page">
    <h2>对外接口文档</h2>
    <t-tabs v-model="activeTab">
      <t-tab-panel value="http" label="HTTP 请求">
        <HttpTab />
      </t-tab-panel>
      <t-tab-panel value="wss" label="WebSocket 长连接">
        <WssTab />
      </t-tab-panel>
    </t-tabs>
  </div>
</template>

<script setup>
import { ref } from "vue"
import HttpTab from "./apidocs/HttpTab.vue"
import WssTab from "./apidocs/WssTab.vue"

const activeTab = ref("http")
</script>

<style scoped>
.api-docs-page { max-width: 1200px; margin: 0 auto; padding: 8px 20px; }
.api-docs-page h2 { font-size: 20px; font-weight: 600; margin-bottom: 20px; color: #333; padding-top: 8px; }
</style>
