"""音乐学院发音数据集批次入库 CLI(第 8 周 C)

用法(在 backend/ 目录执行):
  python tools/import_dataset.py <交付目录> \\
      --batch-name 第一批_正确发音_20261115前 --phase 1 --purpose calibration \\
      --annotation-csv 标注表.csv --recorder-csv 录音人登记表.csv \\
      --consent-dir 知情同意书 [--db pronunciation.db] [--dry-run]

- 先 --dry-run 看报告(不落库),确认无异常再正式导入;
- 同批次同文件名幂等,可反复执行补漏(标注表后补时重跑即可);
- 交付目录按规范第九章的结构摆放(wav 可嵌套在 S001/ 子目录里,脚本递归扫描);
- CSV 模板见 backend/tools/templates/(Excel 直接打开,UTF-8 带 BOM)。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(ROOT))

import database  # noqa: E402  (init_db 幂等建表,含六张数据集表)
import dataset  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("source_dir", help="交付目录(递归扫描 *.wav)")
    parser.add_argument("--batch-name", default="", help="批次名,如 第一批_正确发音_20261115前")
    parser.add_argument("--phase", type=int, default=1, choices=[1, 2], help="第几批(1 校准/2 纠音训练)")
    parser.add_argument("--purpose", default="calibration", choices=["calibration", "training"])
    parser.add_argument("--annotation-csv", default="", help="标注表 CSV 路径")
    parser.add_argument("--recorder-csv", default="", help="录音人登记表 CSV 路径")
    parser.add_argument("--consent-dir", default="", help="知情同意书目录")
    parser.add_argument("--db", default="pronunciation.db", help="SQLite 库路径(默认 backend/pronunciation.db)")
    parser.add_argument("--dry-run", action="store_true", help="只出报告不落库")
    args = parser.parse_args()

    database.init_db(args.db)  # 幂等;老库自动补六张表
    report = dataset.import_dataset(
        source_dir=args.source_dir,
        db_path=args.db,
        batch_name=args.batch_name,
        phase=args.phase,
        purpose=args.purpose,
        annotation_csv=args.annotation_csv,
        recorder_csv=args.recorder_csv,
        consent_dir=args.consent_dir,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
