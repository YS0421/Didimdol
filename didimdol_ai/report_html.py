"""metrics.build_report() 결과 → 디딤돌 사이트(didimdol.cloud) 디자인에 맞춘 리포트 HTML.

두 가지 형태로 내보낸다.
- render_fragment(): 사이트 페이지 안에 그대로 끼워 넣는 조각 (<style> + <section class="dd-report"> + <script>).
  · CSS는 모두 .dd-report 아래로 범위를 한정해 사이트 스타일과 충돌하지 않는다.
  · 다크 모드는 사이트와 같은 방식(<html class="dark"> 또는 data-theme="dark")을 따른다.
  · 글꼴은 사이트 글꼴(Pretendard)을 그대로 물려받는다.
- render(): 단독으로 열어 보는 전체 HTML 문서 (미리보기·메일 첨부용). 시스템 다크 모드를 따른다.

디자인 토큰은 사이트 Tailwind 설정에서 가져왔다 (didim-ink/green/muted/line/mint/mist/forest, 다크는 gray-900/800/700 + emerald-400).

정보 위계 (가독성):
1) 한 줄 요약(목표까지 얼마나 왔는지) → 2) 코치의 말 → 3) 다음 한 칸 → 4) 육각형과 축별 상태
5) 월간 상세는 접힌 묶음(details)으로: 열어 볼 사람만 본다. 숫자 표는 '숫자로 보기'에 접어 둔다.
"""

from __future__ import annotations

import html
import json
import math
from typing import Optional

from .text import fix_josa

KIND_LABEL = {"praise": "칭찬", "encourage": "응원", "push": "한 걸음 더"}
# 2×2 방향을 사용자 말로
# 상태 표시(목표 도달/목표까지 n)만으로 알 수 없는 경우만 한 줄 덧붙인다 — 같은 문구가 축마다 반복되지 않게
QUAD_HINT = {"record_proof": "스스로는 높게 봤어요. 해 본 적 있다면 카드로 남겨 보세요",
             "confidence_expression": "기록이 충분해요. 자소서·면접에서 자신 있게 말해도 돼요"}
# 육각형 꼭짓점에 쓰는 짧은 이름 (모바일에서도 읽히게)
SHORT_AXIS = {"domain": "전공 지식", "research": "연구·실험", "data": "데이터·도구", "problem": "문제해결",
              "communication": "소통·문서", "collaboration": "협업·자기관리"}
STYLE_NAMES = {"analyze": "분석", "make": "만들기", "talk": "소통", "plan": "기획"}

CSS = """
.dd-report{--dd-bg:#fff;--dd-surface:#fff;--dd-soft:#eff7f2;--dd-mint:#e4f3eb;--dd-line:#dce8e0;--dd-ink:#153d31;
--dd-text:#1e2939;--dd-muted:#687b74;--dd-accent:#007e5c;--dd-accent-soft:#e4f3eb;--dd-forest:#123e30;--dd-on-forest:#fff;
--dd-self:#a8601b;--dd-target:#8a9b94;--dd-grid:#e3ece6;--dd-warn-bg:#fdf6e7;--dd-warn:#7a5512;--dd-track:#e9f1ec;--dd-stat:#fff;
color-scheme:light;font-family:inherit;color:var(--dd-text);line-height:1.65;letter-spacing:-0.2px;
max-width:1200px;margin:0 auto;-webkit-font-smoothing:antialiased}
:where(.dark,[data-theme="dark"]) .dd-report{--dd-bg:#101828;--dd-surface:#1e2939;--dd-soft:#28354a;--dd-mint:#1e2939;--dd-stat:#101828;
--dd-line:#364153;--dd-ink:#fff;--dd-text:#e5e7eb;--dd-muted:#99a1af;--dd-accent:#00d492;--dd-accent-soft:rgba(0,212,146,.12);
--dd-forest:#184a37;--dd-on-forest:#fff;--dd-self:#f0b45a;--dd-target:#6a7282;--dd-grid:#364153;--dd-warn-bg:rgba(240,180,90,.12);
--dd-warn:#f0c987;--dd-track:#2a3546;color-scheme:dark}
.dd-report *{box-sizing:border-box}
.dd-report h2,.dd-report h3,.dd-report p{margin:0}
.dd-report .dd-stack{display:flex;flex-direction:column;gap:20px}
.dd-report .dd-card{background:var(--dd-surface);border:1px solid var(--dd-line);border-radius:20px;padding:24px}
.dd-report .dd-card-title{font-size:20px;font-weight:700;color:var(--dd-ink);letter-spacing:-0.4px;margin-bottom:4px}
.dd-report .dd-card-desc{font-size:14px;color:var(--dd-muted);margin-bottom:16px}
/* 요약 */
.dd-report .dd-hero{background:var(--dd-mint);border:1px solid var(--dd-mint);border-radius:24px;padding:28px}
:where(.dark,[data-theme="dark"]) .dd-report .dd-hero{border-color:var(--dd-line)}
.dd-report .dd-eyebrow{font-size:13px;font-weight:700;color:var(--dd-accent);margin-bottom:6px}
.dd-report .dd-hero h2{font-size:26px;line-height:1.35;font-weight:700;color:var(--dd-ink);letter-spacing:-0.6px}
.dd-report .dd-lead{font-size:16px;color:var(--dd-text);margin-top:8px}
.dd-report .dd-means{font-size:14px;color:var(--dd-muted);margin-top:4px}
.dd-report .dd-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(120px,100%),1fr));gap:12px;margin-top:20px}
.dd-report .dd-stat{background:var(--dd-stat);border-radius:16px;padding:14px 16px}
.dd-report .dd-stat b{display:block;font-size:24px;font-weight:700;color:var(--dd-ink);font-variant-numeric:tabular-nums;line-height:1.3}
.dd-report .dd-stat span{font-size:13px;color:var(--dd-muted)}
.dd-report .dd-meter{height:8px;border-radius:99px;background:var(--dd-track);margin-top:8px;overflow:hidden}
.dd-report .dd-meter i{display:block;height:100%;border-radius:99px;background:var(--dd-accent)}
.dd-report .dd-principle{font-size:13px;color:var(--dd-muted);margin-top:14px}
/* 2단 */
.dd-report .dd-cols{display:grid;grid-template-columns:1fr;gap:20px}
@media (min-width:880px){.dd-report .dd-cols{grid-template-columns:1fr 1fr;align-items:start}}
/* 코치의 말 */
.dd-report .dd-msg{padding:14px 0;border-top:1px solid var(--dd-line)}
.dd-report .dd-msg:first-of-type{border-top:0;padding-top:4px}
.dd-report .dd-pill{display:inline-block;font-size:12px;font-weight:700;padding:2px 10px;border-radius:99px;
background:var(--dd-accent-soft);color:var(--dd-accent);margin-bottom:6px}
.dd-report .dd-msg p{font-size:16px;color:var(--dd-text)}
.dd-report .dd-rest{margin-top:14px;background:var(--dd-forest);color:var(--dd-on-forest);border-radius:16px;padding:16px 18px}
.dd-report .dd-rest b{display:block;font-size:14px;margin-bottom:2px}
.dd-report .dd-rest p{font-size:15px;opacity:.92}
/* 다음 한 칸 */
.dd-report ol.dd-steps{list-style:none;margin:0;padding:0;counter-reset:s}
.dd-report ol.dd-steps li{counter-increment:s;display:grid;grid-template-columns:32px 1fr;gap:12px;padding:14px 0;
border-top:1px solid var(--dd-line)}
.dd-report ol.dd-steps li:first-child{border-top:0;padding-top:4px}
.dd-report ol.dd-steps li::before{content:counter(s);width:32px;height:32px;border-radius:10px;background:var(--dd-soft);
color:var(--dd-accent);font-weight:700;display:flex;align-items:center;justify-content:center;font-size:15px}
.dd-report .dd-step-title{font-size:16px;font-weight:700;color:var(--dd-ink)}
.dd-report .dd-step-how{font-size:14px;color:var(--dd-text);margin-top:2px}
.dd-report .dd-step-meta{font-size:13px;color:var(--dd-muted);margin-top:6px}
.dd-report .dd-note{background:var(--dd-warn-bg);color:var(--dd-warn);border-radius:12px;padding:10px 14px;font-size:14px;margin-bottom:12px}
/* 육각형 */
.dd-report .dd-hex{display:grid;grid-template-columns:1fr;gap:20px;align-items:center}
@media (min-width:880px){.dd-report .dd-hex{grid-template-columns:minmax(0,420px) 1fr}}
.dd-report svg{max-width:100%;height:auto;display:block}
.dd-report .dd-legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--dd-muted);margin-top:8px}
.dd-report .dd-legend i{display:inline-block;width:16px;height:0;border-top:2.5px solid;margin-right:6px;vertical-align:middle}
.dd-report ul.dd-axes{list-style:none;margin:0;padding:0}
.dd-report ul.dd-axes li{padding:12px 0;border-top:1px solid var(--dd-line)}
.dd-report ul.dd-axes li:first-child{border-top:0}
.dd-report .dd-axis-head{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.dd-report .dd-axis-name{font-size:15px;font-weight:700;color:var(--dd-ink)}
.dd-report .dd-axis-state{font-size:13px;color:var(--dd-muted);white-space:nowrap}
.dd-report .dd-axis-state.ok{color:var(--dd-accent);font-weight:700}
.dd-report .dd-bar{position:relative;height:8px;border-radius:99px;background:var(--dd-track);margin:8px 0 6px}
.dd-report .dd-bar i{position:absolute;left:0;top:0;bottom:0;border-radius:99px;background:var(--dd-accent)}
.dd-report .dd-bar s{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--dd-ink);opacity:.55;border-radius:2px}
.dd-report .dd-axis-hint{font-size:13px;color:var(--dd-muted)}
.dd-report .dd-up{color:var(--dd-accent);font-weight:700}
.dd-report li.dd-na .dd-axis-name{color:var(--dd-muted);font-weight:500}
/* 접는 묶음 */
.dd-report details.dd-more{border-top:1px solid var(--dd-line);padding:4px 0}
.dd-report details.dd-more:first-of-type{border-top:0}
.dd-report details.dd-more>summary{list-style:none;cursor:pointer;display:flex;justify-content:space-between;align-items:center;
padding:14px 0;font-size:16px;font-weight:700;color:var(--dd-ink)}
.dd-report details.dd-more>summary::-webkit-details-marker{display:none}
.dd-report details.dd-more>summary::after{content:"";width:9px;height:9px;border-right:2px solid var(--dd-muted);
border-bottom:2px solid var(--dd-muted);transform:rotate(45deg);margin:0 6px 4px 0;transition:transform .15s}
.dd-report details.dd-more[open]>summary::after{transform:rotate(-135deg);margin-bottom:-4px}
.dd-report details.dd-more>summary span{font-size:13px;font-weight:500;color:var(--dd-muted);margin-left:8px}
.dd-report .dd-more-body{padding:0 0 16px}
.dd-report details.dd-plain>summary{cursor:pointer;font-size:13px;color:var(--dd-muted);margin-top:12px}
.dd-report .dd-tags{display:flex;flex-wrap:wrap;gap:8px}
.dd-report .dd-tag{font-size:13px;padding:4px 12px;border-radius:99px;background:var(--dd-soft);color:var(--dd-text)}
.dd-report .dd-tag.done{background:var(--dd-accent-soft);color:var(--dd-accent);font-weight:700}
.dd-report .dd-small{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr));gap:16px}
.dd-report .dd-small-title{font-size:13px;font-weight:700;color:var(--dd-text);margin-bottom:4px}
.dd-report .dd-kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(160px,100%),1fr));gap:12px}
.dd-report .dd-kv div{background:var(--dd-soft);border-radius:14px;padding:12px 14px}
.dd-report .dd-kv b{display:block;font-size:18px;color:var(--dd-ink);font-variant-numeric:tabular-nums}
.dd-report .dd-kv span{font-size:13px;color:var(--dd-muted)}
.dd-report .dd-list{margin:0;padding:0;list-style:none}
.dd-report .dd-list li{padding:10px 0;border-top:1px solid var(--dd-line);font-size:14px}
.dd-report .dd-list li:first-child{border-top:0}
.dd-report .dd-list b{color:var(--dd-ink)}
.dd-report .dd-private{font-size:13px;color:var(--dd-muted);margin-bottom:10px}
.dd-report table{width:100%;border-collapse:collapse;font-size:13px}
.dd-report th,.dd-report td{text-align:left;padding:8px;border-bottom:1px solid var(--dd-line)}
.dd-report th{color:var(--dd-muted);font-weight:500}
.dd-report td.n{font-variant-numeric:tabular-nums}
.dd-report .dd-scroll{overflow-x:auto}
.dd-report .dd-tip{position:fixed;pointer-events:none;background:var(--dd-surface);color:var(--dd-text);border:1px solid var(--dd-line);
border-radius:10px;padding:6px 10px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.12);display:none;z-index:50;max-width:240px}
@media (max-width:560px){.dd-report .dd-card{padding:20px 18px}.dd-report .dd-hero{padding:22px 18px}
.dd-report .dd-hero h2{font-size:22px}.dd-report .dd-stat{padding:12px 14px}
.dd-report .dd-stat b{font-size:20px}}
"""

# 같은 페이지에 리포트가 여러 개 있어도 한 번만 동작하고, 리포트 안에서만 동작한다
TOOLTIP_JS = """
(function(){document.querySelectorAll('.dd-report:not([data-dd-ready])').forEach(function(root){
root.setAttribute('data-dd-ready','1');var tip=root.querySelector('.dd-tip');if(!tip)return;
root.querySelectorAll('[data-tip]').forEach(function(el){
el.addEventListener('mousemove',function(e){tip.textContent=el.getAttribute('data-tip');tip.style.display='block';
var x=Math.min(e.clientX+12,window.innerWidth-tip.offsetWidth-8);tip.style.left=x+'px';tip.style.top=(e.clientY+14)+'px';});
el.addEventListener('mouseleave',function(){tip.style.display='none';});});});})();
"""

# 단독 문서에서만: 사이트처럼 html에 dark 클래스를 붙여 시스템 다크 모드를 따른다
THEME_JS = """
(function(){var d=document.documentElement;if(!d.classList.contains('dark')&&d.getAttribute('data-theme')!=='light'&&
window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches){d.classList.add('dark');}})();
"""

PAGE_CSS = """
html{background:#fff}html.dark{background:#101828}
body{margin:0;padding:24px 16px 48px;font-family:"Pretendard Variable",Pretendard,ui-sans-serif,system-ui,-apple-system,
"Segoe UI",Roboto,"Noto Sans KR","Malgun Gothic",sans-serif}
"""


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _num(v: Optional[float]) -> str:
    return "-" if v is None else f"{v:.1f}".rstrip("0").rstrip(".")


def _pct(v: Optional[float]) -> str:
    return "-" if v is None else f"{v * 100:.0f}%"


# ---------------------------------------------------------------- 육각형 (레이더)


def radar_svg(report: dict) -> str:
    """목표선(점선)·지금 근거(채움)·자기평가(선) 3겹만 그린다. 지난주 비교는 축 목록의 변화량으로 보여 준다."""
    names, axes = report["axis_names"], report["axes"]
    ids = list(names)
    W, H, cx, cy, R = 420, 330, 210, 165, 108  # 좌우에 짧은 축 이름이 들어갈 여백

    def pt(i: int, v: Optional[float]) -> tuple[float, float]:
        ang = -math.pi / 2 + 2 * math.pi * i / len(ids)
        r = R * ((v or 1) - 1) / 4
        return cx + r * math.cos(ang), cy + r * math.sin(ang)

    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="육각형 능력치: 목표선, 지금의 나(기록), 내가 본 나">']
    for lv in (2, 3, 4, 5):
        ring = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, lv) for i in range(len(ids))))
        p.append(f'<polygon points="{ring}" fill="none" stroke="var(--dd-grid)" stroke-width="1"/>')
    for i, a in enumerate(ids):
        x, y = pt(i, 5)
        p.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="var(--dd-grid)" stroke-width="1"/>')
        lx, ly = pt(i, 5.7)
        anchor = "middle" if abs(lx - cx) < 10 else ("start" if lx > cx else "end")
        dy = -4 if ly < cy - 10 else (14 if ly > cy + 10 else 5)
        linked = axes[a]["target"] is not None
        p.append(f'<text x="{lx:.1f}" y="{ly + dy:.1f}" text-anchor="{anchor}" font-size="15" font-weight="{700 if linked else 400}" '
                 f'fill="{"var(--dd-ink)" if linked else "var(--dd-muted)"}">{_e(SHORT_AXIS.get(a, names[a]))}</text>')

    def poly(vals: list[Optional[float]], color: str, dash: str = "", fill: bool = False, width: float = 2) -> str:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, v) for i, v in enumerate(vals)))
        f = f'fill="{color}" fill-opacity=".16"' if fill else 'fill="none"'
        d = f' stroke-dasharray="{dash}"' if dash else ""
        return f'<polygon points="{pts}" {f} stroke="{color}" stroke-width="{width}"{d} stroke-linejoin="round"/>'

    p.append(poly([axes[a]["target"] for a in ids], "var(--dd-target)", "5 4", width=1.75))
    p.append(poly([axes[a]["self"] for a in ids], "var(--dd-self)", width=1.75))
    p.append(poly([axes[a]["evidence"] for a in ids], "var(--dd-accent)", fill=True, width=2.5))
    for i, a in enumerate(ids):
        v = axes[a]["evidence"]
        if v is None:
            continue
        x, y = pt(i, v)
        tip = f"{names[a]} · 기록 {_num(v)} / 목표 {_num(axes[a]['target'])} / 내가 본 나 {_num(axes[a]['self'])}"
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="var(--dd-accent)" stroke="var(--dd-surface)" stroke-width="2"/>'
                 f'<circle cx="{x:.1f}" cy="{y:.1f}" r="15" fill="transparent" data-tip="{_e(tip)}"/>')
    p.append("</svg>")
    return "".join(p)


def _axis_rows(report: dict) -> str:
    names, axes, prev = report["axis_names"], report["axes"], report.get("previous_axes") or {}
    linked = [a for a in names if axes[a]["target"] is not None]
    unlinked = [a for a in names if axes[a]["target"] is None]
    rows = []
    for a in linked:
        s = axes[a]
        ev, tg = s["evidence"] or 1.0, s["target"]
        reached = ev >= tg - 1e-9
        state = ('<span class="dd-axis-state ok">목표 도달</span>' if reached
                 else f'<span class="dd-axis-state">목표까지 {_num(tg - ev)}</span>')
        delta = (s["evidence"] or 0) - ((prev.get(a) or {}).get("evidence") or 0) if prev.get(a) else 0
        hint = QUAD_HINT.get(s.get("quadrant") or "", "")
        up = (" · " if hint else "") + f'<span class="dd-up">지난주보다 +{_num(delta)}</span>' if delta > 0.05 else ""
        rows.append(
            f'<li><div class="dd-axis-head"><span class="dd-axis-name">{_e(names[a])}</span>{state}</div>'
            f'<div class="dd-bar" data-tip="{_e(f"{names[a]} · 기록 {_num(s["evidence"])} / 목표 {_num(tg)}")}">'
            f'<i style="width:{max(0, min(100, (ev - 1) / 4 * 100)):.0f}%"></i>'
            f'<s style="left:calc({(tg - 1) / 4 * 100:.0f}% - 1px)"></s></div>'
            + (f'<div class="dd-axis-hint">{_e(hint)}{up}</div>' if hint or up else "") + '</li>')
    if unlinked:
        rows.append(f'<li class="dd-na"><div class="dd-axis-head"><span class="dd-axis-name">'
                    f'{_e(", ".join(names[a] for a in unlinked))}</span>'
                    '<span class="dd-axis-state">이번 목표와 무관</span></div></li>')
    return f'<ul class="dd-axes">{"".join(rows)}</ul>'


def _axis_table(report: dict) -> str:
    names, axes, prev = report["axis_names"], report["axes"], report.get("previous_axes")
    rows = "".join(
        f"<tr><td>{_e(names[a])}</td><td class='n'>{_num(s['target'])}</td><td class='n'>{_num(s['evidence'])}</td>"
        f"<td class='n'>{_num(s['self'])}</td><td class='n'>{_num(prev[a]['evidence']) if prev else '-'}</td></tr>"
        for a, s in axes.items())
    return ("<details class='dd-plain'><summary>숫자로 보기</summary><div class='dd-scroll'><table><thead><tr><th>축</th>"
            "<th>목표</th><th>기록</th><th>내가 본 나</th><th>지난주 기록</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></details>")


# ---------------------------------------------------------------- 작은 추이 차트


def axis_line_svg(name: str, weeks: list[str], values: list[Optional[float]], target: Optional[float]) -> str:
    W, H, L, B, T, Rr = 280, 120, 24, 20, 12, 8
    n = len(weeks)

    def x(i): return L + (W - L - Rr) * (i / (n - 1) if n > 1 else 0.5)
    def y(v): return T + (H - T - B) * (1 - ((v or 1) - 1) / 4)

    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{_e(name)} 주간 기록 점수">']
    for v in (1, 3, 5):
        p.append(f'<line x1="{L}" x2="{W - Rr}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="var(--dd-grid)" stroke-width="1"/>'
                 f'<text x="{L - 6}" y="{y(v) + 4:.1f}" font-size="10" text-anchor="end" fill="var(--dd-muted)">{v}</text>')
    if target is not None:
        p.append(f'<line x1="{L}" x2="{W - Rr}" y1="{y(target):.1f}" y2="{y(target):.1f}" stroke="var(--dd-target)" '
                 f'stroke-width="1.5" stroke-dasharray="5 4"/>')
    pts = [(x(i), y(v), v, weeks[i]) for i, v in enumerate(values) if v is not None]
    if pts:
        p.append('<polyline fill="none" stroke="var(--dd-accent)" stroke-width="2.5" stroke-linejoin="round" points="'
                 + " ".join(f"{a:.1f},{b:.1f}" for a, b, _, _ in pts) + '"/>')
        for a, b, v, w in pts:
            p.append(f'<rect x="{a - 12:.1f}" y="{T}" width="24" height="{H - T - B}" fill="transparent" '
                     f'data-tip="{_e(f"{w} · {name} 기록 {_num(v)}")}"/>')
        a, b, v, _ = pts[-1]
        p.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="4" fill="var(--dd-accent)" stroke="var(--dd-surface)" stroke-width="2"/>')
    for i in ((0, n - 1) if n > 1 else (0,)):
        p.append(f'<text x="{x(i):.1f}" y="{H - 4}" font-size="10" text-anchor="{"start" if i == 0 else "end"}" '
                 f'fill="var(--dd-muted)">{_e(weeks[i])}</text>')
    p.append("</svg>")
    return "".join(p)


# ---------------------------------------------------------------- 묶음 조각


def _hero(report: dict, standalone_title: str) -> str:
    gp, growth, names = report["goal_progress"], report["growth"], report["axis_names"]
    ach = gp["achievement"]
    weeks_left = report["goal"]["weeks_left"]
    lead = (f"목표까지 {_pct(ach)} 왔어요." if ach is not None else "기록이 쌓이면 목표까지 얼마나 왔는지 보여 드릴게요.")
    if growth.get("most_grown"):
        lead += f" 이번에는 {names[growth['most_grown']]}이(가) 가장 많이 자랐어요."
    stats = [f'<div class="dd-stat"><b>{_pct(ach)}</b><span>목표 달성도</span>'
             f'<div class="dd-meter"><i style="width:{(ach or 0) * 100:.0f}%"></i></div></div>',
             f'<div class="dd-stat"><b>{weeks_left}주</b><span>목표 기한까지</span></div>']
    ex = report.get("execution") or {}
    if ex.get("milestones_total"):
        stats.append(f'<div class="dd-stat"><b>{ex["milestones_done"]}/{ex["milestones_total"]}</b>'
                     f'<span>{"이번 달" if report["kind"] == "monthly" else "지금까지"} 끝낸 할 일</span></div>')
    cov = report.get("requirement_coverage")
    if report["kind"] == "monthly" and cov and cov.get("covered_ratio") is not None:
        stats.append(f'<div class="dd-stat"><b>{_pct(cov["covered_ratio"])}</b><span>공고 요구 항목 충족</span></div>')
    means = report["goal"].get("means")
    means_html = f'<p class="dd-means">수단 · {_e(means)}</p>' if means else ""
    return (f'<header class="dd-hero"><p class="dd-eyebrow">{_e(standalone_title)} · {_e(report["week"])}</p>'
            f'<h2>{_e(report["goal"]["title"])}</h2>{means_html}<p class="dd-lead">{_e(fix_josa(lead))}</p>'
            f'<div class="dd-stats">{"".join(stats)}</div>'
            '<p class="dd-principle">남과 견주지 않고, 내 목표와 지난주의 나를 기준으로 봐요.</p></header>')


def _coach(feedback: Optional[list[dict]], healing: str) -> str:
    if not feedback and not healing:
        return ""
    msgs = "".join(f'<div class="dd-msg"><span class="dd-pill">{_e(KIND_LABEL.get(f.get("kind"), "코치"))}</span>'
                   f'<p>{_e(f.get("text", ""))}</p></div>' for f in (feedback or []))
    rest = (f'<div class="dd-rest"><b>숲에서 잠깐 쉬어 가요</b><p>{_e(healing)}</p></div>' if healing else "")
    return (f'<section class="dd-card"><h3 class="dd-card-title">이번 주 코치의 말</h3>'
            f'<p class="dd-card-desc">기록과 체크인을 보고 골랐어요.</p>{msgs}{rest}</section>')


def _steps(report: dict) -> str:
    acts = report["next_actions"]
    if not acts:
        return ""
    note = ('<p class="dd-note">남은 시간으로는 모든 항목을 채우기 어려워요. 위에서부터 하나씩 하거나, 목표 기한을 조정해 봐요.</p>'
            if report["needs_adjustment"] else "")
    items = []
    for a in acts[:3]:
        meta = [f"약 {_num(a['hours'])}시간"]
        if a["small_step"]:
            meta.append("작은 첫걸음")
        elif a["to_level"] > a["from_level"]:
            meta.append(f"수준 {a['from_level']} → {a['to_level']}")
        if a.get("card_kind"):
            meta.append(f"끝나면 {a['card_kind']} 카드로 남기기")
        why = (f'<details class="dd-plain"><summary>왜 필요해요?</summary><p class="dd-step-how">공고 원문: '
               f'“{_e(a["source_quote"])}”</p></details>' if a.get("source_quote") else "")
        items.append(f'<li><div><p class="dd-step-title">{_e(a["title"])}</p><p class="dd-step-how">{_e(a["how"])}</p>'
                     f'<p class="dd-step-meta">{_e(" · ".join(meta))}</p>{why}</div></li>')
    return (f'<section class="dd-card"><h3 class="dd-card-title">다음 한 칸</h3>'
            f'<p class="dd-card-desc">이번 주에 해 볼 일이에요. 위에서부터 하면 돼요.</p>{note}'
            f'<ol class="dd-steps">{"".join(items)}</ol></section>')


def _hexagon(report: dict) -> str:
    legend = ('<div class="dd-legend"><span><i style="border-color:var(--dd-accent)"></i>지금의 나 (기록)</span>'
              '<span><i style="border-color:var(--dd-self)"></i>내가 본 나</span>'
              '<span><i style="border-color:var(--dd-target);border-top-style:dashed"></i>목표</span></div>')
    return (f'<section class="dd-card"><h3 class="dd-card-title">나의 육각형 능력치</h3>'
            f'<p class="dd-card-desc">경험 카드로 확인된 기록을 목표 직무가 요구하는 수준과 비교해요.</p>'
            f'<div class="dd-hex"><div>{radar_svg(report)}{legend}</div><div>{_axis_rows(report)}{_axis_table(report)}</div></div>'
            f'</section>')


def _checklist(report: dict) -> str:
    if not report["checklist"]:
        return ""
    tags = "".join(f'<span class="dd-tag{" done" if c["done"] else ""}">{"✓ " if c["done"] else ""}{_e(c["label"])}</span>'
                   for c in report["checklist"])
    return (f'<section class="dd-card"><h3 class="dd-card-title">지원 전에 챙길 것</h3>'
            f'<p class="dd-card-desc">자격증·어학·교육처럼 육각형 밖의 공고 요건이에요.</p><div class="dd-tags">{tags}</div></section>')


def _more(title: str, hint: str, body: str, open_: bool = False) -> str:
    return (f'<details class="dd-more"{" open" if open_ else ""}><summary><div>{_e(title)}<span>{_e(hint)}</span></div>'
            f'</summary><div class="dd-more-body">{body}</div></details>')


def _monthly(report: dict) -> str:
    names, parts = report["axis_names"], []
    s = report["series"]
    panels = "".join(
        f'<div><p class="dd-small-title">{_e(names[a])}</p>{axis_line_svg(names[a], s["weeks"], s["evidence"][a], s["targets"][a])}</div>'
        for a in names if s["targets"][a] is not None)
    if panels:
        parts.append(_more("주차별 변화", "점선은 목표", f'<div class="dd-small">{panels}</div>', open_=True))

    cov = report["requirement_coverage"]
    if cov["items"]:
        order = {"없음": 0, "부분": 1, "충족": 2}
        items = sorted(cov["items"], key=lambda i: (order.get(i["status"], 3), i["label"]))
        rows = "".join(f'<li><span class="dd-tag{" done" if i["status"] == "충족" else ""}">{_e(i["status"])}</span> '
                       f'<b>{_e(i["label"])}</b> <span class="dd-axis-hint">필요 {i["required"]} · 지금 {i["current"]}</span></li>'
                       for i in items)
        c = cov["counts"]
        parts.append(_more("목표 직무 요구 항목", f'충족 {c.get("충족", 0)} · 부분 {c.get("부분", 0)} · 없음 {c.get("없음", 0)}',
                           f'<ul class="dd-list">{rows}</ul>'))

    sa = report["self_awareness"]["tendency"]
    st = report["style"]
    look = []
    if sa:
        look.append('<div class="dd-tags">' + "".join(f'<span class="dd-tag">{_e(names[a])} · {_e(t)}</span>'
                                                      for a, t in sa.items()) + "</div>")
    if st.get("alignment") is not None:
        top = max(st["activity_share"], key=st["activity_share"].get) if st.get("activity_share") else None
        look.append(f'<p class="dd-step-how" style="margin-top:12px">검사로 본 성향과 실제 기록된 활동이 {_pct(st["alignment"])} 겹쳐요.'
                    + (f' 기록에서는 ‘{STYLE_NAMES.get(top, top)}’ 활동이 가장 많아요.' if top else "") + "</p>")
    if look:
        parts.append(_more("나를 보는 눈", "자기평가와 기록, 성향과 활동", "".join(look)))

    exp = []
    if report["strengths"]:
        exp.append('<ul class="dd-list">' + "".join(
            f'<li><b>{_e(x["title"])}</b><br><span class="dd-axis-hint">{_e(", ".join(x["keywords"]))}</span></li>'
            for x in report["strengths"]) + "</ul>")
    if report["tech_stack"]:
        exp.append('<p class="dd-small-title" style="margin-top:12px">써 본 도구·기법</p><div class="dd-tags">' + "".join(
            f'<span class="dd-tag">{_e(t["tool"])}{" ×" + str(t["count"]) if t["count"] > 1 else ""}</span>'
            for t in report["tech_stack"]) + "</div>")
    if exp:
        parts.append(_more("자소서·면접에 쓸 경험", "대표 경험과 도구", "".join(exp)))

    ex, mt = report["execution"], report["mentoring"]
    kv = [(f'{_num(ex["avg_hours"])}시간', f'한 주에 보통 (계획 {_num(ex["planned_hours"])}시간)')]
    if ex["milestone_completion"] is not None:
        kv.append((_pct(ex["milestone_completion"]), "할 일 완료율"))
    kv.append((f'{mt["answered"]}/{mt["asked"]}', "멘토 답변 받은 질문"))
    kv.append((f'{mt["followed_up"]}개', "조언을 행동으로 옮김"))
    parts.append(_more("실행과 멘토링", "시간·완료율·멘토링",
                       '<div class="dd-kv">' + "".join(f'<div><b>{_e(a)}</b><span>{_e(b)}</span></div>' for a, b in kv) + "</div>"))

    cond = report["condition"]
    if cond["series"]:
        tags = "".join(f'<span class="dd-tag">{_e(w)} · {c}/5</span>' for w, c in cond["series"])
        parts.append(_more("나의 컨디션 흐름", "나만 볼 수 있어요",
                           '<p class="dd-private">이 정보는 나만 볼 수 있고, 진로 점수에는 쓰이지 않아요.</p>'
                           f'<div class="dd-tags">{tags}</div>'))
    return (f'<section class="dd-card"><h3 class="dd-card-title">한 달 돌아보기</h3>'
            f'<p class="dd-card-desc">필요한 것만 펼쳐 보세요.</p>{"".join(parts)}</section>')


# ---------------------------------------------------------------- 공개 함수


def render_fragment(report: dict, feedback: Optional[list[dict]] = None, healing: str = "") -> str:
    """사이트 페이지에 그대로 끼워 넣는 조각. 범위가 한정된 <style>, 본문 <section>, 툴팁 <script>로 이뤄진다."""
    title = "월간 리포트" if report["kind"] == "monthly" else "주간 리포트"
    feedback = [{**f, "text": fix_josa(f.get("text", ""))} for f in (feedback or [])]
    blocks = [_hero(report, title)]
    coach, steps = _coach(feedback, healing), _steps(report)
    if coach and steps:
        blocks.append(f'<div class="dd-cols">{coach}{steps}</div>')
    else:
        blocks.append(coach or steps)
    blocks += [_hexagon(report), _checklist(report)]
    if report["kind"] == "monthly":
        blocks.append(_monthly(report))
    body = "".join(b for b in blocks if b)
    return (f"<style>{CSS}</style>"
            f'<section class="dd-report" aria-label="디딤돌 {_e(title)}"><div class="dd-stack">{body}</div>'
            f'<div class="dd-tip" role="tooltip"></div></section>'
            f"<script>{TOOLTIP_JS}</script>")


def render(report: dict, feedback: Optional[list[dict]] = None, healing: str = "") -> str:
    """단독으로 여는 전체 HTML 문서 (외부 리소스 없음). 시스템 다크 모드를 따른다."""
    title = "월간 리포트" if report["kind"] == "monthly" else "주간 리포트"
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>디딤돌 {_e(title)}</title>'
            f"<script>{THEME_JS}</script><style>{PAGE_CSS}</style></head>"
            f"<body>{render_fragment(report, feedback, healing)}</body></html>")


def report_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
