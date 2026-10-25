import type {
  PronunciationUnit,
  LearningRecord,
  UserProgress,
  PronunciationAssessment,
  AdminStats,
  ApiResponse,
  PaginatedResponse,
  SearchParams,
  MediaAsset,
  CmsUnit,
  UserFeedbackItem,
} from '@/types'

// API基础配置
const API_BASE_URL = 'http://localhost:8000/api'

/**
 * 管理员登录态（C 第 7 周给 /api/admin/* 加了 X-Token 鉴权）
 * ---------------------------------------------------------------------------
 * 前端只存 token（localStorage），所有请求在 request() 里自动带上 X-Token。
 * 401 由页面兜底：清 token、回到登录卡片，不把"未登录"伪装成"接口异常"。
 */
const ADMIN_TOKEN_KEY = 'voice_admin_token'
let adminToken = ''

try {
  adminToken = localStorage.getItem(ADMIN_TOKEN_KEY) ?? ''
} catch {
  adminToken = ''
}

export function getAdminToken(): string {
  return adminToken
}

export function setAdminToken(token: string | null): void {
  adminToken = token ?? ''
  try {
    if (adminToken) localStorage.setItem(ADMIN_TOKEN_KEY, adminToken)
    else localStorage.removeItem(ADMIN_TOKEN_KEY)
  } catch {
    /* 隐私模式下写不了 localStorage，内存里的 token 仍可用 */
  }
}

// 通用请求函数
async function request<T>(
  url: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const isFormData = options.body instanceof FormData
  const response = await fetch(`${API_BASE_URL}${url}`, {
    headers: {
      // FormData 时不设置 Content-Type，让浏览器自动带上 boundary
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      // 后台接口鉴权：没登录时为空，后端会回 401
      ...(adminToken ? { 'X-Token': adminToken } : {}),
      ...options.headers,
    },
    ...options,
  })

  if (!response.ok) {
    if (response.status === 401) {
      // token 失效：清掉本地登录态，让后台页回到登录卡片
      setAdminToken(null)
    }
    throw new Error(`HTTP error! status: ${response.status}`)
  }

  return response.json()
}

// 发音单元API
export const pronunciationUnitApi = {
  // 获取所有发音单元
  getAll(params?: SearchParams): Promise<ApiResponse<PaginatedResponse<PronunciationUnit>>> {
    const queryString = params ? '?' + new URLSearchParams(params as any).toString() : ''
    return request(`/pronunciation-units${queryString}`)
  },

  // 获取单个发音单元
  getById(id: string): Promise<ApiResponse<PronunciationUnit>> {
    return request(`/pronunciation-units/${id}`)
  },

  // 创建发音单元
  create(unit: Omit<PronunciationUnit, 'id' | 'createdAt' | 'updatedAt'>): Promise<ApiResponse<PronunciationUnit>> {
    return request('/pronunciation-units', {
      method: 'POST',
      body: JSON.stringify(unit),
    })
  },

  // 更新发音单元
  update(id: string, unit: Partial<PronunciationUnit>): Promise<ApiResponse<PronunciationUnit>> {
    return request(`/pronunciation-units/${id}`, {
      method: 'PUT',
      body: JSON.stringify(unit),
    })
  },

  // 删除发音单元
  delete(id: string): Promise<ApiResponse<void>> {
    return request(`/pronunciation-units/${id}`, {
      method: 'DELETE',
    })
  },
}

// 创建学习记录的入参（录音 Blob + 评估结果，multipart 上传）
export interface CreateLearningRecordPayload {
  userId: string
  unitId: string
  pinyin: string
  character: string
  score: number
  accuracy: number
  fluency: number
  pronunciation: number
  duration: number
  feedback?: string
  audio: Blob
}

// 学习记录API
export const learningRecordApi = {
  // 获取用户学习记录（不含音频，音频按 audioUrl 单独拉取）
  getByUser(userId: string, limit = 20): Promise<ApiResponse<LearningRecord[]>> {
    return request(`/users/${userId}/learning-records?limit=${limit}`)
  },

  // 创建学习记录：录音二进制(multipart) + 评估结果一并落库，后端同事务更新进度
  create(payload: CreateLearningRecordPayload): Promise<ApiResponse<{ id: string }>> {
    const formData = new FormData()
    formData.append('userId', payload.userId)
    formData.append('unitId', payload.unitId)
    formData.append('pinyin', payload.pinyin)
    formData.append('character', payload.character)
    formData.append('score', String(payload.score))
    formData.append('accuracy', String(payload.accuracy))
    formData.append('fluency', String(payload.fluency))
    formData.append('pronunciation', String(payload.pronunciation))
    formData.append('duration', String(payload.duration))
    formData.append('feedback', payload.feedback ?? '')
    formData.append('audio', payload.audio, 'recording.webm')

    return request('/learning-records', {
      method: 'POST',
      body: formData,
    })
  },

  // 获取学习记录详情
  getById(id: string): Promise<ApiResponse<LearningRecord>> {
    return request(`/learning-records/${id}`)
  },

  // 按需拉取录音二进制，返回可播放的 blob URL
  async getRecordAudio(id: string): Promise<string> {
    const response = await fetch(`${API_BASE_URL}/learning-records/${id}/audio`)
    if (!response.ok) {
      throw new Error(`录音加载失败: HTTP ${response.status}`)
    }
    const blob = await response.blob()
    return URL.createObjectURL(blob)
  },

  delete(id: string): Promise<ApiResponse<void>> {
    return request(`/learning-records/${id}`, { method: 'DELETE' })
  },

  deleteAll(userId: string): Promise<ApiResponse<{ deleted: number }>> {
    return request(`/users/${userId}/learning-records`, { method: 'DELETE' })
  },
}

// 用户进度API
export const userProgressApi = {
  // 获取用户进度
  getByUser(userId: string): Promise<ApiResponse<UserProgress>> {
    return request(`/users/${userId}/progress`)
  },

  // 更新用户进度
  update(userId: string, progress: Partial<UserProgress>): Promise<ApiResponse<UserProgress>> {
    return request(`/users/${userId}/progress`, {
      method: 'POST',
      body: JSON.stringify(progress),
    })
  },
}

// 后台管理API
export const adminApi = {
  getAllLearningRecords(limit = 100): Promise<ApiResponse<LearningRecord[]>> {
    return request(`/admin/learning-records?limit=${limit}`)
  },

  getStats(): Promise<ApiResponse<AdminStats>> {
    return request('/admin/stats')
  },

  getFeedbacks(status = ''): Promise<ApiResponse<UserFeedbackItem[]>> {
    const q = status ? `?status=${encodeURIComponent(status)}` : ''
    return request(`/admin/feedback${q}`)
  },

  updateFeedback(id: string, status: string, handleNote: string): Promise<ApiResponse<void>> {
    return request(`/admin/feedback/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ status, handleNote }),
    })
  },
}

// 管理员登录（C 第 7 周：/api/admin/login 返回 token，后续接口带 X-Token）
export const adminAuthApi = {
  login(username: string, password: string): Promise<ApiResponse<{ token: string; username: string; displayName: string }>> {
    return request('/admin/login', { method: 'POST', body: JSON.stringify({ username, password }) })
  },

  logout(): Promise<ApiResponse<void>> {
    return request('/admin/logout', { method: 'POST' })
  },

  /** 登录态自检：拿一个需要鉴权的接口探一下，401 会被 request() 清 token */
  check(): Promise<ApiResponse<CmsUnit[]>> {
    return request('/admin/units')
  },
}

// CMS 审核流转（C 第 7/8 周：四状态机 + 版本快照 + 操作日志）
export const cmsApi = {
  /** 管理员视角的单元列表（全状态可见，可按 draft/pending_review/rejected/published 过滤） */
  units(status = ''): Promise<ApiResponse<CmsUnit[]>> {
    const q = status ? `?status=${encodeURIComponent(status)}` : ''
    return request(`/admin/units${q}`)
  },

  getUnit(id: string): Promise<ApiResponse<CmsUnit>> {
    return request(`/admin/units/${encodeURIComponent(id)}`)
  },

  /** 版本历史快照 */
  versions(id: string): Promise<ApiResponse<any[]>> {
    return request(`/admin/units/${encodeURIComponent(id)}/versions`)
  },

  submitReview(id: string): Promise<ApiResponse<CmsUnit>> {
    return request(`/admin/units/${encodeURIComponent(id)}/submit-review`, { method: 'POST' })
  },

  approve(id: string): Promise<ApiResponse<CmsUnit>> {
    return request(`/admin/units/${encodeURIComponent(id)}/approve`, { method: 'POST' })
  },

  reject(id: string, comment: string): Promise<ApiResponse<CmsUnit>> {
    return request(`/admin/units/${encodeURIComponent(id)}/reject`, {
      method: 'POST',
      body: JSON.stringify({ review_comment: comment }),
    })
  },

  unpublish(id: string): Promise<ApiResponse<CmsUnit>> {
    return request(`/admin/units/${encodeURIComponent(id)}/unpublish`, { method: 'POST' })
  },

  /** 检测开关：verified=true 表示该关可开放检测（不能稳定评分的关只学不测） */
  setDetection(id: string, verified: boolean): Promise<ApiResponse<CmsUnit>> {
    return request(`/admin/units/${encodeURIComponent(id)}/set-detection`, {
      method: 'POST',
      body: JSON.stringify({ verified }),
    })
  },

  auditLogs(resourceId = '', limit = 100): Promise<ApiResponse<any[]>> {
    const params = new URLSearchParams()
    if (resourceId) params.set('resource_id', resourceId)
    params.set('limit', String(limit))
    return request(`/admin/audit-logs?${params.toString()}`)
  },
}

// CMS 发音单元
export const unitsApi = {
  list(status = ''): Promise<ApiResponse<CmsUnit[]>> {
    const q = status ? `?status=${encodeURIComponent(status)}` : ''
    return request(`/units${q}`)
  },

  getById(id: string): Promise<ApiResponse<CmsUnit>> {
    return request(`/units/${id}`)
  },

  create(data: Partial<CmsUnit>): Promise<ApiResponse<{ id: string }>> {
    return request('/units', { method: 'POST', body: JSON.stringify(data) })
  },

  update(id: string, data: Partial<CmsUnit>): Promise<ApiResponse<void>> {
    return request(`/units/${id}`, { method: 'PUT', body: JSON.stringify(data) })
  },

  delete(id: string): Promise<ApiResponse<void>> {
    return request(`/units/${id}`, { method: 'DELETE' })
  },
}

// 关卡 API（30 关 L01–L30 · 第 4 周 D 交付：接 C 的 /api/units）
//
// 说明：本项目前端已统一走上面的 request() 封装层（基于 fetch，承担 axios 的封装职责：
// 统一 baseURL / 请求头 / 错误抛出），因此这里复用同一层，不额外引入 axios 依赖，
// 避免 1.0 期出现两套网络层。
export const levelsApi = {
  /**
   * 关卡列表。
   * @param status '' = 全部（后台 CMS 用）；'published' = 仅已发布（大众端关卡页用，
   *   未审核内容不公开）
   */
  list(status = ''): Promise<ApiResponse<CmsUnit[]>> {
    return unitsApi.list(status)
  },

  /** 单关详情 */
  getById(levelId: string): Promise<ApiResponse<CmsUnit>> {
    return unitsApi.getById(levelId)
  },
}

// 用户反馈
export const feedbackApi = {
  submit(payload: {
    userId: string
    type: string
    page: string
    unitId?: string
    rating?: string
    message?: string
  }): Promise<ApiResponse<{ id: string }>> {
    return request('/feedback', { method: 'POST', body: JSON.stringify(payload) })
  },
}

// 收藏
export const favoritesApi = {
  list(userId: string): Promise<ApiResponse<string[]>> {
    return request(`/users/${userId}/favorites`)
  },

  add(userId: string, unitId: string): Promise<ApiResponse<void>> {
    return request(`/users/${userId}/favorites/${unitId}`, { method: 'POST' })
  },

  remove(userId: string, unitId: string): Promise<ApiResponse<void>> {
    return request(`/users/${userId}/favorites/${unitId}`, { method: 'DELETE' })
  },
}

// 音频分析API
//
// 说明（第 5 周 D 修复）：
//   1) 后端 Form 参数名是 unit_id，不是 unitId —— 原来这里传错会让后端直接 422；
//   2) 录音分析**不**走 request() 的「非 2xx 就抛错」策略：单元还没开放检测时，后端返回
//      400 + 一句中文说明（例如「『xx』的检测任务尚未通过验证…」），那句话要原样给用户看，
//      不能被压成「服务器错误: 400」。所以单独提供 analyzeRaw。
export interface AudioAnalyzeResponse {
  code: number
  message?: string
  /** 录音质量不达标时后端返回 evaluable:false 的精简结构，故此处不写死类型 */
  data?: PronunciationAssessment | Record<string, unknown> | null
}

export const audioAnalysisApi = {
  /**
   * 上传录音做发音分析，返回后端原始 JSON（不按状态码抛错，保留后端的中文说明）。
   * recording store 走这个方法，避免再硬编码 http://localhost:8000。
   */
  async analyzeRaw(audio: Blob, unitId: string): Promise<AudioAnalyzeResponse> {
    const formData = new FormData()
    formData.append('audio', audio, 'recording.webm')
    formData.append('unit_id', unitId)

    const response = await fetch(`${API_BASE_URL}/audio/analyze`, {
      method: 'POST',
      body: formData,
    })

    let payload: AudioAnalyzeResponse | null = null
    try {
      payload = (await response.json()) as AudioAnalyzeResponse
    } catch {
      payload = null
    }
    if (!payload) {
      throw new Error(`服务器没有返回可解析的结果（HTTP ${response.status}）`)
    }
    return payload
  },

  // 上传音频进行分析（统一走 request()，2xx 之外的响应会抛错）
  analyze(audioFile: File, unitId: string): Promise<ApiResponse<PronunciationAssessment>> {
    const formData = new FormData()
    formData.append('audio', audioFile)
    formData.append('unit_id', unitId)

    return request('/audio/analyze', {
      method: 'POST',
      body: formData,
      headers: {}, // 让浏览器自动设置Content-Type
    })
  },

  // 实时分析音频流
  analyzeStream(audioData: ArrayBuffer, unitId: string): Promise<ApiResponse<PronunciationAssessment>> {
    return request('/audio/analyze-stream', {
      method: 'POST',
      body: JSON.stringify({
        audioData: Array.from(new Uint8Array(audioData)),
        unitId,
      }),
    })
  },
}

// 媒体资源API
export const mediaApi = {
  // 上传媒体资源
  upload(file: File, type: string): Promise<ApiResponse<MediaAsset>> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('file_type', type)

    return request('/media/upload', {
      method: 'POST',
      body: formData,
      headers: {},
    })
  },

  // 获取媒体资源
  getById(id: string): Promise<ApiResponse<MediaAsset>> {
    return request(`/media/${id}`)
  },

  // 删除媒体资源
  delete(id: string): Promise<ApiResponse<void>> {
    return request(`/media/${id}`, {
      method: 'DELETE',
    })
  },
}

// WebSocket连接管理
export class WebSocketManager {
  private ws: WebSocket | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 1000
  private listeners: Map<string, Set<(data: any) => void>> = new Map()

  constructor(private url: string) {}

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(this.url)

        this.ws.onopen = () => {
          console.log('WebSocket connected')
          this.reconnectAttempts = 0
          resolve()
        }

        this.ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data)
            this.emit(data.type, data.data)
          } catch (error) {
            console.error('Failed to parse WebSocket message:', error)
          }
        }

        this.ws.onclose = () => {
          console.log('WebSocket disconnected')
          this.attemptReconnect()
        }

        this.ws.onerror = (error) => {
          console.error('WebSocket error:', error)
          reject(error)
        }
      } catch (error) {
        reject(error)
      }
    })
  }

  private attemptReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++
      console.log(`Attempting to reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`)
      
      setTimeout(() => {
        this.connect().catch(() => {})
      }, this.reconnectDelay * this.reconnectAttempts)
    }
  }

  send(data: any) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  on(event: string, callback: (data: any) => void) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set())
    }
    this.listeners.get(event)!.add(callback)
  }

  off(event: string, callback: (data: any) => void) {
    this.listeners.get(event)?.delete(callback)
  }

  private emit(event: string, data: any) {
    this.listeners.get(event)?.forEach((callback) => callback(data))
  }

  disconnect() {
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }
}

// 导出WebSocket管理器实例
export const wsManager = new WebSocketManager('ws://localhost:8000/ws/audio-stream')