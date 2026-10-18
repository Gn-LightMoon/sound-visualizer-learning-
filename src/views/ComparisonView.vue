<script setup lang="ts">
/**
 * 多次录音对比（第 7 周 D：ComparisonView 接真实多次录音对比，不留 mock）
 * ---------------------------------------------------------------------------
 * 旧版这一页是纯 mock：录音只写 'mock-url'，相似度是 `72 + Math.random()*20` ——
 * 典型的假数据（已删除）。现在这一版：
 *   - 数据只来自 `/users/{id}/learning-records`（真实落库的多次练习，含录音 BLOB）；
 *   - 音频用 `/learning-records/{id}/audio` 现拉现播，失败就如实报错，不假装播放；
 *   - 对比项是后端的真实分数与三维指标（准确度 / 流利度 / 发音），差值直接算，
 *     不包装成"相似度"这种编出来的指标；
 *   - 没有记录 / 只有一条 / 未同意存档都有独立状态，不摆空图表。
 * 页号口径：本页属于 P10「我的声音档案」（见 src/data/pages.ts 的 routeNames）。
 */
import { computed, onMounted, onUnmounted, ref, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { useUserStore } from '@/stores/user'
import { learningRecordApi } from '@/api'
import { useArchiveConsent } from '@/composables/useArchiveConsent'
import { usePageCopy } from '@/composables/usePageCopy'
import PageState from '@/components/PageState.vue'
import SiteFooter from '@/components/SiteFooter.vue'
import type { LearningRecord } from '@/types'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const { consented, grant } = useArchiveConsent()
const { copy } = usePageCopy('P10')

const loading = ref(false)
const unitId = ref(String(route.query.unit ?? ''))
const leftId = ref('')
const rightId = ref('')
const playingSide = ref<'left' | 'right' | null>(null)
const playerError = ref('')
const trendRef = ref<HTMLDivElement | null>(null)

let audioEl: HTMLAudioElement | null = null
let audioUrl: string | null = null

function stopAudio() {
  if (audioEl) {
    audioEl.pause()
    audioEl = null
  }
  if (audioUrl) {
    URL.revokeObjectURL(audioUrl)
    audioUrl = null
  }
  playingSide.value = null
}

/** 同一任务（unitId）下的多次记录，按时间升序，方便看"越练越好还是越练越偏" */
const byUnit = computed(() => {
  const map = new Map<string, LearningRecord[]>()
  for (const record of userStore.learningRecords) {
    if (!map.has(record.unitId)) map.set(record.unitId, [])
    map.get(record.unitId)!.push(record)
  }
  for (const list of map.values()) {
    list.sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime())
  }
  return map
})

const unitOptions = computed(() =>
  [...byUnit.value.entries()].map(([id, list]) => {
    const first = list[0]
    return {
      id,
      label: `${first?.character || id}（${first?.pinyin || id}）· ${list.length} 次`,
      count: list.length,
    }
  }),
)

const records = computed<LearningRecord[]>(() =>
  unitId.value ? byUnit.value.get(unitId.value) ?? [] : [],
)

const left = computed(() => records.value.find(r => r.id === leftId.value) ?? null)
const right = computed(() => records.value.find(r => r.id === rightId.value) ?? null)

/** 默认选最近两次：A = 较早一次，B = 较近一次 */
function pickDefaults() {
  const list = records.value
  if (list.length < 2) {
    leftId.value = list[0]?.id ?? ''
    rightId.value = ''
    return
  }
  leftId.value = list[list.length - 2]!.id
  rightId.value = list[list.length - 1]!.id
}

watch(unitId, () => {
  pickDefaults()
  nextTick(() => renderTrend())
})

const showLoading = computed(() => loading.value || userStore.isLoading)
const showError = computed(() => !showLoading.value && !!userStore.error)
const showEmpty = computed(() => !showLoading.value && !showError.value && userStore.learningRecords.length === 0)
const showTooFew = computed(
  () => !showEmpty.value && !showLoading.value && !showError.value && !!unitId.value && records.value.length < 2,
)

async function reload() {
  loading.value = true
  try {
    await userStore.fetchLearningRecords()
    if (!unitId.value || !byUnit.value.has(unitId.value)) {
      unitId.value = [...byUnit.value.keys()][0] ?? ''
    }
    pickDefaults()
  } finally {
    loading.value = false
  }
  await nextTick()
  renderTrend()
}

onMounted(async () => {
  if (!consented.value) {
    // 未同意存档 → 档案里不会有记录；先给说明，不替用户读库
    loading.value = false
    return
  }
  await reload()
})

onUnmounted(() => {
  stopAudio()
  const chart = trendRef.value ? echarts.getInstanceByDom(trendRef.value) : null
  chart?.dispose()
})

async function play(side: 'left' | 'right') {
  const record = side === 'left' ? left.value : right.value
  if (!record) return
  stopAudio()
  playerError.value = ''
  playingSide.value = side
  try {
    const url = await learningRecordApi.getRecordAudio(record.id)
    const element = new Audio(url)
    audioEl = element
    audioUrl = url
    element.onended = () => stopAudio()
    element.onerror = () => {
      playerError.value = '这条录音加载失败（文件可能已被清理）。'
      stopAudio()
    }
    await element.play()
  } catch (err) {
    playerError.value = err instanceof Error ? err.message : String(err)
    playingSide.value = null
  }
}

/** 真实差值：B（较近）减 A（较早），正值 = 进步 */
const diff = computed(() => {
  if (!left.value || !right.value) return null
  return {
    score: Math.round((right.value.score - left.value.score) * 10) / 10,
    accuracy: Math.round(right.value.accuracy - left.value.accuracy),
    fluency: Math.round(right.value.fluency - left.value.fluency),
    pronunciation: Math.round(right.value.pronunciation - left.value.pronunciation),
  }
})

function deltaText(value: number, unit = ''): string {
  if (!value) return '持平'
  return `${value > 0 ? '↑ ' : '↓ '}${Math.abs(value)}${unit}`
}

function deltaClass(value: number): 'up' | 'down' | 'flat' {
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return 'flat'
}

function trendLabel(record: LearningRecord): string {
  return new Date(record.createdAt).toLocaleString(undefined, {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function renderTrend() {
  if (!trendRef.value) return
  const list = records.value
  echarts.getInstanceByDom(trendRef.value)?.dispose()
  if (list.length < 2) return
  const chart = echarts.init(trendRef.value)
  chart.setOption({
    title: { text: '同一任务的历次表现', left: 'center', textStyle: { fontSize: 13 } },
    tooltip: { trigger: 'axis' },
    legend: { data: ['总分', '准确度', '流利度'], bottom: 0, textStyle: { fontSize: 11 } },
    grid: { left: 44, right: 20, top: 36, bottom: 44 },
    xAxis: {
      type: 'category',
      data: list.map(r => trendLabel(r)),
      axisLabel: { fontSize: 10, rotate: 30 },
    },
    yAxis: { type: 'value', min: 0, max: 100, name: '分' },
    series: [
      {
        name: '总分',
        type: 'line',
        smooth: true,
        symbolSize: 7,
        lineStyle: { width: 3, color: '#409eff' },
        itemStyle: { color: '#409eff' },
        data: list.map(r => Math.round(r.score * 10) / 10),
      },
      {
        name: '准确度',
        type: 'line',
        smooth: true,
        lineStyle: { width: 2, color: '#67c23a' },
        itemStyle: { color: '#67c23a' },
        data: list.map(r => Math.round(r.accuracy)),
      },
      {
        name: '流利度',
        type: 'line',
        smooth: true,
        lineStyle: { width: 2, type: 'dashed', color: '#e6a23c' },
        itemStyle: { color: '#e6a23c' },
        data: list.map(r => Math.round(r.fluency)),
      },
    ],
  })
}
</script>

<template>
  <div class="compare-view">
    <header class="compare-header">
      <h2>多次录音对比</h2>
      <p class="intro">{{ copy.subtitle }}</p>
      <p class="meta">只读你自己练过、并同意保存的记录；不做排名，也不和别人的录音比。</p>
    </header>

    <!-- 未同意存档：档案里不会有记录，先把话说明白，不假装能对比 -->
    <el-card v-if="!consented" class="consent-card">
      <h3>还看不到对比</h3>
      <p>录音默认不保存，所以现在档案里还没有可对比的记录。</p>
      <p class="hint">
        同意保存后，每次练习的分数与录音会写进「我的声音」，才能比较前后几次的变化；同意可以随时撤回并删除。
      </p>
      <div class="actions">
        <el-button type="primary" @click="grant(); reload()">同意保存并查看</el-button>
        <el-button @click="router.push('/learn')">先去闯关（不保存）</el-button>
      </div>
    </el-card>

    <template v-else>
      <PageState v-if="showLoading" state="loading" :copy="copy" />
      <PageState
        v-else-if="showError"
        state="error"
        :copy="copy"
        :detail="userStore.error || ''"
        @action="reload"
      />
      <PageState v-else-if="showEmpty" state="empty" :copy="copy" @action="router.push('/learn')" />

      <el-card v-else class="picker-card">
        <div class="picker-row">
          <label>选择任务</label>
          <el-select v-model="unitId" placeholder="选一个练过的任务" style="width: 260px">
            <el-option v-for="u in unitOptions" :key="u.id" :label="u.label" :value="u.id" />
          </el-select>
          <el-tag size="small" type="info" effect="plain">该任务共 {{ records.length }} 次记录</el-tag>
          <el-button :icon="'Refresh'" text @click="reload">刷新</el-button>
        </div>

        <p v-if="showTooFew" class="hint">
          这个任务只有 {{ records.length }} 条记录，至少练两次才能对比前后变化。
        </p>

        <div v-else class="picker-row">
          <label>较早一次</label>
          <el-select v-model="leftId" placeholder="选 A" style="width: 230px">
            <el-option
              v-for="r in records"
              :key="r.id"
              :label="`${trendLabel(r)} · ${Math.round(r.score)} 分`"
              :value="r.id"
            />
          </el-select>
          <label>较近一次</label>
          <el-select v-model="rightId" placeholder="选 B" style="width: 230px">
            <el-option
              v-for="r in records"
              :key="r.id"
              :label="`${trendLabel(r)} · ${Math.round(r.score)} 分`"
              :value="r.id"
            />
          </el-select>
        </div>
      </el-card>

      <!-- 两段真实录音并排 -->
      <div v-if="left && right" class="compare-grid">
        <el-card v-for="side in (['left', 'right'] as const)" :key="side" class="record-card">
          <template #header>
            <div class="card-head">
              <strong>{{ side === 'left' ? 'A · 较早一次' : 'B · 较近一次' }}</strong>
              <span class="time">{{ new Date((side === 'left' ? left : right)!.createdAt).toLocaleString() }}</span>
            </div>
          </template>
          <div class="record-word">
            <span class="char">{{ (side === 'left' ? left : right)!.character || unitId }}</span>
            <span class="pinyin">{{ (side === 'left' ? left : right)!.pinyin }}</span>
          </div>
          <div class="score-row">
            <span class="score">{{ Math.round((side === 'left' ? left : right)!.score) }}</span>
            <span class="score-label">总分</span>
          </div>
          <div class="metrics">
            <div class="metric">
              <span>准确度</span>
              <el-progress :percentage="Math.round((side === 'left' ? left : right)!.accuracy)" :stroke-width="8" />
            </div>
            <div class="metric">
              <span>流利度</span>
              <el-progress :percentage="Math.round((side === 'left' ? left : right)!.fluency)" :stroke-width="8" color="#67c23a" />
            </div>
            <div class="metric">
              <span>发音</span>
              <el-progress :percentage="Math.round((side === 'left' ? left : right)!.pronunciation)" :stroke-width="8" color="#e6a23c" />
            </div>
          </div>
          <p class="feedback">{{ (side === 'left' ? left : right)!.feedback || '（这次没有留下文字结论）' }}</p>
          <el-button size="small" :loading="playingSide === side" @click="play(side)">
            {{ playingSide === side ? '播放中…' : '播放这段录音' }}
          </el-button>
        </el-card>

        <el-card class="diff-card">
          <h3>变化（B 相对 A）</h3>
          <template v-if="diff">
            <div class="diff-row" :class="deltaClass(diff.score)">
              <span>总分</span><strong>{{ deltaText(diff.score, ' 分') }}</strong>
            </div>
            <div class="diff-row" :class="deltaClass(diff.accuracy)">
              <span>准确度</span><strong>{{ deltaText(diff.accuracy, ' 分') }}</strong>
            </div>
            <div class="diff-row" :class="deltaClass(diff.fluency)">
              <span>流利度</span><strong>{{ deltaText(diff.fluency, ' 分') }}</strong>
            </div>
            <div class="diff-row" :class="deltaClass(diff.pronunciation)">
              <span>发音</span><strong>{{ deltaText(diff.pronunciation, ' 分') }}</strong>
            </div>
            <p class="note">差值只说明这两次录音的前后变化，不代表发音水平定论；换环境、换设备也会影响分数。</p>
          </template>
        </el-card>
      </div>

      <p v-if="playerError" class="play-error">{{ playerError }}</p>

      <el-card v-show="records.length >= 2" class="trend-card">
        <div ref="trendRef" class="trend-chart"></div>
        <p class="chart-desc">同一任务的全部 {{ records.length }} 次记录（时间轴按练习先后）。</p>
      </el-card>

      <div v-if="left && right" class="tail-actions">
        <el-button type="primary" @click="router.push(`/learn/${unitId}`)">再练一次</el-button>
        <el-button @click="router.push('/archive')">回到声音档案</el-button>
      </div>
    </template>

    <SiteFooter />
  </div>
</template>

<style scoped>
.compare-view { max-width: 1000px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.compare-header h2 { margin: 0; font-size: 20px; color: #303133; }
.intro { margin: 8px 0 4px; color: #606266; font-size: 14px; }
.meta, .hint { margin: 0; color: #909399; font-size: 12px; line-height: 1.7; }
.consent-card h3 { margin: 0 0 8px; font-size: 16px; }
.actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
.picker-card :deep(.el-card__body) { display: flex; flex-direction: column; gap: 10px; }
.picker-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.picker-row label { font-size: 13px; color: #606266; }
.compare-grid { display: grid; grid-template-columns: 1fr 1fr 0.9fr; gap: 14px; }
.card-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.card-head .time { font-size: 11px; color: #909399; }
.record-word { display: flex; align-items: baseline; gap: 8px; }
.record-word .char { font-size: 30px; font-weight: 700; color: #303133; }
.record-word .pinyin { color: #409eff; }
.score-row { display: flex; align-items: baseline; gap: 6px; margin: 6px 0 10px; }
.score { font-size: 28px; font-weight: 700; color: #303133; }
.score-label { font-size: 12px; color: #909399; }
.metrics { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; }
.metric { display: grid; grid-template-columns: 52px 1fr; align-items: center; gap: 8px; font-size: 12px; color: #606266; }
.feedback { font-size: 12px; color: #606266; line-height: 1.6; min-height: 34px; }
.diff-card h3 { margin: 0 0 10px; font-size: 15px; }
.diff-row { display: flex; justify-content: space-between; font-size: 13px; padding: 6px 0; border-bottom: 1px dashed #ebeef5; }
.diff-row.up strong { color: #67c23a; }
.diff-row.down strong { color: #f56c6c; }
.diff-row.flat strong { color: #909399; }
.note { margin: 10px 0 0; font-size: 11px; color: #a8abb2; line-height: 1.6; }
.play-error { margin: 0; font-size: 12px; color: #c45656; }
.trend-card :deep(.el-card__body) { padding-top: 8px; }
.trend-chart { width: 100%; height: 260px; }
.chart-desc { margin: 4px 0 0; font-size: 11px; color: #909399; text-align: center; }
.tail-actions { display: flex; gap: 10px; }
@media (max-width: 900px) {
  .compare-grid { grid-template-columns: 1fr; }
}
</style>
