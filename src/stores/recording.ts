import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { audioAnalysisApi } from '@/api'
import type { RecordingState, AudioAnalysisResult, PronunciationAssessment, FeedbackItem } from '@/types'

function mapFeedback(raw: any[]): FeedbackItem[] {
  return (raw || []).map(f => ({
    type: f.type || 'suggestion',
    category: f.category || 'tone',
    phenomenon: f.phenomenon || f.message || '',
    link: f.link || f.detail || '',
    hint: f.hint || '',
    practice: f.practice || '',
    message: f.message || f.phenomenon || '',
    detail: f.detail || f.link || '',
    improvement: f.improvement || `${f.hint || ''}${f.practice ? '；然后：' + f.practice : ''}`,
  }))
}

/**
 * 「有声 / 无声」掩码的兼容解析（第 6 周 D 修复）
 * ---------------------------------------------------------------------------
 * 背景：结果页的声调曲线要用 voiced_flag 把无声段断开（null），
 * 但后端 /api/audio/analyze 返回的字段名历史上拼成了 `voiecd_flag`（多一个 c），
 * 而且该字段一直是空数组、从未填充 —— 等于这条优化是死代码。
 * 这里按三种来源依次兜底，保证「有声断线」一定能生效：
 *   1) voiced_flag      —— 约定的正式字段名
 *   2) voiecd_flag      —— 后端现存拼写（待 A/B 改名，改名后本兜底自动失效）
 *   3) voiced_probs≥0.5 —— 由后端已填充的概率派生
 * 三者都没有时返回 []，结果页会回落到「f0 > 0 判定」，不会报错。
 */
function resolveVoicedFlag(raw: any): boolean[] {
  const direct = raw?.voiced_flag
  if (Array.isArray(direct) && direct.length) return direct as boolean[]
  const legacy = raw?.voiecd_flag
  if (Array.isArray(legacy) && legacy.length) return legacy as boolean[]
  const probs = raw?.voiced_probs
  if (Array.isArray(probs) && probs.length) return probs.map((p: number) => Number(p) >= 0.5)
  return []
}

function mapAssessment(data: any): PronunciationAssessment {
  const audioRaw = data.audio_analysis
  const audioAnalysis: AudioAnalysisResult | null = audioRaw
    ? {
        f0: audioRaw.f0 || [],
        f1: audioRaw.f1 || [],
        f2: audioRaw.f2 || [],
        energy: audioRaw.energy || [],
        duration: audioRaw.duration || 0,
        sampleRate: audioRaw.sample_rate || 0,
        mfcc: audioRaw.mfcc || [],
        // 有声掩码与概率：以前这里漏传，导致结果页拿不到 voiced_flag（第 6 周补）
        voiced_flag: resolveVoicedFlag(audioRaw),
        voiced_probs: audioRaw.voiced_probs || [],
        recognizedText: audioRaw.recognized_text || '',
        detectedTone: audioRaw.detected_tone || 0,
        toneScore: audioRaw.tone_score || 0,
        phonemeScore: audioRaw.phoneme_score || 0,
        phonemes: (audioRaw.phonemes || []).map((p: any) => ({
          phoneme: p.phoneme,
          expected: p.expected,
          detected: p.detected,
          score: p.score,
          feedback: p.feedback,
        })),
        standardF0: audioRaw.standard_f0 || [],
      }
    : null

  const feedback = mapFeedback(data.feedback)
  const headline = feedback[0]?.phenomenon || data.message || ''

  return {
    score: data.score ?? 0,
    accuracy: data.accuracy ?? 0,
    fluency: data.fluency ?? 0,
    pronunciation: data.pronunciation ?? 0,
    feedback,
    audioAnalysis,
    evaluable: data.evaluable !== false && (data.quality?.passed !== false),
    quality: data.quality || { passed: true, summary: '', items: [] },
    reliability: data.reliability || 'not_available',
    reliabilityNote: data.reliability_note || '',
    boundary: data.boundary || {
      statement: '检测结果仅用于发音学习参考，不作为普通话水平等级认定或医学诊断依据。',
    },
    headline,
  }
}

export const useRecordingStore = defineStore('recording', () => {
  const recordingState = ref<RecordingState>({
    isRecording: false,
    isPaused: false,
    duration: 0,
    audioBlob: null,
    audioUrl: null,
  })

  const analysisResult = ref<AudioAnalysisResult | null>(null)
  const assessment = ref<PronunciationAssessment | null>(null)
  const isAnalyzing = ref(false)
  const error = ref<string | null>(null)

  let mediaRecorder: MediaRecorder | null = null
  let audioChunks: Blob[] = []
  let timerInterval: number | null = null
  let audioContext: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  let microphone: MediaStreamAudioSourceNode | null = null

  const isRecording = computed(() => recordingState.value.isRecording)
  const isPaused = computed(() => recordingState.value.isPaused)
  const duration = computed(() => recordingState.value.duration)
  const audioUrl = computed(() => recordingState.value.audioUrl)
  const hasRecording = computed(() => recordingState.value.audioBlob !== null)

  const formattedDuration = computed(() => {
    const minutes = Math.floor(recordingState.value.duration / 60)
    const seconds = recordingState.value.duration % 60
    return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
  })

  async function startRecording() {
    try {
      error.value = null
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' })
      audioChunks = []
      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunks.push(event.data)
      }
      mediaRecorder.onstop = () => {
        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' })
        recordingState.value.audioBlob = audioBlob
        recordingState.value.audioUrl = URL.createObjectURL(audioBlob)
        stream.getTracks().forEach(track => track.stop())
      }
      audioContext = new AudioContext()
      analyser = audioContext.createAnalyser()
      analyser.fftSize = 2048
      microphone = audioContext.createMediaStreamSource(stream)
      microphone.connect(analyser)
      mediaRecorder.start(100)
      recordingState.value.isRecording = true
      recordingState.value.isPaused = false
      recordingState.value.duration = 0
      timerInterval = window.setInterval(() => { recordingState.value.duration++ }, 1000)
    } catch (err) {
      error.value = '无法访问麦克风。请在浏览器设置中允许麦克风权限后重试。'
      console.error(err)
    }
  }

  /**
   * 停止录音。
   * 返回 Promise：resolve 时录音 Blob 已经写进 store。
   * 原因：MediaRecorder.stop() 之后 onstop 是异步触发的，如果"刚点停止就点分析"，
   * analyzeRecording 会读到空的 audioBlob 而报「没有录音可分析」——这是录音→分析之间
   * 的一个竞态，必须等 onstop 完成再分析。
   */
  function stopRecording(): Promise<void> {
    if (timerInterval) { clearInterval(timerInterval); timerInterval = null }
    if (audioContext) { audioContext.close(); audioContext = null }
    recordingState.value.isRecording = false
    recordingState.value.isPaused = false
    return new Promise<void>((resolve) => {
      const recorder = mediaRecorder
      if (!recorder || recorder.state === 'inactive') {
        resolve()
        return
      }
      // onstop（在 startRecording 里绑定，负责写入 Blob）先执行；await 的后续代码
      // 会在整个事件派发结束后才跑，因此拿到的一定是本次录音的 Blob。
      recorder.addEventListener('stop', () => resolve(), { once: true })
      recorder.stop()
    })
  }

  function clearRecording() {
    if (recordingState.value.audioUrl) URL.revokeObjectURL(recordingState.value.audioUrl)
    recordingState.value = { isRecording: false, isPaused: false, duration: 0, audioBlob: null, audioUrl: null }
    analysisResult.value = null
    assessment.value = null
    error.value = null
  }

  async function analyzeRecording(unitId: string) {
    if (!recordingState.value.audioBlob) {
      error.value = '没有录音可分析'
      return
    }
    isAnalyzing.value = true
    error.value = null
    analysisResult.value = null
    assessment.value = null
    try {
      // 走统一的网络层（src/api/index.ts 的 audioAnalysisApi），不再硬编码后端地址。
      // analyzeRaw 会保留后端 400 时的中文说明，不会压成「服务器错误: 400」。
      const result = await audioAnalysisApi.analyzeRaw(recordingState.value.audioBlob, unitId)
      if (result.code === 200 && result.data) {
        const mapped = mapAssessment(result.data)
        assessment.value = mapped
        analysisResult.value = mapped.audioAnalysis
      } else {
        throw new Error(result.message || '分析失败')
      }
    } catch (err: any) {
      error.value = `分析失败：${err.message || '后端服务不可用'}`
      analysisResult.value = null
      assessment.value = null
    } finally {
      isAnalyzing.value = false
    }
  }

  function getAnalyser() { return analyser }
  function clearError() { error.value = null }

  return {
    recordingState, analysisResult, assessment, isAnalyzing, error,
    isRecording, isPaused, duration, audioUrl, hasRecording, formattedDuration,
    startRecording, stopRecording, clearRecording, analyzeRecording, getAnalyser, clearError,
  }
})
