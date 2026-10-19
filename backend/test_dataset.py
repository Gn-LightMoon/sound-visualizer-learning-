# test_dataset.py
# C 角色第 8 周自测（pytest 版，交 H 跑回归）
# 覆盖：音乐学院六张表建表 + 错误码播种 + 文件名机器解析
#      + 批次导入闭环（登记表/标注表/同意书）+ 幂等 + dry-run 不落库
#      + 问题标签三层存储（CON-06 C 部分）+ 数据集浏览接口鉴权。
# 只依赖 database.py / dataset.py / tag_store.py / dataset_routes.py
# （不 import main.py，因此不需要 torch/librosa）。
# 运行方式：cd backend && python -m pytest test_dataset.py -v
import csv
import os
import sys
import tempfile
import wave
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database  # noqa: E402
import dataset  # noqa: E402
import tag_store  # noqa: E402


@pytest.fixture(scope="module")
def db():
    """独立临时库：跑完即删，绝不污染开发库 pronunciation.db"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database.DB_PATH = tmp.name
    database.init_db(tmp.name)
    yield tmp.name
    os.remove(tmp.name)


def _write_wav(path: Path, seconds: float = 1.0, rate: int = 16000) -> None:
    """生成一条最短有效 WAV（静音），供 wave 头解析与文件扫描使用"""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * frames)


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


# ---------- 1. 六张表建表 + 错误码播种 ----------
def test_dataset_tables_created(db):
    conn = database._connect()
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    for t in ("recorders", "consents", "import_batches", "samples", "annotations", "error_codes"):
        assert t in tables, f"缺少表 {t}: {tables}"


def test_error_codes_seeded(db):
    conn = database._connect()
    rows = conn.execute("SELECT code FROM error_codes ORDER BY code").fetchall()
    conn.close()
    codes = [r["code"] for r in rows]
    assert sorted(codes, key=lambda c: int(c[1:])) == [f"e{i}" for i in range(1, 11)], f"错误码字典不符: {codes}"


def test_tag_tables_created(db):
    conn = database._connect()
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    for t in ("problem_tags", "unit_problem_tags", "record_problem_tags"):
        assert t in tables, f"缺少表 {t}: {tables}"


# ---------- 2. 文件名机器解析（问题#22） ----------
@pytest.mark.parametrize(
    "name,expected",
    [
        ("b_p_ba1_S001_03_correct.wav",
         {"unit": "b_p", "target": "ba1", "recorder_code": "S001", "take_no": 3,
          "intent": "correct", "error_code": "", "discarded": False}),
        ("ma_tone_ma3_S002_07_correct.wav",
         {"unit": "ma_tone", "target": "ma3", "recorder_code": "S002", "take_no": 7,
          "intent": "correct", "error_code": "", "discarded": False}),
        ("n_l_na1_S001_05_error_e1.wav",
         {"unit": "n_l", "target": "na1", "recorder_code": "S001", "take_no": 5,
          "intent": "error", "error_code": "e1", "discarded": False}),
        # 8.3 合并写法 error_e1（单段）
        ("n_l_la1_S001_02_error_e1.wav",
         {"unit": "n_l", "target": "la1", "recorder_code": "S001", "take_no": 2,
          "intent": "error", "error_code": "e1", "discarded": False}),
        # 问题#24 的 correct_discard 与裸 discard 两种写法
        ("ba_ba1_S001_05_correct_discard.wav",
         {"unit": "ba", "target": "ba1", "recorder_code": "S001", "take_no": 5,
          "intent": "correct", "error_code": "", "discarded": True}),
        ("a_a1_S001_01_correct.wav",
         {"unit": "a", "target": "a1", "recorder_code": "S001", "take_no": 1,
          "intent": "correct", "error_code": "", "discarded": False}),
    ],
)
def test_parse_ok(name, expected):
    assert dataset.parse_dataset_filename(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "abc.wav",                        # 完全无关
        "b_p_ba1_S001_02.wav",            # 缺结果段
        "b_p_ba1_张三_02_correct.wav",     # 录音人编号不合法
        "b_p_ba1_S001_2_correct.wav",     # 遍数不是两位数
        "ma1_S001_01_correct.wav",        # 缺单元段
        "b_p_ba_S001_01_correct.wav",     # 目标音缺声调数字
    ],
)
def test_parse_bad(name):
    assert dataset.parse_dataset_filename(name) is None


# ---------- 3. 批次导入闭环 + 幂等 + dry-run ----------
@pytest.fixture(scope="module")
def delivery(tmp_path_factory):
    """模拟规范第九章的交付目录：S001 子目录 + 登记表/标注表/同意书"""
    root = tmp_path_factory.mktemp("delivery")
    wavs = [
        "b_p_ba1_S001_01_correct.wav",
        "b_p_pa1_S001_02_error_e6.wav",
        "n_l_na1_S001_02_error_e1.wav",
        "ma_tone_ma3_S001_01_correct.wav",
        "bad_name.wav",  # 无法解析，应进 unparseable
    ]
    for name in wavs:
        _write_wav(root / "S001" / name)
    _write_csv(
        root / "录音人登记表.csv",
        ["编号", "姓名", "性别", "年龄段", "方言背景", "普通话等级", "设备型号", "首次录音日期"],
        [["S001", "张三", "女", "20-30", "无", "一级乙等", "USB电容麦A", "2026-11-01"]],
    )
    _write_csv(
        root / "标注表.csv",
        ["文件名", "录音人编号", "单元", "目标音", "第几遍", "听感对不对", "错在哪",
         "错在哪个维度", "录音质量", "标注人", "标注日期", "备注"],
        [
            ["b_p_ba1_S001_01_correct.wav", "S001", "b_p", "ba1", "01", "✅", "", "无", "good", "张老师", "2026-11-02", ""],
            ["b_p_pa1_S001_02_error_e6.wav", "S001", "b_p", "pa1", "02", "❌", "e6", "声母", "good", "张老师", "2026-11-02", ""],
            ["n_l_na1_S001_02_error_e1.wav", "S001", "n_l", "na1", "02", "❌", "e1", "声母", "bad", "张老师", "2026-11-02", "爆音"],
            # ma_tone 行故意不标 → 进 missing_annotation
            # 标注了但目录里没有的 → 进 orphan_annotations
            ["z_zh_zha1_S002_01_correct.wav", "S002", "z_zh", "zha1", "01", "✅", "", "无", "good", "李老师", "2026-11-03", ""],
        ],
    )
    (root / "知情同意书").mkdir()
    (root / "知情同意书" / "S001_同意书_张三.pdf").write_bytes(b"%PDF fake")
    return root


def test_import_round_trip(db, delivery):
    report = dataset.import_dataset(
        source_dir=str(delivery),
        db_path=db,
        batch_name="第一批_正确发音",
        phase=1,
        purpose="calibration",
        annotation_csv=str(delivery / "标注表.csv"),
        recorder_csv=str(delivery / "录音人登记表.csv"),
        consent_dir=str(delivery / "知情同意书"),
    )
    assert report["files_found"] == 5
    assert report["imported"] == 4, report
    assert report["unparseable"] == ["S001/bad_name.wav"], report
    assert report["annotation_imported"] == 3, report
    assert report["missing_annotation"] == ["ma_tone_ma3_S001_01_correct.wav"], report
    assert report["orphan_annotations"] == ["z_zh_zha1_S002_01_correct.wav"], report
    assert report["recorder_imported"] == 1
    assert report["consent_imported"] == 1

    conn = database._connect()
    sample = conn.execute(
        "SELECT * FROM samples WHERE file_name = 'b_p_ba1_S001_01_correct.wav'"
    ).fetchone()
    assert sample is not None
    assert sample["unit"] == "b_p" and sample["target"] == "ba1"
    assert sample["take_no"] == 1 and sample["intent"] == "correct"
    assert sample["quality"] == "good"  # 标注表回填
    assert sample["duration"] > 0 and sample["sample_rate"] == 16000  # WAV 头解析
    # 错误样本的 e 码与丢弃标记
    err = conn.execute(
        "SELECT * FROM samples WHERE file_name = 'b_p_pa1_S001_02_error_e6.wav'"
    ).fetchone()
    assert err["intent"] == "error" and err["error_code"] == "e6"
    # 标注行关联与听感结论（问题#23：以标注表为准）
    ann = conn.execute(
        "SELECT * FROM annotations WHERE sample_id = ?", (sample["id"],)
    ).fetchone()
    assert ann["is_correct"] == 1 and ann["error_dimension"] == "无"
    bad_ann = conn.execute(
        """SELECT a.* FROM annotations a JOIN samples s ON a.sample_id = s.id
           WHERE s.file_name = 'n_l_na1_S001_02_error_e1.wav'"""
    ).fetchone()
    assert bad_ann["error_code"] == "e1" and bad_ann["quality"] == "bad"
    # 批次计数与状态
    batch = conn.execute("SELECT * FROM import_batches WHERE id = ?", (report["batch_id"],)).fetchone()
    assert batch["imported_count"] == 4 and batch["status"] == "partial"  # 有 unparseable → partial
    conn.close()


def test_import_idempotent(db, delivery):
    first = dataset.import_dataset(source_dir=str(delivery), db_path=db, batch_name="第一批")
    second = dataset.import_dataset(source_dir=str(delivery), db_path=db, batch_name="第一批")
    assert second["imported"] == 0
    assert second["skipped_dup"] == first["imported"]
    # 同批次同文件名只有一行样本(不同批次允许同名:第二批含第一批的 correct 基线)
    conn = database._connect()
    count = conn.execute(
        "SELECT COUNT(*) FROM samples WHERE file_name = ? AND batch_id = ?",
        ("b_p_ba1_S001_01_correct.wav", second["batch_id"]),
    ).fetchone()[0]
    conn.close()
    assert count == 1


def test_import_dry_run(db, delivery):
    before = dataset.dataset_summary(db)["batches"]
    report = dataset.import_dataset(source_dir=str(delivery), db_path=db, batch_name="dry", dry_run=True)
    assert report["imported"] > 0
    assert dataset.dataset_summary(db)["batches"] == before  # 批次未落库


# ---------- 4. 问题标签三层存储（CON-06 C 部分） ----------
def test_tag_store_round_trip(db):
    tag_store.upsert_tag(db, {
        "code": "t_nl_confusion", "dimension": "声母", "name": "n/l 混淆",
        "description": "n 鼻音与 l 边音互混", "feedbackTemplate": "rule_nl",
    })
    tag_store.set_unit_tag(db, "L01", "t_nl_confusion", enabled=True)
    tag_store.add_record_tag(db, "rec_demo", "t_nl_confusion", detail="detected l, expected n", severity=2)

    tags = tag_store.list_tags(db)
    assert [t["code"] for t in tags] == ["t_nl_confusion"]
    assert tags[0]["dimension"] == "声母"

    hit = tag_store.tags_for_record(db, "rec_demo")
    assert len(hit) == 1
    assert hit[0]["tag_code"] == "t_nl_confusion" and hit[0]["severity"] == 2

    # upsert 幂等：同 code 更新不重复
    tag_store.upsert_tag(db, {"code": "t_nl_confusion", "name": "n/l 混淆(改)"})
    assert len(tag_store.list_tags(db)) == 1
    assert tag_store.list_tags(db)[0]["name"] == "n/l 混淆(改)"


# ---------- 5. 数据集浏览接口（鉴权 + 汇报口径） ----------
@pytest.fixture(scope="module")
def client(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import cms_routes
    import dataset_routes

    app = FastAPI()
    app.include_router(cms_routes.router)
    app.include_router(dataset_routes.router)
    with TestClient(app) as c:
        yield c


def _login(client) -> str:
    r = client.post("/api/admin/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["data"]["token"]


def test_dataset_routes_require_auth(client):
    assert client.get("/api/admin/dataset/summary").status_code == 401


def test_dataset_routes_with_token(client, delivery):
    token = _login(client)
    headers = {"X-Token": token}
    r = client.get("/api/admin/dataset/summary", headers=headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["recorders"] >= 1 and data["consents"] >= 1 and data["errorCodes"] == 10
    r = client.get("/api/admin/dataset/batches", headers=headers)
    assert r.status_code == 200 and len(r.json()["data"]) >= 1
    batch_id = r.json()["data"][0]["id"]
    r = client.get(f"/api/admin/dataset/batches/{batch_id}/samples", headers=headers)
    assert r.status_code == 200 and len(r.json()["data"]) >= 1
