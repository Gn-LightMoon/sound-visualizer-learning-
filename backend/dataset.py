"""音乐学院发音数据集入库(第 8 周 C:六张表 + 文件名机器解析 + 批次导入)

对齐《发音数据集采集与标注规范》V3.0 + 《发现的问题清单》35 条:
- 六张表:recorders 录音人 / consents 同意书 / import_batches 导入批次 /
  samples 样本 / annotations 标注 / error_codes 错误码;
- 文件名必须机器可解析(问题#22):{单元}_{目标音}_{编号}_{遍数}_correct|error[_e码][_discard];
- 训练标签一律以标注表(annotations)为准,文件名只表示录制意图(问题#23);
- 同意书先签后录、第一批就交(问题#28);登记表含设备型号(问题#29,校准需统一设备);
- 声调不是音素:标注维度字段取名 error_dimension(问题#9);
- error_codes 的 applicable_units 沿用规范 7.3 原文(V3.1 修正单元名后再更新,问题#18)。

本模块只依赖 stdlib + 一个已打开的 sqlite3 连接,建表逻辑由 database.init_db 调用,
与 database.py 的既有风格一致(原生 sqlite3、snake_case 列、ISO8601 UTC 时间)。
"""
import json
import os
import re
import sqlite3
import uuid
import wave
from datetime import datetime, timezone


def _now() -> str:
    """当前时间(ISO8601 UTC)"""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 错误码字典(规范 7.3,第一批入库时播种;适用于错误样本与标注表「错在哪」列)
# ---------------------------------------------------------------------------
ERROR_CODES = [
    ("e1", "n 读成 l(鼻音变边音)", "舌尖轻触上齿龈不贴紧,气流从舌两侧流出,鼻腔不出气", ["n_l"]),
    ("e2", "l 读成 n(边音变鼻音)", "舌尖贴紧上齿龈,软腭下垂使气流进入鼻腔", ["n_l"]),
    ("e3", "平舌 z/c/s 读成翘舌 zh/ch/sh", "舌尖上卷抵住硬腭前部", ["z_zh"]),
    ("e4", "翘舌 zh/ch/sh 读成平舌 z/c/s", "舌尖放平抵住齿背,不上翘", ["z_zh"]),
    ("e5", "送气音读成不送气音", "发 p/t/k/q 时抑制气流,声带与气流同步启动", ["b_p", "d_t", "g_k", "j_q_x"]),
    ("e6", "不送气音读成送气音", "发 b/d/g/j 后增加送气,声带振动前气流先行", ["b_p", "d_t", "g_k", "j_q_x"]),
    ("e7", "ü 读成 u", "唇形放松,舌位后移", ["u_u"]),
    ("e8", "u 读成 ü", "唇形收紧更圆,舌位前移", ["u_u"]),
    ("e9", "声调调值不准", "调值偏离五度标记法标准(55/35/214/51)", []),
    ("e10", "j/q/x 舌面音读成 s/sh 舌尖音", "舌面音转为舌尖音", ["j_q_x"]),
]


# ---------------------------------------------------------------------------
# 建表(幂等,由 database.init_db 调用;老库升级即迁移,已有数据不丢)
# ---------------------------------------------------------------------------
def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS recorders (
            code TEXT PRIMARY KEY,                -- 录音人编号 S001,分配后不得变更(2.2)
            name TEXT NOT NULL DEFAULT '',        -- 姓名
            gender TEXT NOT NULL DEFAULT '',      -- 性别
            age_group TEXT NOT NULL DEFAULT '',   -- 年龄段
            dialect_background TEXT NOT NULL DEFAULT '',  -- 方言背景
            mandarin_level TEXT NOT NULL DEFAULT '',       -- 普通话等级(问题#30:第一批以此为准)
            equipment TEXT NOT NULL DEFAULT '',   -- 设备型号(问题#29:校准需统一设备)
            first_record_date TEXT NOT NULL DEFAULT '',    -- 首次录音日期
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS consents (
            id TEXT PRIMARY KEY,                  -- 知情同意书(问题#28:先签后录,第一批就交)
            recorder_code TEXT NOT NULL,          -- 对应录音人
            file_path TEXT NOT NULL DEFAULT '',   -- 如 S001_同意书_姓名.pdf
            signed_date TEXT NOT NULL DEFAULT '', -- 签署日期
            batch_id TEXT NOT NULL DEFAULT '',    -- 随哪个批次交付
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_consents_recorder ON consents(recorder_code);

        CREATE TABLE IF NOT EXISTS import_batches (
            id TEXT PRIMARY KEY,                  -- 导入批次 uuid
            name TEXT NOT NULL DEFAULT '',        -- 第一批_正确发音_20261115前
            phase INTEGER NOT NULL DEFAULT 1,     -- 第几批(1 校准 / 2 纠音训练)
            purpose TEXT NOT NULL DEFAULT 'calibration',  -- calibration / training
            source_dir TEXT NOT NULL DEFAULT '',  -- 交付目录
            expected_count INTEGER NOT NULL DEFAULT 0,    -- 应收条数(如 610)
            imported_count INTEGER NOT NULL DEFAULT 0,    -- 实际入库条数
            status TEXT NOT NULL DEFAULT 'importing',     -- importing / imported / partial
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS samples (
            id TEXT PRIMARY KEY,                  -- 一条音频一行
            file_name TEXT NOT NULL,              -- 完整文件名 b_p_ba1_S001_03_correct.wav
            unit TEXT NOT NULL DEFAULT '',        -- 单元名(问题#17/#18:单元≠目标音)
            target TEXT NOT NULL DEFAULT '',      -- 目标音 ba1(带声调数字)
            recorder_code TEXT NOT NULL DEFAULT '',  -- 录音人编号
            take_no INTEGER NOT NULL DEFAULT 0,   -- 第几遍
            intent TEXT NOT NULL DEFAULT 'correct',   -- 文件名意图(问题#23:标签以标注表为准)
            error_code TEXT NOT NULL DEFAULT '',  -- 文件名里的 e 码(正确录音为空)
            discarded INTEGER NOT NULL DEFAULT 0, -- 文件名带 _discard(问题#24:已废弃)
            batch_id TEXT NOT NULL DEFAULT '',
            file_path TEXT NOT NULL DEFAULT '',   -- 交付目录内相对路径
            duration REAL NOT NULL DEFAULT 0,     -- 秒(导入时读 WAV 头,非 WAV 为 0)
            sample_rate INTEGER NOT NULL DEFAULT 0,
            file_size INTEGER NOT NULL DEFAULT 0,
            quality TEXT NOT NULL DEFAULT '',     -- good/ok/bad(导入时取自标注表,便于筛选)
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_samples_batch ON samples(batch_id);
        CREATE INDEX IF NOT EXISTS idx_samples_target ON samples(target);

        CREATE TABLE IF NOT EXISTS annotations (
            id TEXT PRIMARY KEY,                  -- 标注表一行(8.1 节)
            sample_id TEXT NOT NULL,              -- 关联 samples.id(按文件名匹配)
            is_correct INTEGER,                   -- 听感对不对:1 对 / 0 错 / NULL 未填
                                                 -- (问题#24:爆音等质量问题时听感栏留空)
            error_code TEXT NOT NULL DEFAULT '',  -- 错在哪:e1-e10 或具体描述
            error_dimension TEXT NOT NULL DEFAULT '',  -- 错在哪个维度:声母/韵母/声调/无(问题#9)
            quality TEXT NOT NULL DEFAULT '',     -- good/ok/bad
            annotator TEXT NOT NULL DEFAULT '',   -- 标注人(问题#31:单人标注+抽检复核)
            annotate_date TEXT NOT NULL DEFAULT '',  -- YYYY-MM-DD
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_annotations_sample ON annotations(sample_id);

        CREATE TABLE IF NOT EXISTS error_codes (
            code TEXT PRIMARY KEY,                -- e1-e10(规范 7.3)
            name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            applicable_units TEXT NOT NULL DEFAULT '[]',  -- JSON 数组,适用单元名
            created_at TEXT NOT NULL
        );
        """
    )
    _seed_error_codes(conn)


def _seed_error_codes(conn: sqlite3.Connection) -> None:
    """幂等播种错误码字典(仅插入不存在的)"""
    now = _now()
    for code, name, desc, units in ERROR_CODES:
        exists = conn.execute("SELECT 1 FROM error_codes WHERE code = ?", (code,)).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO error_codes (code, name, description, applicable_units, created_at) VALUES (?, ?, ?, ?, ?)",
            (code, name, desc, json.dumps(units, ensure_ascii=False), now),
        )


# ---------------------------------------------------------------------------
# 文件名机器解析(问题#22:命名必须机器可解析,入库脚本的唯一解析入口)
# 正确:{单元}_{目标音}_{编号}_{遍数}_correct.wav
# 错误:{单元}_{目标音}_{编号}_{遍数}_error_{e码}.wav
# 废弃:…_correct_discard.wav / …_discard.wav(问题#24 两种写法都容忍)
# 兼容 8.3 的合并写法 error_e1(单段)。
# ---------------------------------------------------------------------------
def parse_dataset_filename(file_name: str) -> dict | None:
    stem = file_name
    if stem.lower().endswith(".wav"):
        stem = stem[:-4]
    parts = stem.split("_")
    if len(parts) < 5:  # 最少:单元_目标音_编号_遍数_correct = 5 段
        return None

    discarded = False
    if parts[-1].lower() == "discard":
        discarded = True
        parts.pop()

    last = parts[-1].lower()
    intent = ""
    error_code = ""
    if re.fullmatch(r"e\d+", last):  # 6 段拆分写法:…_error_e1 的 e1 段
        error_code = last
        parts.pop()
        if not parts or parts[-1].lower() != "error":
            return None
        intent = "error"
        parts.pop()
    elif re.fullmatch(r"error_e\d+", last):  # 8.3 合并写法 error_e1
        intent, error_code = "error", last[len("error_"):]
        parts.pop()
    elif last in ("correct", "error"):
        intent = last
        parts.pop()
    else:
        return None

    if len(parts) < 4:
        return None
    take_no, recorder, target = parts[-1], parts[-2], parts[-3]
    if not re.fullmatch(r"\d{2}", take_no):
        return None
    if not re.fullmatch(r"S\d+", recorder, re.IGNORECASE):
        return None
    if not re.fullmatch(r"[a-z]+\d", target):
        return None
    unit = "_".join(parts[:-3])
    if not unit:
        return None
    return {
        "unit": unit,
        "target": target,
        "recorder_code": recorder.upper(),
        "take_no": int(take_no),
        "intent": intent,
        "error_code": error_code,
        "discarded": discarded,
    }


def _wav_meta(file_path: str) -> tuple[float, int]:
    """读 WAV 头取时长(秒)与采样率;失败返回 (0, 0) 不阻断导入"""
    try:
        with wave.open(file_path, "rb") as w:
            frames, rate = w.getnframes(), w.getframerate()
            return (frames / rate if rate else 0.0, rate)
    except (wave.Error, OSError, EOFError):
        return (0.0, 0)


# ---------------------------------------------------------------------------
# 批次导入(CLI 与测试共用):目录扫描 → 文件名解析 → 登记表/标注表/同意书落库
# 幂等:同批次内同文件名跳过,可重复执行补录。
# ---------------------------------------------------------------------------
def _read_csv_rows(path: str) -> list[dict]:
    """读 CSV(utf-8-sig,Excel 存的中文表头可带 BOM);返回 [{"表头": 值}]"""
    import csv

    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items()})
    return rows


def _pick(row: dict, *keys: str) -> str:
    """按多个候选表头模糊取值(兼容 8.1 改名前后的表头)"""
    for key in keys:
        for header, value in row.items():
            if key in header:
                return value
    return ""


def _load_recorders(conn: sqlite3.Connection, path: str) -> int:
    count = 0
    for row in _read_csv_rows(path):
        code = _pick(row, "编号")
        if not re.fullmatch(r"S\d+", code or "", re.IGNORECASE):
            continue
        code = code.upper()
        conn.execute(
            """INSERT INTO recorders
               (code, name, gender, age_group, dialect_background, mandarin_level,
                equipment, first_record_date, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(code) DO UPDATE SET
                 name=excluded.name, gender=excluded.gender, age_group=excluded.age_group,
                 dialect_background=excluded.dialect_background, mandarin_level=excluded.mandarin_level,
                 equipment=excluded.equipment, first_record_date=excluded.first_record_date""",
            (
                code,
                _pick(row, "姓名"),
                _pick(row, "性别"),
                _pick(row, "年龄"),
                _pick(row, "方言"),
                _pick(row, "普通话", "等级"),
                _pick(row, "设备"),
                _pick(row, "首次", "日期"),
                _pick(row, "备注"),
                _now(),
            ),
        )
        count += 1
    return count


def _load_consents(conn: sqlite3.Connection, consent_dir: str, batch_id: str) -> int:
    """扫描同意书目录(文件名 S001_同意书_*.pdf),未签的录音人不拦截但可查缺口"""
    count = 0
    if not os.path.isdir(consent_dir):
        return 0
    for name in sorted(os.listdir(consent_dir)):
        m = re.match(r"(S\d+)_同意书", name, re.IGNORECASE)
        if not m:
            continue
        conn.execute(
            "INSERT INTO consents (id, recorder_code, file_path, signed_date, batch_id, note, created_at)"
            " VALUES (?, ?, ?, '', ?, ?, ?)",
            (uuid.uuid4().hex, m.group(1).upper(), name, batch_id, "导入时登记,签署日期待补录", _now()),
        )
        count += 1
    return count


def _load_annotations(conn: sqlite3.Connection, path: str, samples_by_file: dict) -> dict:
    """标注表落库:按文件名关联样本;训练标签以本表为准(问题#23)"""
    imported = 0
    orphans = []
    annotated_files = set()
    for row in _read_csv_rows(path):
        file_name = _pick(row, "文件名")
        annotated_files.add(file_name)
        sample_id = samples_by_file.get(file_name)
        if sample_id is None:
            orphans.append(file_name)
            continue
        is_correct = None
        verdict = _pick(row, "听感", "对不对")
        if verdict in ("✅", "对", "正确", "1", "yes", "Yes"):
            is_correct = 1
        elif verdict in ("❌", "错", "错误", "0", "no", "No"):
            is_correct = 0
        quality = _pick(row, "质量", "录音质量").lower()
        if quality not in ("good", "ok", "bad"):
            quality = ""
        conn.execute(
            """INSERT INTO annotations
               (id, sample_id, is_correct, error_code, error_dimension, quality,
                annotator, annotate_date, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                uuid.uuid4().hex,
                sample_id,
                is_correct,
                _pick(row, "错在哪", "错误类型"),
                _pick(row, "哪个音素", "维度"),
                quality,
                _pick(row, "标注人"),
                _pick(row, "标注日期", "日期"),
                _pick(row, "备注"),
                _now(),
            ),
        )
        if quality:  # 顺手回填样本的 quality,便于按可用性筛选
            conn.execute("UPDATE samples SET quality = ? WHERE id = ?", (quality, sample_id))
        imported += 1
    return {"imported": imported, "orphans": orphans, "files": annotated_files}


def import_dataset(
    source_dir: str,
    db_path: str,
    batch_name: str = "",
    phase: int = 1,
    purpose: str = "calibration",
    annotation_csv: str = "",
    recorder_csv: str = "",
    consent_dir: str = "",
    dry_run: bool = False,
) -> dict:
    """执行一次批次导入,返回报告 dict(不抛异常;单文件解析失败进 unparseable)。

    幂等口径:同一 (batch_id, file_name) 不重复入库,可反复执行补漏。
    """
    report = {
        "batch_name": batch_name,
        "files_found": 0,
        "imported": 0,
        "skipped_dup": 0,
        "unparseable": [],
        "missing_annotation": [],
        "annotation_imported": 0,
        "orphan_annotations": [],
        "recorder_imported": 0,
        "consent_imported": 0,
        "dry_run": dry_run,
    }
    if not os.path.isdir(source_dir):
        report["error"] = f"目录不存在:{source_dir}"
        return report

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_schema(conn)
        now = _now()
        # 批次 id 由参数确定性生成:同一目录+批次名重跑 = 同一个批次,
        # 样本按 (batch_id, file_name) 幂等,补漏重跑不会新建批次(CLI 反复执行安全)。
        batch_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{batch_name}|{phase}|{purpose}|{os.path.abspath(source_dir)}",
        ).hex
        if dry_run:
            conn.rollback()  # dry-run 不落库:后面所有写入都在未提交事务里,回滚丢弃
        else:
            conn.execute("BEGIN")
        conn.execute(
            """INSERT INTO import_batches
               (id, name, phase, purpose, source_dir, expected_count, imported_count, status, note, created_at)
               VALUES (?, ?, ?, ?, ?, 0, 0, 'importing', '', ?)
               ON CONFLICT(id) DO UPDATE SET source_dir=excluded.source_dir""",
            (batch_id, batch_name, phase, purpose, os.path.abspath(source_dir), now),
        )

        wav_files = []
        for root, _dirs, files in os.walk(source_dir):
            for name in sorted(files):
                if name.lower().endswith(".wav"):
                    wav_files.append(os.path.join(root, name))
        report["files_found"] = len(wav_files)

        samples_by_file = {}
        for full_path in wav_files:
            rel = os.path.relpath(full_path, source_dir).replace(os.sep, "/")
            file_name = os.path.basename(rel)
            parsed = parse_dataset_filename(file_name)
            if parsed is None:
                report["unparseable"].append(rel)
                continue
            exists = conn.execute(
                "SELECT 1 FROM samples WHERE batch_id = ? AND file_name = ?",
                (batch_id, file_name),
            ).fetchone()
            if exists:
                report["skipped_dup"] += 1
                continue
            duration, sample_rate = _wav_meta(full_path)
            sample_id = uuid.uuid4().hex
            conn.execute(
                """INSERT INTO samples
                   (id, file_name, unit, target, recorder_code, take_no, intent, error_code,
                    discarded, batch_id, file_path, duration, sample_rate, file_size, quality, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)""",
                (
                    sample_id, file_name, parsed["unit"], parsed["target"],
                    parsed["recorder_code"], parsed["take_no"], parsed["intent"],
                    parsed["error_code"], 1 if parsed["discarded"] else 0,
                    batch_id, rel, duration, sample_rate,
                    os.path.getsize(full_path), now,
                ),
            )
            samples_by_file[file_name] = sample_id
            report["imported"] += 1

        if recorder_csv:
            report["recorder_imported"] = _load_recorders(conn, recorder_csv)
        if consent_dir:
            report["consent_imported"] = _load_consents(conn, consent_dir, batch_id)
        if annotation_csv:
            ann = _load_annotations(conn, annotation_csv, samples_by_file)
            report["annotation_imported"] = ann["imported"]
            report["orphan_annotations"] = ann["orphans"]
            report["missing_annotation"] = [
                f for f in sorted(samples_by_file) if f not in ann["files"]
            ]

        conn.execute(
            "UPDATE import_batches SET imported_count = ?, status = ? WHERE id = ?",
            (report["imported"], "partial" if report["unparseable"] else "imported", batch_id),
        )
        if not dry_run:
            conn.commit()
        report["batch_id"] = batch_id
        return report
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 查询接口(CMS 浏览 / 汇报口径用,由 dataset_routes 暴露)
# ---------------------------------------------------------------------------
def list_batches(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM import_batches ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_recorders(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM recorders ORDER BY code").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_samples(db_path: str, batch_id: str, limit: int = 200) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM samples WHERE batch_id = ? ORDER BY file_name LIMIT ?",
            (batch_id, max(1, min(limit, 1000))),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_annotations(db_path: str, sample_id: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM annotations WHERE sample_id = ? ORDER BY created_at", (sample_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def dataset_summary(db_path: str) -> dict:
    """汇报口径:批次/样本/标注/录音人/同意书/错误码 六项计数"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        one = lambda sql, args=(): conn.execute(sql, args).fetchone()[0]  # noqa: E731
        return {
            "batches": one("SELECT COUNT(*) FROM import_batches"),
            "samples": one("SELECT COUNT(*) FROM samples"),
            "annotations": one("SELECT COUNT(*) FROM annotations"),
            "recorders": one("SELECT COUNT(*) FROM recorders"),
            "consents": one("SELECT COUNT(*) FROM consents"),
            "errorCodes": one("SELECT COUNT(*) FROM error_codes"),
        }
    finally:
        conn.close()
