from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class AttachmentLink:
    name: str
    url: Optional[str]  # None이면 다운로드 경로를 알 수 없음 (JS 전용 등)


@dataclass
class Attachment:
    name: str
    url: Optional[str]
    local_path: Optional[str] = None
    text: str = ""
    skipped_reason: Optional[str] = None  # robots_disallowed / no_url / too_large / unsupported / error:...


@dataclass
class PostingRef:
    """목록 페이지에서 얻는 정보."""

    institute: str
    external_id: str
    title: str
    url: str
    posted_on: Optional[date] = None
    apply_start_on: Optional[date] = None
    apply_end_on: Optional[date] = None
    status_text: str = ""


@dataclass
class Posting:
    ref: PostingRef
    body_text: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    include: bool = False
    exclude_reason: Optional[str] = None
    category: Optional[str] = None  # research / admin / experience
    targets: list[str] = field(default_factory=list)  # enrolled / expected / graduated
    is_closed: bool = False

    @property
    def uid(self) -> str:
        return f"{self.ref.institute}:{self.ref.external_id}"

    @property
    def full_text(self) -> str:
        parts = [self.ref.title, self.body_text] + [a.text for a in self.attachments if a.text]
        return "\n\n".join(p for p in parts if p)
