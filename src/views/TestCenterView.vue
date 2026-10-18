<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useRecordingStore } from '@/stores/recording'
import { useUnitsStore } from '@/stores/units'
import { useUserStore } from '@/stores/user'
import { useArchiveConsent, confirmArchiveConsent } from '@/composables/useArchiveConsent'
import { useSpeechDemo } from '@/composables/useSpeechDemo'
import { usePageCopy } from '@/composables/usePageCopy'
import { CORE_UNIT_IDS } from '@/data/coreUnits'
import PageState from '@/components/PageState.vue'
import PageFeedback from '@/components/PageFeedback.vue'

const route = useRoute()
const router = useRouter()
const recordingStore = useRecordingStore()
const unitsStore = useUnitsStore()
const userStore = useUserStore()
const { consented } = useArchiveConsent()
const speech = useSpeechDemo()

/** 儿童化文案位：P05（D 留位，G / I 定稿） */
const { copy } = usePageCopy('P05')

const unitId = ref(String(route.query.unit || 'ma'))
const envOk = ref(false)
const authOk = ref(false)
const countdown = ref(0)
const unit = ref<any>(null)
const micError = ref<string | null>(null)
const saveError = ref<string | null>(null)
/** 接口成功但没带回分析结果（第 8 周 D：这类情况不能跳到空白结果页） */
const noResultError = ref<string | null>(null)

const verifiedTasks = computed(() =>
  unitsStore.coreUnits.filter(u => u.verified && CORE_UNIT_IDS.includes(u.id as any))
)

/**
 * 任务加载状态：loading → error → 空。
 * 已发布单元里一个都没通过检测验证 → unopened（按 SRS 收缩规则，不是整版失败）；
 * 连已发布单元都没有 → empty。
 */
const loadState = computed<'loading' | 'error' | 'empty' | 'unopened' | null>(() => {
  if (unitsStore.loading) return 'loading'
  if (unitsStore.error) return 'error'
  if (verifiedTasks.value.length) return null
  return unitsStore.coreUnits.length ? 'unopened' : 'empty'
})

/** 分析阶段状态：正在分析 → loading；分析或落库失败 → error（原始错误进 detail） */
const analysisState = computed<'loading' | 'error' | null>(() => {
  if (recordingStore.isAnalyzing) return 'loading'
  if (recordingStore.error || saveError.value || noResultError.value) return 'error'
  return null
})

const analysisDetail = computed(() => {
  if (noResultError.value) return noResultError.value
  if (saveError.value) return `本轮结果未能保存到学习记录：${saveError.value}`
  return recordingStore.error || undefined
})

async function loadUnits() {
  await unitsStore.fetchPublished()
  unit.value = await unitsStore.getUnit(unitId.value)
}

/** 加载 / 错误 / 未开放态下的主按钮：未开放时切到第一个可检测任务，其余重新拉取单元 */
function handleLoadAction() {
  if (loadState.value === 'unopened') {
    const first = verifiedTasks.value[0]
    if (first) selectTask(first.id)
    return
  }
  loadUnits()
}

/** 分析失败后的主按钮：清掉本轮错误，回到「重录 → 再提交」 */
function retryAnalysis() {
  saveError.value = null
  noResultError.value = null
  recordingStore.clearError()
}

onMounted(loadUnits)

async function selectTask(id: string) {
  unitId.value = id
  unit.value = await unitsStore.getUnit(id)
  recordingStore.clearRecording()
  router.replace({ query: { unit: id } })
}

async function checkMic() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    authOk.value = true
    micError.value = null
    stream.getTracks().forEach(t => t.stop())
  } catch (e: any) {
    micError.value = e?.message || String(e)
    ElMessage.error(`${copy.error} 麦克风未授权：${micError.value}`)
  }
}

async function startTest() {
  if (!envOk.value || !authOk.value) {
    ElMessage.warning(copy.error)
    return
  }
  countdown.value = 3
  const timer = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0) {
      clearInterval(timer)
      recordingStore.startRecording()
    }
  }, 1000)
}

async function submit() {
  await recordingStore.stopRecording() // 等录音 Blob 就绪，避免竞态取到空录音
  saveError.value = null
  noResultError.value = null
  try {
    await recordingStore.analyzeRecording(unitId.value)
  } catch (e: any) {
    // 分析链路的异常仍按文案位提示，原始信息留在 detail
    saveError.value = e?.message || String(e)
    ElMessage.error(copy.error)
    return
  }
  if (recordingStore.error) {
    ElMessage.error(recordingStore.error)
    return
  }
  const a = recordingStore.assessment
  // 接口 200 但没带 data（或 data 被解析成空）时以前会直接跳到结果页，结果页拿不到结论、
  // 只能显示「上次练习结果 / 还没有录音结果」，看起来像分析没做完（第 8 周 D 修复）。
  // 这里就地拦下：说明原因、留在本页重录，绝不跳到空白结果页。
  if (!a) {
    noResultError.value = '分析没有返回结果（可能是录音太短或上传失败），请重录一次'
    ElMessage.error(noResultError.value)
    return
  }
  // 存档必须家长同意（第 7 周 D）：三次保存入口（关卡页 / 历史单元 / 检测中心）统一问一次，
  // 选「这次不保存」就只在结果页展示。分析结果在内存里，不影响 P09 的图表与四步反馈。
  // 不可评价的录音不写档案：不把"录音不合格"记成一次 0 分练习。
  if (a.evaluable && await confirmArchiveConsent()) {
    try {
      await userStore.addLearningRecord({
        unitId: unitId.value,
        pinyin: unit.value?.pinyin || '',
        character: unit.value?.character || '',
        score: a.score,
        accuracy: a.accuracy,
        fluency: a.fluency,
        pronunciation: a.pronunciation,
        duration: recordingStore.duration,
        feedback: a.feedback.map(f => f.phenomenon).join('; '),
        audioBlob: recordingStore.recordingState.audioBlob ?? new Blob(),
      })
    } catch (e: any) {
      // 落库失败不阻塞：分析结果已在内存里（P09 会照常完整展示样式与图表），
      // 但必须如实告知这次练习没进档案，不能静默——与关卡页 LearningView 的口径一致。
      saveError.value = e?.message || String(e)
      ElMessage.error(`分析结果仍会显示，但这次练习没能存进档案：${saveError.value}`)
    }
  } else if (a.evaluable) {
    ElMessage.info('这次结果没有存进档案；同意保存后，下一次练习才会记录。')
  }
  router.push(`/feedback/${unitId.value}`)
}
</script>

<template>
  <div class="test-center">
    <h2>检测中心</h2>
    <p class="intro">{{ copy.subtitle }}</p>

    <!-- 任务加载 / 错误 / 未开放统一走 P05 文案位：后端没连上要说清，不能让人误读成「就是没有任务」 -->
    <PageState
      :state="loadState"
      :copy="copy"
      :detail="loadState === 'error' ? (unitsStore.error || undefined) : undefined"
      @action="handleLoadAction"
    />

    <template v-if="!loadState">
      <!-- TEST-01 任务选择 -->
      <el-card class="step-card">
        <h4>1. 选择任务</h4>
        <el-radio-group v-model="unitId" @change="selectTask">
          <el-radio v-for="t in verifiedTasks" :key="t.id" :value="t.id" border class="task-radio">
            {{ t.character }}（{{ t.pinyin }}）
          </el-radio>
        </el-radio-group>
      </el-card>

      <el-card v-if="unit" class="task-card">
        <h3>任务：{{ unit.character }}（{{ unit.pinyin }}）</h3>
        <p>{{ unit.conclusion }}</p>
        <p class="meta">请朗读：{{ unit.character.split('/')[0] }} · 预计约 30 秒</p>
      </el-card>

      <!-- TEST-02 示范 -->
      <el-card class="step-card">
        <h4>2. 听示范</h4>
        <el-button @click="speech.speak(unit?.character?.split('/')[0] || '妈', 'normal')">正常速度</el-button>
        <el-button @click="speech.speak(unit?.character?.split('/')[0] || '妈', 'slow')">慢速</el-button>
        <p class="tts-note">{{ speech.disclaimer }}</p>
      </el-card>

      <!-- TEST-03 环境检查 -->
      <el-card class="step-card">
        <h4>3. 环境检查</h4>
        <el-checkbox v-model="envOk">我已确认环境安静、麦克风距离约 10–20 cm、设备正常</el-checkbox>
      </el-card>

      <!-- TEST-04/05 用途与授权 -->
      <el-card class="step-card">
        <h4>4. 用途说明与麦克风授权</h4>
        <p>录音用于本次检测分析。{{ consented ? '已同意保存到个人档案。' : '未同意前不会长期保存，也不用于研究或模型训练。' }}</p>
        <el-button @click="checkMic">请求麦克风权限</el-button>
        <el-tag v-if="authOk" type="success" style="margin-left:8px">已授权</el-tag>
        <p v-else class="hint">若拒绝授权，请在浏览器设置中开启麦克风后刷新页面。</p>
        <p v-if="micError" class="hint mic-error">授权失败原因：{{ micError }}</p>
      </el-card>

      <!-- TEST-06 录音 -->
      <el-card class="step-card">
        <h4>5. 录音</h4>
        <div v-if="countdown > 0" class="countdown">{{ countdown }}</div>
        <el-button v-if="!recordingStore.isRecording" type="danger" @click="startTest">{{ copy.cta }}</el-button>
        <el-button v-else type="info" @click="recordingStore.stopRecording()">停止</el-button>
        <audio v-if="recordingStore.audioUrl" :src="recordingStore.audioUrl" controls class="playback" />
        <div class="actions">
          <el-button @click="recordingStore.clearRecording()">重录</el-button>
          <el-button type="primary" :disabled="!recordingStore.hasRecording" :loading="recordingStore.isAnalyzing" @click="submit">提交分析</el-button>
        </div>
      </el-card>

      <!-- TEST-07 处理状态：分析与分析失败都走文案位，原始错误进 detail -->
      <PageState
        :state="analysisState"
        :copy="copy"
        :detail="analysisState === 'error' ? analysisDetail : undefined"
        :show-action="analysisState === 'error'"
        @action="retryAnalysis"
      />
    </template>

    <PageFeedback page="test-center" :unit-id="unitId" type="result" />
  </div>
</template>

<style scoped>
.test-center { max-width: 720px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.intro { color: #606266; font-size: 14px; margin: 0; }
.task-card h3 { margin: 0 0 8px; }
.meta, .tts-note, .hint { font-size: 13px; color: #909399; }
.mic-error { color: #c45656; }
.step-card h4 { margin: 0 0 12px; }
.task-radio { margin: 4px 8px 4px 0; }
.countdown { font-size: 48px; font-weight: 700; text-align: center; color: #409eff; }
.playback { display: block; margin-top: 12px; width: 100%; }
.actions { margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
</style>
