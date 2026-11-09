<script setup lang="ts">
/**
 * AppShell：V3 外壳（顶部品牌条 + 底部悬浮导航 + 页脚）。
 * - 顶部：品牌标识、白色搜索框（统一走 /search?q=）、账号入口；≤900px 压缩。
 * - 底部：居中悬浮导航，中间箭头控制呼出 / 收起；收起状态记在 localStorage。
 * - 内容区最大 1120px，底部留出导航高度，避免遮挡。
 */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStorage } from '@vueuse/core'
import { useContextStore } from '@/stores/context'
import { useTheme } from '@/utils/theme'
import AppIcon from '@/components/ui/AppIcon.vue'

const route = useRoute()
const router = useRouter()
const contextStore = useContextStore()

/** 主题切换：暖沙 / 青瓷 */
const { label: themeLabel, toggleTheme } = useTheme()

const navLeft = [
  { to: '/', label: '首页', icon: 'home' },
  { to: '/library', label: '发音库', icon: 'book' },
  { to: '/map', label: '发音地图', icon: 'map' },
]

const navRight = [
  { to: '/principles', label: '专业资料', icon: 'doc' },
  { to: '/archive', label: '声音档案', icon: 'folder' },
  { to: '/account', label: '我的', icon: 'user' },
]

const searchTerm = ref('')

/** 手机上首次进入默认收起（悬浮导航会挡住内容），桌面默认展开；用户手动切换后记住 */
const collapsed = useStorage('vs_dock_collapsed', window.matchMedia('(max-width: 760px)').matches)

const accountLabel = computed(
  () => (contextStore.isAuthenticated && contextStore.context.username) || '登录 / 注册',
)

function isActive(to: string): boolean {
  if (to === '/') return route.path === '/'
  if (to === '/library') return route.path === '/library' || route.path.startsWith('/learn')
  return route.path === to || route.path.startsWith(`${to}/`)
}

function submitSearch() {
  const q = searchTerm.value.trim()
  if (!q) return
  void router.push({ path: '/search', query: { q } })
  searchTerm.value = ''
}

/** 小屏点完导航就收起，别挡内容（与原型一致） */
function onNavClick() {
  if (window.matchMedia('(max-width: 760px)').matches) collapsed.value = true
}
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="topbar-in">
        <RouterLink to="/" class="brand" aria-label="看得见的声音 · 回到首页">
          <span class="brand-mark"><AppIcon name="wave" size="sm" /></span>
          <span class="brand-tx">
            <b>看得见的声音</b>
            <small>拼音发音学习</small>
          </span>
        </RouterLink>

        <form class="top-search" role="search" @submit.prevent="submitSearch">
          <AppIcon name="search" size="sm" class="top-search-ico" />
          <input
            v-model="searchTerm"
            type="search"
            placeholder="搜拼音、汉字或关卡名"
            aria-label="搜索关卡"
            enterkeyhint="search"
          />
          <button type="submit" aria-label="搜一个音"><AppIcon name="search" size="sm" /></button>
        </form>

        <button
          type="button"
          class="theme-switch"
          :title="`切换主题色（当前：${themeLabel}）`"
          :aria-label="`切换主题色，当前为${themeLabel}`"
          @click="toggleTheme"
        >
          <span class="theme-dots" aria-hidden="true"><i /><i /></span>
          <span class="theme-name">{{ themeLabel }}</span>
        </button>

        <RouterLink to="/account" class="account-entry" :title="accountLabel">
          <AppIcon name="user" size="sm" />
          <span class="account-label">{{ accountLabel }}</span>
        </RouterLink>
      </div>
    </header>

    <div class="wrap">
      <main class="shell-main">
        <slot />
      </main>

      <footer class="site-foot">
        <div class="foot-parent">
          <b>给爸爸妈妈的话：</b><br />
          这是普通话拼音学习；结果仅供学习参考；不是等级考试，也不是看病。<br />
          评分只在能录音的关上出现；录音不合格时会停下评分，并且说明怎么重录。
        </div>
        <div class="foot-links">
          <RouterLink to="/principles" class="vs-btn vs-btn--ghost vs-btn--small">
            <AppIcon name="doc" size="sm" />专业资料
          </RouterLink>
          <RouterLink to="/library" class="vs-btn vs-btn--ghost vs-btn--small">
            <AppIcon name="book" size="sm" />发音库
          </RouterLink>
          <RouterLink to="/archive" class="vs-btn vs-btn--ghost vs-btn--small">
            <AppIcon name="folder" size="sm" />声音档案
          </RouterLink>
        </div>
        <div class="foot-closing">学习参考，不作为普通话等级认定或医学诊断。</div>
      </footer>
    </div>

    <div class="dock" :class="{ collapsed }">
      <div id="dock-bar" class="dock-bar">
        <nav class="dock-nav" aria-label="主导航">
          <RouterLink
            v-for="item in navLeft"
            :key="item.to"
            :to="item.to"
            class="dockitem"
            :class="{ on: isActive(item.to) }"
            :aria-current="isActive(item.to) ? 'page' : undefined"
            @click="onNavClick"
          >
            <AppIcon :name="item.icon" size="sm" />{{ item.label }}
          </RouterLink>
        </nav>

        <button
          class="dock-toggle"
          type="button"
          :aria-expanded="!collapsed"
          aria-controls="dock-bar"
          :aria-label="collapsed ? '呼出导航' : '隐藏导航'"
          :title="collapsed ? '呼出导航' : '隐藏导航'"
          @click="collapsed = !collapsed"
        >
          <AppIcon name="chev" size="sm" />
        </button>

        <nav class="dock-nav" aria-label="更多导航">
          <RouterLink
            v-for="item in navRight"
            :key="item.to"
            :to="item.to"
            class="dockitem"
            :class="{ on: isActive(item.to) }"
            :aria-current="isActive(item.to) ? 'page' : undefined"
            @click="onNavClick"
          >
            <AppIcon :name="item.icon" size="sm" />{{ item.label }}
          </RouterLink>
        </nav>
      </div>
    </div>
  </div>
</template>

<style scoped lang="sass">
/* 外壳兜住横向溢出：内容再宽也不让整页左右滚动（表格等自带滚动容器） */
.app-shell
  overflow-x: clip

/* ============================ 顶部品牌条 ============================ */

.topbar
  position: sticky
  top: 0
  z-index: 60
  background: rgba(var(--vs-bg-rgb), 0.86)
  -webkit-backdrop-filter: saturate(170%) blur(18px)
  backdrop-filter: blur(18px) saturate(170%)
  border-bottom: 1px solid rgba(var(--vs-line2-rgb), 0.62)

.topbar-in
  max-width: 1120px
  margin: 0 auto
  height: 64px
  padding: 0 24px
  display: flex
  align-items: center
  gap: 16px

.brand
  display: flex
  align-items: center
  gap: 8px
  flex: none
  cursor: pointer
  text-decoration: none

.brand-mark
  width: 32px
  height: 32px
  border-radius: 8px
  flex: none
  color: var(--vs-on-coffee)
  display: flex
  align-items: center
  justify-content: center
  background: linear-gradient(160deg, var(--vs-sand), var(--vs-brand))
  box-shadow: 0 4px 10px rgba(var(--vs-glow-rgb), 0.3)

.brand-tx
  b
    display: block
    font-size: 15px
    font-weight: 700
    letter-spacing: 0.2px
    line-height: 1.3
    color: var(--vs-ink)
  small
    display: block
    font-size: 11px
    color: var(--vs-mute)
    line-height: 1.3

/* 顶部白色搜索框：与首页搜索同一出口 */
.top-search
  margin-left: auto
  display: flex
  align-items: center
  gap: 6px
  width: min(300px, 40vw)
  height: 42px
  padding: 0 5px 0 14px
  background: var(--vs-card)
  border: 1px solid var(--vs-line2)
  border-radius: 8px
  box-shadow: 0 1px 2px rgba(var(--vs-shadow-rgb), 0.05)
  transition: border-color 0.16s var(--vs-ease), box-shadow 0.16s var(--vs-ease)

  &:focus-within
    border-color: var(--vs-line-strong)
    box-shadow: 0 0 0 4px rgba(var(--vs-glow-rgb), 0.1)

  .top-search-ico
    color: var(--vs-mute)
    width: 16px
    height: 16px

  input
    flex: 1
    min-width: 0
    border: none
    outline: none
    background: transparent
    font-family: inherit
    font-size: 13.5px
    color: var(--vs-ink)
    height: 100%

  input::placeholder
    color: var(--vs-mute)

  button
    flex: none
    width: 32px
    height: 32px
    border: none
    border-radius: 8px
    cursor: pointer
    background: linear-gradient(180deg, var(--vs-coffee-a), var(--vs-coffee-b))
    color: var(--vs-on-coffee)
    display: flex
    align-items: center
    justify-content: center
    transition: background 0.16s var(--vs-ease)

  button:hover
    background: linear-gradient(180deg, var(--vs-coffee-a-hover), var(--vs-coffee-b-hover))

  button .vs-ico
    width: 15px
    height: 15px

.account-entry
  flex: none
  display: inline-flex
  align-items: center
  gap: 6px
  max-width: 150px
  height: 38px
  padding: 0 12px
  border-radius: 8px
  background: var(--vs-card)
  color: var(--vs-ink2)
  box-shadow: inset 0 0 0 1px var(--vs-line2)
  font-size: 13px
  font-weight: 600
  text-decoration: none
  transition: background 0.16s var(--vs-ease), color 0.16s var(--vs-ease)

.account-entry:hover
  background: var(--vs-soft-2)
  color: var(--vs-coffee)

.account-label
  overflow: hidden
  text-overflow: ellipsis
  white-space: nowrap

/* 主题切换：两个色点 + 当前主题名（暖沙 / 青瓷） */
.theme-switch
  flex: none
  display: inline-flex
  align-items: center
  gap: 7px
  height: 38px
  padding: 0 12px 0 10px
  border: none
  border-radius: 8px
  background: var(--vs-card)
  color: var(--vs-ink2)
  box-shadow: inset 0 0 0 1px var(--vs-line2)
  font-family: inherit
  font-size: 13px
  font-weight: 600
  cursor: pointer
  transition: background 0.16s var(--vs-ease), color 0.16s var(--vs-ease)

.theme-switch:hover
  background: var(--vs-soft-2)
  color: var(--vs-coffee)

.theme-switch:focus-visible
  outline: 2px solid var(--vs-brand)
  outline-offset: 2px

.theme-dots
  display: inline-flex
  gap: 3px
  flex: none
  i
    display: block
    width: 9px
    height: 9px
    border-radius: 50%
  i:first-child
    background: var(--vs-brand)
  i:last-child
    background: var(--vs-bg)
    box-shadow: inset 0 0 0 1px var(--vs-line2)

.theme-name
  white-space: nowrap

/* ============================ 内容区 ============================ */

.wrap
  max-width: 1120px
  margin: 0 auto
  padding: 0 24px 168px

.shell-main
  padding-top: 16px
  min-height: 60vh

/* ============================ 页脚 ============================ */

.site-foot
  margin-top: 72px
  padding-top: 24px
  border-top: 1px solid var(--vs-line2)

.foot-parent
  background: var(--vs-card)
  border: 1px solid var(--vs-line)
  border-radius: 8px
  padding: 24px
  font-size: 13px
  color: var(--vs-sub)
  line-height: 1.9
  b
    color: var(--vs-ink)

.foot-links
  margin-top: 16px
  display: flex
  gap: 8px
  flex-wrap: wrap

.foot-closing
  margin-top: 16px
  font-size: 12px
  color: var(--vs-mute)

/* ============================ 底部悬浮导航 ============================ */

.dock
  position: fixed
  left: 50%
  bottom: calc(22px + var(--vs-safe))
  transform: translateX(-50%)
  z-index: 75
  display: flex
  justify-content: center
  max-width: calc(100vw - 24px)

.dock-bar
  display: flex
  align-items: center
  gap: 2px
  padding: 7px
  background: rgba(var(--vs-card-rgb), 0.92)
  -webkit-backdrop-filter: saturate(180%) blur(22px)
  backdrop-filter: saturate(180%) blur(22px)
  border: 1px solid rgba(var(--vs-line2-rgb), 0.95)
  border-radius: 16px
  box-shadow: 0 12px 30px rgba(var(--vs-shadow-rgb), 0.14), 0 2px 6px rgba(var(--vs-shadow-rgb), 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.9)
  transition: background 0.3s var(--vs-ease), border-color 0.3s var(--vs-ease), box-shadow 0.3s var(--vs-ease), border-radius 0.3s var(--vs-ease)

.dock-nav
  display: flex
  align-items: center
  gap: 2px
  min-width: 0
  max-width: 340px
  overflow: hidden
  transition: max-width 0.38s var(--vs-ease), opacity 0.22s var(--vs-ease)

.dockitem
  display: flex
  flex-direction: column
  align-items: center
  justify-content: center
  gap: 3px
  border: none
  background: none
  cursor: pointer
  white-space: nowrap
  min-width: 60px
  padding: 7px 10px 6px
  border-radius: 10px
  font-size: 11.5px
  font-weight: 600
  line-height: 1.2
  color: var(--vs-sub)
  text-decoration: none
  transition: background 0.18s var(--vs-ease), color 0.18s var(--vs-ease), box-shadow 0.18s var(--vs-ease)

.dockitem .vs-ico
  width: 19px
  height: 19px

.dockitem:hover
  background: var(--vs-soft)
  color: var(--vs-brand-d)

.dockitem.on,
.dockitem.on:hover
  background: linear-gradient(180deg, var(--vs-coffee-a), var(--vs-coffee-b))
  color: var(--vs-on-coffee)
  box-shadow: 0 6px 14px rgba(var(--vs-shadow-rgb), 0.26)

.dock-toggle
  flex: none
  width: 44px
  height: 44px
  border: none
  border-radius: 50%
  cursor: pointer
  background: linear-gradient(180deg, var(--vs-coffee-a), var(--vs-coffee-b))
  color: var(--vs-on-coffee)
  display: flex
  align-items: center
  justify-content: center
  box-shadow: 0 8px 18px rgba(var(--vs-shadow-rgb), 0.28)
  transition: background 0.18s var(--vs-ease), transform 0.18s var(--vs-ease)

.dock-toggle:hover
  background: linear-gradient(180deg, var(--vs-coffee-a-hover), var(--vs-coffee-b-hover))

.dock-toggle:active
  transform: scale(0.94)

.dock-toggle .vs-ico
  width: 18px
  height: 18px
  transition: transform 0.36s var(--vs-ease)

/* 收起：只剩中间的圆形箭头，箭头翻上来表示「点一下呼出」 */
.dock.collapsed .dock-bar
  background: transparent
  border-color: transparent
  box-shadow: none
  border-radius: 999px

.dock.collapsed .dock-nav
  max-width: 0
  opacity: 0

.dock.collapsed .dock-toggle .vs-ico
  transform: rotate(180deg)

/* ============================ 响应式 ============================ */

@media (max-width: 1023px)
  .dockitem
    min-width: 54px
    padding: 7px 8px 6px
    font-size: 11px

  .dock-nav
    max-width: 302px

@media (max-width: 900px)
  .brand-tx small
    display: none

  .topbar-in
    height: 56px
    padding: 0 16px
    gap: 10px

  .brand
    min-width: 0
    overflow: hidden

  .brand-tx b
    font-size: 14px

  /* 搜索框可压缩：品牌 + 搜索 + 账号在 390px 内排得下，避免整页横向溢出 */
  .top-search
    flex: 1 1 0
    min-width: 0
    width: auto
    max-width: 220px
    margin-left: auto

  .account-label
    display: none

  .account-entry
    width: 38px
    padding: 0
    justify-content: center

  /* 窄屏只留两个色点，省出搜索框宽度 */
  .theme-name
    display: none

  .theme-switch
    width: 38px
    padding: 0
    justify-content: center

  .wrap
    padding: 0 16px 150px

  .shell-main
    padding-top: 12px

/* 小屏：悬浮导航折成两行，圆形箭头按钮落在最下方居中 */
@media (max-width: 760px)
  .dock
    left: 0
    right: 0
    transform: none
    max-width: none
    padding: 0 12px
    bottom: calc(12px + var(--vs-safe))

  .dock-bar
    flex-direction: column
    align-items: stretch
    width: 100%
    gap: 4px
    padding: 6px

  .dock-nav
    display: grid
    grid-template-columns: repeat(3, 1fr)
    gap: 2px
    max-width: 100%
    max-height: 132px

  .dockitem
    min-width: 0
    flex-direction: row
    gap: 6px
    padding: 9px 4px
    font-size: 11px

  .dockitem .vs-ico
    width: 16px
    height: 16px

  .dock-toggle
    order: 3
    align-self: center
    width: 100%
    height: 34px
    border-radius: 10px

  .dock.collapsed .dock-bar
    width: auto
    align-self: center

  .dock.collapsed .dock-nav
    max-width: 100%
    max-height: 0
    opacity: 0

  .dock.collapsed .dock-toggle
    width: 46px
    height: 46px
    border-radius: 50%
</style>
