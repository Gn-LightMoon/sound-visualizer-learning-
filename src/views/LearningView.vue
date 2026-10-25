<script setup lang="ts">
/**
 * P08 关卡页（第 4 周 D 交付：LearningView 关卡页骨架）
 * ---------------------------------------------------------------------------
 * 两种形态（同一个页号，列表 + 单关）：
 *   - /learn         → 30 关 L01–L30 总览骨架（关卡身份来自 CON-02 冻结表）
 *   - /learn/:id     → 单关骨架（示范 / 练习 / 检测开关 + 上一关下一关）
 *
 * 数据链路（D 接 C）：
 *   CMS: GET /api/units?status=published  →  src/api/index.ts (levelsApi) → src/stores/levels.ts
 *   冻结表: src/data/levels.ts（只提供 ID / 顺序 / 目标音 / 分组 / 例字 / 文案位）
 *
 * 未开放 / 只学不测的关：只显示状态说明，不出现录音按钮、不出现分数（禁止假分）。
 * 历史单元（不在 30 关内）：落到 UnitLearningPanel，保留原有示范单元能力，不计入十页验收口径。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useLevelsStore } from '@/stores/levels'
import { useRecordingStore } from '@/stores/recording'
import { useUserStore } from '@/stores/user'
import { useArchiveConsent, confirmArchiveConsent } from '@/composables/useArchiveConsent'
import { useDemoPlayer } from '@/composables/useDemoPlayer'
import { usePageCopy } from '@/composables/usePageCopy'
import PageState from '@/components/PageState.vue'
import { getLevelNeighbors } from '@/data/levels'
import UnitLearningPanel from '@/components/UnitLearningPanel.vue'

const route = useRoute()
const router = useRouter()
const levelsStore = useLevelsStore()
const recordingStore = useRecordingStore()
const userStore = useUserStore()
/** 家长同意存档（第 7 周 D）：不登录也能闯关，但录音默认不留存 */
const { consented } = useArchiveConsent()
/**
 * 示范音播放（第 5 周 D 交付：关卡页至少一关示范可播放）
 *   有 CMS 正式示范音 unit.demoAudio → 播真实音频；
 *   没有 → 回落浏览器语音合成，并挂「非正式授权示范音」声明。
 * C 补 demo_audio 列并发布后，前端不需要再改代码。
 */
const { play: playDemoSource, isPlaying: isDemoPlaying, disclaimer: ttsDisclaimer } = useDemoPlayer()

/** 儿童化文案位：P08（唯一登记处 src/data/pages.ts，G / I 定稿后只改那一处） */
const { copy } = usePageCopy('P08')

const routeId = computed(() => (route.params.id as string | undefined) ?? '')
const isListMode = computed(() => !routeId.value)
const level = computed(() => (routeId.value ? levelsStore.getLevel(routeId.value) : undefined))
/** 历史单元：有 id 但不在冻结的 30 关里 */
const isLegacyUnit = computed(() => !!routeId.value && !level.value)

/** 送后端分析的 unit_id：优先用 CMS 命中的 id（后端 UNIT_REFERENCE 按 CMS id 校验） */
const activeUnitId = computed(() => level.value?.cmsId ?? '')
const neighbors = computed(() => (level.value ? getLevelNeighbors(level.value.code) : {}))

/**
 * 本关是否只能用语音合成示意。
 * true → 页面上必须挂 TTS 声明，不把合成音冒充正式授权示范音（SRS 要求如实标注）。
 */
const demoIsSynthetic = computed(() => !level.value?.unit?.demoAudio)

const canvasRef = ref<HTMLCanvasElement | null>(null)
let animationFrame: number | null = null

onMounted(() => {
  if (!isLegacyUnit.value) levelsStore.fetchLevels()
})
onUnmounted(() => stopVisualization())

function availabilityText(l: { availability: string }): string {
  if (l.availability === 'open') return '可以练习 + 可以检测'
  if (l.availability === 'learn_only') return '只学习，暂不检测'
  return '未开放'
}

/**
 * 「录音检测」卡片的说明文案（第 8 周 D 修复）
 * ---------------------------------------------------------------------------
 * 原来这里一律用 copy.unopened（「这一关还没开放」），但只学不测的关其实是**已发布**的，
 * 上面已经有一条「只学习、不检测」的提示，卡片里再说「还没开放」就自相矛盾，
 * 会被验收当成文案错误。这里按三态分别给话术。
 */
const detectionHint = computed(() =>
  level.value?.availability === 'learn_only'
    ? '这一关只学不测：评分还不能稳定复现，所以不开放检测、不会给出分数。跟着示范把音读稳就好。'
    : copy.unopened,
)

/** 未开放的关不渲染示范入口与教学卡片：内容还没过审，不拿占位内容充数（第 8 周 D） */
const showLevelBody = computed(() => level.value?.availability !== 'unopened')

/**
 * 「只看能练的」开关（第 8 周收口）
 * 30 关里目前只有 4 关能练，默认铺满灰卡片会让孩子找不到入口；
 * 开关打开只留可练可测的关，并给一个直接跳到第 1 关可练的按钮。
 */
const onlyOpen = ref(false)
const visibleGroups = computed(() =>
  onlyOpen.value
    ? levelsStore.levelGroups.map(g => ({ ...g, items: g.items.filter(l => l.availability === 'open') }))
    : levelsStore.levelGroups,
)

function goFirstOpen() {
  const first = levelsStore.levels.find(l => l.availability === 'open')
  if (first) openLevel(first.code)
}

function availabilityTag(l: { availability: string }): 'success' | 'warning' | 'info' {
  if (l.availability === 'open') return 'success'
  if (l.availability === 'learn_only') return 'warning'
  return 'info'
}

/** 列表卡片上的短标签（第 8 周收口：手机两列时「可以练习 + 可以检测」会顶出卡片） */
function availabilityShort(l: { availability: string }): string {
  if (l.availability === 'open') return '可练可测'
  if (l.availability === 'learn_only') return '只学不测'
  return '未开放'
}

/** 已发布的关：未开放的关页里用它给出「先练这几关」，不摆空白页 */
const openLevels = computed(() => levelsStore.levels.filter(l => l.availability === 'open'))

function openLevel(code: string) {
  router.push(`/learn/${code}`)
}

/** 示范朗读文本：优先 CMS 的例字，其次冻结表的例字 */
const demoText = computed(() => level.value?.unit?.character || level.value?.char || '')

function playDemo() {
  const text = demoText.value
  if (!text) return
  playDemoSource(text, level.value?.unit?.demoAudio, false)
    .catch(() => ElMessage.warning('这台设备暂时不能播放示范音，先跟着老师读一遍吧'))
}

function playSlow() {
  const text = demoText.value
  if (!text) return
  playDemoSource(text, level.value?.unit?.demoAudio, true)
    .catch(() => ElMessage.warning('慢速播放失败，稍后再试'))
}

/* ------------------------------ 录音 → 结果页闭环 ------------------------------ */
async function startRecording() {
  await recordingStore.startRecording()
  startVisualization()
}

function stopRecording() {
  recordingStore.stopRecording()
  stopVisualization()
}

function startVisualization() {
  const analyser = recordingStore.getAnalyser()
  if (!analyser || !canvasRef.value) return
  const canvas = canvasRef.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const safeAnalyser = analyser
  const bufLen = safeAnalyser.frequencyBinCount
  const data = new Uint8Array(bufLen)
  function draw() {
    animationFrame = requestAnimationFrame(draw)
    safeAnalyser.getByteTimeDomainData(data)
    ctx!.fillStyle = '#1a1a2e'
    ctx!.fillRect(0, 0, canvas.width, canvas.height)
    ctx!.lineWidth = 2; ctx!.strokeStyle = '#409eff'; ctx!.beginPath()
    const sw = canvas.width / bufLen; let x = 0
    for (let i = 0; i < bufLen; i++) {
      const y = ((data[i] ?? 128) / 128.0) * canvas.height / 2
      i === 0 ? ctx!.moveTo(x, y) : ctx!.lineTo(x, y)
      x += sw
    }
    ctx!.lineTo(canvas.width, canvas.height / 2); ctx!.stroke()
  }
  draw()
}

function stopVisualization() {
  if (animationFrame) { cancelAnimationFrame(animationFrame); animationFrame = null }
}

async function analyzeAndGoFeedback() {
  if (!activeUnitId.value) return
  await recordingStore.stopRecording()
  await recordingStore.analyzeRecording(activeUnitId.value)
  const assessment = recordingStore.assessment
  // 分析失败 / 没拿到结果：就地给出原因并留在本页重录，绝不跳到空白结果页
  if (recordingStore.error || !assessment) {
    ElMessage.error(recordingStore.error || '分析没有返回结果，请重录一次')
    return
  }
  // 存档必须家长同意（第 7 周 D）：未同意时弹一次确认，选「这次不保存」就不落库，
  // 但分析结果照常带进结果页展示（P09 从内存读，不依赖数据库）。
  // 不可评价的录音同样不写档案：不把"录音不合格"记成一次 0 分练习。
  if (!assessment.evaluable) {
    ElMessage.info('这次录音无法可靠评价，结果不会存进档案（不记 0 分）。')
    router.push(`/feedback/${activeUnitId.value}`)
    return
  }
  const allowed = await confirmArchiveConsent()
  if (!allowed) {
    ElMessage.info('这次结果没有存进档案；同意保存后，下一次练习才会记录。')
    router.push(`/feedback/${activeUnitId.value}`)
    return
  }
  try {
    await userStore.addLearningRecord({
      unitId: activeUnitId.value,
      pinyin: level.value?.unit?.pinyin || level.value?.pinyin || '',
      character: level.value?.unit?.character || level.value?.char || '',
      score: assessment.score || 0,
      accuracy: assessment.accuracy || 0,
      fluency: assessment.fluency || 0,
      pronunciation: assessment.pronunciation || 0,
      duration: recordingStore.duration,
      feedback: assessment.feedback.map(f => f.message).join('; ') || '',
      audioBlob: recordingStore.recordingState.audioBlob ?? new Blob(),
    })
  } catch {
    ElMessage.error('学习记录保存失败（分析结果仍会显示），请确认后端服务已启动')
  }
  router.push(`/feedback/${activeUnitId.value}`)
}
</script>

<template>
  <!-- ============ 历史单元：不在 30 关冻结表内 ============ -->
  <UnitLearningPanel v-if="isLegacyUnit" :unit-id="routeId" />

  <!-- ============ 单关骨架 ============ -->
  <div v-else-if="!isListMode" class="level-view">
    <!-- 加载中（关卡身份来自冻结表，可先渲染；内容状态等 CMS 返回后再判，避免闪一下「未开放」） -->
    <div v-if="levelsStore.loading && !levelsStore.loaded" class="state-card">
      <PageState state="loading" :copy="copy" />
    </div>

    <!-- 加载失败：说清是后端没连上，不让人误判成「这一关不存在」 -->
    <div v-else-if="levelsStore.error" class="state-card">
      <PageState
        state="error"
        :copy="copy"
        :detail="levelsStore.error"
        action-text="重新加载"
        @action="levelsStore.fetchLevels(true)"
      />
    </div>

    <!-- 不在 30 关内的 id（兜底） -->
    <div v-else-if="!level" class="state-card">
      <PageState
        state="empty"
        :copy="copy"
        action-text="回到关卡列表"
        @action="router.push('/learn')"
      />
    </div>

    <template v-else>
      <!-- 关卡头部：身份（冻结表）+ 状态（CMS） -->
      <div class="level-header card">
        <div class="level-badge">{{ level.code }}</div>
        <div class="level-identity">
          <div class="level-target">
            {{ level.target }}
            <span class="level-pinyin">{{ level.unit?.pinyin || level.pinyin }}</span>
          </div>
          <div class="level-sub">
            <el-tag size="small" effect="plain">{{ level.groupLabel }}</el-tag>
            <span class="level-char">例字：{{ level.unit?.character || level.char }}</span>
            <el-tag size="small" :type="availabilityTag(level)" effect="light">
              {{ availabilityText(level) }}
            </el-tag>
          </div>
          <p class="level-hint">{{ level.childHint }}</p>
        </div>
        <div class="level-actions">
          <template v-if="showLevelBody">
            <el-button type="primary" :icon="'VideoPlay'" :loading="isDemoPlaying" @click="playDemo">
              听示范
            </el-button>
            <el-button :icon="'VideoPause'" @click="playSlow">慢速</el-button>
          </template>
          <!-- 未开放：不给示范入口（内容未过审），只留状态说明与回列表 -->
          <span v-else class="level-actions-note">内容通过审核后开放示范与练习</span>
        </div>
      </div>

      <!-- 示范音来源如实标注：有正式授权示范音就说明，没有就明说这是合成示意，不冒充 -->
      <template v-if="showLevelBody">
        <p v-if="demoIsSynthetic" class="disclaimer demo-source">{{ ttsDisclaimer }}</p>
        <p v-else class="disclaimer demo-source is-real">示范音来自 CMS 已审核发布的正式录音。</p>
      </template>

      <!-- 未开放 / 只学不测：明确状态，不给检测入口、不给分数 -->
      <el-alert
        v-if="level.availability === 'unopened'"
        class="card"
        type="info"
        show-icon
        :closable="false"
        :title="copy.unopened"
        description="本关的内容还没通过审核发布，按 SRS 收缩规则记「未开放」：可以先练前面已经开放的关卡。"
      />
      <!-- 未开放不代表页面只能空着：把「现在能练的关」直接列出来（第 8 周收口） -->
      <div v-if="level.availability === 'unopened' && openLevels.length" class="card block open-suggest">
        <h3>先练这几关（已经开放）</h3>
        <div class="open-chips">
          <el-button
            v-for="l in openLevels"
            :key="l.code"
            size="small"
            @click="openLevel(l.code)"
          >
            {{ l.code }} {{ l.target }} · {{ l.unit?.character || l.char }}
          </el-button>
        </div>
        <p class="block-text muted">本关通过审核后会在这里出现；现在先把能练的音读稳。</p>
      </div>
      <el-alert
        v-else-if="level.availability === 'learn_only'"
        class="card"
        type="warning"
        show-icon
        :closable="false"
        title="这一关只学习、不检测"
        description="当前评分还不能稳定复现，所以不开放检测，也就不会给出分数。跟着示范读熟就好。"
      />

      <!-- 未开放：整块教学区不渲染（没有过审内容就不摆空卡片，也不给检测入口） -->
      <div v-if="showLevelBody" class="level-body">
        <!-- 示范 / 练习：内容来自 CMS -->
        <div class="card block">
          <h3>跟着读</h3>
          <div v-if="level.unit">
            <p class="block-text">{{ level.unit.conclusion || level.unit.description }}</p>
            <p v-if="level.unit.detail" class="block-detail">{{ level.unit.detail }}</p>

            <div v-if="level.unit.steps?.length" class="step-list">
              <div v-for="(s, i) in level.unit.steps" :key="i" class="step-item">
                <span class="step-index">{{ i + 1 }}</span>
                <div>
                  <strong>{{ s.title || s.text || '练习一步' }}</strong>
                  <p v-if="s.text && s.title">{{ s.text }}</p>
                  <p v-if="s.duration" class="step-duration">约 {{ s.duration }}</p>
                </div>
              </div>
            </div>
            <p v-else class="block-text muted">{{ copy.empty }}</p>
          </div>
          <p v-else class="block-text muted">{{ copy.empty }}</p>
        </div>

        <!-- 检测：只有「已发布 + 已开放检测」才出现录音链路 -->
        <div class="card block">
          <h3>录音检测</h3>
          <template v-if="level.detectionOpen && activeUnitId">
            <div class="recording-controls">
              <el-button
                v-if="!recordingStore.isRecording"
                type="danger"
                :icon="'Microphone'"
                size="large"
                circle
                class="record-btn"
                @click="startRecording"
              />
              <el-button
                v-else
                type="info"
                :icon="'VideoPause'"
                size="large"
                circle
                class="record-btn recording"
                @click="stopRecording"
              />
              <span class="record-time">{{ recordingStore.formattedDuration }}</span>
            </div>
            <canvas ref="canvasRef" width="600" height="120" class="waveform-canvas"></canvas>
            <div v-if="recordingStore.hasRecording" class="record-actions">
              <el-button :icon="'Refresh'" @click="recordingStore.clearRecording">重录</el-button>
              <el-button
                type="primary"
                :icon="'DataAnalysis'"
                :loading="recordingStore.isAnalyzing"
                @click="analyzeAndGoFeedback"
              >
                {{ recordingStore.isAnalyzing ? '分析中…' : '看看读得怎么样' }}
              </el-button>
            </div>
            <!-- 家长同意存档：未同意时如实说明「不保存」，同意才会写档案（第 7 周 D） -->
            <p class="archive-hint">
              <template v-if="consented">已同意保存：本次结果会写入「我的声音」档案，可随时撤回并删除。</template>
              <template v-else>录音默认不保存。分析完会问你一次「要不要存进档案」，家长同意后才写入。</template>
            </p>
            <!-- 分析失败必须说清原因，不能静默（后端没起、麦克风异常、网络失败都在这里暴露） -->
            <el-alert
              v-if="recordingStore.error"
              class="record-error"
              type="error"
              show-icon
              :closable="false"
              :title="recordingStore.error"
              description="请确认后端已启动（npm run backend）、麦克风正常，然后点「重录」再试一次。"
            />
          </template>
          <p v-else class="block-text muted">
            {{ detectionHint }}
          </p>
        </div>

        <!-- 常见误区：内容来自 CMS -->
        <div class="card block">
          <h3>容易读错的地方</h3>
          <div v-if="level.unit?.mistakes?.length" class="mistake-list">
            <div v-for="(m, i) in level.unit.mistakes" :key="i" class="mistake-item">
              <el-icon color="#e6a23c"><Warning /></el-icon>
              <div>
                <strong>{{ m.title || m.phenomenon || '注意' }}</strong>
                <p>{{ m.text || m.hint || '' }}</p>
              </div>
            </div>
          </div>
          <p v-else class="block-text muted">{{ copy.empty }}</p>
        </div>
      </div>

      <!-- 关卡导航 -->
      <div class="card level-nav">
        <el-button :disabled="!neighbors.prev" @click="neighbors.prev && openLevel(neighbors.prev.code)">
          ← 上一关 {{ neighbors.prev ? `${neighbors.prev.code} ${neighbors.prev.target}` : '' }}
        </el-button>
        <el-button @click="router.push('/learn')">全部 30 关</el-button>
        <el-button :disabled="!neighbors.next" @click="neighbors.next && openLevel(neighbors.next.code)">
          下一关 {{ neighbors.next ? `${neighbors.next.code} ${neighbors.next.target}` : '' }} →
        </el-button>
      </div>
    </template>
  </div>

  <!-- ============ 30 关总览骨架 ============ -->
  <div v-else class="levels-view">
    <div class="card levels-header">
      <div>
        <h2>{{ copy.subtitle }}</h2>
        <p class="levels-meta">
          共 {{ levelsStore.levels.length }} 关 ·
          可练可测 {{ levelsStore.openedCount }} ·
          只学不测 {{ levelsStore.learnOnlyCount }} ·
          未开放 {{ levelsStore.unopenedCount }}
        </p>
      </div>
      <div class="levels-header-actions">
        <!-- 第 8 周收口：30 关里有 26 关还没发布，默认铺满整片灰卡片，
             孩子不好找到"现在能练的"。给一个开关 + 一键跳到第一关可练的。 -->
        <el-switch
          v-model="onlyOpen"
          size="small"
          active-text="只看能练的"
          :disabled="!levelsStore.openedCount"
        />
        <el-button
          v-if="levelsStore.openedCount"
          type="primary"
          plain
          :icon="'VideoPlay'"
          @click="goFirstOpen"
        >
          从能练的第 1 关开始
        </el-button>
        <el-button :icon="'Refresh'" :loading="levelsStore.loading" @click="levelsStore.fetchLevels(true)">
          刷新关卡
        </el-button>
      </div>
    </div>

    <PageState
      v-if="levelsStore.error"
      state="error"
      :copy="copy"
      :detail="levelsStore.error"
      action-text="重新加载"
      @action="levelsStore.fetchLevels(true)"
    />

    <PageState
      v-else-if="levelsStore.loading && !levelsStore.levels.length"
      state="loading"
      :copy="copy"
    />

    <!-- 只看能练的：滤空时说明原因，不摆空白区 -->
    <p v-else-if="onlyOpen && !visibleGroups.some(g => g.items.length)" class="levels-hint">
      现在还没有开放检测的关；等老师发布后这里就会出现。
    </p>

    <template v-for="group in visibleGroups" :key="group.key">
      <div v-if="group.items.length" class="group-block">
        <div class="group-title">
          <span>{{ group.label }}</span>
          <small>{{ group.items.length }} 关</small>
        </div>
        <div class="level-grid">
          <div
            v-for="l in group.items"
            :key="l.code"
            class="level-card"
            :class="[`is-${l.availability}`]"
            @click="openLevel(l.code)"
          >
            <div class="level-card-top">
              <span class="level-card-code">{{ l.code }}</span>
              <el-tag size="small" :type="availabilityTag(l)" effect="light">{{ availabilityShort(l) }}</el-tag>
            </div>
            <div class="level-card-target">{{ l.target }}</div>
            <div class="level-card-char">{{ l.unit?.character || l.char }}</div>
          </div>
        </div>
      </div>
    </template>

    <p class="levels-foot">
      关卡身份（ID / 顺序 / 目标音）已按 CON-02 冻结；内容与检测开关以 CMS（C 的
      <code>/api/units</code>）为准，未发布即「未开放」。
    </p>
  </div>
</template>

<style scoped>
.card { background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06); }
.card + .card, .card + .el-alert, .el-alert + .level-body { margin-top: 16px; }

/* ---- 状态卡 ---- */
.state-card { background: #fff; border-radius: 12px; padding: 32px; text-align: center; box-shadow: 0 2px 12px rgba(0,0,0,0.06); display: flex; flex-direction: column; align-items: center; gap: 10px; }
.state-title { font-size: 16px; font-weight: 600; color: #303133; margin: 0; }
.state-text { font-size: 13px; color: #909399; margin: 0; line-height: 1.7; }

/* ---- 单关 ---- */
.level-header { display: flex; align-items: center; gap: 20px; }
.level-badge { flex: 0 0 auto; background: #409eff; color: #fff; font-weight: 700; font-size: 20px; border-radius: 12px; padding: 14px 18px; letter-spacing: 1px; }
.level-identity { flex: 1; }
.level-target { font-size: 40px; font-weight: 700; color: #303133; line-height: 1.1; }
.level-pinyin { font-size: 20px; color: #409eff; margin-left: 12px; }
.level-sub { display: flex; align-items: center; gap: 10px; margin-top: 6px; flex-wrap: wrap; }
.level-char { font-size: 13px; color: #606266; }
.level-hint { margin: 8px 0 0; font-size: 14px; color: #606266; }
.level-actions { display: flex; flex-direction: column; gap: 8px; }
.level-actions-note { max-width: 160px; font-size: 12px; color: #a8abb2; line-height: 1.6; }
.level-body { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }
.block h3 { margin: 0 0 12px; font-size: 16px; color: #303133; }
.block-text { font-size: 14px; color: #303133; line-height: 1.7; margin: 0 0 8px; }
.block-text.muted { color: #a8abb2; }
.block-detail { font-size: 13px; color: #606266; line-height: 1.7; margin: 0 0 12px; }
.disclaimer { margin: 12px 0 0; font-size: 12px; color: #a8abb2; }
.demo-source { margin: 8px 2px 0; }
.demo-source.is-real { color: #67c23a; }
.level-nav { display: flex; justify-content: space-between; margin-top: 16px; }
.open-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }

/* ---- 步骤 / 误区 ---- */
.step-list, .mistake-list { display: flex; flex-direction: column; gap: 10px; }
.step-item, .mistake-item { display: flex; gap: 10px; align-items: flex-start; background: #f5f7fa; border-radius: 8px; padding: 10px 12px; }
.step-index { flex: 0 0 22px; height: 22px; border-radius: 50%; background: #409eff; color: #fff; font-size: 12px; display: flex; align-items: center; justify-content: center; }
.step-item strong, .mistake-item strong { color: #303133; font-size: 14px; }
.step-item p, .mistake-item p { margin: 2px 0 0; font-size: 13px; color: #606266; }
.step-duration { color: #a8abb2 !important; }

/* ---- 录音 ---- */
.recording-controls { display: flex; align-items: center; gap: 16px; margin-bottom: 12px; }
.record-btn { width: 60px; height: 60px; font-size: 22px; }
.record-btn.recording { animation: pulse 1s infinite; }
@keyframes pulse { 0% { transform: scale(1) } 50% { transform: scale(1.08) } 100% { transform: scale(1) } }
.record-time { font-size: 22px; font-weight: 600; color: #303133; font-variant-numeric: tabular-nums; }
.waveform-canvas { width: 100%; height: 110px; border-radius: 8px; background: #1a1a2e; }
.record-actions { margin-top: 12px; display: flex; gap: 12px; }
.archive-hint { margin: 10px 0 0; font-size: 12px; color: #a8abb2; line-height: 1.6; }
.record-error { margin-top: 12px; text-align: left; }

/* ---- 列表 ---- */
.levels-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.levels-header-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.levels-hint { margin: 4px 0 0; font-size: 13px; color: #909399; }
.levels-header h2 { margin: 0; font-size: 18px; color: #303133; }
.levels-meta { margin: 6px 0 0; font-size: 13px; color: #909399; }
.group-block { margin-top: 20px; }
.group-title { display: flex; align-items: baseline; gap: 8px; font-size: 15px; font-weight: 600; color: #303133; margin-bottom: 10px; }
.group-title small { font-weight: 400; color: #a8abb2; }
.level-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
.level-card { background: #fff; border-radius: 12px; padding: 14px; box-shadow: 0 2px 10px rgba(0,0,0,0.06); cursor: pointer; transition: transform .15s, box-shadow .15s; border: 1px solid transparent; }
.level-card:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0,0,0,0.1); }
.level-card.is-unopened { opacity: .62; }
.level-card.is-open { border-color: #b3e19d; }
.level-card.is-learn_only { border-color: #f3d19e; }
.level-card-top { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
.level-card-code { font-size: 12px; color: #909399; letter-spacing: .5px; }
.level-card-target { font-size: 30px; font-weight: 700; color: #303133; margin-top: 8px; }
.level-card-char { font-size: 13px; color: #909399; margin-top: 2px; }
.levels-foot { margin-top: 20px; font-size: 12px; color: #a8abb2; line-height: 1.7; }

@media (max-width: 900px) {
  .level-body { grid-template-columns: 1fr; }
  .level-header { flex-direction: column; align-items: flex-start; }
}
</style>
