<script setup lang="ts">
/**
 * 后台管理（CMS）
 * ---------------------------------------------------------------------------
 * 第 8 周收口：合并 C 的第 7 周 CMS 后，`/api/admin/*` 全部要 `X-Token`，
 * 且发布必须走审核流转（不能像以前那样直接把 status 改成 published）。本页相应改成：
 *   1) 先登录（POST /api/admin/login → token 存 localStorage，request() 自动带 X-Token）；
 *   2) 状态只读，发布/驳回/下架/提交审核走四状态机按钮；
 *   3) 检测开关走 set-detection（verified 是"能不能检测"的开关，不是"审没审核"）；
 *   4) 版本号、创建人、审核人/时间、驳回意见都显示出来，方便追溯。
 * 边界：C 的规则「创建人不能审核自己的内容」——同一个管理员建的单元要换另一位管理员审核，
 * 页面会把这个错误原样提示出来，不吞掉。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  adminAuthApi,
  adminApi,
  cmsApi,
  getAdminToken,
  mediaApi,
  setAdminToken,
  unitsApi,
} from '@/api'
import type { CmsUnit, LearningRecord, UserFeedbackItem } from '@/types'

const STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  pending_review: '待审核',
  rejected: '已驳回',
  published: '已发布',
}

const STATUS_TAG: Record<string, 'info' | 'warning' | 'danger' | 'success'> = {
  draft: 'info',
  pending_review: 'warning',
  rejected: 'danger',
  published: 'success',
}

const activeTab = ref('content')
const units = ref<CmsUnit[]>([])
const feedbacks = ref<UserFeedbackItem[]>([])
const allRecords = ref<LearningRecord[]>([])
const stats = ref<any>(null)
const logs = ref<any[]>([])
const loading = ref(false)
const statusFilter = ref('')
const actionLoadingId = ref('')

// ---- 登录态 ----
const loggedIn = ref(!!getAdminToken())
const loginLoading = ref(false)
const loginForm = ref({ username: 'admin', password: '' })

async function doLogin() {
  if (!loginForm.value.username || !loginForm.value.password) {
    ElMessage.warning('请输入管理员账号和密码')
    return
  }
  loginLoading.value = true
  try {
    const res = await adminAuthApi.login(loginForm.value.username, loginForm.value.password)
    setAdminToken(res.data.token)
    loggedIn.value = true
    loginForm.value.password = ''
    ElMessage.success(`已登录：${res.data.displayName || res.data.username}`)
    await reloadUnits()
  } catch (e: any) {
    ElMessage.error(/401/.test(e?.message || '') ? '账号或密码不对' : `登录失败：${e?.message || e}`)
  } finally {
    loginLoading.value = false
  }
}

async function doLogout() {
  try {
    await adminAuthApi.logout()
  } catch {
    /* 后端还没起来/网络断了也照样退出本地登录态 */
  }
  setAdminToken(null)
  loggedIn.value = false
  units.value = []
  ElMessage.success('已退出登录')
}

// ---- 内容 ----
const visibleUnits = computed(() =>
  statusFilter.value ? units.value.filter(u => u.status === statusFilter.value) : units.value,
)
const pendingUnits = computed(() => units.value.filter(u => u.status === 'pending_review'))

async function reloadUnits() {
  loading.value = true
  try {
    // 管理员接口能看全状态；没登录时退回大众接口（只读，调试用）
    const res = loggedIn.value ? await cmsApi.units() : await unitsApi.list()
    units.value = res.data
  } catch (e: any) {
    if (/401/.test(e?.message || '')) {
      setAdminToken(null)
      loggedIn.value = false
      ElMessage.warning('登录已过期，请重新登录')
    } else {
      ElMessage.error(`单元列表加载失败：${e?.message || e}`)
    }
  } finally {
    loading.value = false
  }
}

async function runAction(unit: CmsUnit, action: 'submit' | 'approve' | 'reject' | 'unpublish') {
  actionLoadingId.value = unit.id
  try {
    if (action === 'submit') await cmsApi.submitReview(unit.id)
    if (action === 'approve') await cmsApi.approve(unit.id)
    if (action === 'unpublish') await cmsApi.unpublish(unit.id)
    if (action === 'reject') {
      const { value } = await ElMessageBox.prompt('请写驳回原因（会显示给内容负责人）', '驳回', {
        confirmButtonText: '确认驳回',
        cancelButtonText: '取消',
        inputPlaceholder: '例如：示范音还没换，先别发布',
      })
      if (!value?.trim()) {
        ElMessage.warning('驳回必须写原因')
        return
      }
      await cmsApi.reject(unit.id, value.trim())
    }
    await reloadUnits()
    ElMessage.success('操作成功')
  } catch (e: any) {
    // CmsStateError 的中文原因（例如「创建人不能审核自己的内容」）原样显示
    ElMessage.error(e?.message || '操作失败')
  } finally {
    actionLoadingId.value = ''
  }
}

async function toggleDetection(unit: CmsUnit) {
  actionLoadingId.value = unit.id
  try {
    await cmsApi.setDetection(unit.id, !unit.verified)
    await reloadUnits()
    ElMessage.success(unit.verified ? '已关闭检测（只学不测）' : '已开启检测（可练可测）')
  } catch (e: any) {
    ElMessage.error(e?.message || '检测开关切换失败')
  } finally {
    actionLoadingId.value = ''
  }
}

// ---- 编辑 ----
const dialogVisible = ref(false)
const editingUnit = ref<Partial<CmsUnit> | null>(null)

function openCreate() {
  editingUnit.value = { status: 'draft', verified: false, category: '声母', order: units.value.length + 1 }
  dialogVisible.value = true
}

function editUnit(u: CmsUnit) {
  editingUnit.value = { ...u }
  dialogVisible.value = true
}

async function saveUnit() {
  if (!editingUnit.value) return
  try {
    if (editingUnit.value.id) {
      await unitsApi.update(editingUnit.value.id, editingUnit.value)
    } else {
      await unitsApi.create(editingUnit.value)
    }
    dialogVisible.value = false
    await reloadUnits()
    ElMessage.success('已保存（新建单元是草稿，需提交审核后发布）')
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  }
}

async function removeUnit(id: string) {
  try {
    await unitsApi.delete(id)
    await reloadUnits()
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e?.message || '删除失败')
  }
}

function preview(id: string) {
  window.open(`/learn/${id}`, '_blank')
}

async function onMediaUpload(file: File) {
  try {
    await mediaApi.upload(file, 'audio')
    ElMessage.success('上传成功')
  } catch {
    ElMessage.error('上传失败')
  }
  return false
}

// ---- 反馈 / 统计 / 日志 ----
async function loadFeedbacks() {
  try {
    const res = await adminApi.getFeedbacks()
    feedbacks.value = res.data
  } catch (e: any) {
    ElMessage.error(`反馈加载失败：${e?.message || e}`)
  }
}

async function loadStats() {
  loading.value = true
  try {
    const [s, r] = await Promise.all([adminApi.getStats(), adminApi.getAllLearningRecords(100)])
    stats.value = s.data
    allRecords.value = r.data
  } catch (e: any) {
    ElMessage.error(`统计加载失败：${e?.message || e}`)
  } finally {
    loading.value = false
  }
}

async function loadLogs() {
  try {
    const res = await cmsApi.auditLogs('', 200)
    logs.value = res.data
  } catch (e: any) {
    ElMessage.error(`操作日志加载失败：${e?.message || e}`)
  }
}

async function handleFeedback(id: string, status: 'adopted' | 'rejected') {
  try {
    await adminApi.updateFeedback(id, status, status === 'adopted' ? '已采纳' : '暂不采纳')
    await loadFeedbacks()
    ElMessage.success('已处理')
  } catch (e: any) {
    ElMessage.error(e?.message || '处理失败')
  }
}

watch(activeTab, (tab) => {
  if (!loggedIn.value) return
  if (tab === 'stats') loadStats()
  if (tab === 'feedback') loadFeedbacks()
  if (tab === 'logs') loadLogs()
})

// 带着旧 token 进来先自检一次，失败就回登录卡片
if (loggedIn.value) reloadUnits()
</script>

<template>
  <div class="admin-view">
    <!-- 未登录：先登录（C 第 7 周起 /api/admin/* 要 X-Token） -->
    <el-card v-if="!loggedIn" class="login-card">
      <h3>后台管理登录</h3>
      <p class="hint">
        第 7 周起后台接口需要管理员登录。初次启动后端会自动创建管理员 <code>admin / admin123</code>，
        上线前请用「改密码」接口换掉。
      </p>
      <el-form label-width="70px" @submit.prevent="doLogin">
        <el-form-item label="账号">
          <el-input v-model="loginForm.username" placeholder="admin" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="loginForm.password"
            type="password"
            show-password
            placeholder="初始密码 admin123"
            autocomplete="current-password"
            @keyup.enter="doLogin"
          />
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="loginLoading" @click="doLogin">登录</el-button>
    </el-card>

    <template v-else>
      <div class="admin-bar">
        <el-tag type="success" effect="plain">已登录管理员</el-tag>
        <el-button size="small" @click="reloadUnits">刷新</el-button>
        <el-button size="small" @click="doLogout">退出登录</el-button>
      </div>

      <el-tabs v-model="activeTab">
        <el-tab-pane label="内容管理" name="content">
          <el-card>
            <template #header>
              <div class="card-head">
                <span>发音单元（CMS）· 共 {{ units.length }} 条</span>
                <div class="head-actions">
                  <el-select v-model="statusFilter" size="small" placeholder="全部状态" clearable style="width: 130px">
                    <el-option v-for="(label, key) in STATUS_LABEL" :key="key" :label="label" :value="key" />
                  </el-select>
                  <el-button type="primary" size="small" @click="openCreate">添加单元</el-button>
                </div>
              </div>
            </template>
            <el-table :data="visibleUnits" stripe max-height="560">
              <el-table-column prop="order" label="#" width="50" />
              <el-table-column prop="id" label="ID" width="90" />
              <el-table-column prop="pinyin" label="拼音" width="110" />
              <el-table-column prop="character" label="汉字" width="80" />
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="STATUS_TAG[row.status] || 'info'" size="small">{{ STATUS_LABEL[row.status] || row.status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="检测" width="80">
                <template #default="{ row }">
                  <el-tag :type="row.verified ? 'success' : 'info'" size="small" effect="plain">
                    {{ row.verified ? '可测' : '只学' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="version" label="版本" width="70" />
              <el-table-column label="操作" width="360">
                <template #default="{ row }">
                  <el-button v-if="row.status === 'draft' || row.status === 'rejected'" size="small" :loading="actionLoadingId === row.id" @click="runAction(row, 'submit')">提交审核</el-button>
                  <el-button v-if="row.status === 'pending_review'" size="small" type="success" :loading="actionLoadingId === row.id" @click="runAction(row, 'approve')">通过并发布</el-button>
                  <el-button v-if="row.status === 'pending_review'" size="small" type="danger" plain @click="runAction(row, 'reject')">驳回</el-button>
                  <el-button v-if="row.status === 'published'" size="small" type="warning" plain @click="runAction(row, 'unpublish')">下架</el-button>
                  <el-button v-if="row.status === 'published'" size="small" :loading="actionLoadingId === row.id" @click="toggleDetection(row)">
                    {{ row.verified ? '关检测' : '开检测' }}
                  </el-button>
                  <el-button v-if="row.status === 'draft' || row.status === 'rejected'" size="small" @click="editUnit(row)">编辑</el-button>
                  <el-button size="small" @click="preview(row.id)">预览</el-button>
                  <el-button v-if="row.status === 'draft' || row.status === 'rejected'" size="small" type="danger" plain @click="removeUnit(row.id)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-tab-pane>

        <el-tab-pane label="待审核" name="review">
          <el-card>
            <template #header><span>待审核队列（{{ pendingUnits.length }} 条）</span></template>
            <p class="hint">审核通过即发布到大众端；驳回必须写原因。创建人不能审核自己的内容。</p>
            <el-table :data="pendingUnits" stripe>
              <el-table-column prop="id" label="ID" width="90" />
              <el-table-column prop="pinyin" label="拼音" width="110" />
              <el-table-column prop="character" label="汉字" width="80" />
              <el-table-column prop="creator" label="创建人" width="100" />
              <el-table-column label="提交时间" width="180">
                <template #default="{ row }">{{ row.submitReviewTime || '-' }}</template>
              </el-table-column>
              <el-table-column label="操作" width="220">
                <template #default="{ row }">
                  <el-button size="small" type="success" :loading="actionLoadingId === row.id" @click="runAction(row, 'approve')">通过并发布</el-button>
                  <el-button size="small" type="danger" plain @click="runAction(row, 'reject')">驳回</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-tab-pane>

        <el-tab-pane label="媒体管理" name="media">
          <el-upload drag :auto-upload="true" :before-upload="onMediaUpload" accept="audio/*,image/*">
            <el-icon :size="48"><UploadFilled /></el-icon>
            <div>上传音频/图片（写入 uploads/）</div>
          </el-upload>
        </el-tab-pane>

        <el-tab-pane label="用户反馈" name="feedback">
          <el-table :data="feedbacks" stripe>
            <el-table-column prop="createdAt" label="时间" width="180" />
            <el-table-column prop="page" label="页面" width="120" />
            <el-table-column prop="rating" label="评价" width="80" />
            <el-table-column prop="message" label="内容" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="90" />
            <el-table-column label="处理" width="180">
              <template #default="{ row }">
                <el-button size="small" @click="handleFeedback(row.id, 'adopted')">采纳</el-button>
                <el-button size="small" @click="handleFeedback(row.id, 'rejected')">暂不采纳</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="数据统计" name="stats">
          <div v-loading="loading" class="stats-grid">
            <el-card v-for="item in [
              { label: '总用户', value: stats?.totalUsers ?? '-' },
              { label: '今日练习', value: stats?.todayRecords ?? '-' },
              { label: '平均评分', value: stats?.averageScore ?? '-' },
            ]" :key="item.label">
              <div class="stat-val">{{ item.value }}</div>
              <div class="stat-lbl">{{ item.label }}</div>
            </el-card>
          </div>
          <el-table :data="allRecords" stripe style="margin-top:16px">
            <el-table-column label="时间"><template #default="{ row }">{{ new Date(row.createdAt).toLocaleString() }}</template></el-table-column>
            <el-table-column prop="unitId" label="单元" />
            <el-table-column prop="score" label="评分" />
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="操作日志" name="logs">
          <el-table :data="logs" stripe>
            <el-table-column prop="createdAt" label="时间" width="180" />
            <el-table-column prop="operator" label="操作人" width="110" />
            <el-table-column prop="action" label="动作" width="120" />
            <el-table-column prop="resourceId" label="对象" width="110" />
            <el-table-column prop="remark" label="说明" show-overflow-tooltip />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </template>

    <el-dialog v-model="dialogVisible" title="编辑单元" width="560px">
      <el-form v-if="editingUnit" label-width="80px">
        <el-form-item label="ID"><el-input v-model="editingUnit.id" :disabled="!!editingUnit.id" /></el-form-item>
        <el-form-item label="拼音"><el-input v-model="editingUnit.pinyin" /></el-form-item>
        <el-form-item label="汉字"><el-input v-model="editingUnit.character" /></el-form-item>
        <el-form-item label="分类"><el-input v-model="editingUnit.category" /></el-form-item>
        <el-form-item label="结论"><el-input v-model="editingUnit.conclusion" type="textarea" /></el-form-item>
        <el-form-item label="详情"><el-input v-model="editingUnit.detail" type="textarea" /></el-form-item>
        <el-form-item label="示范音">
          <el-input v-model="editingUnit.demoAudio" placeholder="已审核发布的示范音地址，例如 /api/media/{id}/file" />
          <p class="field-note">填入后关卡页直接播真实录音；留空则用语音合成示意。</p>
        </el-form-item>
        <el-form-item label="当前状态">
          <el-tag :type="STATUS_TAG[editingUnit.status || 'draft'] || 'info'">{{ STATUS_LABEL[editingUnit.status || 'draft'] || editingUnit.status }}</el-tag>
          <span class="field-note">状态不能直接改：发布走「提交审核 → 审核通过」，下架走「下架」。</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveUnit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.admin-view { background: #fff; border-radius: 12px; padding: 24px; }
.login-card { max-width: 460px; margin: 40px auto; }
.login-card h3 { margin: 0 0 8px; }
.hint { color: #909399; font-size: 12px; line-height: 1.7; margin: 0 0 12px; }
.admin-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.card-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
.head-actions { display: flex; gap: 8px; align-items: center; }
.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.stat-val { font-size: 24px; font-weight: 700; }
.stat-lbl { color: #909399; font-size: 13px; }
.field-note { margin: 4px 0 0 10px; font-size: 12px; color: #a8abb2; line-height: 1.5; }
code { background: #f5f7fa; border-radius: 4px; padding: 1px 5px; }
</style>
