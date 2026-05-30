<template>
  <div class="monitor-page">
    <h2>运行监控</h2>
    <t-tabs v-model="activeTab">
      <t-tab-panel value="config" label="监控配置">
        <ConfigTab />
      </t-tab-panel>
      <t-tab-panel value="logs" label="运行日志">
        <LogsTab />
      </t-tab-panel>
    </t-tabs>
  </div>
</template>

<script setup>
import { ref } from "vue"
import LogsTab from "./monitor/LogsTab.vue"
import ConfigTab from "./monitor/ConfigTab.vue"

const activeTab = ref("config")
</script>

<style scoped>
.monitor-page { max-width: 1200px; margin: 0 auto; }
.monitor-page h2 { font-size: 20px; font-weight: 600; margin-bottom: 20px; color: #333; }
</style>
