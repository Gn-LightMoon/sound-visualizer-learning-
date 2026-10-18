<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useRecordingStore } from '@/stores/recording'
import * as echarts from 'echarts'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js'
import { getUnitMeta } from '@/data/pinyinUnits'
import { maskByVoiced, smoothSeries } from '@/utils/toneCurve'
import PageFeedback from '@/components/PageFeedback.vue'
import PageState from '@/components/PageState.vue'
import { usePageCopy } from '@/composables/usePageCopy'
import { useUserStore } from '@/stores/user'
import { learningRecordApi } from '@/api'
import { ElMessage } from 'element-plus'
import type { LearningRecord } from '@/types'

const route = useRoute()
const router = useRouter()
const recordingStore = useRecordingStore()
const userStore = useUserStore()
const { copy } = usePageCopy('P09')

const unitId = computed(() => route.params.id as string)
const assessment = computed(() => recordingStore.assessment)

// =============================================
// 刷新 / 直开本页时的结果恢复
// 分析结果（含 F0/MFCC/共振峰/能量）只存在于前端内存，LearningRecord 里没有
// audioAnalysis，所以恢复出来的只能是「上次练习结果」的分数与文字反馈，图表无法恢复。
// 状态机：idle/loading（请求中）→ done（有记录）/ empty（该关无记录）/ error（接口失败）
// =============================================
type RestoreState = 'idle' | 'loading' | 'done' | 'empty' | 'error'

const restoreState = ref<RestoreState>('idle')
const restoreError = ref('')
const lastRecord = ref<LearningRecord | null>(null)
const isPlaying = ref(false)

// 播放中的 blob URL 与音频实例，卸载/重播前都要释放，避免内存泄漏
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
  isPlaying.value = false
}

// 恢复该关最近一次练习记录：取用户记录 → 筛当前 unitId → 按 createdAt 倒序取最新一条
async function restoreLastRecord() {
  restoreState.value = 'loading'
  restoreError.value = ''
  try {
    const res = await learningRecordApi.getByUser(userStore.userId, 50)
    const mine = (res.data || [])
      .filter(r => r.unitId === unitId.value)
      .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
    const latest = mine[0] ?? null
    if (!latest) {
      lastRecord.value = null
      restoreState.value = 'empty'
      return
    }
    lastRecord.value = latest
    restoreState.value = 'done'
  } catch (err) {
    lastRecord.value = null
    restoreError.value = err instanceof Error ? err.message : String(err)
    restoreState.value = 'error'
  }
}

// 同一组件内切换关卡（/feedback/a → /feedback/b）时重新恢复，避免停留在上一关的记录
watch(unitId, () => {
  if (assessment.value) return
  stopAudio()
  lastRecord.value = null
  void restoreLastRecord()
})

// 按需拉取录音 blob URL 播放（后端 /learning-records/{id}/audio）
async function playLastRecord() {
  const record = lastRecord.value
  if (!record) return
  try {
    stopAudio()
    const url = await learningRecordApi.getRecordAudio(record.id)
    const el = new Audio(url)
    el.onended = () => { isPlaying.value = false }
    el.onerror = () => { isPlaying.value = false }
    audioUrl = url
    audioEl = el
    isPlaying.value = true
    await el.play()
  } catch (err) {
    console.error(err)
    stopAudio()
    ElMessage.error(copy.error)
  }
}

const toneChartRef = ref<HTMLDivElement | null>(null)
const threeContainerRef = ref<HTMLDivElement | null>(null)
const spectrogramRef = ref<HTMLCanvasElement | null>(null)
const formantChartRef = ref<HTMLDivElement | null>(null)
const energyChartRef = ref<HTMLDivElement | null>(null)

// =============================================
// 发音特征解析：根据拼音推导口腔各部位姿态
// =============================================
interface ArticulationPose {
  // 下颌开合度 0~1
  jaw: number
  // 舌位：舌尖/舌中/舌根的目标位置与缩放（x 前后、y 高低、z 左右）
  tongueTip: { x: number; y: number; z: number; sy: number }
  tongueMid: { x: number; y: number; z: number; sy: number }
  tongueBack: { x: number; y: number; z: number; sy: number }
  // 嘴唇：展唇(横向拉伸) 0~1、圆唇(向前收拢) 0~1
  lipSpread: number
  lipRound: number
  // 软腭下降（鼻音时打开鼻腔通道）0~1
  velum: number
  // 气流强度
  airflow: number
}

// 声母分类：舌位基准
const TONGUE_LOW = { x: 0, y: -0.18, z: 0, sy: 0.8 }   // 舌平放

// 声母 → 发音姿态
function getInitialPose(initial: string): ArticulationPose {
  switch (initial) {
    // 双唇音 b p m：双唇闭合，舌平放
    case 'b': case 'p': case 'm':
      return {
        jaw: 0.15, tongueTip: { ...TONGUE_LOW, x: 0.05 }, tongueMid: { ...TONGUE_LOW }, tongueBack: { ...TONGUE_LOW },
        lipSpread: 0.1, lipRound: 0.3, velum: initial === 'm' ? 1 : 0, airflow: initial === 'p' ? 1 : 0.3,
      }
    // 唇齿音 f：下唇抵上齿，舌平放稍后
    case 'f':
      return {
        jaw: 0.2, tongueTip: { ...TONGUE_LOW, x: -0.08 }, tongueMid: { ...TONGUE_LOW }, tongueBack: { ...TONGUE_LOW },
        lipSpread: 0.3, lipRound: 0.1, velum: 0, airflow: 0.9,
      }
    // 舌尖中音 d t n l：舌尖抵上齿龈，舌中部下沉
    case 'd': case 't': case 'n': case 'l':
      return {
        jaw: 0.3, tongueTip: { x: 0.08, y: 0, z: 0, sy: 1.5 }, tongueMid: { ...TONGUE_LOW }, tongueBack: { ...TONGUE_LOW },
        lipSpread: 0.2, lipRound: 0.1, velum: initial === 'n' ? 1 : 0, airflow: initial === 't' ? 1 : 0.3,
      }
    // 舌根音 g k h：舌根抬起抵软腭
    case 'g': case 'k': case 'h':
      return {
        jaw: 0.35, tongueTip: { ...TONGUE_LOW }, tongueMid: { ...TONGUE_LOW }, tongueBack: { x: -0.1, y: 0.08, z: 0, sy: 1.6 },
        lipSpread: 0.2, lipRound: 0.1, velum: 0, airflow: initial === 'k' ? 1 : (initial === 'h' ? 0.9 : 0.3),
      }
    // 舌面音 j q x：舌面前部抵硬腭，舌面抬高
    case 'j': case 'q': case 'x':
      return {
        jaw: 0.2, tongueTip: { x: 0.1, y: 0.05, z: 0, sy: 1.7 }, tongueMid: { x: 0.05, y: 0.05, z: 0, sy: 1.5 }, tongueBack: { ...TONGUE_LOW },
        lipSpread: 0.6, lipRound: 0, velum: 0, airflow: initial === 'q' ? 1 : (initial === 'x' ? 0.9 : 0.3),
      }
    // 翘舌音 zh ch sh r：舌尖卷起抵硬腭前部
    case 'zh': case 'ch': case 'sh': case 'r':
      return {
        jaw: 0.25, tongueTip: { x: 0.02, y: 0.1, z: 0, sy: 1.8 }, tongueMid: { x: 0, y: 0.02, z: 0, sy: 1.3 }, tongueBack: { ...TONGUE_LOW },
        lipSpread: 0.3, lipRound: 0.15, velum: 0, airflow: initial === 'ch' ? 1 : (initial === 'sh' ? 0.9 : 0.3),
      }
    // 平舌音 z c s：舌尖抵下齿背，舌平
    case 'z': case 'c': case 's':
      return {
        jaw: 0.2, tongueTip: { x: 0.1, y: -0.15, z: 0, sy: 1.0 }, tongueMid: { ...TONGUE_LOW }, tongueBack: { ...TONGUE_LOW },
        lipSpread: 0.3, lipRound: 0.1, velum: 0, airflow: initial === 'c' ? 1 : (initial === 's' ? 0.9 : 0.3),
      }
    default:
      return {
        jaw: 0.3, tongueTip: { ...TONGUE_LOW }, tongueMid: { ...TONGUE_LOW }, tongueBack: { ...TONGUE_LOW },
        lipSpread: 0.3, lipRound: 0.1, velum: 0, airflow: 0.3,
      }
  }
}

// 韵母 → 口型姿态
function getFinalPose(finals: string): ArticulationPose {
  const has = (re: RegExp) => re.test(finals)
  const isNasal = has(/n$/) || has(/ng$/)
  let pose: ArticulationPose
  if (has(/a/)) {
    // a 开口大、舌低
    pose = {
      jaw: 0.9, tongueTip: { x: 0, y: -0.25, z: 0, sy: 0.8 }, tongueMid: { x: 0, y: -0.2, z: 0, sy: 0.8 }, tongueBack: { x: 0, y: -0.15, z: 0, sy: 0.8 },
      lipSpread: 0.4, lipRound: 0.1, velum: isNasal ? 0.8 : 0, airflow: 0.4,
    }
  } else if (has(/o/)) {
    // o 圆唇、舌后缩
    pose = {
      jaw: 0.7, tongueTip: { x: -0.05, y: -0.15, z: 0, sy: 0.9 }, tongueMid: { x: -0.08, y: -0.1, z: 0, sy: 1.0 }, tongueBack: { x: -0.15, y: -0.05, z: 0, sy: 1.2 },
      lipSpread: 0.1, lipRound: 0.9, velum: isNasal ? 0.8 : 0, airflow: 0.4,
    }
  } else if (has(/i/)) {
    // i 展唇、舌位高前
    pose = {
      jaw: 0.35, tongueTip: { x: 0.15, y: 0.02, z: 0, sy: 1.4 }, tongueMid: { x: 0.1, y: 0.02, z: 0, sy: 1.3 }, tongueBack: { ...TONGUE_LOW },
      lipSpread: 1, lipRound: 0, velum: isNasal ? 0.8 : 0, airflow: 0.35,
    }
  } else if (has(/u/)) {
    // u 圆唇、舌位高后
    pose = {
      jaw: 0.35, tongueTip: { x: -0.05, y: -0.1, z: 0, sy: 1.0 }, tongueMid: { x: -0.1, y: -0.05, z: 0, sy: 1.1 }, tongueBack: { x: -0.15, y: 0, z: 0, sy: 1.3 },
      lipSpread: 0.05, lipRound: 1, velum: isNasal ? 0.8 : 0, airflow: 0.3,
    }
  } else if (has(/ü|v/)) {
    // ü 撮口、舌位高前
    pose = {
      jaw: 0.3, tongueTip: { x: 0.15, y: 0.05, z: 0, sy: 1.5 }, tongueMid: { x: 0.1, y: 0.05, z: 0, sy: 1.4 }, tongueBack: { ...TONGUE_LOW },
      lipSpread: 0.15, lipRound: 0.85, velum: isNasal ? 0.8 : 0, airflow: 0.3,
    }
  } else {
    // e 半开口、舌中
    pose = {
      jaw: 0.6, tongueTip: { x: 0, y: -0.12, z: 0, sy: 1.0 }, tongueMid: { x: 0, y: -0.1, z: 0, sy: 1.0 }, tongueBack: { x: 0, y: -0.05, z: 0, sy: 1.0 },
      lipSpread: 0.3, lipRound: 0.2, velum: isNasal ? 0.8 : 0, airflow: 0.35,
    }
  }
  return pose
}

// 从拼音解析声母/韵母
function splitPinyin(pinyin: string): { initial: string; finals: string } {
  const initials = ['zh', 'ch', 'sh', 'b', 'p', 'm', 'f', 'd', 't', 'n', 'l', 'g', 'k', 'h', 'j', 'q', 'x', 'r', 'z', 'c', 's', 'y', 'w']
  for (const ini of initials) {
    if (pinyin.startsWith(ini)) {
      return { initial: ini, finals: pinyin.slice(ini.length) }
    }
  }
  return { initial: '', finals: pinyin }
}

// 综合声母与韵母，得到最终发音姿态
function getArticulationPose(unitId: string): ArticulationPose {
  // 声调练习单元如 ma_t2 → 去后缀取 ma
  const baseId = unitId.replace(/_[a-z0-9]+$/i, '')
  const { initial, finals } = splitPinyin(baseId)
  const initialPose = initial ? getInitialPose(initial) : null
  const finalPose = getFinalPose(finals)

  // 无声母（零声母音节如 a/o/er）直接用韵母姿态
  if (!initialPose) return finalPose

  // 组合：下颌取韵母（元音主导口型），舌位声母为准（辅音成阻），唇形按元音
  return {
    jaw: Math.max(initialPose.jaw, finalPose.jaw * 0.7),
    tongueTip: initialPose.tongueTip,
    tongueMid: initialPose.tongueMid,
    tongueBack: initialPose.tongueBack,
    lipSpread: finalPose.lipSpread,
    lipRound: finalPose.lipRound,
    velum: Math.max(initialPose.velum, finalPose.velum),
    airflow: initialPose.airflow,
  }
}

// 当前单元的发音姿态（供动画使用）
const currentPose = computed(() => getArticulationPose(unitId.value))

// =============================================
// 精细 3D 口腔模型：上颚/软腭/上下颌/舌头/牙齿/嘴唇/声带/气流
// =============================================
function initThreeScene() {
  if (!threeContainerRef.value) return
  const container = threeContainerRef.value
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0xf7f4ef)
  // 浅色暖调背景，贴近教材纸张质感
  scene.fog = new THREE.Fog(0xf7f4ef, 8, 16)

  const camera = new THREE.PerspectiveCamera(42, container.clientWidth / container.clientHeight, 0.1, 100)
  // 默认侧面（矢状面）视角：第一眼就是教科书口腔剖面图
  camera.position.set(3.1, 0.05, 0.02)
  camera.lookAt(0, -0.1, 0)
  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setSize(container.clientWidth, container.clientHeight)
  renderer.shadowMap.enabled = true
  container.appendChild(renderer.domElement)

  // CSS2D 渲染器（汉字/发音信息标注，不随透视变形）
  const labelRenderer = new CSS2DRenderer()
  labelRenderer.setSize(container.clientWidth, container.clientHeight)
  labelRenderer.domElement.style.position = 'absolute'
  labelRenderer.domElement.style.top = '0'
  labelRenderer.domElement.style.left = '0'
  labelRenderer.domElement.style.pointerEvents = 'none'
  container.appendChild(labelRenderer.domElement)

  // 当前汉字 + 发音部位标注
  const meta = getUnitMeta(unitId.value)
  const labelDiv = document.createElement('div')
  labelDiv.style.cssText = 'text-align:center;color:#6b3a52;font-family:sans-serif;user-select:none;'
  const charSpan = document.createElement('div')
  charSpan.textContent = meta?.char || unitId.value
  charSpan.style.cssText = 'font-size:34px;font-weight:700;text-shadow:0 1px 4px rgba(255,255,255,0.8);'
  const pinyinSpan = document.createElement('div')
  pinyinSpan.textContent = meta?.tone || ''
  pinyinSpan.style.cssText = 'font-size:14px;color:#4a7a9a;margin-top:2px;'
  labelDiv.appendChild(charSpan)
  labelDiv.appendChild(pinyinSpan)
  const label = new CSS2DObject(labelDiv)
  label.position.set(0, 1.55, 0)
  scene.add(label)

  // 部位中文标注（悬停查看详细说明，帮助学习者看懂口腔结构）
  // 相机在 x 轴正方向看向原点，屏幕投影中 y 控制上下、z 控制左右、x 控制远近缩放
  // 坐标已按截图中模型的视觉方向重新对齐，使标签贴合对应结构外缘
  const partLabelItems = [
    { name: '鼻腔', desc: '鼻音（m、n、ng）的气流从这里流出', x: 0.15, y: 0.75, z: 0.0 },
    { name: '上颚', desc: '硬腭。舌面音（j、q、x）舌尖抵住硬腭前部', x: 0.15, y: 0.32, z: 0.15 },
    { name: '软腭', desc: '发鼻音时下垂，让气流转向鼻腔', x: 0.15, y: 0.42, z: -0.28 },
    { name: '悬雍垂', desc: '小舌，和软腭一起控制鼻音', x: 0.15, y: 0.18, z: -0.38 },
    { name: '上牙', desc: '唇齿音（f）下唇抵住上齿', x: 0.15, y: 0.08, z: 0.42 },
    { name: '下牙', desc: '平舌音（z、c、s）舌尖抵住下齿背', x: 0.15, y: -0.28, z: 0.35 },
    { name: '上唇', desc: '双唇音（b、p、m）上下唇闭合', x: 0.15, y: 0.2, z: 0.78 },
    { name: '下唇', desc: '唇齿音（f）下唇靠近上齿', x: 0.15, y: -0.35, z: 0.78 },
    { name: '舌头', desc: '舌尖、舌中、舌根控制大多数声母的发音部位', x: 0.15, y: -0.12, z: 0.08 },
    { name: '喉', desc: '气流从肺部经喉部进入口腔', x: 0.15, y: -0.28, z: -0.82 },
  ] as const
  for (const p of partLabelItems) {
    const pDiv = document.createElement('div')
    pDiv.textContent = p.name
    pDiv.title = p.desc
    // 始终浮于前景：半透明底 + 细描边，文字本身半透明，不遮挡 3D 模型
    pDiv.style.cssText = 'pointer-events:auto;cursor:help;z-index:10;background:rgba(255,255,255,0.45);border:1px solid rgba(255,255,255,0.7);border-radius:6px;padding:2px 8px;font-size:12px;font-weight:600;color:rgba(58,46,42,0.82);font-family:sans-serif;user-select:none;white-space:nowrap;box-shadow:0 1px 4px rgba(0,0,0,0.15);'
    const obj = new CSS2DObject(pDiv)
    obj.position.set(p.x, p.y, p.z)
    // 置于较高渲染顺序，确保标签叠在模型前景
    obj.renderOrder = 999
    scene.add(obj)
  }

  // ---- 灯光：柔和暖光，突出口腔内部结构 ----
  scene.add(new THREE.AmbientLight(0xffffff, 0.65))
  const hemi = new THREE.HemisphereLight(0xfff5ee, 0xc8b8a8, 0.6)
  scene.add(hemi)
  const dirMain = new THREE.DirectionalLight(0xfff0e0, 1.0)
  dirMain.position.set(2, 3, 4)
  scene.add(dirMain)
  const dirFill = new THREE.DirectionalLight(0xe8f0ff, 0.5)
  dirFill.position.set(-3, 1, 2)
  scene.add(dirFill)

  // ---- 辅助坐标网格（轻微）----
  // const grid = new THREE.GridHelper(4, 20, 0x334466, 0x223344)
  // grid.position.y = -1.2
  // scene.add(grid)

  // ---- 部件容器 ----
  // 上颌组（固定）
  const upperJaw = new THREE.Group()
  scene.add(upperJaw)
  // 下颌组（随开合旋转）
  const lowerJaw = new THREE.Group()
  lowerJaw.position.set(0, -0.55, 0.1)
  scene.add(lowerJaw)

  // ==================== 头部半透明轮廓（侧面剖面感） ====================
  const headMat = new THREE.MeshPhongMaterial({
    color: 0xc8b4a0, transparent: true, opacity: 0.12, side: THREE.DoubleSide, depthWrite: false,
  })
  const head = new THREE.Mesh(new THREE.SphereGeometry(1.35, 48, 32), headMat)
  head.scale.set(1, 0.9, 1.1)
  head.position.y = -0.05
  scene.add(head)
  // 剖面参考线（中线轮廓）
  const cutLineMat = new THREE.LineBasicMaterial({ color: 0xb8a898, transparent: true, opacity: 0.35 })
  const cutPts: THREE.Vector3[] = []
  for (let i = 0; i <= 40; i++) {
    const a = (i / 40) * Math.PI
    cutPts.push(new THREE.Vector3(Math.cos(a) * 1.3, Math.sin(a) * 1.15, 0))
  }
  scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(cutPts), cutLineMat))

  // ==================== 上颚（硬腭）：拱形穹顶 ====================
  const palateMat = new THREE.MeshPhongMaterial({
    color: 0xe0859a, transparent: true, opacity: 0.6, side: THREE.DoubleSide, depthWrite: false, shininess: 20,
  })
  const palate = new THREE.Mesh(new THREE.SphereGeometry(0.95, 48, 24, 0, Math.PI * 2, 0, Math.PI * 0.55), palateMat)
  palate.position.set(0, 0.42, -0.05)
  palate.scale.set(1, 0.62, 1)
  upperJaw.add(palate)
  // 硬腭纹路
  const ridgeMat = new THREE.LineBasicMaterial({ color: 0xc86078, transparent: true, opacity: 0.45 })
  const ridgePts: THREE.Vector3[] = []
  for (let i = 0; i <= 30; i++) {
    const a = (i / 30) * Math.PI * 0.9 - Math.PI * 0.45
    ridgePts.push(new THREE.Vector3(Math.sin(a) * 0.9, 0.42, Math.cos(a) * 0.9 * 0.35))
  }
  const ridgeLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints(ridgePts), ridgeMat)
  upperJaw.add(ridgeLine)

  // ==================== 软腭（可下垂，鼻音打开通道） ====================
  const velumMat = new THREE.MeshPhongMaterial({
    color: 0xd86078, transparent: true, opacity: 0.75, side: THREE.DoubleSide,
  })
  const velum = new THREE.Mesh(new THREE.SphereGeometry(0.4, 32, 16, 0, Math.PI * 2, Math.PI * 0.45, Math.PI * 0.55), velumMat)
  velum.position.set(0, 0.35, -0.75)
  velum.scale.set(0.7, 1, 0.55)
  upperJaw.add(velum)
  // 悬雍垂（小舌）
  const uvulaMat = new THREE.MeshPhongMaterial({ color: 0xc85068 })
  const uvula = new THREE.Mesh(new THREE.ConeGeometry(0.07, 0.2, 12), uvulaMat)
  uvula.position.set(0, 0.28, -0.78)
  upperJaw.add(uvula)

  // ==================== 鼻腔（鼻音通道，鼻音时气流由此流出） ====================
  const nosePath = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0, 0.78, 0.5),
    new THREE.Vector3(0, 0.9, 0),
    new THREE.Vector3(0, 0.85, -0.55),
  ])
  const noseGeom = new THREE.TubeGeometry(nosePath, 24, 0.1, 12, false)
  const noseMat = new THREE.MeshPhongMaterial({
    color: 0x7f9cc0, transparent: true, opacity: 0.5, side: THREE.DoubleSide, depthWrite: false,
  })
  const nose = new THREE.Mesh(noseGeom, noseMat)
  upperJaw.add(nose)

  // ==================== 上牙齿：门牙 + 两侧臼齿 ====================
  const teethMat = new THREE.MeshPhongMaterial({ color: 0xece0cc, shininess: 60 })
  const upperTeeth = new THREE.Group()
  upperJaw.add(upperTeeth)
  for (let i = -2; i <= 2; i++) {
    const incisor = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.16, 0.06), teethMat)
    incisor.position.set(i * 0.09, 0.16, 0.45 + Math.abs(i) * 0.015)
    incisor.rotation.z = i * 0.08
    upperTeeth.add(incisor)
  }
  // 上臼齿
  for (let i = 1; i <= 3; i++) {
    for (const side of [-1, 1]) {
      const molar = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.12, 0.08), teethMat)
      molar.position.set(side * (0.3 + i * 0.12), 0.14, 0.3 - i * 0.04)
      molar.rotation.z = side * 0.3
      molar.rotation.y = side * 0.2
      upperTeeth.add(molar)
    }
  }

  // ==================== 下颌骨 + 下牙齿 ====================
  const mandibleMat = new THREE.MeshPhongMaterial({
    color: 0x8f4052, transparent: true, opacity: 0.45, side: THREE.DoubleSide,
  })
  const mandible = new THREE.Mesh(new THREE.SphereGeometry(0.85, 40, 20, 0, Math.PI * 2, Math.PI * 0.45, Math.PI * 0.55), mandibleMat)
  mandible.position.y = 0.12
  mandible.scale.set(1, 0.6, 1)
  lowerJaw.add(mandible)

  const lowerTeeth = new THREE.Group()
  lowerJaw.add(lowerTeeth)
  for (let i = -2; i <= 2; i++) {
    const incisor = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.15, 0.06), teethMat)
    incisor.position.set(i * 0.09, 0.1, 0.42 + Math.abs(i) * 0.015)
    incisor.rotation.z = i * 0.08
    lowerTeeth.add(incisor)
  }
  for (let i = 1; i <= 3; i++) {
    for (const side of [-1, 1]) {
      const molar = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.11, 0.08), teethMat)
      molar.position.set(side * (0.3 + i * 0.12), 0.08, 0.26 - i * 0.04)
      molar.rotation.z = side * 0.3
      molar.rotation.y = side * 0.2
      lowerTeeth.add(molar)
    }
  }

  // ==================== 舌头：三段球体拼成扁长舌形（舌尖/舌中/舌根独立驱动） ====================
  const tongueMat = new THREE.MeshPhongMaterial({
    color: 0xd45068, transparent: true, opacity: 0.95, shininess: 30,
  })
  // 舌尖（圆润、可翘起，对应 d/t/n/l、zh/ch/sh、j/q/x 等舌位）
  const tongueTipMesh = new THREE.Mesh(new THREE.SphereGeometry(0.2, 24, 16), tongueMat)
  tongueTipMesh.scale.set(1, 0.55, 0.9)
  tongueTipMesh.position.set(0.42, -0.38, 0.55)
  lowerJaw.add(tongueTipMesh)
  // 舌中
  const tongueMidMesh = new THREE.Mesh(new THREE.SphereGeometry(0.27, 24, 16), tongueMat)
  tongueMidMesh.scale.set(1, 0.55, 0.9)
  tongueMidMesh.position.set(0, -0.4, -0.02)
  lowerJaw.add(tongueMidMesh)
  // 舌根（贴近咽喉，对应 g/k/h 舌根音）
  const tongueBackMesh = new THREE.Mesh(new THREE.SphereGeometry(0.24, 24, 16), tongueMat)
  tongueBackMesh.scale.set(1, 0.55, 0.9)
  tongueBackMesh.position.set(-0.42, -0.36, -0.55)
  lowerJaw.add(tongueBackMesh)

  // ==================== 嘴唇（上下唇，随开合与圆展变化） ====================
  const lipMat = new THREE.MeshPhongMaterial({ color: 0xc84860, shininess: 40 })
  const upperLip = new THREE.Mesh(new THREE.TorusGeometry(0.55, 0.09, 16, 40, Math.PI * 0.7), lipMat)
  upperLip.position.set(0, 0.12, 0.72)
  upperLip.rotation.set(Math.PI / 2, 0, Math.PI / 2)
  upperLip.scale.z = 0.85
  upperJaw.add(upperLip)
  const lowerLip = new THREE.Mesh(new THREE.TorusGeometry(0.55, 0.09, 16, 40, Math.PI * 0.7), lipMat)
  lowerLip.position.set(0, -0.12, 0.72)
  lowerLip.rotation.set(Math.PI / 2, 0, Math.PI / 2)
  lowerLip.scale.z = 0.85
  lowerJaw.add(lowerLip)

  // ==================== 气流粒子（从喉部向口外喷出，鼻音时部分走鼻腔） ====================
  const particleCount = 300
  const positions = new Float32Array(particleCount * 3)
  const velocities = new Float32Array(particleCount * 3)
  for (let i = 0; i < particleCount; i++) {
    resetParticle(i)
  }
  function resetParticle(i: number) {
    positions[i * 3] = (Math.random() - 0.5) * 0.4
    positions[i * 3 + 1] = -0.55 + (Math.random() - 0.5) * 0.2
    positions[i * 3 + 2] = -0.8 - Math.random() * 0.4
    velocities[i * 3] = (Math.random() - 0.5) * 0.3
    velocities[i * 3 + 1] = (Math.random() - 0.5) * 0.2
    velocities[i * 3 + 2] = 0.4 + Math.random() * 0.5
  }
  const particlesGeom = new THREE.BufferGeometry()
  particlesGeom.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  const particlesMat = new THREE.PointsMaterial({
    color: 0x3f7fc0, size: 0.05, transparent: true, opacity: 0.85, depthWrite: false,
  })
  const particles = new THREE.Points(particlesGeom, particlesMat)
  scene.add(particles)

  // ==================== 控制器 ====================
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.minDistance = 1.5
  controls.maxDistance = 8
  controls.target.set(0, -0.15, 0)

  // ==================== 动画循环 ====================
  let time = 0
  let rafId = 0
  // 当前姿态（线性插值逼近目标）
  const current = {
    jaw: 0.3, lipSpread: 0.3, lipRound: 0.1, velum: 0,
    tipX: 0, tipY: 0, midY: 0, backY: 0, backX: 0,
    airflow: 0.4,
  }

  function animate() {
    rafId = requestAnimationFrame(animate)
    time += 0.016
    const pose = currentPose.value

    // ---- 平滑逼近目标姿态 ----
    const k = 0.06
    current.jaw += (pose.jaw - current.jaw) * k
    current.lipSpread += (pose.lipSpread - current.lipSpread) * k
    current.lipRound += (pose.lipRound - current.lipRound) * k
    current.velum += (pose.velum - current.velum) * k
    current.tipX += (pose.tongueTip.x - current.tipX) * k
    current.tipY += (pose.tongueTip.y - current.tipY) * k
    current.midY += (pose.tongueMid.y - current.midY) * k
    current.backY += (pose.tongueBack.y - current.backY) * k
    current.backX += (pose.tongueBack.x - current.backX) * k
    current.airflow += (pose.airflow - current.airflow) * k

    // ---- 下颌开合（绕后方关节旋转） ----
    lowerJaw.rotation.x = -current.jaw * 0.5

    // ---- 舌头：三段球体独立驱动，模拟舌形弯曲 ----
    tongueTipMesh.position.set(current.tipX + 0.42, current.tipY - 0.38, 0.55)
    tongueMidMesh.position.set(0, current.midY - 0.4, -0.02)
    tongueBackMesh.position.set(current.backX - 0.42, current.backY - 0.36, -0.55)
    // 舌尖抬起时舌体微微上翘、收窄（翘舌/舌面音）
    const lift = (current.tipY + 0.18) / 0.3
    tongueTipMesh.scale.set(1, 0.55 - lift * 0.1, 0.9)
    tongueMidMesh.scale.set(1, 0.55 - lift * 0.08, 0.9)

    // ---- 嘴唇：开合 + 圆展 ----
    const lipOpen = current.jaw * 0.22
    upperLip.position.y = 0.12 + lipOpen * 0.15
    lowerLip.position.y = -0.12 - lipOpen * 0.35
    // 圆唇：横向收拢、向前凸；展唇：横向拉伸
    const roundScale = 1 - current.lipRound * 0.5
    upperLip.scale.set(roundScale * (1 + current.lipSpread * 0.3), roundScale * 0.9, 0.85 + current.lipRound * 0.5)
    lowerLip.scale.set(roundScale * (1 + current.lipSpread * 0.3), roundScale * 0.9, 0.85 + current.lipRound * 0.5)
    // 圆唇时嘴唇前移
    upperLip.position.z = 0.72 + current.lipRound * 0.25
    lowerLip.position.z = 0.72 + current.lipRound * 0.25

    // ---- 软腭：鼻音时下垂，打开鼻腔通道 ----
    velum.rotation.x = current.velum * 0.9
    velum.position.y = 0.35 - current.velum * 0.25
    uvula.rotation.x = current.velum * 0.9
    uvula.position.y = 0.28 - current.velum * 0.3

    // ---- 气流粒子：从喉部喷向口外；鼻音时部分从鼻腔通道飘出 ----
    const speedFactor = 0.6 + current.airflow * 1.6
    const posAttr = particlesGeom.attributes.position as THREE.BufferAttribute | undefined
    if (!posAttr) return
    const pos = posAttr.array as Float32Array
    const nasalOn = current.velum > 0.5
    for (let i = 0; i < particleCount; i++) {
      const useNasal = nasalOn && i % 3 === 0
      const idx = i * 3
      pos[idx] = (pos[idx] ?? 0) + (velocities[idx] ?? 0) * speedFactor
      pos[idx + 1] = (pos[idx + 1] ?? 0) + ((velocities[idx + 1] ?? 0) + (useNasal ? 0.55 : 0)) * speedFactor
      pos[idx + 2] = (pos[idx + 2] ?? 0) + (velocities[idx + 2] ?? 0) * speedFactor
      if (useNasal) {
        // 走鼻腔的粒子升到鼻腔高度后重新生成
        if ((pos[idx + 1] ?? 0) > 0.85) resetParticle(i)
      } else if ((pos[idx + 2] ?? 0) > 1.35) {
        resetParticle(i)
      }
    }
    posAttr.needsUpdate = true
    particlesMat.opacity = 0.35 + current.airflow * 0.45

    controls.update()
    renderer.render(scene, camera)
    labelRenderer.render(scene, camera)
  }
  animate()

  // 返回清理函数（组件卸载时释放资源）
  return () => {
    cancelAnimationFrame(rafId)
    renderer.dispose()
    controls.dispose()
    if (renderer.domElement.parentNode === container) {
      container.removeChild(renderer.domElement)
    }
    if (labelRenderer.domElement.parentNode === container) {
      container.removeChild(labelRenderer.domElement)
    }
  }
}

// 声调曲线对比图（标准曲线由后端生成）
// 改动1 -- > 使用voiced_flag决定是否保留f0：有声保留，无声设为null断线
// 第 8 周 D（体验打磨）：叠加 E 的 src/utils/toneCurve.ts 前两步——屏蔽静音、段内平滑。
//   F0 提取本身有抖动，直接画会呈锯齿；平滑只在连续有声段内做，遇到静音（null）就断开，
//   不跨静音段平均，避免把字与字之间的空白算进来。
//   注意：E 的第 3 步「T 值（0–5）归一化」尚未采用——它需要和 A 确认标准曲线的调域口径，
//   用错调域会把「说得低」误判成「说错了」；等 A/E 定稿后再在 P09 切换。
function initToneChart() {
  if (!toneChartRef.value) return
  const existing = echarts.getInstanceByDom(toneChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(toneChartRef.value)

  const rawF0: number[] = assessment.value?.audioAnalysis?.f0 || []
  const voiced: (boolean | undefined)[] = assessment.value?.audioAnalysis?.voiced_flag || []
  const voicedProbs: number[] = assessment.value?.audioAnalysis?.voiced_probs || []

  // 用 voiced_flag 掩码：unvoiced -> null（ECharts 遇到 null 会断线），再做段内平滑
  const voicedMask = voiced.length ? (voiced as boolean[]) : undefined
  const userF0 = smoothSeries(maskByVoiced(rawF0, voicedMask), 2)

  // 标准曲线：只画后端真实返回的 standardF0（第 8 周 D 修复假数据）
  // ---------------------------------------------------------------------------
  // 这里原来有个兜底：后端没给 standard_f0 时，按 detectedTone 用公式（120+t*80 之类）
  // 临时造一条「标准发音」曲线。那不是任何真实录音，属于排期禁止的「假分 / 假曲线」，
  // 而且一旦 30 关正式发布（后端 UNIT_REFERENCE 里还没有 L02 这些新 id，就不会返回
  // standard_f0），这条假曲线会被当成真实标准线展示。现在：没有就不画，并如实说明。
  const standardRaw: number[] = assessment.value?.audioAnalysis?.standardF0 || []
  const hasStandard = standardRaw.length > 0

  // 后端标准曲线与本次 F0 帧数可能不一致，按帧索引对齐到 rawF0.length（保证同一时间轴）
  const standardF0: (number | null)[] = hasStandard
    ? rawF0.map((_, i) => {
        const idx = Math.min(
          standardRaw.length - 1,
          Math.floor((i / Math.max(1, rawF0.length)) * standardRaw.length),
        )
        const v = standardRaw[idx]
        return typeof v === 'number' && v > 0 ? v : null
      })
    : []

  const labels = rawF0.map((_, i) => i)

  chart.setOption({
    title: {
      text: hasStandard ? '声调曲线对比' : '声调曲线（本次未返回标准曲线）',
      left: 'center',
      textStyle: { fontSize: 14 },
    },
    tooltip: {
      trigger: 'axis',
      // tooltip 显示：频率 + 是否有声 + voiced_prob（若有）
      formatter: (params: any) => {
        // params 为数组：0=您的发音,1=标准发音（视图序列顺序）
        const p = Array.isArray(params) ? params[0] : params
        const idx = p?.dataIndex ?? 0
        const val = p?.data ?? null
        // 有声/无声：后端填了 voiced_flag 就用它，否则按原始 f0>0 判定（第 8 周 D 修正）
        const rawVal = rawF0[idx]
        const isVoiced = typeof voiced[idx] === 'boolean'
          ? (voiced[idx] as boolean)
          : (typeof rawVal === 'number' && rawVal > 0)
        const prob = voicedProbs[idx]
        const voicedTxt = isVoiced ? '有声' : '无声'
        const probTxt = (typeof prob === 'number') ? `<br/>voiced_prob: ${prob.toFixed(2)}` : ''
        return `时间: ${idx}<br/>频率: ${val === null ? '—' : (val.toFixed ? val.toFixed(1) + ' Hz' : val)}<br/>${voicedTxt}${probTxt}`
      }
    },
    legend: hasStandard ? { data: ['您的发音', '标准发音'], bottom: 0 } : { show: false },
    xAxis: { type: 'category', data: labels, name: '时间' },
    yAxis: { type: 'value', name: '频率 (Hz)' },
    series: [
      {
        name: '您的发音',
        type: 'line',
        data: userF0,
        connectNulls: false, // 断线
        smooth: true,
        lineStyle: { color: '#409eff', width: 3 },
        itemStyle: { color: '#409eff' },
        symbol: 'circle',
        symbolSize: 6,
        // 通过 emphasis 或 tooltip 显示 voiced_prob（已经在 tooltip formatter 中处理）
      },
      ...(hasStandard
        ? [{
            name: '标准发音',
            type: 'line' as const,
            data: standardF0,
            smooth: true,
            connectNulls: false,
            lineStyle: { color: '#67c23a', width: 3, type: 'dashed' as const },
            itemStyle: { color: '#67c23a' },
            symbol: 'none',
          }]
        : []),
    ],
    grid: { left: 60, right: 30, top: 40, bottom: 40 },
  })
}

// 声谱图（语谱图）
function initSpectrogram() {
  if (!spectrogramRef.value) return
  const canvas = spectrogramRef.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  canvas.width = 500
  canvas.height = 200
  const w = canvas.width
  const h = canvas.height

  // 用后端返回的真实MFCC数据生成频谱图（无假数据回退）
  const timeSteps = 100
  const freqBins = 80
  const mfcc = assessment.value?.audioAnalysis?.mfcc || []

  // 若后端未返回MFCC数据，显示空白并标注
  const hasMfcc = mfcc.length > 0 && (mfcc[0]?.length ?? 0) > 0

  for (let t = 0; t < timeSteps; t++) {
    for (let f = 0; f < freqBins; f++) {
      // 用MFCC数据生成能量值
      let energy = 0
      if (hasMfcc) {
        const mfccIdx = Math.floor(f / freqBins * mfcc.length)
        const timeIdx = Math.floor(t / timeSteps * (mfcc[0]?.length || 1))
        energy = Math.abs(mfcc[mfccIdx]?.[timeIdx] || 0)
      } else {
        energy = 0
      }
      energy = Math.max(0, Math.min(1, energy))

      // 颜色映射：深蓝→青→绿→黄→红
      const r = Math.floor(energy < 0.5 ? energy * 2 * 255 : 255)
      const g = Math.floor(energy < 0.5 ? energy * 2 * 255 : (1 - energy) * 2 * 255)
      const b = Math.floor(energy < 0.5 ? 255 : (1 - energy) * 2 * 255)

      ctx.fillStyle = `rgb(${r},${g},${b})`
      ctx.fillRect((t / timeSteps) * w, (1 - f / freqBins) * h, w / timeSteps + 1, h / freqBins + 1)
    }
  }

  // 坐标轴标签
  ctx.fillStyle = '#909399'
  ctx.font = '11px sans-serif'
  ctx.fillText('时间 →', w - 50, h - 5)
  ctx.save()
  ctx.translate(12, h / 2)
  ctx.rotate(-Math.PI / 2)
  ctx.fillText('频率 →', -20, 0)
  ctx.restore()
}

// 共振峰轨迹图 (F1-F2空间)
function initFormantChart() {
  if (!formantChartRef.value) return
  const existing = echarts.getInstanceByDom(formantChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(formantChartRef.value)

  const f1Data = assessment.value?.audioAnalysis?.f1 || []
  const f2Data = assessment.value?.audioAnalysis?.f2 || []

  // 采样减少点数
  const step = Math.max(1, Math.floor(f1Data.length / 30))
  const scatterData: number[][] = []
  for (let i = 0; i < f1Data.length; i += step) {
    scatterData.push([f2Data[i] ?? 0, f1Data[i] ?? 0])
  }

  // 标准元音位置 (F2, F1)
  const standardVowels: [string, number[]][] = [
    ['i', [2400, 280]], ['e', [2100, 400]], ['a', [1100, 750]],
    ['o', [800, 500]], ['u', [600, 300]],
  ]

  chart.setOption({
    title: { text: '共振峰轨迹图 (F1-F2)', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {
      formatter: (p: any) => {
        if (p.seriesIndex === 0) return `F1: ${p.data[1].toFixed(0)} Hz<br/>F2: ${p.data[0].toFixed(0)} Hz`
        return p.name
      },
    },
    xAxis: { type: 'value', name: 'F2 (Hz)', inverse: true, min: 500, max: 2500 },
    yAxis: { type: 'value', name: 'F1 (Hz)', inverse: true, min: 200, max: 900 },
    series: [
      {
        name: '您的发音',
        type: 'line',
        data: scatterData,
        smooth: true,
        lineStyle: { color: '#409eff', width: 3 },
        itemStyle: { color: '#409eff' },
        symbolSize: 6,
      },
      {
        name: '标准元音',
        type: 'scatter',
        data: standardVowels.map(v => ({ value: v[1], name: v[0] })),
        symbolSize: 14,
        itemStyle: { color: '#67c23a' },
        label: { show: true, formatter: '{b}', position: 'right', fontSize: 12 },
      },
    ],
    legend: { data: ['您的发音', '标准元音'], bottom: 0 },
    grid: { left: 60, right: 40, top: 40, bottom: 40 },
  })
}

// 能量包络图
function initEnergyChart() {
  if (!energyChartRef.value) return
  const existing = echarts.getInstanceByDom(energyChartRef.value)
  if (existing) existing.dispose()
  const chart = echarts.init(energyChartRef.value)

  const energy = assessment.value?.audioAnalysis?.energy || []
  const labels = energy.map((_, i) => i)
  const duration = assessment.value?.audioAnalysis?.duration || 1.5

  chart.setOption({
    title: { text: '能量包络图', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis', formatter: (p: any) => `时间: ${(p[0].dataIndex / energy.length * duration).toFixed(2)}s<br/>能量: ${p[0].data.toFixed(3)}` },
    xAxis: {
      type: 'category',
      data: labels,
      name: '时间',
      axisLabel: { formatter: (v: string) => (parseInt(v) / energy.length * duration).toFixed(1) + 's' },
    },
    yAxis: { type: 'value', name: '能量', min: 0, max: 1 },
    series: [{
      type: 'line',
      data: energy,
      smooth: true,
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(64,158,255,0.6)' },
          { offset: 1, color: 'rgba(64,158,255,0.05)' },
        ]),
      },
      lineStyle: { color: '#409eff', width: 2 },
      itemStyle: { color: '#409eff' },
      symbol: 'none',
    }],
    grid: { left: 60, right: 30, top: 40, bottom: 40 },
  })
}

function scoreColorOf(score: number) {
  if (score >= 80) return '#67c23a'
  if (score >= 60) return '#e6a23c'
  return '#f56c6c'
}

const scoreColor = computed(() => scoreColorOf(assessment.value?.score || 0))
// 恢复出来的「上次练习结果」也沿用同一套分数配色
const lastScoreColor = computed(() => scoreColorOf(lastRecord.value?.score || 0))

// 数据图表统一渲染（声调/声谱/共振峰/能量），重绘前已做 dispose 防护
function renderDataCharts() {
  initToneChart()
  initSpectrogram()
  initFormantChart()
  initEnergyChart()
}

// 3D 场景清理函数（卸载时调用）
let disposeThree: (() => void) | null = null

onMounted(async () => {
  // 内存里没有本次分析结果（刷新 / 直开本页 / 上次分析失败）→ 从后端学习记录里恢复
  if (!assessment.value) {
    void restoreLastRecord()
  }

  // 等待DOM渲染完成后再初始化图表
  await nextTick()
  setTimeout(() => {
    renderDataCharts()
    disposeThree = initThreeScene() ?? null
  }, 100)
})

onUnmounted(() => {
  disposeThree?.()
  disposeThree = null
  stopAudio()
})

// 当后端分析结果到达（可能晚于组件挂载）时重绘数据图表，避免空白
watch(
  () => assessment.value?.audioAnalysis,
  (val) => {
    if (val && (val.f0?.length || val.energy?.length || val.mfcc?.length)) {
      nextTick(() => renderDataCharts())
    }
  }
)
</script>

<template>
  <div class="feedback-view">
    <!-- 没有内存结果时的恢复流程：分析结果只保存在内存里，刷新页面 / 直接打开本页 /
         上一次分析失败都会走到这里。三种情况分别是「请求中」「该关无记录」「接口失败」，
         绝不留空白页（这是「点了分析没反馈」的真实原因）。文案统一走 P09 文案位。 -->
    <PageState
      v-if="!assessment && (restoreState === 'idle' || restoreState === 'loading')"
      state="loading"
      :copy="copy"
      class="card-block"
    />

    <PageState
      v-else-if="!assessment && restoreState === 'error'"
      state="error"
      :copy="copy"
      :detail="restoreError"
      class="card-block"
      @action="restoreLastRecord"
    />

    <!-- 有记录：渲染上次练习结果（分数 + 文字反馈，图表无法恢复） -->
    <div v-else-if="!assessment && restoreState === 'done' && lastRecord" class="card-block last-result">
      <div class="last-result-head">
        <h3>上次练习结果</h3>
        <span class="last-result-time">{{ new Date(lastRecord.createdAt).toLocaleString() }}</span>
      </div>
      <p class="last-result-note">{{ copy.subtitle }}</p>

      <div class="last-result-main">
        <div class="last-result-word">
          <span class="last-char">{{ lastRecord.character || unitId }}</span>
          <span v-if="lastRecord.pinyin" class="last-pinyin">{{ lastRecord.pinyin }}</span>
        </div>
        <div class="last-result-score">
          <span class="last-score-number" :style="{ color: lastScoreColor }">{{ Math.round(lastRecord.score) }}</span>
          <span class="last-score-label">总分</span>
        </div>
      </div>

      <div class="last-result-metrics">
        <div class="score-item"><span>准确度</span><el-progress :percentage="Math.round(lastRecord.accuracy)" color="#409eff" /></div>
        <div class="score-item"><span>流利度</span><el-progress :percentage="Math.round(lastRecord.fluency)" color="#67c23a" /></div>
        <div class="score-item"><span>发音</span><el-progress :percentage="Math.round(lastRecord.pronunciation)" color="#e6a23c" /></div>
      </div>

      <p v-if="lastRecord.feedback" class="last-result-feedback">{{ lastRecord.feedback }}</p>

      <div class="last-result-actions">
        <el-button type="primary" :loading="isPlaying" @click="playLastRecord">播放上次录音</el-button>
        <el-button @click="router.push(`/learn/${unitId}`)">回关卡重新录音</el-button>
        <el-button @click="router.push('/archive')">看我的档案</el-button>
      </div>
    </div>

    <!-- 没有任何该关记录（以及其它兜底情况）：给出回关卡重录的入口 -->
    <div v-else-if="!assessment" class="card-block no-result">
      <PageState state="empty" :copy="copy" @action="router.push(`/learn/${unitId}`)" />
      <div class="no-result-actions">
        <el-button @click="router.push('/test')">去检测中心</el-button>
        <el-button @click="router.push('/learn')">看全部 30 关</el-button>
      </div>
    </div>

    <!-- 录音质量 / 结论 / 可靠性 / 边界 -->
    <div v-if="assessment" class="result-meta card-block">
      <el-alert
        v-if="assessment && !assessment.evaluable"
        type="warning"
        :title="assessment.quality?.summary || '录音质量不达标'"
        description="当前录音无法可靠评价。请按下方提示调整环境后重录。"
        show-icon
        :closable="false"
      />
      <div v-if="assessment && !assessment.evaluable" class="unevaluable-actions">
        <el-button type="danger" @click="router.push(`/learn/${unitId}`)">返回单元重录</el-button>
        <el-button @click="router.push(`/test?unit=${unitId}`)">在检测中心重录</el-button>
      </div>
      <template v-else-if="assessment">
        <p class="headline-label">当前任务结论</p>
        <h2 class="headline">{{ assessment.headline || assessment.feedback[0]?.phenomenon || '分析完成' }}</h2>
        <el-tag :type="assessment.reliability === 'reliable' ? 'success' : assessment.reliability === 'reference_only' ? 'warning' : 'info'">
          {{ { reliable: '结果可靠', reference_only: '仅供参考', not_available: '暂不评价' }[assessment.reliability] }}
        </el-tag>
        <p class="reliability-note">{{ assessment.reliabilityNote }}</p>
      </template>

      <div v-if="assessment?.quality?.items?.length" class="quality-list">
        <h4>录音质量</h4>
        <div v-for="item in assessment.quality.items" :key="item.key" class="quality-item" :class="item.status">
          <strong>{{ item.label }}</strong> — {{ item.message }}
        </div>
      </div>

      <el-alert v-if="assessment?.boundary?.statement" type="info" :title="assessment.boundary.statement" show-icon :closable="false" class="boundary" />
    </div>

    <!-- 四步反馈（仅可评价时） -->
    <div v-if="assessment?.evaluable && assessment?.feedback?.length" class="four-step card-block">
      <h3>练习建议（四步反馈）</h3>
      <div v-for="(item, idx) in assessment.feedback" :key="idx" class="step-item" :class="item.type">
        <p><strong>① 现象</strong>{{ item.phenomenon || item.message }}</p>
        <p><strong>② 可能环节</strong>{{ item.link || item.detail }}</p>
        <p><strong>③ 可感知提示</strong>{{ item.hint }}</p>
        <p><strong>④ 安全短练习</strong>{{ item.practice || item.improvement }}</p>
      </div>
    </div>

    <!-- 综合评分（辅参考，非主结论） -->
    <div v-if="assessment?.evaluable" class="score-section">
      <div class="score-ring">
        <el-progress type="circle" :percentage="Math.round(assessment?.score || 0)" :color="scoreColor" :width="140" :stroke-width="12">
          <template #default="{ percentage }">
            <div class="score-inner">
              <span class="score-number">{{ percentage }}</span>
              <span class="score-label">综合评分</span>
            </div>
          </template>
        </el-progress>
      </div>
      <div class="score-detail">
        <div class="score-item"><span>准确度</span><el-progress :percentage="Math.round(assessment?.accuracy || 0)" :color="'#409eff'" /></div>
        <div class="score-item"><span>流利度</span><el-progress :percentage="Math.round(assessment?.fluency || 0)" :color="'#67c23a'" /></div>
        <div class="score-item"><span>发音</span><el-progress :percentage="Math.round(assessment?.pronunciation || 0)" :color="'#e6a23c'" /></div>
      </div>
    </div>

    <!-- 音素级分析（深度学习识别结果） -->
    <div class="phoneme-section" v-if="assessment?.evaluable && assessment?.audioAnalysis?.phonemes?.length">
      <h3>音素级分析 <small>基于 Wav2Vec2 深度学习模型识别</small></h3>
      <div class="phoneme-list">
        <div v-for="(p, idx) in assessment!.audioAnalysis!.phonemes" :key="idx" class="phoneme-item" :class="p.score >= 80 ? 'good' : (p.score >= 60 ? 'warn' : 'bad')">
          <div class="phoneme-name">{{ p.phoneme }}</div>
          <div class="phoneme-compare">
            <span class="expected">目标：{{ p.expected }}</span>
            <span class="arrow">→</span>
            <span class="detected">识别：{{ p.detected }}</span>
          </div>
          <div class="phoneme-score">
            <el-progress :percentage="Math.round(p.score)" :stroke-width="10" :color="p.score >= 80 ? '#67c23a' : (p.score >= 60 ? '#e6a23c' : '#f56c6c')" />
          </div>
          <p class="phoneme-feedback">{{ p.feedback }}</p>
        </div>
      </div>
      <div class="phoneme-summary" v-if="assessment?.audioAnalysis?.recognizedText">
        <span class="label">识别文本：</span>
        <span class="value">{{ assessment!.audioAnalysis!.recognizedText }}</span>
        <span class="label">识别声调：</span>
        <span class="value">第{{ assessment!.audioAnalysis!.detectedTone || '（依据F0判定）' }}声</span>
      </div>
    </div>

    <!-- 服务端未加载 ASR 模型时如实说明：原来是静默留白，容易被当成"页面没做完"（第 6 周 D 补） -->
    <el-alert
      v-if="assessment?.evaluable && assessment?.audioAnalysis
        && !assessment?.audioAnalysis?.phonemes?.length && !assessment?.audioAnalysis?.recognizedText"
      class="phoneme-unavailable"
      type="info"
      show-icon
      :closable="false"
      title="本次结果不含音素级分析（服务端未加载语音识别模型）"
      description="声调曲线、共振峰、能量与上方四步反馈都来自声学分析，结论不受影响。需要音素级对比时，请在服务端加载 ASR 模型（POST /api/asr/load）后再录一次。"
    />

    <!-- 声调曲线 + 3D动画（仅可评价时展示） -->
    <div v-if="assessment?.evaluable && assessment?.audioAnalysis" class="analysis-row">
      <div class="chart-card">
        <div ref="toneChartRef" class="chart-container"></div>
      </div>
      <div class="three-card">
        <h4>3D发音动画 <small>（剖面示意 · 拖拽旋转 · 滚轮缩放 · 悬停部位查看说明）</small></h4>
        <div ref="threeContainerRef" class="three-container"></div>
      </div>
    </div>

    <!-- 声谱图 + 共振峰 + 能量图（仅可评价时展示） -->
    <div v-if="assessment?.evaluable && assessment?.audioAnalysis" class="analysis-row three-col">
      <div class="chart-card">
        <h4>声谱图（语谱图）</h4>
        <canvas ref="spectrogramRef" class="spectrogram-canvas"></canvas>
        <p class="chart-desc">颜色越亮表示该频率在该时间点的能量越强</p>
      </div>
      <div class="chart-card">
        <div ref="formantChartRef" class="chart-container"></div>
      </div>
      <div class="chart-card">
        <div ref="energyChartRef" class="chart-container"></div>
      </div>
    </div>

    <!-- 反馈建议（兼容旧展示，四步反馈已在上方） -->
    <div v-if="false" class="feedback-section">
      <h3>改进建议</h3>
      <div class="feedback-list">
        <div v-for="(item, idx) in (assessment?.feedback || [])" :key="idx" class="feedback-item" :class="item.type">
          <el-icon v-if="item.type === 'error'" color="#f56c6c"><CircleCloseFilled /></el-icon>
          <el-icon v-else-if="item.type === 'warning'" color="#e6a23c"><WarningFilled /></el-icon>
          <el-icon v-else color="#409eff"><InfoFilled /></el-icon>
          <div>
            <strong>{{ item.message }}</strong>
            <p>{{ item.detail }}</p>
            <p class="improvement">💡 {{ item.improvement }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div v-if="assessment" class="action-bar">
      <el-button :icon="'Refresh'" size="large" @click="router.push(`/learn/${unitId}`)">再次录音</el-button>
      <el-button v-if="assessment?.evaluable" type="success" :icon="'VideoPlay'" size="large" @click="router.push(`/learn/${unitId}`)">开始练习</el-button>
      <el-button type="primary" plain size="large" @click="router.push('/archive')">保存到档案</el-button>
      <el-button :icon="'Back'" size="large" @click="router.push('/library')">返回发音库</el-button>
    </div>

    <PageFeedback :page="`feedback/${unitId}`" :unit-id="unitId" type="result" />
  </div>
</template>

<style scoped>
.feedback-view { display: flex; flex-direction: column; gap: 20px; }
.no-result-actions { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 16px; }
/* 上次练习结果（刷新 / 直开后从学习记录恢复） */
.last-result-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.last-result-head h3 { margin: 0; font-size: 16px; color: #303133; }
.last-result-time { font-size: 12px; color: #909399; }
.last-result-note { margin: 8px 0 16px; font-size: 13px; color: #909399; }
.last-result-main { display: flex; align-items: center; gap: 40px; }
.last-result-word { display: flex; align-items: baseline; gap: 10px; }
.last-char { font-size: 40px; font-weight: 700; color: #303133; }
.last-pinyin { font-size: 16px; color: #4a7a9a; }
.last-result-score { display: flex; flex-direction: column; align-items: center; }
.last-score-number { font-size: 36px; font-weight: 700; }
.last-score-label { font-size: 12px; color: #909399; }
.last-result-metrics { display: flex; flex-direction: column; gap: 12px; margin-top: 20px; }
.last-result-feedback { margin: 16px 0 0; padding: 12px 16px; background: #f5f7fa; border-radius: 8px; font-size: 13px; color: #606266; }
.last-result-actions { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 16px; }
.card-block { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06); }
.headline-label { font-size: 13px; color: #909399; margin: 0; }
.headline { margin: 8px 0 12px; font-size: 20px; color: #303133; }
.reliability-note { font-size: 13px; color: #606266; margin-top: 8px; }
.quality-list { margin-top: 16px; }
.quality-item { font-size: 13px; padding: 6px 0; }
/* 后端质量项状态是 pass / warn / fail，映射到 ok / warn / fail 后按状态上色（第 8 周 D） */
.quality-item.ok { color: #606266; }
.quality-item.warn { color: #e6a23c; }
.quality-item.fail { color: #f56c6c; }
.four-step h3 { margin: 0 0 12px; }
.step-item { padding: 12px; margin-bottom: 8px; border-radius: 8px; background: #f5f7fa; font-size: 13px; }
.step-item.error { background: #fef0f0; }
.step-item.warning { background: #fdf6ec; }
.step-item p { margin: 4px 0; }
.boundary { margin-top: 12px; }
.unevaluable-actions { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 12px; }
.score-section { background: white; border-radius: 12px; padding: 24px; display: flex; align-items: center; gap: 40px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.score-ring { flex-shrink: 0; }
.score-inner { text-align: center; }
.score-number { font-size: 36px; font-weight: 700; color: #303133; display: block; }
.score-label { font-size: 12px; color: #909399; }
.score-detail { flex: 1; display: flex; flex-direction: column; gap: 12px; }
.score-item { display: flex; align-items: center; gap: 12px; }
.score-item span { width: 60px; font-size: 14px; color: #606266; }
.analysis-row { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.phoneme-unavailable { margin-top: 4px; }
.analysis-row.three-col { grid-template-columns: 1fr 1fr 1fr; }
.spectrogram-canvas { width: 100%; height: 200px; border-radius: 8px; background: #0a0a1a; }
.chart-desc { font-size: 11px; color: #909399; text-align: center; margin-top: 6px; }
.chart-card h4 { margin: 0 0 8px; font-size: 14px; color: #303133; }
.chart-card, .three-card { background: white; border-radius: 12px; padding: 16px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.chart-container { width: 100%; height: 300px; }
.three-card { position: relative; }
.three-card h4 { margin: 0 0 8px; font-size: 14px; color: #303133; }
.three-card h4 small { font-size: 11px; color: #909399; font-weight: normal; }
.three-container { position: relative; width: 100%; height: 300px; border-radius: 8px; overflow: hidden; }
.phoneme-section { background: white; border-radius: 12px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.phoneme-section h3 { margin: 0 0 16px; font-size: 16px; color: #303133; }
.phoneme-section h3 small { font-size: 12px; color: #909399; font-weight: normal; }
.phoneme-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
.phoneme-item { border-radius: 8px; padding: 14px; border: 1px solid #e4e7ed; }
.phoneme-item.good { border-color: #b3e19d; background: #f0f9eb; }
.phoneme-item.warn { border-color: #f3d19e; background: #fdf6ec; }
.phoneme-item.bad { border-color: #fbc4c4; background: #fef0f0; }
.phoneme-name { font-weight: 700; color: #303133; margin-bottom: 8px; font-size: 14px; }
.phoneme-compare { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #606266; margin-bottom: 8px; }
.phoneme-compare .arrow { color: #c0c4cc; }
.phoneme-score { margin-bottom: 6px; }
.phoneme-feedback { margin: 0; font-size: 12px; color: #909399; }
.phoneme-summary { margin-top: 16px; padding: 12px 16px; background: #ecf5ff; border-radius: 8px; font-size: 13px; color: #303133; }
.phoneme-summary .label { color: #909399; margin-right: 4px; }
.phoneme-summary .value { font-weight: 500; margin-right: 20px; }
.feedback-section { background: white; border-radius: 12px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.feedback-section h3 { margin: 0 0 16px; font-size: 16px; color: #303133; }
.feedback-list { display: flex; flex-direction: column; gap: 12px; }
.feedback-item { display: flex; gap: 12px; align-items: flex-start; padding: 16px; border-radius: 8px; background: #f5f7fa; }
.feedback-item.error { background: #fef0f0; }
.feedback-item.warning { background: #fdf6ec; }
.feedback-item.suggestion { background: #ecf5ff; }
.feedback-item strong { color: #303133; display: block; margin-bottom: 4px; }
.feedback-item p { margin: 2px 0; color: #606266; font-size: 13px; }
.improvement { color: #409eff !important; font-weight: 500; }
.action-bar { display: flex; justify-content: center; gap: 16px; padding: 16px 0; }
</style>