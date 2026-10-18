# CMS 初筛接口调研（Z3 · 第 4 周）

> 定位：用本地大模型对「后台录入的发音单元内容」做智能初筛，自动标记异常，辅助 C 的人工审核流程。
> 本文件为第 4 周调研产出，是后续第 6 周「方案定稿」、第 8 周「自动标异常录入」的依据。

---

## 一、背景与目标

排期里 Z 组的 CMS 初筛定位：

- 第 6 周：CMS 智能初筛接口方案定稿（Z2/Z3 分头验证）
- 第 8 周：CMS 智能初筛接口（给 C 用，自动标异常录入）
- 第 9 周：CMS 初筛上线联调；补初筛误判样本人工复核流程

**目标**：管理员（C）在后台录入发音单元后、正式审核前，先由大模型自动"体检"一遍内容，标出疑似异常，降低人工审核漏检率。

---

## 二、现状盘点（初筛的原材料）

现有 CMS 内容表 `pronunciation_units` 字段：

| 字段 | 含义 | 初筛是否关注 |
|------|------|:---:|
| `id` | 单元唯一标识 | — |
| `pinyin` | 拼音（含声调） | ✅ 声调/合法性 |
| `character` | 汉字 | ✅ 与拼音对应 |
| `category` | 分类（声母/韵母/声调） | ✅ 枚举与一致性 |
| `description` | 简述 | ✅ 完整性 |
| `conclusion` | 结论（怎么发） | ✅ 内容硬伤 |
| `detail` | 详细说明 | ✅ 内容硬伤 |
| `mistakes` | 常见误区（JSON 数组） | ✅ 结构完整 |
| `steps` | 练习步骤（JSON 数组） | ✅ 结构完整 |
| `related` | 相关单元（JSON 数组） | 可选 |
| `status` | draft / published | — |
| `verified` | 是否验证开放 | — |

现有接口：`/api/units` 的增删改查（`GET/POST/PUT/DELETE`）已齐全，录入入口是 `POST /api/units`。

---

## 三、初筛接口设计（输入/输出契约）

### 输入：一条待审发音单元

```json
{
  "unit": {
    "id": "ba",
    "pinyin": "bā",
    "character": "八",
    "category": "声母",
    "description": "不送气双唇塞音",
    "conclusion": "b 是不送气双唇塞音：双唇闭合后突然放开",
    "detail": "双唇先闭拢憋气，然后突然放开，声带不振动（清音），无气流冲出。",
    "mistakes": [{"title": "送气混淆", "text": "b 送气过多会变成 p"}],
    "steps": [{"title": "听示范", "text": "听 ba 发音"}]
  }
}
```

### 输出：初筛结果

```json
{
  "verdict": "review",
  "issues": [
    {"field": "category", "severity": "warning", "message": "单元 id 为 ba，但 category 填的是「声母」，请确认是否应为「声母」（本单元核心是声母 b）"}
  ],
  "suggestion": "建议人工复核 category 与 conclusion 是否一致。"
}
```

**verdict 三档**：

| verdict | 含义 | 后续动作 |
|---------|------|----------|
| `pass` | 无明显问题 | 可直接进入人工审核 |
| `review` | 有疑似问题 | 标注异常项，人工复核 |
| `reject` | 明显错误 | 退回修改 |

---

## 四、异常规则清单（初筛筛什么）

初筛 = **规则校验（硬编码）+ 大模型语义校验（LLM）** 两段组合：

| # | 规则 | 字段 | 方式 | 示例 |
|---|------|------|------|------|
| R1 | 拼音合法性 | `pinyin` | 规则 | 声母/韵母/声调是否合法 |
| R2 | 分类枚举 | `category` | 规则 | 必须在 {声母, 韵母, 声调} 内 |
| R3 | 字段非空 | `conclusion/detail` | 规则 | 是否为空或过短 |
| R4 | 结构完整 | `steps/mistakes` | 规则 | 数组是否为空 |
| R5 | 拼音-汉字对应 | `pinyin/character` | LLM | "bā" 应对 "八"，填 "妈" 则异常 |
| R6 | 分类-内容一致 | `category/conclusion` | LLM | conclusion 讲 b 的发音，category 却填"韵母" |
| R7 | 内容硬伤 | `conclusion/detail` | LLM | conclusion 说"b 是鼻音"（实际是塞音） |

> 结论：R1–R4 可用代码直接校验，无需大模型；R5–R7 需要语义理解，交给 Qwen2.5。两者组合即可覆盖主要异常类型。

---

## 五、实现方案（复用 llm_service）

初筛接口内部调用已封装的 `llm_service.chat()`，提示词要求模型输出结构化 JSON：

```text
你是普通话发音内容审核员。请检查下面这条发音单元的内容是否有错误：
{unit_json}

只输出 JSON，结构：
{"verdict":"pass/review/reject","issues":[{"field":"...","severity":"warning/error","message":"..."}],"suggestion":"一句话"}
```

调用链：

```
POST /api/cms/preview  →  规则校验(R1-R4)  →  llm_service.chat(R5-R7)  →  合并输出 verdict/issues
```

后端新增接口（草案，第 6 周定稿）：

```python
@app.post("/api/cms/preview")
def cms_preview(unit: dict):
    rule_issues = rule_check(unit)          # R1-R4 硬编码
    llm_issues = llm_check(unit)            # R5-R7 调 llm_service
    ...
```

---

## 六、与 C 审核流的对接（预留）

C 第 4 周在做「录入 → 审核」状态机。初筛接口作为**录入后、人工审核前**的一道自动关卡：

```
录入(POST /api/units)  →  初筛(/api/cms/preview)  →  人工审核(C)  →  发布(published)
```

待对齐点（等 C 状态机推上来后）：
1. 初筛结果是否落库（如单元增加 `review_status` 字段）；
2. 初筛是「同步阻塞」还是「异步批量」跑；
3. 初筛误判样本的人工复核流程（第 9 周）。

---

## 七、风险与后续

- **风险 1**：LLM 输出不稳定（可能不按 JSON 格式吐）。缓解：提示词强约束 + 解析失败降级为 `review`。
- **风险 2**：初筛误判（把正常内容标异常）。缓解：第 9 周补「误判样本人工复核」闭环。
- **后续**：第 6 周 Z2/Z3 分头验证方案；第 8 周落到 C 的审核流；第 9 周上线联调。

---

## 附：本周（第 4 周）可交付物清单

1. ✅ 本调研文档（接口契约 + 规则清单 + 实现方案）
2. ✅ `/api/llm/chat`（第 1、2 周欠账补齐，供初筛调用底座）
3. ⏳ `/api/cms/preview` 初筛接口（草案，第 6 周正式定稿再实现）
