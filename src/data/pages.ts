/**
 * 十页 P01–P10 路由与儿童化文案位（第 4 周 D 交付：确认十页路由与儿童化文案位）
 * ---------------------------------------------------------------------------
 * 口径来源：《团队学习与第一二学期开发周排期详细方案》
 *   - 模块落点表：「前端路由 src/router/index.ts 对应首页、搜索、地图、原理、发音库、资料、检测、
 *     关卡、结果、档案、后台」
 *   - 排期正文锚点：P04 = 发音原理、P06 = 发音库（仅家长路径 / CMS 预览）、P07 = 专业资料、
 *     P09 = 结果页
 *   - SRS D-15：孩子导航不含发音库
 *
 * 因此十页的其余编号按「先入口后流程」推定为：P01 首页 / P02 搜索 / P03 地图 / P04 原理 /
 * P05 检测 / P06 发音库 / P07 专业资料 / P08 关卡 / P09 结果 / P10 档案；后台 /admin 属 CMS，
 * 不计入十页儿童页面。
 *
 * ⚠ 待确认：P01/P02/P03/P05/P08/P10 的具体编号需与 F（SRS V1.1 验收口径负责人）逐条核对，
 *   核对前本文件即前端唯一登记处，任何页面不得再自造编号。确认后只需改本文件 + router meta。
 *
 * 文案位：D 留位（key 固定），文案由 G（儿童化）/ I（内容）定稿后替换，
 *   页面只消费 PAGE_COPY[code]，不要在页面里散写硬编码提示语。
 */

export interface PageCopySlots {
  /** 一句话说明：为什么孩子要用这一页 */
  subtitle: string
  /** 加载中 */
  loading: string
  /** 空状态（尚未有内容，但页面本身可用） */
  empty: string
  /** 加载失败（后端不可用） */
  error: string
  /** 未开放（按 SRS 收缩规则，不算整版失败，也不得写成「敬请期待」凑数） */
  unopened: string
  /** 主要动作按钮 */
  cta: string
}

export interface PageDef {
  /** 页号 P01–P10（后台 /admin 用 'ADMIN'） */
  code: string
  /** 路由 path（多段路由用数组） */
  paths: string[]
  /** 路由 name（与 router 保持一致） */
  name: string
  /** 同一页号下的其它路由 name（如关卡页：levels 列表 + level 单关） */
  routeNames?: string[]
  /** 后台/管理用途标题 */
  title: string
  /** 孩子端标题（文案位） */
  childTitle: string
  /** 是否进入孩子导航（D-15：发音库不进入） */
  childNav: boolean
  /** 图标（Element Plus 图标名） */
  icon: string
  copy: PageCopySlots
}

export const PAGES: PageDef[] = [
  {
    code: 'P01',
    paths: ['/'],
    name: 'home',
    title: '首页',
    childTitle: '开始闯关',
    childNav: true,
    icon: 'HomeFilled',
    copy: {
      subtitle: '一个音一个音地练，说清楚每个字。',
      loading: '正在准备今天的练习…',
      empty: '还没有可以练的关卡，等老师开放吧。',
      error: '没连上服务器，检查一下后端有没有启动。',
      unopened: '这一部分还没开放。',
      cta: '开始',
    },
  },
  {
    code: 'P02',
    paths: ['/search'],
    name: 'search',
    title: '搜索结果',
    childTitle: '找一找',
    childNav: true,
    icon: 'Search',
    copy: {
      subtitle: '输入一个字、一个拼音，或者你的小问题。',
      loading: '正在找…',
      empty: '没找到这个音，换个说法再试试。',
      error: '搜索失败，稍后再试一次。',
      unopened: '这个音还没开放。',
      cta: '搜索',
    },
  },
  {
    code: 'P03',
    paths: ['/map'],
    name: 'map',
    title: '发音地图',
    childTitle: '闯关地图',
    childNav: true,
    icon: 'MapLocation',
    copy: {
      subtitle: '看看 30 关排在哪里，接下来练哪一关。',
      loading: '地图正在展开…',
      empty: '地图上还没有关卡。',
      error: '地图加载失败，稍后再试。',
      unopened: '这一片还没开放。',
      cta: '去这一关',
    },
  },
  {
    code: 'P04',
    paths: ['/principles'],
    name: 'principles',
    title: '发音原理',
    childTitle: '声音怎么来的',
    childNav: true,
    icon: 'Reading',
    copy: {
      subtitle: '声音是怎么从嘴巴里出来的？',
      loading: '正在准备讲解…',
      empty: '这里的内容还在整理。',
      error: '内容加载失败。',
      unopened: '这一节还没开放。',
      cta: '看一看',
    },
  },
  {
    code: 'P05',
    paths: ['/test'],
    name: 'test',
    title: '检测中心',
    childTitle: '录一句试试',
    childNav: true,
    icon: 'Microphone',
    copy: {
      subtitle: '录一句，看看清楚不清楚。',
      loading: '正在准备麦克风…',
      empty: '还没有开放检测的关卡。',
      error: '录音或分析失败，检查后端与麦克风权限。',
      unopened: '这一关还不能检测，先跟着练。',
      cta: '开始录音',
    },
  },
  {
    code: 'P06',
    paths: ['/library'],
    name: 'library',
    title: '发音库',
    childTitle: '发音库（家长）',
    childNav: false, // SRS D-15：孩子导航不含发音库，仅家长路径 / CMS 预览
    icon: 'Collection',
    copy: {
      subtitle: '家长查看：已发布的发音单元与进度。',
      loading: '正在加载发音库…',
      empty: '还没有已发布的单元。',
      error: '发音库加载失败。',
      unopened: '该单元未发布，不公开展示。',
      cta: '查看',
    },
  },
  {
    code: 'P07',
    paths: ['/materials'],
    name: 'materials',
    title: '专业资料',
    childTitle: '给爸爸妈妈看',
    childNav: false,
    icon: 'Document',
    copy: {
      subtitle: '呼吸、共鸣、发声、口型：给家长的参考资料。',
      loading: '正在加载资料…',
      empty: '资料还在整理，来源与许可靠后再发布。',
      error: '资料加载失败。',
      unopened: '这部分资料还没开放。',
      cta: '查看来源',
    },
  },
  {
    code: 'P08',
    paths: ['/learn', '/learn/:id'],
    name: 'levels',
    routeNames: ['levels', 'level'],
    title: '关卡页',
    childTitle: '开始这一关',
    childNav: true,
    icon: 'Flag',
    copy: {
      subtitle: '听示范、跟着读，一关一关来。',
      loading: '正在打开这一关…',
      empty: '这一关还没有内容。',
      error: '关卡加载失败，检查后端是否启动。',
      unopened: '这一关还没开放，先去前面几关吧。',
      cta: '开始练',
    },
  },
  {
    code: 'P09',
    paths: ['/feedback/:id'],
    name: 'feedback',
    title: '检测结果',
    childTitle: '看看读得怎么样',
    childNav: false,
    icon: 'DataAnalysis',
    copy: {
      subtitle: '这里会告诉你哪里读得好、哪里再练一次。',
      loading: '正在看你的录音…',
      empty: '还没有录音结果。',
      error: '结果加载失败，可以重新录一次。',
      unopened: '这一关只学习、不检测。',
      cta: '再练一次',
    },
  },
  {
    code: 'P10',
    paths: ['/archive'],
    name: 'archive',
    // /compare 是 P10 下的子页（多次录音对比），页号不另起
    routeNames: ['archive', 'compare'],
    title: '我的声音档案',
    childTitle: '我的声音',
    childNav: true,
    icon: 'FolderOpened',
    copy: {
      subtitle: '听过、练过的都记在这里，家长同意后才保存。',
      loading: '正在打开档案…',
      empty: '还没有记录，练一次就会出现。',
      error: '档案加载失败。',
      unopened: '档案功能未开放。',
      cta: '去看看',
    },
  },
]

/** 后台（CMS）：不属于十页儿童页面，单独登记避免与 P01–P10 混编 */
export const ADMIN_PAGE: PageDef = {
  code: 'ADMIN',
  paths: ['/admin'],
  name: 'admin',
  title: '后台管理',
  childTitle: '后台管理',
  childNav: false,
  icon: 'Setting',
  copy: {
    subtitle: '内容录入、审核、发布与反馈处理。',
    loading: '正在加载后台数据…',
    empty: '暂无数据。',
    error: '后台接口异常。',
    unopened: '未开放。',
    cta: '刷新',
  },
}

export const ALL_PAGES: PageDef[] = [...PAGES, ADMIN_PAGE]

const PAGE_BY_CODE = new Map(ALL_PAGES.map(p => [p.code, p]))

export function getPage(code: string): PageDef | undefined {
  return PAGE_BY_CODE.get(code)
}

/** 路由 name → 页号，写进 router meta.pageCode，供面包屑 / 埋点 / 验收清单统一取用 */
export const PAGE_CODE_BY_ROUTE_NAME: Record<string, string> = ALL_PAGES.reduce(
  (acc, p) => {
    for (const n of [p.name, ...(p.routeNames ?? [])]) acc[n] = p.code
    return acc
  },
  {} as Record<string, string>,
)

/** 孩子导航（D-15：不含发音库 / 结果页 / 后台） */
export const CHILD_NAV_PAGES: PageDef[] = PAGES.filter(p => p.childNav)
