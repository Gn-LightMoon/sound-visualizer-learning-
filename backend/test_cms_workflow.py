# test_cms_workflow.py
# C 角色第 6 周自测脚本（迁移 week4 版本到仓库 sqlite3 基线上）
# 覆盖：录入即草稿 -> 编辑(版本递增) -> 提交审核 -> 通过/驳回 -> 驳回后修改重提
#      -> 下架 -> 检测开关 -> 全部非法流转拦截 -> 操作日志链路。
# 只依赖 database.py（不 import main.py，因此不需要 torch/librosa）。
# 运行方式：cd backend && python test_cms_workflow.py
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database  # noqa: E402
from database import CmsStateError  # noqa: E402

# 用独立临时库，跑完即删，绝不污染开发库 pronunciation.db
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
TEST_DB = _tmp.name
database.DB_PATH = TEST_DB
database.init_db(TEST_DB)

passed = 0


def _raises(fn) -> bool:
    """执行 fn，若抛出 CmsStateError 返回 True（表示非法流转被正确拦截）"""
    try:
        fn()
    except CmsStateError:
        return True
    return False


def check(name: str, condition: bool, extra: str = ""):
    global passed
    assert condition, f"[FAIL] {name} {extra}"
    passed += 1
    print(f"[PASS] {name}")


def new_unit(uid, pinyin, **kw):
    return database.create_unit({"id": uid, "pinyin": pinyin, **kw}, "tester")


# ---------- 1. 建库与基础 ----------
conn = database._connect()
tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
conn.close()
check("audit_log 表已创建", "audit_log" in tables, str(tables))

u1 = new_unit("L01", "a", character="啊")
check("录入即草稿", database.get_unit("L01")["status"] == "draft")
check("新单元版本号为 1", database.get_unit("L01")["version"] == 1)
check("草稿不出现在 published 列表", all(x["id"] != "L01" for x in database.get_units("published")))

# 即使请求体带 status=published，录入仍强制草稿
new_unit("L02", "o", character="哦", status="published")
check("录入强制草稿（带published也无效）", database.get_unit("L02")["status"] == "draft")

# ---------- 2. 草稿编辑 + 版本递增 ----------
database.update_unit("L01", {"detail": "第一版内容"}, "tester")
check("草稿可编辑", database.get_unit("L01")["detail"] == "第一版内容")
check("编辑后版本递增到 2", database.get_unit("L01")["version"] == 2)
check("update 记录在案", any(
    l["action"] == "update" for l in database.get_audit_logs("L01")))

# ---------- 3. 提交审核 ----------
r = database.submit_review("L01", "tester")
check("提交审核 -> pending_review", r["status"] == "pending_review")
check("提交时间已记录", r["submitReviewTime"] is not None)
check("提交后不能重复提交", _raises(lambda: database.submit_review("L01", "tester")))
check("待审核状态禁止编辑", _raises(lambda: database.update_unit("L01", {"detail": "x"}, "tester")))

# ---------- 4. 审核通过 ----------
r = database.approve_unit("L01", "tester")
check("审核通过 -> published", r["status"] == "published")
check("审核人与时间已记录", r["reviewer"] == "tester" and r["reviewTime"] is not None)
check("发布后出现在 published 列表", any(x["id"] == "L01" for x in database.get_units("published")))
check("已发布再通过 -> 拦截", _raises(lambda: database.approve_unit("L01", "tester")))
check("草稿直接通过 -> 拦截", _raises(lambda: database.approve_unit("L02", "tester")))
check("已发布内容禁止编辑", _raises(lambda: database.update_unit("L01", {"detail": "x"}, "tester")))

# 已发布单元允许单独切换检测开关字段（CON-04）
r = database.update_unit("L01", {"verified": True}, "tester")
check("已发布可单独切换 verified（内容字段未动）", r and database.get_unit("L01")["verified"] is True)

# ---------- 5. 审核驳回 ----------
check("驳回必须带原因", _raises(lambda: database.reject_unit("L02", "tester", "")))
# L02 先提交再驳回
database.submit_review("L02", "tester")
r = database.reject_unit("L02", "tester", "音标写错了")
check("驳回 -> rejected", r["status"] == "rejected")
check("驳回原因已保存", r["reviewComment"] == "音标写错了")
check("驳回内容不出现在 published", all(x["id"] != "L02" for x in database.get_units("published")))
check("驳回后可编辑", database.update_unit("L02", {"pinyin": "o"}, "tester") and True)

# 重提：上一轮审核结论清空
r = database.submit_review("L02", "tester")
check("驳回后重提回到 pending", r["status"] == "pending_review")
check("重提清空旧审核结论", r["reviewComment"] is None and r["reviewer"] is None)
r = database.approve_unit("L02", "tester")
check("重审通过", r["status"] == "published")
check("已发布不能驳回", _raises(lambda: database.reject_unit("L02", "tester", "x")))

# ---------- 6. 下架 ----------
r = database.unpublish_unit("L01", "tester")
check("下架 -> draft", r["status"] == "draft")
check("下架后大众端不可见", all(x["id"] != "L01" for x in database.get_units("published")))
check("草稿状态不能下架", _raises(lambda: database.unpublish_unit("L01", "tester")))

# ---------- 7. 检测开关（任何状态可切换） ----------
r = database.set_detection("L01", "tester", True)
check("草稿也可切换检测开关", r["verified"] is True)
r = database.set_detection("L01", "tester", False)
check("检测开关可关闭", r["verified"] is False)

# ---------- 8. 状态不能通过编辑接口直改 ----------
check(
    "编辑接口直改状态 -> 拦截",
    _raises(lambda: database.update_unit("L01", {"status": "published"}, "tester")),
)

# ---------- 9. 不存在的单元 ----------
check("不存在的单元提交审核返回 None", database.submit_review("L99", "tester") is None)
check("不存在的单元编辑返回 False", database.update_unit("L99", {"detail": "x"}, "tester") is False)
check("不存在的单元删除返回 False", database.delete_unit("L99", "tester") is False)

# ---------- 10. 操作日志链路 ----------
logs = database.get_audit_logs("L01")
actions = [x["action"] for x in logs]
# get_audit_logs 返回倒序（最新在前），时间顺序应为：
# create -> update(版本2) -> submit -> approve -> update(verified) -> unpublish
#      -> set_detection(开) -> set_detection(关)
check(
    "L01 日志链完整且有序",
    actions[-8:] == ["set_detection", "set_detection", "unpublish", "update",
                     "approve", "submit_review", "update", "create"],
    str(actions),
)
check("日志操作人记录正确", all(x["operator"] == "tester" for x in logs))
reject_logs = database.get_audit_logs("L02")
check("驳回日志带原因", any(
    x["action"] == "reject" and "音标写错了" in x["remark"] for x in reject_logs))
check("日志可按 limit 截断", len(database.get_audit_logs(limit=3)) == 3)

# ---------- 11. 删除落日志 ----------
new_unit("ext1", "z", character="资")
check("删除扩展单元成功", database.delete_unit("ext1", "tester") is True)
check("删除有日志", any(x["action"] == "delete" for x in database.get_audit_logs("ext1")))

# ---------- 12. 新字段（30 关正式字段口径） ----------
new_unit("L30", "mā", character="妈", demo_audio="/media/demo/L30.wav", practice=["跟读", "录音"])
u = database.get_unit("L30")
check("demoAudio 字段入库", u["demoAudio"] == "/media/demo/L30.wav")
check("practice 字段入库", u["practice"] == ["跟读", "录音"])
check("版本/审核字段都在返回结构中",
      "version" in u and "submitReviewTime" in u and "reviewComment" in u)

os.remove(TEST_DB)
print(f"\n全部自测通过：{passed} 个检查点。")
