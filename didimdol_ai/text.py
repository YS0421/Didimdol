"""문장 다듬기 도우미."""

from __future__ import annotations

import re

_PAIRS = {"이(가)": ("이", "가"), "을(를)": ("을", "를"), "은(는)": ("은", "는"), "과(와)": ("과", "와")}
_JOSA = re.compile(r"(.)(['’\")」]*)(이\(가\)|을\(를\)|은\(는\)|과\(와\))")


def fix_josa(text: str) -> str:
    """'이(가)', '을(를)', '은(는)', '과(와)'를 앞 글자 받침에 맞게 고른다. 앞 글자가 한글이 아니면 그대로 둔다."""

    def pick(m: re.Match) -> str:
        ch, quote, token = m.group(1), m.group(2), m.group(3)
        if not ("가" <= ch <= "힣"):
            return m.group(0)
        has_final = (ord(ch) - 0xAC00) % 28 != 0
        return ch + quote + _PAIRS[token][0 if has_final else 1]

    return _JOSA.sub(pick, text)
