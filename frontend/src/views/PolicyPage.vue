<template>
  <div class="policy-page">
    <h2>策略翻译</h2>
    <t-tabs v-model="activeTab">
      <t-tab-panel value="translate" label="翻译与提示词">
        <TranslateTab />
      </t-tab-panel>
      <t-tab-panel value="config" label="模型配置">
        <ConfigTab />
      </t-tab-panel>
      <t-tab-panel value="registry" label="策略库">
        <RegistryTab />
      </t-tab-panel>
      <t-tab-panel value="logs" label="翻译日志">
        <LogsTab />
      </t-tab-panel>
      <t-tab-panel value="default" label="默认策略">
        <DefaultPolicyTab />
      </t-tab-panel>
    </t-tabs>
  </div>
</template>

<script setup>
import { ref } from "vue"
import TranslateTab from "./policy/TranslateTab.vue"
import ConfigTab from "./policy/ConfigTab.vue"
import RegistryTab from "./policy/RegistryTab.vue"
import LogsTab from "./policy/LogsTab.vue"
import DefaultPolicyTab from "./policy/DefaultPolicyTab.vue"

const activeTab = ref("translate")
</script>

<style scoped>
.policy-page { max-width: 1200px; margin: 0 auto; }
.policy-page h2 { font-size: 20px; font-weight: 600; margin-bottom: 20px; color: #333; }
</style>
