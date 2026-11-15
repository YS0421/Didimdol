"""매일 1~2회 실행용: 공고 수집 → 새/정정 공고만 Claude 요구 항목 추출 → JSON 내보내기.

사용:  python scripts/daily.py [--pages 2] [--no-llm]
로그:  collector_data/logs/daily-YYYYMMDD-HHMM.log
종료 코드: 0 정상, 1 일부 실패(수집 오류·구조 변경 경고·추출 실패) → 스케줄러 알림에 활용

OS 스케줄러 등록은 이 스크립트가 하지 않는다 (README '정기 실행' 참고).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--no-llm", action="store_true", help="수집만 하고 Claude 추출은 건너뜀")
    args = ap.parse_args()

    from didimdol_ai.collector.__main__ import main as collector_main

    log_dir = ROOT / "collector_data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"daily-{datetime.now():%Y%m%d-%H%M}.log"
    buf = io.StringIO()
    status = 0
    with contextlib.redirect_stdout(buf):
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] 수집 시작")
        status |= collector_main(["run", "--pages", str(args.pages)])
        if not args.no_llm:
            from didimdol_ai.llm.__main__ import main as llm_main
            print("요구 항목 추출 (새 공고·정정 공고만)")
            status |= llm_main(["extract"])
        collector_main(["export", "--out", str(ROOT / "collector_data" / "export.json")])
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] 종료 (status={status})")
    log_path.write_text(buf.getvalue(), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(buf.getvalue())
    print(f"로그 → {log_path}")
    return 1 if status else 0


if __name__ == "__main__":
    raise SystemExit(main())
