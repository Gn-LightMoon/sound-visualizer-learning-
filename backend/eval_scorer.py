# -*- coding: utf-8 -*-
"""
看得见的声音 - 四步反馈评测打分脚本（雏形）

用途：
    加载 eval_samples.json，对每条样本用「反馈生成器」生成四步反馈，
    再按样本 expected 约束逐项检查，输出通过率报告。

评测维度（对应 eval_samples.json 的 eval_dimensions）：
    1. 四步完整性  —— 每条反馈是否含 现象/环节/提示/练习 四步（自动化）
    2. 准确性      —— 是否引用了输入里的关键诊断事实 must_mention（自动化）
    3. 类别命中    —— 是否生成了 expected 指定的 category + level（自动化）
    4. 安全性      —— 是否避开了 forbidden 禁用词（自动化，覆盖"安全/鼓励"部分）
    5. 自然度      —— 暂无法自动，需人工评审（见报告末尾提示）

生成器可插拔：
    当前 baseline 直接调用 feedback_engine.build_four_step_feedback（规则引擎）。
    待 Z2 的提示词模板 / LLM 接口（/api/llm/chat）就绪后，只需替换
    generate_feedback() 函数体，其余评测逻辑完全复用。

用法：
    cd backend && python eval_scorer.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # 保证可从任意目录 import feedback_engine

SAMPLES_PATH = os.path.join(HERE, "eval_samples.json")

# 四步反馈的标准字段名（对应 RES-05：现象→环节→提示→练习）
FOUR_STEPS = ["phenomenon", "link", "hint", "practice"]


def generate_feedback(diagnosis: dict) -> dict:
    """反馈生成器（可插拔）。

    输入：诊断 JSON（样本的 input 字段）
    输出：{"overview": str, "steps": [{"category","type","severity","phenomenon","link","hint","practice"}]}

    TODO(Z2)：接入 LLM 后，把下面的规则引擎实现替换为：
        1) 组装提示词（用 diagnosis）
        2) 调 Ollama /api/llm/chat
        3) 解析出与下面相同结构的 steps
    """
    from feedback_engine import build_four_step_feedback

    phonemes = diagnosis.get("phonemes", [])
    target = diagnosis.get("target", {})
    quality = diagnosis.get("quality", {})

    # 提取录音质量警告项（warn 级）
    quality_warn = None
    for item in quality.get("items", []):
        if item.get("status") == "warn":
            quality_warn = {"message": item.get("message", "")}
            break

    items = build_four_step_feedback(
        tone_combined=diagnosis.get("tone_score", 0.0),
        f0_mean=diagnosis.get("f0_mean", 0.0),
        f0_std=diagnosis.get("f0_std", 0.0),
        ref_f0=diagnosis.get("ref_f0", 200.0),
        detected_tone=diagnosis.get("detected_tone", 0),
        ref_tone=target.get("tone", 1),
        fluency=diagnosis.get("fluency", 50.0),
        phonemes=phonemes,
        quality_warn=quality_warn,
    )

    steps = [
        {
            "category": it.get("category"),
            "type": it.get("type"),
            "severity": it.get("severity"),
            "phenomenon": it.get("phenomenon", ""),
            "link": it.get("link", ""),
            "hint": it.get("hint", ""),
            "practice": it.get("practice", ""),
        }
        for it in items
    ]
    return {"overview": "基于规则引擎共生成 %d 条四步反馈" % len(steps), "steps": steps}


def flatten_text(feedback: dict) -> str:
    """把反馈内容拼成一段文本，供关键词/禁用词检查"""
    parts = [str(feedback.get("overview", ""))]
    for s in feedback.get("steps", []):
        parts.append(" ".join(str(s.get(k, "")) for k in FOUR_STEPS))
    return " ".join(parts)


def check_sample(sample: dict) -> dict:
    """对单条样本执行评测，返回检查明细"""
    feedback = generate_feedback(sample["input"])
    expected = sample["expected"]
    steps = feedback.get("steps", [])
    text = flatten_text(feedback)

    checks = []

    # 1. 四步完整性
    complete = bool(steps) and all(
        all(str(s.get(k, "")).strip() for k in FOUR_STEPS) for s in steps
    )
    checks.append(("四步完整性", complete, "每步需含现象/环节/提示/练习" if not complete else ""))

    # 2. 类别/级别命中
    cat_level = any(
        s.get("category") == expected.get("category")
        and s.get("type") == expected.get("level")
        for s in steps
    )
    checks.append(("类别/级别命中", cat_level,
                   f"需含 {expected.get('category')}/{expected.get('level')}" if not cat_level else ""))

    # 3. 准确性（关键词命中）
    missing = [m for m in expected.get("must_mention", []) if m not in text]
    checks.append(("关键词命中", not missing, "缺:" + ",".join(missing) if missing else ""))

    # 4. 安全/鼓励（禁用词）
    hit = [f for f in expected.get("forbidden", []) if f in text]
    checks.append(("无禁用词", not hit, "命中:" + ",".join(hit) if hit else ""))

    ok = all(c[1] for c in checks)
    return {
        "id": sample["id"],
        "scene": sample["scene"],
        "ok": ok,
        "checks": checks,
        "steps_count": len(steps),
    }


def main() -> int:
    with open(SAMPLES_PATH, encoding="utf-8") as f:
        data = json.load(f)

    samples = data.get("samples", [])
    results = [check_sample(s) for s in samples]
    passed = sum(1 for r in results if r["ok"])

    print("=" * 64)
    print("看得见的声音 · 四步反馈评测报告")
    print("样本总数: %d   通过: %d   通过率: %.1f%%" % (len(results), passed, 100.0 * passed / len(results)))
    print("=" * 64)

    for r in results:
        flag = "PASS" if r["ok"] else "FAIL"
        print("\n[%s] %s  (%s)  -> %d 步反馈" % (flag, r["id"], r["scene"], r["steps_count"]))
        for name, passed_check, detail in r["checks"]:
            mark = "[OK]" if passed_check else "[X ]"
            suffix = ("  " + detail) if detail else ""
            print("      %s %s%s" % (mark, name, suffix))

    print("\n" + "=" * 64)
    print("提示：自然度、鼓励性两个维度无法全自动，请人工抽检 steps 话术是否自然。")
    print("接入 Z2 的 LLM 模板后，替换 generate_feedback() 即可复用本评测框架。")
    print("=" * 64)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
