"""Claude OCR 테스트: 가짜 클라이언트 (실제 API 호출 없음)."""

import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from didimdol_ai.llm.card_draft import draft_cards_from_upload
from didimdol_ai.llm.ocr import MAX_IMAGE_BYTES, _source_block, needs_ocr, ocr_file
from didimdol_ai.llm.requirements import ExtractionError

OCR_TEXT = ("학부연구생 활동 (2026.03~06) 세포 배양과 MTT assay를 수행하고 결과를 엑셀로 정리했다. "
            "연락처 010-1234-5678 [이름]")


def _msg(obj, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, model="fake",
                           content=[SimpleNamespace(type="text", text=json.dumps(obj, ensure_ascii=False))],
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5))


class FakeClient:
    """stream 호출 = OCR, create 호출 = 카드 초안."""

    def __init__(self, ocr_out, stop="end_turn"):
        self.ocr_out, self.stop, self.calls = ocr_out, stop, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream, create=self._create))

    @contextmanager
    def _stream(self, **kw):
        self.calls.append(("ocr", kw))
        yield SimpleNamespace(get_final_message=lambda: _msg(self.ocr_out, self.stop))

    def _create(self, **kw):
        self.calls.append(("draft", kw))
        return _msg({"cards": [{"kind": "학부연구생", "title": "세포 실험", "period": "2026.03~06", "role": "",
                                "actions": "세포 배양과 MTT assay를 수행하고 결과를 엑셀로 정리했다.",
                                "tools": ["MTT assay", "엑셀"], "outcome": "", "learned": "",
                                "source_quote": "세포 배양과 MTT assay를 수행", "questions": []}]})


class OcrTest(unittest.TestCase):
    def test_needs_ocr(self):
        self.assertTrue(needs_ocr("scan.png", ""))
        self.assertTrue(needs_ocr("scan.pdf", "  1  "))  # 스캔 PDF: 글이 거의 없음
        self.assertFalse(needs_ocr("text.pdf", "가" * 300))
        self.assertFalse(needs_ocr("a.hwp", ""))

    def test_source_blocks_and_limits(self):
        self.assertEqual(_source_block("a.JPG", b"x")["source"]["media_type"], "image/jpeg")
        self.assertEqual(_source_block("a.pdf", b"%PDF")["type"], "document")
        with self.assertRaises(ExtractionError):
            _source_block("big.png", b"0" * (MAX_IMAGE_BYTES + 1))
        with self.assertRaises(ExtractionError):
            _source_block("a.bmp", b"x")

    def test_ocr_masks_pii_and_sends_image(self):
        c = FakeClient({"text": OCR_TEXT, "legible": True, "notes": ""})
        r = ocr_file(c, "p.png", b"\x89PNG")
        self.assertNotIn("010-1234-5678", r.text)
        content = c.calls[0][1]["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "image")
        self.assertIn("[이름]", c.calls[0][1]["system"])

    def test_ocr_refusal(self):
        with self.assertRaises(ExtractionError):
            ocr_file(FakeClient({"text": "", "legible": False, "notes": ""}, stop="refusal"), "p.png", b"x")

    def test_upload_image_goes_through_ocr_then_draft(self):
        c = FakeClient({"text": OCR_TEXT, "legible": True, "notes": ""})
        r = draft_cards_from_upload(c, "portfolio.jpg", b"\xff\xd8")
        self.assertTrue(r.ocr_used)
        self.assertEqual([k for k, _ in c.calls], ["ocr", "draft"])
        self.assertEqual(len(r.drafts), 1)  # 근거 구절은 OCR 글 기준으로 검증됨
        self.assertEqual(r.usage["input_tokens"], 20)

    def test_upload_text_file_skips_ocr(self):
        c = FakeClient({"text": "", "legible": True, "notes": ""})
        r = draft_cards_from_upload(c, "p.txt", OCR_TEXT.encode("utf-8") * 2)
        self.assertFalse(r.ocr_used)
        self.assertEqual([k for k, _ in c.calls], ["draft"])

    def test_illegible_image(self):
        with self.assertRaises(ExtractionError):
            draft_cards_from_upload(FakeClient({"text": "", "legible": False, "notes": "흐림"}), "p.png", b"x")


if __name__ == "__main__":
    unittest.main()
