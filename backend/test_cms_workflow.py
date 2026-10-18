# test_cms_workflow.py
# C 角色第 6+7 周自测（pytest 版，交 H 跑回归）
# 覆盖：录入即草稿 -> 编辑(版本递增+版本快照) -> 提交审核 -> 通过/驳回
#      -> 创建人不能审核自己 -> 下架 -> 检测开关 -> 全部非法流转拦截
#      -> 操作日志链路 -> 版本历史追溯 -> 管理员登录鉴权(token/401)。
# 只依赖 database.py 与 cms_routes.py（不 import main.py，因此不需要 torch/librosa）。
# 运行方式：cd backend && python -m pytest test_cms_workflow.py -v
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database  # noqa: E402
from database import CmsStateError  # noqa: E402


@pytest.fixture(scope="module")
def db():
    """独立临时库：跑完即删，绝不污染开发库 pronunciation.db"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database.DB_PATH = tmp.name
    database.init_db(tmp.name)
    yield tmp.name
    os.remove(tmp.name)


@pytest.fixture(scope="module")
def client(db):
    """仅挂 CMS 路由的 FastAPI 测试客户端（HTTP 级鉴权测试用）"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import cms_routes

    app = FastAPI()
    app.include_router(cms_routes.router)
    with TestClient(app) as c:
        yield c


def _raises(fn) -> bool:
    """执行 fn，若抛出 CmsStateError 返回 True（表示非法流转被正确拦截）"""
    with pytest.raises(CmsStateError):
        fn()
    return True


# 创建人 creator1 / 审核人 reviewer1 分开（第 7 周起创建人不能审核自己）
CREATOR = "creator1"
REVIEWER = "reviewer1"


def new_unit(uid, pinyin, operator=CREATOR, **kw):
    return database.create_unit({"id": uid, "pinyin": pinyin, **kw}, operator)


# ---------- 1. 建库与基础 ----------
def test_tables_created(db):
    conn = database._connect()
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    for t in ("audit_log", "admin_user", "admin_token", "unit_version_history"):
        assert t in tables, f"缺少表 {t}: {tables}"


# ---------- 2. 录入即草稿 ----------
def test_create_is_draft(db):
    new_unit("L01", "a", character="啊")
    assert database.get_unit("L01")["status"] == "draft"
    assert database.get_unit("L01")["version"] == 1
    assert all(x["id"] != "L01" for x in database.get_units("published"))
    # 即使请求体带 status=published，录入仍强制草稿
    new_unit("L02", "o", character="哦", status="published")
    assert database.get_unit("L02")["status"] == "draft"


# ---------- 3. 草稿编辑 + 版本递增 ----------
def test_edit_draft_and_version_bump(db):
    database.update_unit("L01", {"detail": "第一版内容"}, CREATOR)
    assert database.get_unit("L01")["detail"] == "第一版内容"
    assert database.get_unit("L01")["version"] == 2
    assert any(l["action"] == "update" for l in database.get_audit_logs("L01"))


# ---------- 4. 提交审核 ----------
def test_submit_review_flow(db):
    r = database.submit_review("L01", CREATOR)
    assert r["status"] == "pending_review"
    assert r["submitReviewTime"] is not None
    assert _raises(lambda: database.submit_review("L01", CREATOR))  # 不能重复提交
    assert _raises(lambda: database.update_unit("L01", {"detail": "x"}, CREATOR))  # 待审核禁编辑


# ---------- 5. 审核通过（审核人 ≠ 创建人） ----------
def test_approve_flow(db):
    r = database.approve_unit("L01", REVIEWER)
    assert r["status"] == "published"
    assert r["reviewer"] == REVIEWER and r["reviewTime"] is not None
    assert any(x["id"] == "L01" for x in database.get_units("published"))
    assert _raises(lambda: database.approve_unit("L01", REVIEWER))  # 已发布再通过
    assert _raises(lambda: database.approve_unit("L02", REVIEWER))  # 草稿直接通过
    assert _raises(lambda: database.update_unit("L01", {"detail": "x"}, CREATOR))  # 已发布禁编辑
    # 已发布单元允许单独切换检测开关字段（CON-04）
    r = database.update_unit("L01", {"verified": True}, CREATOR)
    assert r and database.get_unit("L01")["verified"] is True


# ---------- 6. 审核驳回 ----------
def test_reject_flow(db):
    assert _raises(lambda: database.reject_unit("L02", REVIEWER, ""))  # 驳回必须带原因
    database.submit_review("L02", CREATOR)
    r = database.reject_unit("L02", REVIEWER, "音标写错了")
    assert r["status"] == "rejected"
    assert r["reviewComment"] == "音标写错了"
    assert all(x["id"] != "L02" for x in database.get_units("published"))
    assert database.update_unit("L02", {"pinyin": "o"}, CREATOR) and True  # 驳回后可编辑
    # 重提：上一轮审核结论清空
    r = database.submit_review("L02", CREATOR)
    assert r["status"] == "pending_review"
    assert r["reviewComment"] is None and r["reviewer"] is None
    r = database.approve_unit("L02", REVIEWER)
    assert r["status"] == "published"
    assert _raises(lambda: database.reject_unit("L02", REVIEWER, "x"))  # 已发布不能驳回


# ---------- 7. 下架 ----------
def test_unpublish_flow(db):
    r = database.unpublish_unit("L01", REVIEWER)
    assert r["status"] == "draft"
    assert all(x["id"] != "L01" for x in database.get_units("published"))
    assert _raises(lambda: database.unpublish_unit("L01", REVIEWER))  # 草稿不能下架


# ---------- 8. 检测开关（任何状态可切换） ----------
def test_detection_switch(db):
    r = database.set_detection("L01", REVIEWER, True)
    assert r["verified"] is True
    r = database.set_detection("L01", REVIEWER, False)
    assert r["verified"] is False


# ---------- 9. 状态不能通过编辑接口直改 ----------
def test_status_change_via_edit_blocked(db):
    assert _raises(lambda: database.update_unit("L01", {"status": "published"}, CREATOR))


# ---------- 10. 不存在的单元 ----------
def test_missing_unit_handling(db):
    assert database.submit_review("L99", "tester") is None
    assert database.update_unit("L99", {"detail": "x"}, "tester") is False
    assert database.delete_unit("L99", "tester") is False


# ---------- 11. 操作日志链路 ----------
def test_audit_log_chain(db):
    logs = database.get_audit_logs("L01")
    actions = [x["action"] for x in logs]
    # get_audit_logs 返回倒序（最新在前），时间顺序应为：
    # create -> update(版本2) -> submit -> approve -> update(verified) -> unpublish
    #      -> set_detection(开) -> set_detection(关)
    assert actions[-8:] == ["set_detection", "set_detection", "unpublish", "update",
                            "approve", "submit_review", "update", "create"], str(actions)
    assert all(x["operator"] in (CREATOR, REVIEWER) for x in logs)
    assert any(x["action"] == "approve" and x["operator"] == REVIEWER for x in logs)
    reject_logs = database.get_audit_logs("L02")
    assert any(x["action"] == "reject" and "音标写错了" in x["remark"] for x in reject_logs)
    assert len(database.get_audit_logs(limit=3)) == 3


# ---------- 12. 删除落日志 ----------
def test_delete_logs(db):
    new_unit("ext1", "z", character="资")
    assert database.delete_unit("ext1", "tester") is True
    assert any(x["action"] == "delete" for x in database.get_audit_logs("ext1"))


# ---------- 13. 新字段（30 关正式字段口径） ----------
def test_new_fields_30(db):
    new_unit("L30", "mā", character="妈", demo_audio="/media/demo/L30.wav", practice=["跟读", "录音"])
    u = database.get_unit("L30")
    assert u["demoAudio"] == "/media/demo/L30.wav"
    assert u["practice"] == ["跟读", "录音"]
    assert "version" in u and "submitReviewTime" in u and "reviewComment" in u


# ---------- 14. 创建人不能审核自己（第 7 周 C，代码拦截） ----------
def test_creator_self_review_blocked(db):
    new_unit("L10", "x", operator="alice", character="西")
    assert database.get_unit("L10")["creator"] == "alice"
    database.submit_review("L10", "alice")
    assert _raises(lambda: database.approve_unit("L10", "alice"))  # 自己通过 -> 拦截
    r = database.approve_unit("L10", "bob")  # 换人审核 -> 放行
    assert r["status"] == "published" and r["reviewer"] == "bob"

    new_unit("L11", "sh", operator="alice", character="师")
    database.submit_review("L11", "alice")
    assert _raises(lambda: database.reject_unit("L11", "alice", "写错了"))  # 自己驳回 -> 拦截
    r = database.reject_unit("L11", "bob", "写错了")
    assert r["status"] == "rejected" and r["reviewer"] == "bob"


# ---------- 15. 版本历史快照（第 7 周 C，编辑留痕可追溯） ----------
def test_version_history_snapshots(db):
    vers = database.get_unit_versions("L01")  # 创建 v1 -> 编辑 v2 -> verified 编辑 v3
    assert [v["version"] for v in vers] == [1, 2, 3], vers
    assert vers[0]["reason"] == "创建" and vers[0]["snapshot"]["detail"] == ""
    assert vers[1]["snapshot"]["detail"] == "第一版内容"
    assert vers[2]["snapshot"]["detail"] == "第一版内容" and vers[2]["snapshot"]["verified"] is True
    assert all(v["operator"] == CREATOR for v in vers)
    assert database.get_unit_versions("L99") == []  # 不存在单元返回空


# ---------- 16. 管理员鉴权（database 层：密码/登录/token/改密） ----------
def test_admin_auth_db_level(db):
    assert database.verify_admin("admin", "wrong") is None
    user, disp = database.verify_admin("admin", "admin123")
    assert user == "admin" and disp == "管理员"
    token = database.issue_token("admin")
    assert database.token_to_user(token) == "admin"
    database.revoke_token(token)
    assert database.token_to_user(token) is None
    assert database.token_to_user("") is None
    assert database.token_to_user("bogus-token") is None
    assert database.change_password("admin", "wrong-old", "newpass123") is False
    assert database.change_password("admin", "admin123", "newpass123") is True
    assert database.verify_admin("admin", "admin123") is None
    assert database.verify_admin("admin", "newpass123") is not None
    database.change_password("admin", "newpass123", "admin123")  # 改回，供 HTTP 测试用


# ---------- 17. 管理员鉴权（HTTP 层：登录/401/登出） ----------
def test_admin_http_login_and_401(client):
    r = client.post("/api/admin/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401 and r.json()["code"] == 401
    # 未带 token 调 admin 接口 -> 401
    r = client.get("/api/admin/units")
    assert r.status_code == 401
    # 登录 -> 拿到 token -> 正常访问
    r = client.post("/api/admin/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    token = r.json()["data"]["token"]
    assert r.json()["data"]["username"] == "admin"
    r = client.get("/api/admin/units", headers={"X-Token": token})
    assert r.status_code == 200 and r.json()["code"] == 200
    r = client.get("/api/admin/units/L01/versions", headers={"X-Token": token})
    assert r.status_code == 200 and [v["version"] for v in r.json()["data"]] == [1, 2, 3]
    # 登出 -> token 吊销 -> 再访问 401
    client.post("/api/admin/logout", headers={"X-Token": token})
    r = client.get("/api/admin/units", headers={"X-Token": token})
    assert r.status_code == 401
