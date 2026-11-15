import io
import json
import unittest
import zipfile
from types import SimpleNamespace

from didimdol_ai.collector.extract import extract_text
from didimdol_ai.llm.card_draft import draft_cards_from_text, verify_drafts
from didimdol_ai.llm.requirements import ExtractionError

SOURCE = """1. 학부연구생 (2026.03 ~ 2026.06)
- 프로토콜에 따라 세포 배양과 MTT assay를 수행하고 세포 생존율을 측정함
- 측정 결과를 엑셀로 정리하여 랩미팅에서 공유함
연락처 010-1111-2222"""


def card(**kw):
    base = {"kind": "학부연구생", "title": "세포 실험", "period": "2026.03 ~ 2026.06", "role": "학부연구생",
            "actions": "세포 배양과 MTT assay를 수행하고 세포 생존율을 측정했다. 측정 결과를 엑셀로 정리했다.",
            "tools": ["MTT assay", "엑셀"], "outcome": "", "learned": "",
            "source_quote": "세포 배양과 MTT assay를 수행하고", "questions": ["q1", "q2", "q3"]}
    base.update(kw)
    return base


class VerifyTest(unittest.TestCase):
    def test_grounded_card_kept(self):
        r = verify_drafts({"cards": [card()]}, SOURCE)
        self.assertEqual(len(r.drafts), 1)
        self.assertEqual(r.drafts[0].card.kind, "학부연구생")
        self.assertEqual(len(r.drafts[0].questions), 2)

    def test_fake_quote_rejected(self):
        r = verify_drafts({"cards": [card(source_quote="논문 1저자로 SCI 게재")]}, SOURCE)
        self.assertEqual(r.rejected[0]["reason"], "근거 구절이 원문에 없음")

    def test_invented_actions_rejected(self):
        r = verify_drafts({"cards": [card(actions="국제학회에서 구두 발표하고 특허를 출원했으며 기업과 협업했다.")]}, SOURCE)
        self.assertIn("동떨어짐", r.rejected[0]["reason"])

    def test_tools_not_in_source_removed(self):
        r = verify_drafts({"cards": [card(tools=["MTT assay", "CRISPR"])]}, SOURCE)
        self.assertEqual(r.drafts[0].card.tools, ["MTT assay"])


class FakeClient:
    def __init__(self, out):
        self.calls, self.out = [], out
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(self.out, ensure_ascii=False))],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))


class RequestTest(unittest.TestCase):
    def test_pii_masked_before_sending(self):
        client = FakeClient({"cards": [card()]})
        draft_cards_from_text(client, SOURCE)
        sent = client.calls[0]["messages"][0]["content"]
        self.assertNotIn("010-1111-2222", sent)

    def test_empty_document(self):
        with self.assertRaises(ExtractionError):
            draft_cards_from_text(FakeClient({"cards": []}), "   ")


class DocxTest(unittest.TestCase):
    def test_docx_text(self):
        xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
               '<w:p><w:r><w:t>학부연구생 </w:t></w:r><w:r><w:t>경험</w:t></w:r></w:p>'
               '<w:p><w:r><w:t>세포 배양</w:t></w:r></w:p></w:body></w:document>')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", xml)
        self.assertEqual(extract_text("a.docx", buf.getvalue()), "학부연구생 경험\n세포 배양")


if __name__ == "__main__":
    unittest.main()
