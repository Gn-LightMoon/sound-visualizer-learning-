<script setup lang="ts">
/**
 * 历史「示范单元」面板（原 LearningView 内容原样保留）
 * ---------------------------------------------------------------------------
 * 用途：`/learn/:id` 传入的 id 不属于冻结的 30 关 L01–L30 时（如历史单元 ba / gou / b_p），
 * 继续提供原有的示范播放 + 录音 + 分析能力，作为「内部样本 / 后续扩展」。
 * 按排期口径：历史能力可保留，但不作为 1.0 对外验收的十页关卡口径。
 */
import { ref, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useRecordingStore } from '@/stores/recording'
import { useUserStore } from '@/stores/user'
import { useDemoPlayer } from '@/composables/useDemoPlayer'
import { confirmArchiveConsent } from '@/composables/useArchiveConsent'
import { getUnitMeta, isVerifiedUnit, getVerifiedUnitMeta } from '@/data/pinyinUnits'

const props = defineProps<{ unitId: string }>()

const router = useRouter()
const recordingStore = useRecordingStore()
const userStore = useUserStore()

const unitData: Record<string, any> = {
  ma: { pinyin: 'mā', character: '妈', tone: 1, desc: '双唇鼻音，第一声（阴平）', detail: '双唇紧闭，软腭下降，打开鼻腔通路，声带振动。声调保持高平。' },
  ba: { pinyin: 'bā', character: '八', tone: 1, desc: '双唇清塞音，第一声', detail: '双唇紧闭，然后突然打开，气流冲出。不送气。' },
  pa: { pinyin: 'pā', character: '趴', tone: 1, desc: '双唇清塞音，第一声', detail: '双唇紧闭，然后突然打开，气流冲出。送气。' },
  ta: { pinyin: 'tā', character: '他', tone: 1, desc: '舌尖中清塞音，第一声', detail: '舌尖抵住上齿龈，然后突然放开。' },
  yi: { pinyin: 'yī', character: '一', tone: 1, desc: '齐齿呼，第一声', detail: '口微开，上下齿对齐，舌面前部接近硬腭。' },
  wu: { pinyin: 'wǔ', character: '五', tone: 3, desc: '合口呼，第三声', detail: '双唇拢圆，舌面后部隆起。声调先降后升。' },
  yu: { pinyin: 'yú', character: '鱼', tone: 2, desc: '撮口呼，第二声', detail: '双唇拢圆，舌面前部接近硬腭。声调上升。' },
  mao: { pinyin: 'māo', character: '猫', tone: 1, desc: '双唇鼻音+复韵母', detail: '先发m音，然后滑向ao。' },
  gou: { pinyin: 'gǒu', character: '狗', tone: 3, desc: '舌根音+复韵母', detail: '舌根抵住软腭，然后放开，滑向ou。' },
  niao: { pinyin: 'niǎo', character: '鸟', tone: 3, desc: '舌尖中音+复韵母', detail: '舌尖抵住上齿龈，鼻音，滑向iao。' },
  ma_t2: { pinyin: 'má', character: '麻', tone: 2, desc: '双唇鼻音，第二声（阳平）', detail: '声调从中音升到高音。' },
  ma_t3: { pinyin: 'mǎ', character: '马', tone: 3, desc: '双唇鼻音，第三声（上声）', detail: '声调先降后升。' },
}

const unitId = computed(() => props.unitId)
// 是否已通过验证、开放 AI 检测的核心单元（与后端 GROW-08 分级开放策略一致）
const isVerified = computed(() => isVerifiedUnit(unitId.value))
const verifiedMeta = computed(() => getVerifiedUnitMeta(unitId.value))
// 优先取手工教学数据；未收录的拼音单元（发音库/地图全量单元）自动从共享数据兜底
const unit = computed(() => {
  const known = unitData[unitId.value]
  if (known) {
    return { ...known, pinyin: verifiedMeta.value?.pinyin ?? known.pinyin }
  }
  const meta = getUnitMeta(unitId.value)
  if (meta) {
    return {
      pinyin: verifiedMeta.value?.pinyin ?? meta.tone,
      character: meta.char,
      tone: 1,
      desc: `${unitId.value} 发音练习`,
      detail: '点击「播放示范」听标准发音，然后按下录音按钮练习。对照反馈页的评分与可视化结果不断改进。',
    }
  }
  if (verifiedMeta.value) {
    return {
      pinyin: verifiedMeta.value.pinyin,
      character: verifiedMeta.value.char,
      tone: 1,
      desc: `${verifiedMeta.value.desc}（核心对比单元）`,
      detail: '对比单元需分别朗读多个目标音节，注意区分发音部位与送气/不送气、鼻音/边音等特征。',
    }
  }
  return unitData.ma
})
/**
 * 示范音走全站统一的播放器（第 5 周 D 修复）
 *   原实现自己写了一遍 speechSynthesis，且「慢速播放」按钮没有 @click 是死按钮；
 *   这里改用 useDemoPlayer：有 CMS 正式示范音就播真实音频，没有才回落语音合成，
 *   并如实挂上「非正式授权示范音」声明。
 */
const { play: playDemoSource, isPlaying, disclaimer: ttsDisclaimer } = useDemoPlayer()

const canvasRef = ref<HTMLCanvasElement | null>(null)
let animationFrame: number | null = null

function playDemo(slow = false) {
  const text = unit.value.character
  if (!text) return
  playDemoSource(text, null, slow)
    .catch(() => ElMessage.warning(slow ? '慢速播放失败，稍后再试' : '这台设备暂时不能播放示范音'))
}

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
  stopRecording()
  await recordingStore.analyzeRecording(unitId.value)
  const assessment = recordingStore.assessment
  // 存档必须家长同意（第 7 周 D）：不同意就只在结果页展示，不写数据库
  // 不可评价的录音不写档案：不把"录音不合格"记成一次 0 分练习
  if (assessment && !assessment.evaluable) {
    ElMessage.info('这次录音无法可靠评价，结果不会存进档案（不记 0 分）。')
    router.push(`/feedback/${unitId.value}`)
    return
  }
  if (!(await confirmArchiveConsent())) {
    ElMessage.info('这次结果没有存进档案；同意保存后，下一次练习才会记录。')
    router.push(`/feedback/${unitId.value}`)
    return
  }
  try {
    await userStore.addLearningRecord({
      unitId: unitId.value,
      pinyin: unit.value.pinyin,
      character: unit.value.character,
      score: assessment?.score || 0,
      accuracy: assessment?.accuracy || 0,
      fluency: assessment?.fluency || 0,
      pronunciation: assessment?.pronunciation || 0,
      duration: recordingStore.duration,
      feedback: assessment?.feedback.map(f => f.message).join('; ') || '',
      audioBlob: recordingStore.recordingState.audioBlob ?? new Blob(),
    })
  } catch (err) {
    ElMessage.error('学习记录保存失败，请确认后端服务已启动')
  }
  router.push(`/feedback/${unitId.value}`)
}

onUnmounted(() => { stopVisualization() })
</script>

<template>
  <div class="learning-view">
    <!-- 顶部：发音教学区 -->
    <div class="teaching-section">
      <div class="unit-info">
        <div class="unit-character">{{ unit.character }}</div>
        <div class="unit-pinyin">
          {{ unit.pinyin }}
          <el-tag v-if="isVerified" type="success" size="small" effect="light" class="verify-tag">可检测</el-tag>
          <el-tag v-else type="info" size="small" effect="light" class="verify-tag">仅学习</el-tag>
        </div>
        <div class="unit-desc">{{ unit.desc }}</div>
        <p class="unit-detail">{{ unit.detail }}</p>
      </div>
      <div class="teaching-actions">
        <el-button type="primary" :icon="'VideoPlay'" @click="playDemo(false)" :loading="isPlaying">
          {{ isPlaying ? '播放中...' : '播放示范' }}
        </el-button>
        <!-- 第 5 周 D 修复：这个按钮原来没有 @click，是死按钮 -->
        <el-button :icon="'VideoPause'" @click="playDemo(true)">慢速播放</el-button>
      </div>
      <p class="demo-disclaimer">{{ ttsDisclaimer }}</p>
    </div>

    <!-- 中部：录音练习区 -->
    <div class="recording-section">
      <h3>录音练习</h3>
      <template v-if="isVerified">
        <div class="recording-controls">
          <el-button
            v-if="!recordingStore.isRecording"
            type="danger"
            :icon="'Microphone'"
            size="large"
            circle
            @click="startRecording"
            class="record-btn"
          />
          <el-button
            v-else
            type="info"
            :icon="'VideoPause'"
            size="large"
            circle
            @click="stopRecording"
            class="record-btn recording"
          />
          <span class="record-time">{{ recordingStore.formattedDuration }}</span>
        </div>
        <canvas ref="canvasRef" width="600" height="120" class="waveform-canvas"></canvas>
        <div v-if="recordingStore.hasRecording" class="record-actions">
          <el-button :icon="'Refresh'" @click="recordingStore.clearRecording">重录</el-button>
          <el-button type="primary" :icon="'DataAnalysis'" @click="analyzeAndGoFeedback" :loading="recordingStore.isAnalyzing">
            {{ recordingStore.isAnalyzing ? '分析中...' : '分析发音' }}
          </el-button>
        </div>
      </template>
      <template v-else>
        <div class="verify-hint">
          <el-icon color="#e6a23c" :size="20"><Warning /></el-icon>
          <div class="verify-hint-text">
            <strong>该单元暂未开放 AI 检测</strong>
            <p>本单元可播放示范跟读，如需获得评分与纠音反馈，请前往已开放检测的关卡练习。</p>
          </div>
          <el-button type="primary" size="small" @click="router.push('/learn')">去关卡页</el-button>
        </div>
      </template>
    </div>

    <!-- 底部：常见误区 -->
    <div class="mistakes-section">
      <h3>常见误区</h3>
      <div class="mistake-list">
        <div class="mistake-item" v-if="unitId === 'ma'">
          <el-icon color="#e6a23c"><Warning /></el-icon>
          <div><strong>声调不够高平</strong><p>保持声带张力稳定，不要在结尾下掉。</p></div>
        </div>
        <div class="mistake-item" v-if="unitId === 'ba'">
          <el-icon color="#e6a23c"><Warning /></el-icon>
          <div><strong>送气与不送气混淆</strong><p>b是不送气音，p是送气音。把手放在嘴前感受气流。</p></div>
        </div>
        <div class="mistake-item">
          <el-icon color="#409eff"><InfoFilled /></el-icon>
          <div><strong>练习建议</strong><p>先听示范3-5次，再尝试录音。录完后对比分析结果。</p></div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.learning-view { display: flex; flex-direction: column; gap: 20px; }
.teaching-section { background: white; border-radius: 12px; padding: 24px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.unit-info { flex: 1; }
.unit-character { font-size: 72px; font-weight: 700; color: #303133; line-height: 1; }
.unit-pinyin { font-size: 28px; color: #409eff; margin: 8px 0; display: flex; align-items: center; gap: 10px; }
.verify-tag { flex-shrink: 0; }
.unit-desc { font-size: 14px; color: #909399; }
.unit-detail { font-size: 14px; color: #606266; margin-top: 8px; line-height: 1.6; }
.teaching-actions { display: flex; flex-direction: column; gap: 8px; }
/* 示范音来源声明：没有 CMS 正式示范音时必须如实标注是语音合成示意 */
.demo-disclaimer { flex-basis: 100%; margin: 10px 0 0; font-size: 12px; color: #a8abb2; }
.recording-section { background: white; border-radius: 12px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); text-align: center; }
.recording-section h3 { margin: 0 0 16px; font-size: 16px; color: #303133; }
.verify-hint { display: flex; align-items: center; gap: 12px; text-align: left; padding: 16px; background: #fdf6ec; border: 1px solid #faecd8; border-radius: 8px; }
.verify-hint-text { flex: 1; }
.verify-hint-text strong { color: #b88230; }
.verify-hint-text p { margin: 4px 0 0; color: #8a6d3b; font-size: 13px; line-height: 1.6; }
.recording-controls { display: flex; align-items: center; justify-content: center; gap: 16px; margin-bottom: 16px; }
.record-btn { width: 64px; height: 64px; font-size: 24px; }
.record-btn.recording { animation: pulse 1s infinite; }
@keyframes pulse { 0%{transform:scale(1)} 50%{transform:scale(1.1)} 100%{transform:scale(1)} }
.record-time { font-size: 24px; font-weight: 600; color: #303133; font-variant-numeric: tabular-nums; }
.waveform-canvas { width: 100%; height: 120px; border-radius: 8px; background: #1a1a2e; }
.record-actions { margin-top: 16px; display: flex; justify-content: center; gap: 12px; }
.mistakes-section { background: white; border-radius: 12px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.mistakes-section h3 { margin: 0 0 16px; font-size: 16px; color: #303133; }
.mistake-list { display: flex; flex-direction: column; gap: 12px; }
.mistake-item { display: flex; gap: 12px; align-items: flex-start; padding: 12px; background: #f5f7fa; border-radius: 8px; }
.mistake-item strong { color: #303133; }
.mistake-item p { margin: 4px 0 0; color: #606266; font-size: 13px; }
</style>
