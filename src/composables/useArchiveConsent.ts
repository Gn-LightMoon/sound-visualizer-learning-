import { ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'

export const ARCHIVE_CONSENT_KEY = 'voice_archive_consent_v1'

/**
 * 家长同意存档（第 7 周 D：不登录闯关 + 家长同意存档）
 * ---------------------------------------------------------------------------
 * 之前这里是「每个组件各自 ref + 各自读 localStorage」：HistoryView 里点了同意，
 * 已经挂载的关卡页 / 检测中心拿到的那份 ref 仍是 false —— 同一次会话里三个页面口径不一致。
 * 存档同意是全局状态，必须是模块级单例：任何一处 grant / revoke，所有页面立刻同步；
 * 同时继续写 localStorage，刷新后仍然记住。
 */
const consented = ref(localStorage.getItem(ARCHIVE_CONSENT_KEY) === 'true')

watch(consented, (value) => {
  if (value) localStorage.setItem(ARCHIVE_CONSENT_KEY, 'true')
  else localStorage.removeItem(ARCHIVE_CONSENT_KEY)
})

/** 供测试 / 清档场景复位（不对外暴露 localStorage 细节） */
function grant() {
  consented.value = true
}

function revoke() {
  consented.value = false
}

export function useArchiveConsent() {
  return { consented, grant, revoke }
}

/**
 * 存档前的「家长同意」确认（第 7 周 D）
 * ---------------------------------------------------------------------------
 * 排期口径：访客可以不登录闯关，但**录音默认不留存**，只有家长同意后才写入档案，
 * 且可随时撤回并删除。所以保存动作不能静默发生 —— 这里统一弹一次确认：
 *   「同意并保存」→ 记下同意（全站生效）并继续保存；
 *   「这次不保存」→ 本次结果只在当前页展示，不写数据库。
 * 这段文案是 P08/P05 共用的唯一处，G（儿童化）定稿后只改这里。
 */
export async function confirmArchiveConsent(): Promise<boolean> {
  if (consented.value) return true
  try {
    await ElMessageBox.confirm(
      '这次练习要存进「我的声音」档案吗？只有家长同意后我们才会保存录音与结果，之后可以随时撤回并删除。',
      '保存到档案？',
      {
        confirmButtonText: '同意并保存',
        cancelButtonText: '这次不保存',
        type: 'info',
        distinguishCancelAndClose: true,
      },
    )
    grant()
    return true
  } catch {
    return false
  }
}
