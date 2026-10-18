#!/usr/bin/env node
/**
 * 关卡数据链路可复跑检查（第 4 周 D 交付）
 * ---------------------------------------------------------------------------
 * 检查三件事：
 *   1) C 的 /api/units 是否可用，且「未审核不公开」是否成立（草稿不出现在 published 列表里）
 *   2) L01–L30 是否已按冻结表入库（可为 draft）
 *   3) 前端 stores/levels.ts 的合并口径复算：30 关 = 可练可测 + 只学不测 + 未开放
 *
 * 用法（先起后端）：
 *   cd backend && python main.py
 *   node backend/tools/check_levels_api.mjs            # 默认 http://localhost:8000/api
 *   node backend/tools/check_levels_api.mjs http://localhost:8000/api
 *
 * 退出码：0 全通过；1 有检查项失败（可直接接进 H 的回归脚本）。
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const freezePath = path.resolve(here, '../../src/data/levels.freeze.json');
const BASE = (process.argv[2] ?? 'http://localhost:8000/api').replace(/\/$/, '');

let failed = 0;
const check = (ok, label, detail = '') => {
  if (!ok) failed++;
  console.log(`${ok ? 'OK  ' : 'FAIL'}  ${label}${detail ? `  (${detail})` : ''}`);
};

async function get(pathname) {
  const res = await fetch(`${BASE}${pathname}`);
  if (!res.ok) return { ok: false, status: res.status, data: null };
  const body = await res.json();
  return { ok: true, status: res.status, data: body.data };
}

const freeze = JSON.parse(fs.readFileSync(freezePath, 'utf8'));
const levels = freeze.levels;

const published = await get('/units?status=published');
const all = await get('/units');

check(published.ok, 'GET /api/units?status=published 可用', `status=${published.status}`);
check(all.ok, 'GET /api/units 可用', `status=${all.status}`);
if (!published.ok || !all.ok) {
  console.log('\n后端不可用：请先 `cd backend && python main.py`（或 npm run backend）再跑本检查。');
  process.exit(1);
}

const publishedIds = new Set(published.data.map((u) => u.id));
const allById = new Map(all.data.map((u) => [u.id, u]));

// 1) 未审核不公开：L01–L30 若还是 draft，就不能出现在 published 列表
const draftCodes = levels.map((l) => l.code).filter((c) => !publishedIds.has(c));
const leakedDrafts = draftCodes.filter((c) => {
  const u = allById.get(c);
  return u && u.status !== 'published' && publishedIds.has(c);
});
check(leakedDrafts.length === 0, '未审核（draft）关卡不出现在已发布列表', `${draftCodes.length} 关仍为草稿/未录入`);

// 2) 冻结表关卡是否已入库（draft 也算，正式内容由 C 补）
const inCms = levels.filter((l) => allById.has(l.code) || l.cmsIds.some((id) => allById.has(id)));
console.log(`     冻结表 ${levels.length} 关中，已能在 CMS/历史单元里找到落点：${inCms.length} 关`);

// 3) 复算前端合并口径（与 src/stores/levels.ts 的 buildView 同规则）
let open = 0;
let learnOnly = 0;
let unopened = 0;
const openList = [];
for (const lv of levels) {
  const unit =
    (publishedIds.has(lv.code) ? allById.get(lv.code) : null) ??
    lv.cmsIds.map((id) => (publishedIds.has(id) ? allById.get(id) : null)).find(Boolean) ??
    null;
  const isPublished = !!unit && unit.status === 'published';
  const detectionOpen = isPublished && !!unit.verified;
  if (detectionOpen) {
    open++;
    openList.push(`${lv.code}(${lv.target}→${unit.id})`);
  } else if (isPublished) {
    learnOnly++;
  } else {
    unopened++;
  }
}
check(open + learnOnly + unopened === 30, '30 关状态合计为 30', `可练可测 ${open} / 只学不测 ${learnOnly} / 未开放 ${unopened}`);
console.log(`     可练可测：${openList.join(', ') || '（无）'}`);
console.log(`     冻结版本：${freeze.version}`);

// 4) 已发布关必须完整（第 8 周 D）：P08 会渲染 conclusion + steps + mistakes，
//    任何一项为空都会在页面上变成「这一关还没有内容」的空卡片 —— 正是排期禁止的。
const stepCount = (u) => (Array.isArray(u?.steps) ? u.steps.length : 0);
const mistakeCount = (u) => (Array.isArray(u?.mistakes) ? u.mistakes.length : 0);
const incompletePublished = [];
for (const lv of levels) {
  const unit =
    (publishedIds.has(lv.code) ? allById.get(lv.code) : null) ??
    lv.cmsIds.map((id) => (publishedIds.has(id) ? allById.get(id) : null)).find(Boolean) ??
    null;
  if (!unit) continue;
  const missing = [];
  if (!String(unit.conclusion || '').trim()) missing.push('conclusion');
  if (stepCount(unit) === 0) missing.push('steps');
  if (mistakeCount(unit) === 0) missing.push('mistakes');
  if (missing.length) incompletePublished.push(`${lv.code}(${unit.id}) 缺 ${missing.join('/')}`);
}
check(
  incompletePublished.length === 0,
  '已发布关内容完整（不发空卡片）',
  incompletePublished.length ? incompletePublished.join('；') : `${open + learnOnly} 关已发布关结论/步骤/误区齐全`,
);

// 5) 草稿内容齐备度：C 一旦发布，页面就会读这些字段；缺内容的关发布出来就是空卡片，
//    所以这里提前把「还没内容、暂不可发布」的关列清楚（不阻塞检查，给 C / I 的发布决策用）。
const contentMissing = levels
  .filter((lv) => {
    const u = allById.get(lv.code) ?? null;
    if (!u || u.status === 'published') return false;
    return !String(u.conclusion || '').trim() || stepCount(u) === 0 || mistakeCount(u) === 0;
  })
  .map((lv) => lv.code);
console.log(
  contentMissing.length
    ? `     提示：${contentMissing.length} 关草稿内容仍不完整（${contentMissing.join(', ')}），发布前请先补内容，否则会出现空卡片。`
    : '     草稿内容：L01–L30 的教学字段（结论 / 步骤 / 误区）均已补齐，C 可逐关审核发布。',
);

console.log(failed === 0 ? '\n全部检查通过。' : `\n有 ${failed} 项检查失败。`);
process.exit(failed === 0 ? 0 : 1);
