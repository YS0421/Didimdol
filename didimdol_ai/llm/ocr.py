"""Claude로 읽는 OCR: 스캔 PDF·사진 속 글자를 그대로 옮겨 적는다.

쓰는 곳: 포트폴리오 → 경험 카드 초안. 일반 텍스트 추출(pypdf 등)로 글이 거의 안 나오는 파일만 OCR로 보낸다.
- 받아 적은 글이 '원문'이 되고, 그 뒤 단계(카드 초안의 근거 구절 검사)는 이 글을 기준으로 검증한다.
- 개인 식별 정보(이름·학교·학번·연락처·주소)는 받아 적을 때 [이름] 같은 자리표시로 바꾸게 하고,
  끝난 뒤 코드(mask_pii)로 이메일·전화번호를 한 번 더 가린다.
  다만 이미지 원본 자체는 Claude로 전송되므로, 사용자에게 업로드 전에 이 사실을 안내해야 한다.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..collector.extract import ext_of
from .client import FALLBACK_BETA, model_name
from .evidence import mask_pii
from .requirements import ExtractionError

if TYPE_CHECKING:
    import anthropic

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".gif": "image/gif"}
OCR_EXTS = set(IMAGE_TYPES) | {".pdf"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # Claude API 이미지 1장 한도
MAX_PDF_BYTES = 30 * 1024 * 1024  # 요청 한도 32MB 안쪽
MIN_TEXT_CHARS = 200  # 일반 추출 결과가 이보다 짧으면 스캔 문서로 보고 OCR

SYSTEM_PROMPT = """너는 문서 이미지의 글자를 그대로 옮겨 적는 OCR 도구다.

- 보이는 글자를 읽는 순서대로 **빠짐없이, 고치지 말고** 옮긴다. 요약·해석·번역·맞춤법 교정을 하지 않는다.
- 보이지 않는 내용을 추측해 채우지 않는다. 읽을 수 없는 부분은 [판독 불가]로 쓴다.
- 표는 한 행을 한 줄로, 칸은 " | "로 구분한다. 제목·글머리는 줄을 바꿔 구분한다.
- 개인 식별 정보는 옮기지 말고 자리표시로 바꾼다: 사람 이름 → [이름], 학교·학과명 → [학교], 학번 → [학번],
  전화번호 → [전화], 이메일 → [이메일], 주소 → [주소], 증명사진 → 생략.
  (경험·활동 내용, 기관명, 도구·기법 이름은 그대로 옮긴다.)
- legible은 글자를 대부분 읽을 수 있었으면 true, 흐리거나 글자가 거의 없으면 false."""


def _schema() -> dict:
    return {"type": "object",
            "properties": {"text": {"type": "string"}, "legible": {"type": "boolean"},
                           "notes": {"type": "string"}},
            "required": ["text", "legible", "notes"], "additionalProperties": False}


@dataclass
class OcrResult:
    text: str
    legible: bool
    notes: str = ""
    usage: dict = field(default_factory=dict)


def needs_ocr(name: str, extracted_text: str) -> bool:
    """이미지 파일이거나, 글이 거의 나오지 않은 PDF(스캔본)이면 OCR이 필요하다."""
    ext = ext_of(name)
    if ext in IMAGE_TYPES:
        return True
    return ext == ".pdf" and len(extracted_text.strip()) < MIN_TEXT_CHARS


def _source_block(name: str, data: bytes) -> dict:
    ext = ext_of(name)
    b64 = base64.standard_b64encode(data).decode("ascii")
    if ext in IMAGE_TYPES:
        if len(data) > MAX_IMAGE_BYTES:
            raise ExtractionError("이미지는 한 장에 5MB까지 읽을 수 있어요. 해상도를 낮추거나 PDF로 묶어 올려 주세요.")
        return {"type": "image", "source": {"type": "base64", "media_type": IMAGE_TYPES[ext], "data": b64}}
    if ext == ".pdf":
        if len(data) > MAX_PDF_BYTES:
            raise ExtractionError("스캔 PDF는 30MB까지 읽을 수 있어요.")
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    raise ExtractionError(f"OCR을 지원하지 않는 형식이에요: {ext or '확장자 없음'}")


def ocr_file(client: "anthropic.Anthropic", name: str, data: bytes) -> OcrResult:
    """파일 1개를 Claude로 읽어 글자를 옮겨 적는다. 개인정보는 자리표시와 mask_pii로 가린다."""
    block = _source_block(name, data)
    with client.beta.messages.stream(
        model=model_name(), max_tokens=32000, betas=[FALLBACK_BETA], fallbacks="default",
        system=SYSTEM_PROMPT,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": _schema()}},
        messages=[{"role": "user", "content": [block, {"type": "text", "text": "이 문서의 글자를 옮겨 적어 주세요."}]}],
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason in ("refusal", "max_tokens"):
        raise ExtractionError(f"문서를 읽지 못했어요 ({response.stop_reason}).")
    text_block = next((b.text for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise ExtractionError("응답에 텍스트 블록이 없어요.")
    data_out = json.loads(text_block)
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    return OcrResult(mask_pii(data_out["text"]).strip(), data_out["legible"], data_out["notes"], usage)
