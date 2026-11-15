"""metrics.build_report() 결과 → 독립 실행 HTML (인라인 SVG, 외부 라이브러리 없음).

시각화 원칙 (dataviz 가이드):
- 색은 역할로만: 근거=series-1(파랑), 자기평가=series-2(주황), 지난주=series-3(청록), 목표선=회색 점선(색 아님)
  → 3색은 라이트·다크 모두 all-pairs 검증 통과. 청록은 라이트에서 대비<3:1 → 범례·라벨·표 보기 제공
- 다크 모드는 별도 단계 색(같은 색상 계열)으로 지정
- 모든 차트에 마우스오버 툴팁, 육각형은 표 보기 제공
- 텍스트는 계열 색이 아닌 본문 잉크 색
"""

from __future__ import annotations

import html
import json
import math
from typing import Optional

QUAD = {"record_proof": "기록·증명", "maintain_expand": "유지·확장",
        "learn_experience": "학습·경험", "confidence_expression": "자신감·표현"}

CSS = """
.viz-root{color-scheme:light;--surface-1:#fcfcfb;--page:#f9f9f7;--text-primary:#0b0b0b;--text-secondary:#52514e;
--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);
--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;--seq-strong:#1c5cab;--seq-mid:#6da7ec;--neutral:#e1e0d9}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;--surface-1:#1a1a19;
--page:#0d0d0d;--text-primary:#f0efec;--text-secondary:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
--border:rgba(255,255,255,.10);--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--seq-strong:#6da7ec;--seq-mid:#256abf;--neutral:#383835}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--surface-1:#1a1a19;--page:#0d0d0d;--text-primary:#f0efec;
--text-secondary:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--seq-strong:#6da7ec;--seq-mid:#256abf;--neutral:#383835}
body{margin:0;background:var(--page)}
.viz-root{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--text-primary);background:var(--page);
padding:24px 16px;max-width:960px;margin:0 auto;line-height:1.5}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:0 0 12px}
.sub{color:var(--text-secondary);font-size:14px;margin:0 0 20px}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(150px,100%),1fr));gap:12px;margin-bottom:16px}
.tile{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:14px}
.tile .label{font-size:13px;color:var(--text-secondary)}.tile .value{font-size:28px;font-weight:600}
.tile .note{font-size:12px;color:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;color:var(--text-secondary);margin-bottom:8px}
.legend i{display:inline-block;width:14px;height:0;border-top:2px solid;margin-right:6px;vertical-align:middle}
.radar-wrap{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;align-items:start}
@media (max-width:700px){.radar-wrap{grid-template-columns:1fr}}
svg{max-width:100%;height:auto;display:block}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid)}
th{color:var(--text-secondary);font-weight:500}td.num{font-variant-numeric:tabular-nums}
.small-multiples{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:12px}
.table-scroll{overflow-x:auto}
.panel-title{font-size:13px;color:var(--text-secondary);margin-bottom:4px}
.action{border-top:1px solid var(--grid);padding:10px 0}.action:first-child{border-top:0}
.action b{display:block}.action span{color:var(--text-secondary);font-size:13px}
.chip{display:inline-block;font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--border);
color:var(--text-secondary);margin:2px 4px 2px 0}
.private{font-size:12px;color:var(--muted)}
#tip{position:fixed;pointer-events:none;background:var(--surface-1);color:var(--text-primary);border:1px solid var(--border);
border-radius:8px;padding:6px 10px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.12);display:none;z-index:9;max-width:240px}
details summary{cursor:pointer;color:var(--text-secondary);font-size:13px;margin-top:8px}
"""

TOOLTIP_JS = """
const tip=document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el=>{
 el.addEventListener('mousemove',e=>{tip.textContent=el.dataset.tip;tip.style.display='block';
  const x=Math.min(e.clientX+12,window.innerWidth-tip.offsetWidth-8);tip.style.left=x+'px';tip.style.top=(e.clientY+12)+'px';});
 el.addEventListener('mouseleave',()=>{tip.style.display='none';});
});
"""


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _fmt(v: Optional[float], pct: bool = False) -> str:
    if v is None:
        return "-"
    return f"{v * 100:.0f}%" if pct else f"{v:g}"


# ---------------------------------------------------------------- 육각형 (레이더)


def radar_svg(report: dict) -> str:
    names, axes, prev = report["axis_names"], report["axes"], report.get("previous_axes")
    ids = list(names)
    # 축 이름이 잘리지 않도록 좌우 여백을 넉넉히 (라벨은 그래프 바깥 1.15R 지점, 최대 ~9자)
    W, size, cx, cy, R = 480, 340, 240, 170, 110

    def pt(i: int, v: Optional[float]) -> tuple[float, float]:
        ang = -math.pi / 2 + 2 * math.pi * i / len(ids)
        r = R * ((v or 1) - 1) / 4
        return cx + r * math.cos(ang), cy + r * math.sin(ang)

    parts = [f'<svg viewBox="0 0 {W} {size}" role="img" aria-label="육각형 능력치: 목표선, 근거, 자기평가, 지난주">']
    for lv in range(2, 6):  # 그리드 링
        ring = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, lv) for i in range(len(ids))))
        parts.append(f'<polygon points="{ring}" fill="none" stroke="var(--grid)" stroke-width="1"/>')
    for i, a in enumerate(ids):  # 축선 + 라벨
        x, y = pt(i, 5)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="var(--grid)" stroke-width="1"/>')
        lx, ly = pt(i, 5.6)
        anchor = "middle" if abs(lx - cx) < 10 else ("start" if lx > cx else "end")
        linked = axes[a]["target"] is not None
        color = "var(--text-secondary)" if linked else "var(--muted)"
        dy = -6 if ly < cy - 10 else (14 if ly > cy + 10 else 4)
        parts.append(f'<text x="{lx:.1f}" y="{ly + dy:.1f}" text-anchor="{anchor}" font-size="12" fill="{color}">'
                     f'{_e(names[a])}</text>')
        if not linked:  # '해당 없음'은 둘째 줄로 (폭 절약)
            parts.append(f'<text x="{lx:.1f}" y="{ly + dy + 14:.1f}" text-anchor="{anchor}" font-size="11" '
                         f'fill="var(--muted)">해당 없음</text>')

    def poly(values: list[Optional[float]], color: str, dash: str = "", fill: bool = False) -> str:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, v) for i, v in enumerate(values)))
        f = f'fill="{color}" fill-opacity=".10"' if fill else 'fill="none"'
        d = f'stroke-dasharray="{dash}"' if dash else ""
        return f'<polygon points="{pts}" {f} stroke="{color}" stroke-width="2" {d} stroke-linejoin="round"/>'

    parts.append(poly([axes[a]["target"] for a in ids], "var(--muted)", "4 4"))
    if prev:
        parts.append(poly([prev[a]["evidence"] for a in ids], "var(--series-3)", "2 3"))
    parts.append(poly([axes[a]["self"] for a in ids], "var(--series-2)"))
    parts.append(poly([axes[a]["evidence"] for a in ids], "var(--series-1)", fill=True))
    for i, a in enumerate(ids):  # 근거 꼭짓점: 마커(≥8px) + 표면 링 + 넉넉한 툴팁 영역
        v = axes[a]["evidence"]
        if v is None:
            continue
        x, y = pt(i, v)
        tip = (f"{names[a]} · 근거 {_fmt(v)} / 목표 {_fmt(axes[a]['target'])} / 자기평가 {_fmt(axes[a]['self'])}"
               + (f" → {QUAD[axes[a]['quadrant']]}" if axes[a]["quadrant"] else ""))
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"/>')
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="14" fill="transparent" data-tip="{_e(tip)}"/>')
    parts.append("</svg>")
    return "".join(parts)


def radar_table(report: dict) -> str:
    names, axes, prev = report["axis_names"], report["axes"], report.get("previous_axes")
    rows = "".join(
        f"<tr><td>{_e(names[a])}</td><td class='num'>{_fmt(s['target'])}</td><td class='num'>{_fmt(s['evidence'])}</td>"
        f"<td class='num'>{_fmt(s['self'])}</td><td class='num'>{_fmt(prev[a]['evidence']) if prev else '-'}</td>"
        f"<td>{_e(QUAD.get(s['quadrant'], '-'))}</td></tr>"
        for a, s in axes.items())
    return ("<div class='table-scroll'><table><thead><tr><th>축</th><th>목표선</th><th>근거</th><th>자기평가</th>"
            f"<th>지난주 근거</th><th>방향</th></tr></thead><tbody>{rows}</tbody></table></div>")


# ---------------------------------------------------------------- 시계열 (작은 다중 차트)


def axis_line_svg(name: str, weeks: list[str], values: list[Optional[float]], target: Optional[float]) -> str:
    W, H, L, B, T, Rr = 280, 140, 28, 22, 10, 10
    n = len(weeks)

    def x(i): return L + (W - L - Rr) * (i / (n - 1) if n > 1 else 0.5)
    def y(v): return T + (H - T - B) * (1 - ((v or 1) - 1) / 4)

    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{_e(name)} 주간 근거 점수">']
    for v in (1, 3, 5):
        p.append(f'<line x1="{L}" x2="{W - Rr}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="var(--grid)" stroke-width="1"/>'
                 f'<text x="{L - 6}" y="{y(v) + 4:.1f}" font-size="10" text-anchor="end" fill="var(--muted)">{v}</text>')
    if target is not None:
        p.append(f'<line x1="{L}" x2="{W - Rr}" y1="{y(target):.1f}" y2="{y(target):.1f}" stroke="var(--muted)" '
                 f'stroke-width="1.5" stroke-dasharray="4 4"/><text x="{W - Rr}" y="{y(target) - 4:.1f}" font-size="10" '
                 f'text-anchor="end" fill="var(--text-secondary)">목표 {target:g}</text>')
    pts = [(x(i), y(v), v, weeks[i]) for i, v in enumerate(values) if v is not None]
    if pts:
        p.append('<polyline fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round" points="'
                 + " ".join(f"{a:.1f},{b:.1f}" for a, b, _, _ in pts) + '"/>')
        for a, b, v, w in pts:
            p.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="4" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"/>'
                     f'<rect x="{a - 12:.1f}" y="{T}" width="24" height="{H - T - B}" fill="transparent" '
                     f'data-tip="{_e(f"{w} · {name} 근거 {v:g}")}"/>')
        a, b, v, _ = pts[-1]
        # 목표선 라벨과 겹치면 값 라벨을 점 아래로
        below = target is not None and abs(y(v) - y(target)) < 16
        p.append(f'<text x="{a - 6:.1f}" y="{b + (16 if below else -8):.1f}" font-size="11" text-anchor="end" '
                 f'fill="var(--text-primary)">현재 {v:g}</text>')
    for i in (0, n - 1) if n > 1 else (0,):
        p.append(f'<text x="{x(i):.1f}" y="{H - 6}" font-size="10" text-anchor="{"start" if i == 0 else "end"}" '
                 f'fill="var(--muted)">{_e(weeks[i])}</text>')
    p.append("</svg>")
    return "".join(p)


# ---------------------------------------------------------------- 요구 항목 커버리지 (가로 누적 막대)


def coverage_bar(cov: dict) -> str:
    counts, total = cov["counts"], sum(cov["counts"].values()) or 1
    order = [("충족", "var(--seq-strong)"), ("부분", "var(--seq-mid)"), ("없음", "var(--neutral)")]
    W, H, x, gap = 600, 28, 0.0, 2
    segs = []
    for label, color in order:
        c = counts.get(label, 0)
        if not c:
            continue
        w = W * c / total - gap
        segs.append(f'<rect x="{x:.1f}" y="0" width="{max(w, 1):.1f}" height="{H}" rx="4" fill="{color}" '
                    f'data-tip="{_e(f"{label} {c}개 / 전체 {total}개")}"/>')
        x += w + gap
    legend = "".join(f'<span><i style="border-color:{c};border-top-width:8px"></i>{l} {counts.get(l, 0)}</span>'
                     for l, c in order)
    return (f'<div class="legend">{legend}</div><svg viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="요구 항목 커버리지">{"".join(segs)}</svg>')


# ---------------------------------------------------------------- 페이지


def render(report: dict, feedback: Optional[list[dict]] = None, healing: str = "") -> str:
    names = report["axis_names"]
    gp, growth = report["goal_progress"], report["growth"]
    title = f"{'월간' if report['kind'] == 'monthly' else '주간'} 리포트"
    tiles = [("목표 달성도", _fmt(gp["achievement"], pct=True), "목표선 대비 근거"),
             ("남은 기간", f"{report['goal']['weeks_left']}주", "목표 기한까지")]
    if growth["most_grown"]:
        d = growth["deltas"][growth["most_grown"]]
        tiles.append(("이번에 가장 자란 축", names[growth["most_grown"]], f"근거 +{d:g}"))
    if report["kind"] == "monthly" and report["execution"]["milestone_completion"] is not None:
        ex = report["execution"]
        tiles.append(("마일스톤 완료", _fmt(ex["milestone_completion"], pct=True),
                      f"{ex['milestones_done']}/{ex['milestones_total']}개"))

    body = [f'<h1>{_e(title)} · {_e(report["goal"]["title"])}</h1>',
            f'<p class="sub">{_e(report["week"])} 기준 · 남과 견주지 않고, 내 목표와 지난주의 나를 기준으로 봐요.</p>',
            '<div class="tiles">' + "".join(
                f'<div class="tile"><div class="label">{_e(l)}</div><div class="value">{_e(v)}</div>'
                f'<div class="note">{_e(n)}</div></div>' for l, v, n in tiles) + "</div>"]

    if feedback:
        kinds = {"praise": "칭찬", "encourage": "격려", "push": "한 걸음 더"}
        items = "".join(f'<div class="action"><b>{_e(kinds.get(f["kind"], ""))}</b><span>{_e(f["text"])}</span></div>'
                        for f in feedback)
        if healing:
            items += f'<div class="action"><b>숲에서 쉬어 가기</b><span>{_e(healing)}</span></div>'
        body.append(f'<div class="card"><h2>이번 주 코치의 말</h2>{items}</div>')

    legend = ('<div class="legend"><span><i style="border-color:var(--series-1)"></i>근거 점수</span>'
              '<span><i style="border-color:var(--series-2)"></i>자기평가</span>'
              + ('<span><i style="border-color:var(--series-3);border-top-style:dotted"></i>지난주 근거</span>'
                 if report.get("previous_axes") else "")
              + '<span><i style="border-color:var(--muted);border-top-style:dashed"></i>목표선</span></div>')
    body.append(f'<div class="card"><h2>육각형 능력치</h2>{legend}<div class="radar-wrap"><div>{radar_svg(report)}</div>'
                f'<div>{radar_table(report)}</div></div></div>')

    acts = report["next_actions"]
    if acts:
        rows = "".join(
            f'<div class="action"><b>{_e(a["title"])}</b><span>{_e(a["how"])}</span><br>'
            f'<span class="chip">약 {a["hours"]:g}시간</span>'
            + (f'<span class="chip">수준 {a["from_level"]}→{a["to_level"]}</span>' if not a["small_step"] else '<span class="chip">작은 첫걸음</span>')
            + (f'<span class="chip">끝나면 {_e(a["card_kind"])} 카드</span>' if a["card_kind"] else "")
            + (f'<br><span>근거: “{_e(a["source_quote"])}”</span>' if a["source_quote"] else "")
            + "</div>" for a in acts)
        warn = '<p class="sub">남은 시간으로는 모든 갭을 메우기 어려워요. 우선순위 높은 것부터 하거나 목표 기한을 조정해 봐요.</p>' \
            if report["needs_adjustment"] else ""
        body.append(f'<div class="card"><h2>다음 한 칸</h2>{warn}{rows}</div>')

    if report["checklist"]:
        items = "".join(f'<span class="chip">{"✓" if c["done"] else "○"} {_e(c["label"])}</span>' for c in report["checklist"])
        body.append(f'<div class="card"><h2>공고 체크리스트</h2>{items}</div>')

    if report["kind"] == "monthly":
        s = report["series"]
        panels = "".join(
            f'<div><div class="panel-title">{_e(names[a])}</div>{axis_line_svg(names[a], s["weeks"], s["evidence"][a], s["targets"][a])}</div>'
            for a in names if s["targets"][a] is not None)
        body.append(f'<div class="card"><h2>축별 근거 점수 추이</h2><div class="small-multiples">{panels}</div></div>')
        body.append(f'<div class="card"><h2>목표 직무 요구 항목</h2>{coverage_bar(report["requirement_coverage"])}'
                    '<details><summary>항목별 보기</summary><table><thead><tr><th>항목</th><th>필요</th><th>현재</th>'
                    '<th>상태</th></tr></thead><tbody>' + "".join(
                        f"<tr><td>{_e(i['label'])}</td><td class='num'>{i['required']}</td><td class='num'>{i['current']}</td>"
                        f"<td>{_e(i['status'])}</td></tr>" for i in report["requirement_coverage"]["items"])
                    + "</tbody></table></details></div>")
        sa = report["self_awareness"]["tendency"]
        if sa:
            body.append('<div class="card"><h2>나를 보는 눈</h2>' + "".join(
                f'<span class="chip">{_e(names[a])}: {_e(t)}</span>' for a, t in sa.items()) + "</div>")
        if report["strengths"]:
            body.append('<div class="card"><h2>자소서·면접에 쓸 대표 경험</h2>' + "".join(
                f'<div class="action"><b>{_e(st["title"])}</b><span>{_e(", ".join(st["keywords"]))}</span></div>'
                for st in report["strengths"]) + "</div>")
        if report["tech_stack"]:
            body.append('<div class="card"><h2>써 본 도구·기법</h2>' + "".join(
                f'<span class="chip">{_e(t["tool"])} ×{t["count"]}</span>' for t in report["tech_stack"]) + "</div>")
        st = report["style"]
        if st["alignment"] is not None:
            body.append(f'<div class="card"><h2>성향과 활동</h2><p class="sub">검사로 본 성향과 실제 기록된 활동이 '
                        f'{_fmt(st["alignment"], pct=True)} 겹쳐요.</p></div>')
        ex, mt = report["execution"], report["mentoring"]
        body.append(f'<div class="card"><h2>실행과 멘토링</h2><p class="sub">한 주에 보통 {_fmt(ex["avg_hours"])}시간 '
                    f'(계획 {ex["planned_hours"]:g}시간) · 멘토 질문 {mt["asked"]}개, 답변 {mt["answered"]}개, '
                    f'조언을 행동으로 옮김 {mt["followed_up"]}개</p></div>')
        cond = report["condition"]
        if cond["series"]:
            body.append('<div class="card"><h2>나의 컨디션 흐름</h2><p class="private">이 정보는 나만 볼 수 있고, '
                        '진로 점수에는 쓰이지 않아요.</p>' + "".join(
                            f'<span class="chip">{_e(w)} · {c}/5</span>' for w, c in cond["series"]) + "</div>")

    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>디딤돌 {_e(title)}</title><style>{CSS}</style></head>'
            f'<body><div class="viz-root">{"".join(body)}</div><div id="tip" role="tooltip"></div>'
            f"<script>{TOOLTIP_JS}</script></body></html>")


def report_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
