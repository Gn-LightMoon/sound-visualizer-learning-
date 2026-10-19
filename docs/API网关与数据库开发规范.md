# API 网关与数据库开发规范

> 输出:C(胡鹏伟)· 第 6 周任务(补交于 2026-10-19)
> 适用:后端全体 / D 联调 / H 测试 / F 统稿。以仓库现状实况为准(2026-10-19 拉取 main `893165f` + C-hpw 分支)。
> 本文是 CMS_API.md 的上位规范;接口细节以 CMS_API.md 与各路由 docstring 为准。

---

## 一、服务分层现状与演进口径

仓库现有三个 HTTP 入口,口径如下:

| 入口 | 定位 | 现状 |
|---|---|---|
| `backend/main.py` | 1.0 主服务(学习记录/单元 CMS/媒体/反馈/进度) | 生产入口,`uvicorn main:app` |
| `api/main.py` | 发音诊断 ASR 层(诊断/模型加载/关卡清单) | 三层路由雏形(接入层/业务层/模型层),2.0 大模型接口预留位 |
| `backend/cms_routes.py` | CMS 管理路由(`/api/admin/*`) | APIRouter,挂载于 main.py |

**演进口径**:
- 新增业务一律先按「路由 → 数据层」两段式落:`xxx_routes.py`(HTTP 适配、鉴权、参数校验)+ `database.py`/独立数据模块(纯 sqlite3,无 FastAPI 依赖);
- `api/main.py` 的三层雏形(接入/业务/模型)是 2.0 方向,现阶段不强制迁移,但**不得再往 main.py 里堆新路由**:能用 APIRouter 拆的拆出去(参考 cms_routes / dataset_routes);
- 大模型接口统一走 `/api/llm/*`(Ollama 代理),未来换模型只改 llm_service,路由不动。

## 二、URL 与响应格式(仓库约定,必须一致)

### 2.1 URL

- 全小写、短横线分隔,资源名复数:`/api/units`、`/api/admin/audit-logs`;
- 动作用 HTTP 方法表达,状态流转用子路径:`POST /api/admin/units/{id}/approve`;
- 管理端统一前缀 `/api/admin/*`;公开接口 `/api/*` 不带 admin。

### 2.2 响应

```json
{"code": 200, "message": "说明(可选)", "data": {...}}
```

- 成功:`code=200`,`data` 必带(可为 null);
- 错误:`{"code": 400/401/404/500, "message": "人话错误说明"}`——错误信息必须告诉调用方**怎么改**(反例:"创建失败";正例:"驳回必须填写原因 review_comment");
- 状态码:400 参数/状态机非法,401 未登录/token 失效,404 资源不存在,500 服务端异常(含 ffmpeg 缺失这类环境问题,message 要说清是环境问题还是代码问题);
- 统一 HTTP 异常格式已在 `main.py` 注册 exception_handler,新路由抛 `HTTPException` 即可,不要手写错误 JSON。

## 三、鉴权规范(第 7 周起生效)

- `/api/admin/*` 除 `/login` 外全部要求请求头 `X-Token`(登录返回),校验走 `cms_routes.require_admin` 依赖,未登录 401;
- 操作人 = token 对应的管理员用户名,落库到 audit_log;原 `X-Operator` 假鉴权已下线,新代码禁止再读 X-Operator;
- 初始账号 admin/admin123(首次启动自动创建,尽快改密);密码 PBKDF2-SHA256 加盐,禁止明文;
- 家长/学生账号体系(CON-05)归属定案后,补充到本规范「用户侧鉴权」章节,当前大众端仍为无鉴权 + userId 参数。

## 四、数据库规范

1. **原生 sqlite3**,不用 ORM(SQLAlchemy 学习版已迁走,勿再引入);
2. 列名 snake_case,时间统一 ISO8601 UTC 文本(`created_at`),接口层才映射为 `createdAt` 驼峰;
3. 建表只写在 `database.init_db` 的幂等块里(`CREATE TABLE IF NOT EXISTS`),新增模块表走 `xxx.init_schema(conn)` 挂进 init_db(参考 dataset / tag_store);**老库升级靠增量迁移**(参考 `_ensure_cms_columns`),已有数据绝不丢;
4. 列表/统计接口**禁止携带 BLOB**(音频只走 `/api/learning-records/{id}/audio` 按需拉取);
5. JSON 字段(数组/对象)一律 `json.dumps(..., ensure_ascii=False)` 存文本,读出 `json.loads`;
6. 同一业务的多表写入必须显式事务(`BEGIN` … `commit`/`rollback`),保证「有记录必有进度」这类一致性;
7. 外键弱约束:靠代码校验 + 索引兜底,不依赖 `PRAGMA foreign_keys`;
8. 新增表必须建索引(按查询模式:user_id+created_at、batch_id、record_id 等)。

## 五、音频处理约定

- 浏览器录音是 webm/ogg(opus),librosa 解不了:**必须 ffmpeg 先转 wav**(16kHz 单声道),服务器缺 ffmpeg 时返回 500 且 message 明确说"装 ffmpeg",不要静默失败;
- 临时文件用完即删(`NamedTemporaryFile` + finally);
- 录音质量五维(音量/噪声/截幅/时长/静音)不达标 → 停止评价返回引导语(AC-07),不允许硬评。

## 六、CORS(整改要求,问题清单#35)

现状 `allow_origins=["*"] + allow_credentials=True` 是浏览器规范禁止的组合,带 Cookie/凭证的请求会被浏览器拒。**家长账号上线前必须改为显式 origin 白名单**(前端部署域名 + 本地开发端口),此项由 C 在账号体系上线时一并整改。

## 七、交付与文档约定

- 每个接口改动同步更新 `backend/CMS_API.md`(接口表 + 调用示例);
- 数据层改动必须补 pytest(参考 test_cms_workflow.py / test_dataset.py),测试只依赖 database 层,不 import torch/librosa,交 H 跑回归;
- 提交信息格式:`feat(cms): …(第N周C)`,分支 `C-<名字缩写>`,PR 从团队仓库分支开。

## 八、已知缺口(本规范修订时逐条关闭)

1. `/api/internal/*` 三层路由未落地(汇总口径超前于代码),2.0 排期;
2. 大众端接口无鉴权,userId 由前端传,家长账号上线后必须改为服务端身份;
3. `/api/units` 与 `/api/pronunciation-units` 双入口并存,冻结后统一收敛到 `/api/units`,旧入口保留到 D 前端切换完。
