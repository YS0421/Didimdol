"""Claude API 클라이언트 설정.

키는 코드에 넣지 않는다. 우선순위:
  1) 이미 설정된 환경변수 ANTHROPIC_API_KEY
  2) 프로젝트 루트의 .env 파일 (깃 제외 대상)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # anthropic import가 느린 환경이 있어 실제 호출 시점에만 불러온다
    import anthropic

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def load_dotenv(path: Path = ENV_FILE) -> None:
    """간단한 .env 로더 (KEY=VALUE). 이미 설정된 환경변수는 덮어쓰지 않는다."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def model_name() -> str:
    return os.environ.get("DIDIMDOL_LLM_MODEL", DEFAULT_MODEL)


def make_client() -> "anthropic.Anthropic":
    import anthropic

    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        raise RuntimeError(
            "Claude API 키가 없어요. 프로젝트 루트의 .env 파일에 "
            "ANTHROPIC_API_KEY=<키> 한 줄을 넣어 주세요 (.env.example 참고)."
        )
    return anthropic.Anthropic(max_retries=3)
