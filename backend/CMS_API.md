# CMS 管理接口文档(第 6 周 C · 四状态机版)

> 面向:D 联调 / F 统稿 / H 测试。响应格式统一 `{"code":200,"data":...}`,错误 `{"code":400/404,"message":"..."}`。
> 鉴权:第 7 周管理员登录上线前,操作人经请求头 `X-Operator: 姓名` 传入,缺省 `admin`。

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
- 检测开关 `verified` 与审核状态**相互独立**:任何状态都可切换(是否允许开,对照 A/B 的「可稳定评分清单」)

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
| GET | `/api/admin/units?status=` | 全状态列表,可按 status 筛选 |
| GET | `/api/admin/units/{id}` | 详情(含审核字段/版本/检测开关) |
| POST | `/api/admin/units/{id}/submit-review` | 提交审核:draft/rejected → pending_review |
| POST | `/api/admin/units/{id}/approve` | 审核通过并发布:pending_review → published |
| POST | `/api/admin/units/{id}/reject` | 驳回:pending_review → rejected;body `{"review_comment":"..."}` 必填 |
| POST | `/api/admin/units/{id}/unpublish` | 下架:published → draft(大众端立即不可见) |
| POST | `/api/admin/units/{id}/set-detection` | 检测开关:body `{"verified":true/false}`;对应 CON-04「只学不测」 |
| GET | `/api/admin/audit-logs?resource_id=&limit=` | 操作日志(倒序) |

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
  "submitReviewTime": null, "reviewTime": null, "reviewer": null, "reviewComment": null,
  // ... 原有字段不变
}
```

## 老库自动迁移

`init_db` 启动时自动为旧 `pronunciation_units` 表补列(demo_audio / practice / version / 审核字段),**已有数据不丢、无需手工迁移**;新增 `audit_log` 表记录全部 CMS 操作。

## 自测

```bash
cd backend && python test_cms_workflow.py   # 46 个检查点,独立临时库,跑完即删
```

验收口径(D 的 `backend/tools/check_levels_api.mjs` 不变):`GET /api/units?status=published` 只含 published;
30 关 = 可练可测(published+verified)/ 只学不测(published)/ 未开放(未发布)。
