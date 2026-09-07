<script setup>
import { computed } from 'vue'
import { withBase } from 'vitepress'
import phases from '../generated/progress.json'
const total = computed(() => phases.reduce((n, phase) => n + phase.total, 0))
const done = computed(() => phases.reduce((n, phase) => n + phase.done, 0))
</script>

<template>
  <section class="phase-progress" aria-label="开发任务进度">
    <div class="progress-summary"><strong>{{ done }} / {{ total }}</strong><span>任务已验收 · 以仓库 plan 勾选为准</span></div>
    <div class="phase-grid">
      <a v-for="phase in phases" :key="phase.slug" :href="withBase(`/plan/${phase.name}.html`)" class="phase-card">
        <div class="phase-top"><span class="version">{{ phase.slug.toUpperCase() }}</span><span>{{ phase.done }} / {{ phase.total }}</span></div>
        <strong>{{ phase.title }}</strong>
        <progress :value="phase.done" :max="phase.total" :aria-label="`${phase.slug} 完成 ${phase.done} 项，共 ${phase.total} 项`"></progress>
        <span class="phase-state">{{ phase.done === phase.total ? '任务已全部勾选 · 查看证据' : phase.done ? '开发中 · 继续阅读任务' : '待开发 · 查看故事与验收' }} →</span>
      </a>
    </div>
  </section>
</template>
