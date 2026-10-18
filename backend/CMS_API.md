# CMS 管理接口文档(第 6+7 周 C · 四状态机 + 管理员登录版)

> 面向:D 联调 / F 统稿 / H 测试。响应格式统一 `{"code":200,"data":...}`,错误 `{"code":400/401/404,"message":"..."}`。
> **鉴权(第 7 周起)**:除登录外,全部 `/api/admin/*` 接口须带请求头 `X-Token: <登录返回的 token>`,否则 **401**;操作人 = 登录管理员,原 `X-Operator` 假鉴权已下线。

## 管理员登录(第 7 周新增)

- 初始账号:**admin / admin123**(首次启动自动创建,请尽快改密)
- `POST /api/admin/login` — body `{"username":"admin","password":"admin123"}` → `data.token`(后续请求放 `X-Token` 头)
- `POST /api/admin/logout` — 吊销当前 token(带 `X-Token` 头)
- `POST /api/admin/change-password` — 改密:body `{"oldPassword":"...","newPassword":"..."}`,新密码至少 6 位(带 `X-Token` 头)
- **D 联调注意**:AdminView 所有 admin 调用先登录拿 token;未登录 401 是预期行为

## 状态机(单一事实来源:`database.py` 的 `UNIT_STATUS_TRANSITIONS`)

```
 草稿 draft ──提交审核──> 待审核 pending_review ──审核通过──> 已发布 published
   ▲                          │                                  │
   │                          │ 审核驳回(必填原因)                │ 下架
   └── 驳回后修改重提 ◄────── rejected ◄─────────────────────────┘
```

- 状态值:draft / pending_review / rejected / published(仓库前台按 `status=published` 过滤,未审核不公开)
- **录入即草稿**:POST /api/units 创建的单元恒为 draft,不能直接发布
- **内容编辑仅限草稿/驳回**:待审核、已发布状态编辑返回 400
- **状态变更必须走流转接口**:不可通过编辑接口直接改 status
- **驳回必须带原因**:`review_comment` 为空返回 400
- 重提审核自动清空上一轮审核结论(审核人/时间/驳回意见)
- **创建人不能审核自己**(第 7 周):approve/reject 时操作人 = 创建人 → 400,须换一位管理员审核
- 检测开关 `verified` 与审核状态**相互独立**:任何状态都可切换(是否允许开,对照 A/B 的「可稳定评分清单」)
- **版本历史**(第 7 周):录入存 v1 快照,每次内容编辑存一版快照,`GET /api/admin/units/{id}/versions` 可追溯对比

## 接口清单

### 大众端(原有,不变)

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/units?status=published` | 仅返回已发布单元(未审核不公开) |
| GET | `/api/units/{id}` | 单元详情 |
| POST | `/api/units` | 录入(第 6 周起**恒为草稿**,响应 message 已注明) |
| PUT | `/api/units/{id}` | 编辑内容(仅草稿/驳回;每次编辑 version+1;不允许直改 status) |
| DELETE | `/api/units/{id}` | 删除(核心单元受保护) |

### CMS 管理端 `/api/admin`(新增)

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/admin/login` | 登录,返回 token(唯一不需要 X-Token 的 admin 接口) |
| POST | `/api/admin/logout` | 登出,吊销 token |
| POST | `/api/admin/change-password` | 修改自己的密码 |
| GET | `/api/admin/units?status=` | 全状态列表,可按 status 筛选 |
| GET | `/api/admin/units/{id}` | 详情(含审核字段/创建人/版本/检测开关) |
| GET | `/api/admin/units/{id}/versions` | 版本历史快照(第 7 周):每版内容/操作人/时间 |
| POST | `/api/admin/units/{id}/submit-review` | 提交审核:draft/rejected → pending_review |
| POST | `/api/admin/units/{id}/approve` | 审核通过并发布:pending_review → published(创建人不能审核自己) |
| POST | `/api/admin/units/{id}/reject` | 驳回:pending_review → rejected;body `{"review_comment":"..."}` 必填(创建人不能审核自己) |
| POST | `/api/admin/units/{id}/unpublish` | 下架:published → draft(大众端立即不可见) |
| POST | `/api/admin/units/{id}/set-detection` | 检测开关:body `{"verified":true/false}`;对应 CON-04「只学不测」 |
| GET | `/api/admin/audit-logs?resource_id=&limit=` | 操作日志(倒序) |

> 另:`/api/admin/stats`、`/api/admin/learning-records`、`/api/admin/feedback*`(main.py 内)第 7 周起同样需要 X-Token。

### 单元返回结构新增字段(30 关正式口径,对应 seed_levels_30.py 的 FIELD MAPPING)

```jsonc
{
  "id": "L01",
  "pinyin": "a",            // = FIELD MAPPING 的 target
  "character": "啊",
  "category": "韵母",        // = FIELD MAPPING 的 group
  "status": "draft",         // = FIELD MAPPING 的 review_status
  "verified": false,         // = FIELD MAPPING 的 detection_open(检测开关)
  "demoAudio": "",           // 示范音频路径(D AdminView 已有录入位)
  "practice": [],            // 练习内容(JSON 数组)
  "version": 1,              // 版本号:每次内容编辑自动 +1,可追溯
  "creator": "张三",          // 创建人(第 7 周:创建人不能审核自己)
  "submitReviewTime": null, "reviewTime": null, "reviewer": null, "reviewComment": null,
  // ... 原有字段不变
}
```

## 老库自动迁移

`init_db` 启动时自动为旧 `pronunciation_units` 表补列(demo_audio / practice / version / creator / 审核字段),**已有数据不丢、无需手工迁移**;新增 `audit_log`、`admin_user`、`admin_token`、`unit_version_history` 表。老数据的 creator 为空串,不触发自审拦截。

## 自测

```bash
cd backend && python -m pytest test_cms_workflow.py -v
# 17 个用例(原 46 检查点 + 第 7 周:创建人自审拦截/版本快照/登录鉴权 token 与 401)
# 独立临时库,跑完即删;H 可将其纳入回归
```

验收口径(D 的 `backend/tools/check_levels_api.mjs` 不变):`GET /api/units?status=published` 只含 published;
30 关 = 可练可测(published+verified)/ 只学不测(published)/ 未开放(未发布)。
