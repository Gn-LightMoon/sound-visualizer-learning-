<script setup lang="ts">
/**
 * P01 首页：品牌英雄区（搜索 + 四个入口）、为什么用它、统计、家长科普。
 * 关卡列表不在首页重复（找关走发音地图 / 发音库 / 搜索），首页只给入口与说明。
 */
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useLevelsStore } from '@/stores/levels'
import SearchBox from '@/components/SearchBox.vue'
import AppIcon from '@/components/ui/AppIcon.vue'

const router = useRouter()
const levelsStore = useLevelsStore()

onMounted(() => {
  if (!levelsStore.loaded) void levelsStore.refresh()
})

const published = computed(() => levelsStore.published)
const hasPublished = computed(() => published.value.length > 0)

function onSearch(q: string) {
  void router.push({ path: '/search', query: { q } })
}

function focusSearch() {
  document.querySelector<HTMLInputElement>('.hero .searchbar input')?.focus()
}

/** 家长科普折叠：说清楚、不制造焦虑（文案沿用产品原型） */
const parentFaqs = [
  {
    q: '几岁开始学拼音合适？',
    a: '学龄前不用急着写。先玩声音：听辨、跟读、看口型，把耳朵和嘴巴练熟；小学一年级会系统学拼音，提前熟悉「声音是怎么来的」比提前默写更有用。每个孩子节奏不同，不用和别人比。',
  },
  {
    q: '家里说方言，会影响学拼音吗？',
    a: '会影响个别音，比如平翘舌、n 和 l，这很正常，不是「学不会」。方法是多听标准示范、对着口型模仿，先能分辨再练发音；不必强行纠正家里长辈的口音，也不用当着孩子说「你说错了」。',
  },
  {
    q: '孩子把「哥哥」说成「的的」，要纠正吗？',
    a: '先练「听出不同」：用 g / k、d / t 这类易混关成对听，再练发音。多数孩子随着口腔动作熟练会自己改过来；如果六七岁以后仍有很多音明显不清、影响交流，建议找专业医生评估，别自己下结论。',
  },
  {
    q: '一次练多久？嗓子要护着吗？',
    a: '5–10 分钟就够，一天一到两次；用正常说话的音量，不喊、不压着嗓子。嗓子干了或疼了就停下来喝口水，明天再练——练得久不如练得准。',
  },
]
</script>

<template>
  <div class="home-page">
    <section class="hero">
      <span class="hero-badge">
        <AppIcon name="wave" size="sm" />
        普通话拼音 · {{ published.length }} 关{{ hasPublished ? '都能练' : '正在准备' }}
      </span>
      <h1>看得见的声音</h1>
      <div class="eq" aria-hidden="true">
        <i style="animation-delay: 0s" /><i style="animation-delay: 0.12s" /><i style="animation-delay: 0.24s" />
        <i style="animation-delay: 0.36s" /><i style="animation-delay: 0.48s" /><i style="animation-delay: 0.6s" />
        <i style="animation-delay: 0.48s" /><i style="animation-delay: 0.36s" /><i style="animation-delay: 0.24s" />
        <i style="animation-delay: 0.12s" /><i style="animation-delay: 0s" />
      </div>
      <SearchBox @search="onSearch" />

      <div class="actions">
        <button class="action a1" type="button" @click="focusSearch">
          <span class="bubble"><AppIcon name="search" /></span>
          <b>搜一个音</b>
          <small>找想练的拼音或汉字</small>
        </button>
        <RouterLink class="action a2" to="/principles">
          <span class="bubble"><AppIcon name="doc" /></span>
          <b>专业资料</b>
          <small>发音原理、术语与来源</small>
        </RouterLink>
        <RouterLink class="action a3" to="/map">
          <span class="bubble"><AppIcon name="run" /></span>
          <b>跟着练</b>
          <small>去发音地图挑一关</small>
        </RouterLink>
        <RouterLink class="action a4" to="/archive">
          <span class="bubble"><AppIcon name="folder" /></span>
          <b>声音档案</b>
          <small>回看自己的录音和进步</small>
        </RouterLink>
      </div>
    </section>

    <section class="vs-sect" id="why">
      <h2><span class="vs-bar" />为什么用它</h2>
      <p class="vs-lead">拼音卡只能看字形、听一遍。这里把嘴巴、舌头和声音的样子，一起摆在你眼前。</p>
      <div class="feats">
        <div class="feat">
          <span class="bubble"><AppIcon name="wave" size="sm" /></span>
          <b>声音看得见</b>
          <p>口型、舌头、声音起伏，一屏看全。</p>
        </div>
        <div class="feat">
          <span class="bubble"><AppIcon name="run" size="sm" /></span>
          <b>一关一个音</b>
          <p>关卡排好队，从单韵母到声母，一级一级往上走。</p>
        </div>
        <div class="feat">
          <span class="bubble"><AppIcon name="scale" size="sm" /></span>
          <b>只练不比</b>
          <p>记录只给自己看，不比分数。相近的音，会说「仅供参考」。</p>
        </div>
        <div class="feat">
          <span class="bubble"><AppIcon name="lock" size="sm" /></span>
          <b>数据自己管</b>
          <p>录音存进自己的账号，随时可以单条删除或清空。</p>
        </div>
      </div>
      <div class="stats">
        <div><b>{{ published.length }}</b><span>关拼音</span></div>
        <div><b>4</b><span>步反馈</span></div>
        <div><b>3</b><span>档结果维度</span></div>
        <div><b>0</b><span>排名与公开</span></div>
      </div>
    </section>

    <section class="vs-sect" id="parent">
      <h2><span class="vs-bar" />家长科普</h2>
      <p class="vs-lead">家长最常问的四件事，说清楚，不制造焦虑。</p>
      <details v-for="faq in parentFaqs" :key="faq.q" class="fold">
        <summary><AppIcon name="info" size="sm" />{{ faq.q }}</summary>
        <div class="body">{{ faq.a }}</div>
      </details>
    </section>
  </div>
</template>

<style scoped lang="sass">
.home-page
  padding-bottom: 8px

/* ---------------- 英雄区 ---------------- */

.hero
  position: relative
  text-align: center
  padding: 56px 0 0

.hero-badge
  display: inline-flex
  align-items: center
  gap: 8px
  border: 1px solid var(--vs-line2)
  background: var(--vs-card)
  color: var(--vs-ink2)
  border-radius: 8px
  padding: 6px 12px
  font-size: 12.5px
  font-weight: 600

.hero-badge .vs-ico
  color: var(--vs-brand)

.hero h1
  margin: 24px 0 0
  font-size: 56px
  font-weight: 800
  letter-spacing: -1.5px
  line-height: 1.15
  color: var(--vs-ink)

.eq
  display: flex
  align-items: flex-end
  justify-content: center
  gap: 4px
  height: 24px
  margin-top: 32px

.eq i
  width: 4px
  height: 8px
  border-radius: 2px
  background: var(--vs-brand)
  opacity: 0.5
  animation: vs-eq 1.6s var(--vs-ease) infinite

@keyframes vs-eq
  0%, 100%
    height: 8px
    opacity: 0.35
  50%
    height: 24px
    opacity: 1

.hero :deep(.searchbar)
  margin: 32px auto 0

/* ---------------- 四个入口 ---------------- */

.actions
  display: grid
  grid-template-columns: repeat(4, 1fr)
  gap: 16px
  margin-top: 48px

.action
  border: 1px solid var(--vs-line)
  cursor: pointer
  text-align: left
  color: var(--vs-ink)
  border-radius: 8px
  background: var(--vs-card)
  box-shadow: var(--vs-sh-1)
  padding: 24px 20px
  display: flex
  flex-direction: column
  align-items: flex-start
  gap: 16px
  text-decoration: none
  font-family: inherit
  transition: transform 0.2s var(--vs-ease), box-shadow 0.2s var(--vs-ease), border-color 0.2s var(--vs-ease)

.action:hover
  transform: translateY(-2px)
  border-color: var(--vs-line-hover)
  box-shadow: var(--vs-sh-2)

.action .bubble
  width: 40px
  height: 40px
  border-radius: 8px
  display: flex
  align-items: center
  justify-content: center
  background: var(--vs-brand-soft)
  color: var(--vs-brand-d)

.action.a1 .bubble
  background: var(--vs-soft)
  color: var(--vs-brand-d)
.action.a2 .bubble
  background: var(--vs-soft)
  color: var(--vs-brand)
.action.a3 .bubble
  background: var(--vs-soft)
  color: var(--vs-brand-d)
.action.a4 .bubble
  background: var(--vs-soft)
  color: var(--vs-brand-d)

.action b
  font-size: 15px
  font-weight: 700
  line-height: 1.4

.action small
  color: var(--vs-sub)
  font-size: 12.5px
  line-height: 1.6

/* ---------------- 特性卡 / 统计 ---------------- */

.feats
  display: grid
  grid-template-columns: repeat(4, 1fr)
  gap: 16px
  margin-top: 24px

.feat
  background: var(--vs-card)
  border: 1px solid var(--vs-line)
  border-radius: 8px
  padding: 24px 20px
  box-shadow: var(--vs-sh-1)
  transition: border-color 0.2s var(--vs-ease), box-shadow 0.2s var(--vs-ease)

.feat:hover
  border-color: var(--vs-line-hover)
  box-shadow: var(--vs-sh-2)

.feat .bubble
  width: 32px
  height: 32px
  border-radius: 8px
  display: flex
  align-items: center
  justify-content: center
  background: var(--vs-soft)
  color: var(--vs-brand)
  margin-bottom: 16px

.feat b
  display: block
  font-size: 14.5px
  font-weight: 700

.feat p
  margin: 8px 0 0
  font-size: 13px
  color: var(--vs-sub)
  line-height: 1.65

.stats
  display: grid
  grid-template-columns: repeat(4, 1fr)
  margin-top: 16px
  background: var(--vs-card)
  border: 1px solid var(--vs-line)
  border-radius: 8px
  padding: 24px 8px
  text-align: center
  box-shadow: var(--vs-sh-1)

.stats > div
  border-left: 1px solid var(--vs-line)

.stats > div:first-child
  border-left: none

.stats b
  display: block
  font-size: 28px
  font-weight: 800
  letter-spacing: -1px
  color: var(--vs-ink)
  font-variant-numeric: tabular-nums
  line-height: 1.2

.stats span
  font-size: 12px
  color: var(--vs-sub)

/* ---------------- 家长科普 ---------------- */

.fold
  margin-top: 16px
  background: var(--vs-card)
  border: 1px solid var(--vs-line)
  border-radius: 8px
  overflow: hidden
  box-shadow: var(--vs-sh-1)

.fold summary
  cursor: pointer
  list-style: none
  padding: 16px 24px
  font-size: 15px
  font-weight: 700
  display: flex
  align-items: center
  gap: 8px

.fold summary::-webkit-details-marker
  display: none

.fold summary .vs-ico
  color: var(--vs-sub)

.fold summary:hover
  background: var(--vs-soft-2)

.fold .body
  padding: 0 24px 20px
  font-size: 13.5px
  color: var(--vs-sub)
  line-height: 1.8

/* ---------------- 响应式 ---------------- */

@media (max-width: 1023px)
  .hero h1
    font-size: 44px
    letter-spacing: -1px
  .feats
    grid-template-columns: repeat(2, 1fr)

@media (max-width: 900px)
  .hero
    padding: 40px 0 0
  .hero h1
    font-size: 34px
    letter-spacing: -0.5px
  .actions
    grid-template-columns: repeat(2, 1fr)
    gap: 12px
    margin-top: 32px
  .action
    padding: 16px
    gap: 12px
  .vs-sect
    margin-top: 48px
  .stats
    padding: 16px 4px
  .stats b
    font-size: 22px

@media (max-width: 560px)
  .hero h1
    font-size: 30px
  .feats
    grid-template-columns: 1fr
</style>
