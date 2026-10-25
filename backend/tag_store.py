"""问题标签存储(CON-06 C 部分:标签分流规则草案的存储结构落地)

与 Z0 林愉钧的规则草案配套:C 负责「标签存哪、怎么关联」,规则内容由草案定。
三层结构:
- problem_tags       标签字典(维度/名称/说明/四步反馈模板引用/启停)
- unit_problem_tags  关卡 × 标签启用表(哪一关开放哪些标签,对应「错关推荐」)
- record_problem_tags 检测记录 × 标签分流结果(一次检测命中哪些标签及详情)

1.0 口径:反馈四步话术仍由 feedback_engine 规则模板产出,本表是结构化分流层,
供 2.0「错关推荐」「人审位」做数据基础;先建空表不播种,草案定稿后再批量录入。
本模块只依赖 stdlib + 已打开的 sqlite3 连接,建表由 database.init_db 调用。
"""
import sqlite3
import uuid
from datetime import datetime, timezone


def _now() -> str:
    """当前时间(ISO8601 UTC)"""
    return datetime.now(timezone.utc).isoformat()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS problem_tags (
            code TEXT PRIMARY KEY,                -- 稳定编码 如 t_nl_confusion(草案定稿前可暂用占位)
            dimension TEXT NOT NULL DEFAULT '',   -- 维度:声母/韵母/声调/流利度/录音质量
            name TEXT NOT NULL DEFAULT '',        -- 中文名:n/l 混淆
            description TEXT NOT NULL DEFAULT '', -- 判定说明
            feedback_template TEXT NOT NULL DEFAULT '',  -- 引用 feedback_engine 的四步反馈模板 id
            severity_default INTEGER NOT NULL DEFAULT 1, -- 默认严重度(可被单次检测覆盖)
            status TEXT NOT NULL DEFAULT 'active',       -- active / disabled(停用不参与分流)
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS unit_problem_tags (
            unit_id TEXT NOT NULL,                -- 发音单元 id(30 关/核心单元)
            tag_code TEXT NOT NULL,               -- 启用的问题标签
            enabled INTEGER NOT NULL DEFAULT 1,   -- 该关是否启用此标签
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            PRIMARY KEY (unit_id, tag_code)
        );

        CREATE TABLE IF NOT EXISTS record_problem_tags (
            id TEXT PRIMARY KEY,                  -- 一次检测记录命中的一个标签
            record_id TEXT NOT NULL,              -- 关联 learning_records.id
            tag_code TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',      -- 命中详情(检测值/置信度,JSON 或自由文本)
            severity INTEGER NOT NULL DEFAULT 1,  -- 本次严重度(可覆盖默认)
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_record_tags_record ON record_problem_tags(record_id);
        CREATE INDEX IF NOT EXISTS idx_record_tags_code ON record_problem_tags(tag_code);
        """
    )


# ---------------------------------------------------------------------------
# 标签字典 CRUD(草案期用于试录入;规则内容以 Z0 草案为准)
# ---------------------------------------------------------------------------
def list_tags(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM problem_tags ORDER BY code").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def upsert_tag(db_path: str, data: dict) -> str:
    """新增或更新标签字典项;返回 code"""
    code = (data.get("code") or "").strip()
    if not code:
        raise ValueError("code 不能为空")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO problem_tags
               (code, dimension, name, description, feedback_template, severity_default, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
               ON CONFLICT(code) DO UPDATE SET
                 dimension=excluded.dimension, name=excluded.name,
                 description=excluded.description, feedback_template=excluded.feedback_template,
                 severity_default=excluded.severity_default""",
            (
                code,
                data.get("dimension", ""),
                data.get("name", ""),
                data.get("description", ""),
                data.get("feedbackTemplate", "") or data.get("feedback_template", ""),
                int(data.get("severityDefault", data.get("severity_default", 1))),
                _now(),
            ),
        )
        conn.commit()
        return code
    finally:
        conn.close()


def set_unit_tag(db_path: str, unit_id: str, tag_code: str, enabled: bool = True) -> None:
    """关卡启用/停用某标签"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO unit_problem_tags (unit_id, tag_code, enabled, note, created_at)
               VALUES (?, ?, ?, '', ?)
               ON CONFLICT(unit_id, tag_code) DO UPDATE SET enabled=excluded.enabled""",
            (unit_id, tag_code, 1 if enabled else 0, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def add_record_tag(
    db_path: str,
    record_id: str,
    tag_code: str,
    detail: str = "",
    severity: int = 1,
) -> str:
    """检测分流结果落库:一次检测命中一个标签写一行"""
    tag_id = uuid.uuid4().hex
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO record_problem_tags (id, record_id, tag_code, detail, severity, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tag_id, record_id, tag_code, detail, int(severity), _now()),
        )
        conn.commit()
        return tag_id
    finally:
        conn.close()


def tags_for_record(db_path: str, record_id: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM record_problem_tags WHERE record_id = ? ORDER BY created_at",
            (record_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
