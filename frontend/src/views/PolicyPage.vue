<template>
  <div class="policy-page">
    <h2>策略翻译</h2>
    <t-tabs v-model="topTab" class="top-tabs">
      <t-tab-panel value="translate" label="翻译">
        <t-tabs v-model="subTranslate" class="sub-tabs">
          <t-tab-panel value="prompt" label="翻译与提示词">
            <TranslateTab />
          </t-tab-panel>
          <t-tab-panel value="advice" label="可替代工具引导">
            <AdviceTab />
          </t-tab-panel>
          <t-tab-panel value="config" label="模型配置">
            <ConfigTab />
          </t-tab-panel>
          <t-tab-panel value="logs" label="翻译日志">
            <LogsTab />
          </t-tab-panel>
        </t-tabs>
      </t-tab-panel>
      <t-tab-panel value="policy" label="策略库">
        <t-tabs v-model="subPolicy" class="sub-tabs">
          <t-tab-panel value="registry" label="策略库">
            <RegistryTab />
          </t-tab-panel>
          <t-tab-panel value="default" label="默认策略">
            <DefaultPolicyTab />
          </t-tab-panel>
        </t-tabs>
      </t-tab-panel>
      <t-tab-panel value="ai-writer" label="AI 帮写">
        <div class="single-panel">
          <AiWriterTab />
        </div>
      </t-tab-panel>
      <t-tab-panel value="rsi" label="RSI 自进化">
        <t-tabs v-model="subRsi" class="sub-tabs">
          <t-tab-panel value="flow" label="自进化流程">
            <RsiTab />
          </t-tab-panel>
          <t-tab-panel value="tasks" label="任务历史（只读）">
            <RsiTaskHistory />
          </t-tab-panel>
        </t-tabs>
      </t-tab-panel>
    </t-tabs>
  </div>
</template>

<script setup>
import { ref } from "vue"
import TranslateTab from "./policy/TranslateTab.vue"
import AdviceTab from "./policy/AdviceTab.vue"
import ConfigTab from "./policy/ConfigTab.vue"
import RegistryTab from "./policy/RegistryTab.vue"
import LogsTab from "./policy/LogsTab.vue"
import DefaultPolicyTab from "./policy/DefaultPolicyTab.vue"
import AiWriterTab from "./policy/AiWriterTab.vue"
import RsiTab from "./policy/RsiTab.vue"
import RsiTaskHistory from "./policy/RsiTaskHistory.vue"

const topTab = ref("translate")
const subTranslate = ref("prompt")
const subPolicy = ref("registry")
const subRsi = ref("flow")
</script>

<style scoped>
.policy-page { max-width: 1200px; margin: 0 auto; }
.policy-page h2 { font-size: 20px; font-weight: 600; margin-bottom: 20px; color: #333; }
.sub-tabs { margin-top: 10px; }
.single-panel { margin-top: 10px; }
</style>
