/**
 * 主题色（两套）：
 *   amber  暖沙 —— 米橙底 + 深咖啡按钮 + 红色强调（默认）
 *   celadon 青瓷 —— 浅青底 + 深青绿按钮 + 青绿强调
 * 只改 <html data-theme>，色板由 src/css/theme.sass 的 CSS 变量切换；
 * 选择写进 localStorage，并在 index.html 的首屏脚本里提前应用，避免闪一下。
 */
import { computed, ref } from 'vue'

export type ThemeName = 'amber' | 'celadon'

const STORAGE_KEY = 'vs_theme'

const LABELS: Record<ThemeName, string> = {
  amber: '暖沙',
  celadon: '青瓷',
}

function readTheme(): ThemeName {
  if (typeof document !== 'undefined') {
    const applied = document.documentElement.dataset.theme
    if (applied === 'celadon' || applied === 'amber') return applied
  }
  try {
    return localStorage.getItem(STORAGE_KEY) === 'celadon' ? 'celadon' : 'amber'
  } catch {
    return 'amber'
  }
}

const current = ref<ThemeName>(readTheme())

const THEME_COLORS: Record<ThemeName, string> = {
  amber: '#F2DCBB',
  celadon: '#E9F2E6',
}

function apply(name: ThemeName): void {
  document.documentElement.dataset.theme = name
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', THEME_COLORS[name])
  try {
    localStorage.setItem(STORAGE_KEY, name)
  } catch {
    /* 隐私模式禁用存储时忽略：本次会话仍然生效 */
  }
}

/** 首屏兜底：index.html 已按存储值写过 data-theme，这里只负责把 ref 与 DOM 对齐 */
export function initTheme(): void {
  apply(current.value)
}

export function useTheme() {
  const label = computed(() => LABELS[current.value])

  function setTheme(name: ThemeName): void {
    current.value = name
    apply(name)
  }

  function toggleTheme(): void {
    setTheme(current.value === 'amber' ? 'celadon' : 'amber')
  }

  return { theme: current, label, setTheme, toggleTheme }
}
