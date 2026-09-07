import type { Theme } from 'vitepress'
import DefaultTheme from 'vitepress/theme'
import PhaseProgress from './PhaseProgress.vue'
import './style.css'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component('PhaseProgress', PhaseProgress)
  }
} satisfies Theme
