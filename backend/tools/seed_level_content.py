#!/usr/bin/env python3
"""
30 关 L01–L30 教学内容播种脚本（第 8 周 D：内容补齐）
=================================================================

为什么需要它
------------
第 4 周的 seed_levels_30.py 只把 30 关的「身份」（ID / 顺序 / 目标音 / 例字）写进 CMS，
教学字段（conclusion / detail / steps / mistakes / practice）全部留空。
这意味着：C 只要把某一关从 draft 发布成 published，关卡页（P08）就会立刻出现
「跟着读 → 这一关还没有内容」「容易读错的地方 → 这一关还没有内容」两张空卡片 ——
正好撞上排期第 8 周的红线「已发布关必须完整（少发布可以，空卡片 / 假分不行）」。

本脚本按 backend/tools/level_content.json 把 30 关的教学内容补齐，**只写草稿**：
* 不发布、不改审核状态、不打开检测开关（status / verified 一律保持原值）；
* 内容由 D 起草，待 I（音乐学院内容）审校、C 走 CMS 审核后才允许发布；
* 复用 C 的 database.update_unit，因此版本号自动 +1、操作日志自动可追溯。

数据流
------
    backend/tools/level_content.json   ← 教学内容（唯一真源，改内容只改这个文件）
    src/data/levels.freeze.json        ← 关卡身份（CON-02 冻结，脚本只读）
        ↓  seed_level_content.py
    pronunciation_units（draft）        ← 复用 database.update_unit

用法
----
    # 预览（不写库，逐关打印内容摘要与校验结果）
    python backend/tools/seed_level_content.py --dry-run

    # 写入（默认自动定位后端真正使用的库 backend/pronunciation.db）
    python backend/tools/seed_level_content.py

    # 指定库 / 覆盖已有内容
    python backend/tools/seed_level_content.py --db backend/pronunciation.db --force
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TOOLS_DIR.parent
PROJECT_DIR = BACKEND_DIR.parent
FREEZE_JSON = PROJECT_DIR / "src" / "data" / "levels.freeze.json"
CONTENT_JSON = TOOLS_DIR / "level_content.json"

sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(TOOLS_DIR))
import database  # noqa: E402  （复用 C 的数据访问层）
from seed_levels_30 import pick_db_path  # noqa: E402  （复用同一套选库口径）

OPERATOR = "D-Jian"
# 只有这些状态允许改内容（与 database.EDITABLE_STATUSES 一致；发布/待审核一律不碰）
EDITABLE_STATUSES = {"draft", "rejected"}


def load_json(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"[错误] 找不到文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate(freeze: dict, content: dict) -> list[str]:
    """自检：内容必须覆盖且只覆盖冻结表的 30 关，且每关字段齐全"""
    frozen = [lv["code"] for lv in freeze["levels"]]
    levels = content.get("levels", {})
    codes = list(levels.keys())

    errors: list[str] = []
    missing = [c for c in frozen if c not in levels]
    extra = [c for c in codes if c not in frozen]
    if missing:
        errors.append(f"缺少关卡内容：{', '.join(missing)}")
    if extra:
        errors.append(f"多出冻结表以外的关卡：{', '.join(extra)}")
    if frozen != [f"L{i:02d}" for i in range(1, 31)]:
        errors.append("冻结表 ID 不是连续的 L01–L30（CON-02 口径）")

    for code, item in levels.items():
        if not str(item.get("conclusion", "")).strip():
            errors.append(f"{code} 缺 conclusion（一句话发音要点）")
        if not str(item.get("detail", "")).strip():
            errors.append(f"{code} 缺 detail（口型 / 提示）")
        if len(item.get("steps") or []) < 3:
            errors.append(f"{code} 的 steps 少于 3 步")
        if not item.get("mistakes"):
            errors.append(f"{code} 缺 mistakes（容易读错的地方）")
        if not item.get("practice"):
            errors.append(f"{code} 缺 practice（跟读词例）")
        for step in item.get("steps") or []:
            if not (str(step.get("title", "")).strip() or str(step.get("text", "")).strip()):
                errors.append(f"{code} 有空的练习步骤")
        for m in item.get("mistakes") or []:
            if not (str(m.get("title", "")).strip() or str(m.get("text", "")).strip()):
                errors.append(f"{code} 有空的知识误区")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="30 关教学内容 → CMS 草稿（第 8 周 D 内容补齐）")
    parser.add_argument("--db", help="SQLite 文件路径（默认自动定位后端使用的库）")
    parser.add_argument("--dry-run", action="store_true", help="只校验并打印，不写库")
    parser.add_argument("--force", action="store_true", help="已有内容的关也重新写入（版本 +1）")
    args = parser.parse_args()

    freeze = load_json(FREEZE_JSON)
    content = load_json(CONTENT_JSON)
    errors = validate(freeze, content)
    if errors:
        print("[校验失败] 内容表不完整，未写库：")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"[校验] 通过：{len(content['levels'])} 关内容齐全（conclusion / detail / steps≥3 / mistakes / practice）")
    print(f"[来源] {content.get('source', '（未标注）')}")

    db_path = pick_db_path(args.db)
    print(f"[数据库] {db_path}")

    database.init_db(db_path)  # 幂等：确保表存在（老库会自动补 CMS 列）
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    written = skipped = protected = 0
    try:
        for code in [lv["code"] for lv in freeze["levels"]]:
            row = conn.execute(
                "SELECT status, conclusion FROM pronunciation_units WHERE id = ?", (code,)
            ).fetchone()
            if row is None:
                print(f"  ! {code} 不在库里：先运行 backend/tools/seed_levels_30.py 建草稿")
                skipped += 1
                continue
            status = row["status"]
            if status not in EDITABLE_STATUSES:
                # 已提交审核 / 已发布：内容归 C 的审核流程，脚本不越权
                print(f"  - {code} 状态为「{status}」，跳过（不覆盖审核中/已发布内容）")
                protected += 1
                continue
            if str(row["conclusion"] or "").strip() and not args.force:
                skipped += 1
                continue

            item = content["levels"][code]
            payload = {
                "conclusion": item["conclusion"],
                "detail": item["detail"],
                "steps": item["steps"],
                "mistakes": item["mistakes"],
                "practice": item["practice"],
                "related": item.get("related") or [],
            }
            if args.dry_run:
                print(f"  ~ {code} 将写入：{payload['conclusion'][:28]}…（{len(payload['steps'])} 步 / {len(payload['mistakes'])} 误区）")
                written += 1
                continue

            ok = database.update_unit(code, payload, OPERATOR)
            if not ok:
                print(f"  ! {code} 更新失败（单元不存在）")
                skipped += 1
                continue
            written += 1
            print(f"  + {code} 已写入并升版本（仍为 draft，未公开）")

        if not args.dry_run:
            total = conn.execute("SELECT COUNT(*) FROM pronunciation_units").fetchone()[0]
            filled = conn.execute(
                "SELECT COUNT(*) FROM pronunciation_units "
                "WHERE id GLOB 'L[0-9][0-9]' AND length(conclusion) > 0"
            ).fetchone()[0]
            published = conn.execute(
                "SELECT COUNT(*) FROM pronunciation_units "
                "WHERE id GLOB 'L[0-9][0-9]' AND status = 'published'"
            ).fetchone()[0]
            print(
                f"[完成] 写入 {written} 关，跳过 {skipped} 关（已有内容），保护 {protected} 关（审核中/已发布）；"
                f"表内共 {total} 行，30 关中有内容 {filled} 关，已发布 {published} 关"
            )
            print("[提醒] 这 30 关仍是 draft：大众端 /api/units?status=published 依然看不到，")
            print("       关卡页显示「未开放」，不会出现空卡片或假分。发布请走 I 审校 + C 的 CMS 审核。")
        else:
            print(f"[dry-run] 未写入数据库（将写入 {written} 关）")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
