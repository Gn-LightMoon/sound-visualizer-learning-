"""CMS 管理路由（第 6 周 C：四状态机 + 下架 + 检测开关 + 操作日志
                  第 7 周 C：管理员登录鉴权（X-Token）+ 版本历史快照）

对齐仓库现有口径：
- 表：pronunciation_units / admin_user / admin_token / unit_version_history（database.py 原生 sqlite3）；
- 状态值：draft / pending_review / rejected / published（仓库前台按 published 过滤）；
- 响应格式：{"code": 200, "data": ...}，错误 {"code": 400/401/404, "message": ...}。

鉴权口径（第 7 周起）：
- 除 /login 外，全部 /api/admin/* 接口须带请求头 X-Token（登录返回的 token），否则 401；
- 操作人 = 登录态里的管理员用户名，原 X-Operator 假鉴权已下线。
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import database
from database import CmsStateError

router = APIRouter(prefix="/api/admin", tags=["CMS管理接口"])


def require_admin(x_token: str | None = Header(default=None, alias="X-Token")) -> str:
    """管理员鉴权依赖：校验 X-Token，返回登录用户名；未登录/已吊销抛 401"""
    username = database.token_to_user(x_token or "")
    if username is None:
        raise HTTPException(
            status_code=401, detail="未登录或登录已过期：请先 POST /api/admin/login 获取 token"
        )
    return username


def _ok(data):
    return {"code": 200, "data": data}


def _fail(message: str, status_code: int = 400):
    return JSONResponse(status_code=status_code, content={"code": status_code, "message": message})


def _get_or_404(unit_id: str) -> dict:
    unit = database.get_unit(unit_id)
    if unit is None:
        raise KeyError(unit_id)
    return unit


def _run(action, unit_id: str, operator: str, *args):
    """统一执行流转动作：404 转 KeyError，非法流转转 CmsStateError"""
    try:
        result = action(unit_id, operator, *args)
    except CmsStateError as exc:
        return _fail(str(exc))
    if result is None:
        return _fail(f"发音单元 {unit_id} 不存在", 404)
    return {"code": 200, "message": "操作成功", "data": result}


# ---------------------------------------------------------------------------
# 管理员登录鉴权（第 7 周 C）
# ---------------------------------------------------------------------------
class LoginPayload(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(payload: LoginPayload):
    """管理员登录：成功返回 token，后续请求带 X-Token 头。
    初始账号 admin/admin123（首次启动自动创建，请尽快改密）。"""
    result = database.verify_admin(payload.username, payload.password)
    if result is None:
        return _fail("用户名或密码错误", 401)
    username, display_name = result
    token = database.issue_token(username)
    return _ok({"token": token, "username": username, "displayName": display_name})


@router.post("/logout")
def logout(x_token: str | None = Header(default=None, alias="X-Token")):
    """登出：吊销当前 token"""
    if x_token:
        database.revoke_token(x_token)
    return _ok(True)


@router.post("/change-password")
def change_password(payload: dict, operator: str = Depends(require_admin)):
    """修改自己的密码：body {"oldPassword":"...","newPassword":"..."}，新密码至少 6 位"""
    old = (payload or {}).get("oldPassword", "")
    new = (payload or {}).get("newPassword", "")
    if not new or len(new) < 6:
        return _fail("新密码至少 6 位", 400)
    if not database.change_password(operator, old, new):
        return _fail("旧密码不正确", 400)
    return _ok(True)


# ---------------------------------------------------------------------------
# CMS 单元列表 / 详情（管理员视角：全状态可见）
# ---------------------------------------------------------------------------
@router.get("/units")
def list_units(status: str = "", operator: str = Depends(require_admin)):
    """CMS 单元列表，可按状态筛选：?status=draft/pending_review/rejected/published"""
    return _ok(database.get_units(status))


@router.get("/units/{unit_id}")
def get_unit(unit_id: str, operator: str = Depends(require_admin)):
    """CMS 单元详情（含审核字段/创建人/版本）"""
    try:
        unit = _get_or_404(unit_id)
    except KeyError:
        return _fail(f"发音单元 {unit_id} 不存在", 404)
    return _ok(unit)


@router.get("/units/{unit_id}/versions")
def unit_versions(unit_id: str, operator: str = Depends(require_admin)):
    """版本历史快照（第 7 周 C）：该单元全部版本与每版内容，供追溯对比"""
    if database.get_unit(unit_id) is None:
        return _fail(f"发音单元 {unit_id} 不存在", 404)
    return _ok(database.get_unit_versions(unit_id))


# ---------------------------------------------------------------------------
# CMS 审核流转四状态机
# ---------------------------------------------------------------------------
@router.post("/units/{unit_id}/submit-review")
def submit_review(unit_id: str, operator: str = Depends(require_admin)):
    """提交审核：draft/rejected -> pending_review（重提自动清空上一轮审核结论）"""
    return _run(database.submit_review, unit_id, operator)


@router.post("/units/{unit_id}/approve")
def approve_unit(unit_id: str, operator: str = Depends(require_admin)):
    """审核通过并发布：pending_review -> published（发布后大众端可见；创建人不能审核自己）"""
    return _run(database.approve_unit, unit_id, operator)


@router.post("/units/{unit_id}/reject")
def reject_unit(
    unit_id: str,
    payload: dict,
    operator: str = Depends(require_admin),
):
    """审核驳回：pending_review -> rejected，请求体必须带 review_comment；创建人不能审核自己"""
    return _run(database.reject_unit, unit_id, operator, (payload or {}).get("review_comment", ""))


@router.post("/units/{unit_id}/unpublish")
def unpublish_unit(unit_id: str, operator: str = Depends(require_admin)):
    """下架：published -> draft，大众端立即不可见"""
    return _run(database.unpublish_unit, unit_id, operator)


# ---------------------------------------------------------------------------
# 检测开关（CON-04：不能稳定评分的关只学不测，禁止假分）
# ---------------------------------------------------------------------------
@router.post("/units/{unit_id}/set-detection")
def set_detection(
    unit_id: str,
    payload: dict,
    operator: str = Depends(require_admin),
):
    """检测开关：verified=true 表示该关可开放检测（须对照 A/B 的「可稳定评分清单」）。
    前端口径（与 check_levels_api.mjs 一致）：
    published+verified=可练可测；published=只学不测；未发布=未开放。"""
    verified = bool((payload or {}).get("verified", False))
    return _run(database.set_detection, unit_id, operator, verified)


# ---------------------------------------------------------------------------
# 操作日志
# ---------------------------------------------------------------------------
@router.get("/audit-logs")
def audit_logs(resource_id: str = "", limit: int = 100, operator: str = Depends(require_admin)):
    """操作日志查询：?resource_id=L01 查单个资源，?limit=200 调整条数"""
    return _ok(database.get_audit_logs(resource_id, limit))
