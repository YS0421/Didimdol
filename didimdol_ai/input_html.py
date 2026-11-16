"""자기상태표 입력 화면: 사이트(didimdol.cloud) 자기상태표 페이지에 그대로 끼워 넣는 조각.

세 탭으로 구성한다. 처음 열리는 탭은 목표·기본 정보다.
1) 목표·기본 정보 — 학적 상태, 관심 분야, 주당 시간, 코치 톤, 자유 목표 문장. 관련 인턴은 있을 때만 수단으로 고정
2) 경험 카드     — 직접 쓰기 / 파일·사진 올려 AI 초안 받기(확인 후 저장)
3) 이번 주 체크인 — 6축 자기평가(단계 설명이 바로 보임, 지난주 값 미리 채움), 지난주 할 일 결과, 쓴 시간, 컨디션

저장 방식 (API 키가 브라우저로 나가지 않게):
- 저장할 때마다 이 조각이 `didimdol:save` 이벤트를 보낸다 (detail = {type, payload}). payload는 디딤돌 AI API 요청 형식과 같다.
  type: "checkin"(CheckinIn) | "card"(CardIn) | "profile"(ProfileIn + goal) | "draft"(파일 → 초안 요청)
- config.endpoints[type]이 있으면 그 주소(G7 서버 경로)로 같은 출처 요청을 보낸다. G7 서버가 사용자 DB에 저장하고,
  분석이 필요하면 서버에서 디딤돌 AI API를 부른다. 이벤트에서 preventDefault()를 부르면 조각은 직접 보내지 않는다.

디자인: 리포트(report_html)와 같은 사이트 토큰, .dd-input 아래로 범위를 한정한 CSS, 사이트 다크 모드(.dark) 따름.
"""

from __future__ import annotations

import html
import json
from typing import Optional

from .config import load_axes

KINDS = ["수업", "수업 프로젝트", "학부연구생", "공모전", "인턴", "동아리", "독학", "자격증"]
FIELDS = {"mech": "기계항공", "elec": "전기전자", "chem": "화학생명", "it": "IT", "ai": "AI데이터",
          "material": "소재재료", "energy": "에너지환경", "infra": "건설인프라"}
HOLD_REASONS = {"time": "시간이 부족했어요", "external": "상황 때문에 못 했어요", "unclear": "방법을 잘 몰랐어요",
                "motivation": "마음이 잘 안 났어요"}
HOURS = [(0.5, "1시간 미만"), (2, "1~3시간"), (4.5, "3~6시간"), (8, "6~10시간"), (12, "10시간 이상")]
CONDITION = [(1, "많이 지쳤어요"), (2, "조금 지쳤어요"), (3, "보통이에요"), (4, "괜찮아요"), (5, "아주 좋아요")]
TONES = {"praise": ("칭찬형", "잘한 점을 먼저 짚어 줘요."),
         "balanced": ("균형형", "잘한 점과 다음 할 일을 함께 말해 줘요."),
         "direct": ("직설형", "부족한 점을 분명하게 짚어 줘요.")}
STATUS = {"enrolled": "재학·휴학 중", "expected": "졸업 예정", "graduated": "졸업"}

CSS = """
.dd-input{--dd-surface:#fff;--dd-soft:#eff7f2;--dd-mint:#e4f3eb;--dd-line:#dce8e0;--dd-ink:#153d31;--dd-text:#1e2939;
--dd-muted:#687b74;--dd-accent:#007e5c;--dd-accent-soft:#e4f3eb;--dd-on-accent:#fff;--dd-field:#fff;--dd-danger:#b42318;
--dd-warn-bg:#fdf6e7;--dd-warn:#7a5512;color-scheme:light;font-family:inherit;color:var(--dd-text);line-height:1.65;
letter-spacing:-0.2px;max-width:1200px;margin:0 auto;-webkit-font-smoothing:antialiased}
:where(.dark,[data-theme="dark"]) .dd-input{--dd-surface:#1e2939;--dd-soft:#28354a;--dd-mint:#1e2939;--dd-line:#364153;
--dd-ink:#fff;--dd-text:#e5e7eb;--dd-muted:#99a1af;--dd-accent:#00d492;--dd-accent-soft:rgba(0,212,146,.14);--dd-on-accent:#0b2a1f;
--dd-field:#101828;--dd-danger:#f97066;--dd-warn-bg:rgba(240,180,90,.12);--dd-warn:#f0c987;color-scheme:dark}
.dd-input *{box-sizing:border-box}
.dd-input h2,.dd-input h3,.dd-input p,.dd-input fieldset{margin:0}
.dd-input fieldset{border:0;padding:0;min-width:0}
.dd-input .dd-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.dd-input .dd-head{background:var(--dd-mint);border:1px solid var(--dd-mint);border-radius:24px;padding:28px;margin-bottom:20px}
:where(.dark,[data-theme="dark"]) .dd-input .dd-head{border-color:var(--dd-line)}
.dd-input .dd-head h2{font-size:24px;font-weight:700;color:var(--dd-ink);letter-spacing:-0.6px;line-height:1.4}
.dd-input .dd-head p{font-size:15px;color:var(--dd-muted);margin-top:6px}
/* 탭 */
.dd-input .dd-tabs{display:flex;gap:24px;border-bottom:1px solid var(--dd-line);margin-bottom:20px;overflow-x:auto}
.dd-input .dd-tab{appearance:none;background:none;border:0;padding:12px 0;font:inherit;font-size:15px;color:var(--dd-muted);
cursor:pointer;position:relative;white-space:nowrap;letter-spacing:-0.4px}
.dd-input .dd-tab[aria-selected="true"]{color:var(--dd-accent);font-weight:700}
.dd-input .dd-tab[aria-selected="true"]::after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:2px;background:var(--dd-accent)}
.dd-input .dd-tab small{font-size:12px;color:var(--dd-muted);font-weight:400;margin-left:4px}
.dd-input .dd-tab:focus-visible{outline:2px solid var(--dd-accent);outline-offset:4px;border-radius:4px}
/* 카드·구역 */
.dd-input .dd-card{background:var(--dd-surface);border:1px solid var(--dd-line);border-radius:20px;padding:24px;margin-bottom:16px}
.dd-input .dd-card-title{font-size:18px;font-weight:700;color:var(--dd-ink);letter-spacing:-0.4px}
.dd-input .dd-card-desc{font-size:14px;color:var(--dd-muted);margin:2px 0 16px}
.dd-input .dd-label{display:block;font-size:15px;font-weight:700;color:var(--dd-ink);margin-bottom:2px}
.dd-input .dd-hint{display:block;font-size:13px;color:var(--dd-muted);margin-bottom:8px}
.dd-input .dd-row{margin-bottom:20px}
.dd-input .dd-row:last-child{margin-bottom:0}
.dd-input .dd-grid2{display:grid;grid-template-columns:1fr;gap:0 16px}
@media (min-width:720px){.dd-input .dd-grid2{grid-template-columns:1fr 1fr;align-items:end}}
/* 입력 */
.dd-input input[type=text],.dd-input input[type=number],.dd-input textarea,.dd-input select{width:100%;font:inherit;font-size:15px;
color:var(--dd-ink);background:var(--dd-field);border:1px solid var(--dd-line);border-radius:10px;padding:12px 14px;letter-spacing:-0.4px}
.dd-input textarea{resize:vertical;min-height:112px}
.dd-input input::placeholder,.dd-input textarea::placeholder{color:var(--dd-muted)}
.dd-input input:focus,.dd-input textarea:focus,.dd-input select:focus{outline:none;border-color:var(--dd-accent);
box-shadow:0 0 0 3px var(--dd-accent-soft)}
.dd-input .dd-count{display:block;text-align:right;font-size:12px;color:var(--dd-muted);margin-top:4px}
.dd-input .dd-error{display:block;font-size:13px;color:var(--dd-danger);margin-top:4px}
/* 고르기 버튼 (라디오·체크박스) */
.dd-input .dd-choices{display:flex;flex-wrap:wrap;gap:8px}
.dd-input .dd-choice{position:relative}
.dd-input .dd-choice input{position:absolute;opacity:0;inset:0;width:100%;height:100%;margin:0;cursor:pointer}
.dd-input .dd-choice span{display:inline-flex;align-items:center;justify-content:center;min-height:40px;padding:8px 14px;
border-radius:10px;border:1px solid var(--dd-line);background:var(--dd-field);font-size:14px;color:var(--dd-text);
letter-spacing:-0.4px;transition:background .12s,border-color .12s}
.dd-input .dd-choice input:checked+span{background:var(--dd-accent-soft);border-color:var(--dd-accent);color:var(--dd-accent);font-weight:700}
.dd-input .dd-choice input:focus-visible+span{outline:2px solid var(--dd-accent);outline-offset:2px}
.dd-input .dd-choice:hover span{border-color:var(--dd-accent)}
/* 6축 단계 */
.dd-input .dd-axis{padding:16px 0;border-top:1px solid var(--dd-line)}
.dd-input .dd-axis:first-of-type{border-top:0;padding-top:0}
.dd-input .dd-axis legend{display:flex;width:100%;justify-content:space-between;align-items:baseline;gap:8px;
padding:0;margin-bottom:8px;font-size:16px;font-weight:700;color:var(--dd-ink)}
.dd-input .dd-was{font-size:13px;color:var(--dd-muted);white-space:nowrap}
.dd-input .dd-was b{color:var(--dd-accent)}
.dd-input .dd-steps{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}
.dd-input .dd-steps .dd-choice span{width:100%;min-height:44px;font-size:15px;font-weight:600}
.dd-input .dd-anchor{margin-top:10px;background:var(--dd-soft);border-radius:12px;padding:10px 14px;font-size:14px;color:var(--dd-text);min-height:44px}
.dd-input .dd-anchor b{color:var(--dd-accent);margin-right:6px}
/* 할 일 */
.dd-input .dd-task{padding:14px 0;border-top:1px solid var(--dd-line)}
.dd-input .dd-task:first-of-type{border-top:0;padding-top:0}
.dd-input .dd-task-title{font-size:15px;font-weight:700;color:var(--dd-ink);margin-bottom:8px}
.dd-input .dd-reason{margin-top:10px}
.dd-input .dd-reason[hidden]{display:none}
.dd-input .dd-private{font-size:13px;color:var(--dd-muted);margin-top:8px}
/* 버튼 */
.dd-input .dd-actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:flex-end;margin-top:4px}
.dd-input .dd-btn{appearance:none;font:inherit;font-size:15px;font-weight:700;letter-spacing:-0.4px;min-height:46px;padding:10px 20px;
border-radius:10px;border:1px solid var(--dd-line);background:var(--dd-field);color:var(--dd-accent);cursor:pointer}
.dd-input .dd-btn.primary{background:var(--dd-accent);border-color:var(--dd-accent);color:var(--dd-on-accent)}
.dd-input .dd-btn:hover{filter:brightness(1.05)}
.dd-input .dd-btn:focus-visible{outline:2px solid var(--dd-accent);outline-offset:2px}
.dd-input .dd-btn[disabled]{opacity:.5;cursor:default}
.dd-input .dd-btn.small{min-height:36px;padding:6px 14px;font-size:14px}
.dd-input .dd-status{font-size:14px;color:var(--dd-accent);margin-right:auto}
.dd-input .dd-status.err{color:var(--dd-danger)}
/* 카드 목록·초안 */
.dd-input .dd-saved{list-style:none;margin:0;padding:0}
.dd-input .dd-saved li{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:12px 0;border-top:1px solid var(--dd-line)}
.dd-input .dd-saved li:first-child{border-top:0;padding-top:0}
.dd-input .dd-saved b{display:block;color:var(--dd-ink);font-size:15px}
.dd-input .dd-saved small{color:var(--dd-muted);font-size:13px}
.dd-input .dd-empty{font-size:14px;color:var(--dd-muted)}
.dd-input .dd-drop{display:flex;flex-direction:column;align-items:center;gap:6px;text-align:center;border:1.5px dashed var(--dd-line);
border-radius:16px;padding:22px 16px;background:var(--dd-soft);cursor:pointer}
.dd-input .dd-drop:hover,.dd-input .dd-drop.over{border-color:var(--dd-accent)}
.dd-input .dd-drop b{color:var(--dd-ink);font-size:15px}
.dd-input .dd-drop small{color:var(--dd-muted);font-size:13px}
.dd-input .dd-draft{border:1px solid var(--dd-line);border-radius:16px;padding:16px;margin-top:12px}
.dd-input .dd-draft b{color:var(--dd-ink)}
.dd-input .dd-draft p{font-size:14px;margin-top:4px}
.dd-input .dd-quote{font-size:13px;color:var(--dd-muted);margin-top:6px}
.dd-input .dd-qs{margin:8px 0 0;padding-left:18px;font-size:13px;color:var(--dd-warn)}
.dd-input .dd-note{background:var(--dd-warn-bg);color:var(--dd-warn);border-radius:12px;padding:10px 14px;font-size:14px;margin-top:12px}
.dd-input .dd-tone{display:grid;grid-template-columns:1fr;gap:8px}
@media (min-width:720px){.dd-input .dd-tone{grid-template-columns:repeat(3,1fr)}}
.dd-input .dd-tone .dd-choice span{flex-direction:column;align-items:flex-start;width:100%;padding:12px 14px;text-align:left}
.dd-input .dd-tone .dd-choice small{font-size:13px;font-weight:400;color:var(--dd-muted)}
.dd-input input[type=range]{width:100%;accent-color:var(--dd-accent)}
.dd-input .dd-range-val{font-size:15px;font-weight:700;color:var(--dd-accent)}
.dd-input [hidden]{display:none!important}
@media (max-width:560px){.dd-input .dd-card{padding:20px 16px}.dd-input .dd-head{padding:22px 18px}.dd-input .dd-head h2{font-size:21px}
.dd-input .dd-steps{gap:4px}.dd-input .dd-actions{justify-content:stretch}.dd-input .dd-actions .dd-btn{flex:1}}
"""

JS = r"""
(function(){
function el(tag,attrs,kids){var e=document.createElement(tag);for(var k in (attrs||{})){var v=attrs[k];if(v==null||v===false)continue;
 if(k==='text')e.textContent=v;else if(k==='class')e.className=v;else if(k.slice(0,2)==='on')e.addEventListener(k.slice(2),v);else e.setAttribute(k,v===true?'':v);}
 (kids||[]).forEach(function(c){if(c!=null)e.appendChild(typeof c==='string'?document.createTextNode(c):c);});return e;}
function uid(){return 'c'+Date.now().toString(36)+Math.random().toString(36).slice(2,6);}
function xsrf(){var m=document.cookie.match(/(?:^|; )XSRF-TOKEN=([^;]+)/);return m?decodeURIComponent(m[1]):null;}

function Widget(root){
 var C=JSON.parse(root.querySelector('script[type="application/json"]').textContent);
 var S={ratings:Object.assign({},C.last_ratings||{}),tasks:{},hours:null,condition:null,cards:(C.cards||[]).slice(),editing:null,
  profile:Object.assign({status:'enrolled',interest_fields:[],weekly_hours:6,coach_tone:'balanced'},C.profile||{}),
  goal:C.goal?Object.assign({},C.goal):null,drafts:[]};
 var gid=root.getAttribute('data-dd-id');
 function name(n){return gid+'-'+n;}

 // 저장: 이벤트 → (막지 않았으면) G7 경로로 전송
 function save(type,payload,statusEl,done){
  var ev=new CustomEvent('didimdol:save',{detail:{type:type,payload:payload},bubbles:true,cancelable:true});
  var go=root.dispatchEvent(ev);var url=(C.endpoints||{})[type];
  function ok(res){setStatus(statusEl,'저장했어요.');if(done)done(res);}
  function fail(msg){setStatus(statusEl,msg||'저장하지 못했어요. 잠시 뒤 다시 시도해 주세요.',true);}
  if(!go||!url){ok(null);return;}
  var h={'Accept':'application/json'};var t=xsrf();if(t)h['X-XSRF-TOKEN']=t;
  var body;if(payload instanceof FormData){body=payload;}else{h['Content-Type']='application/json';body=JSON.stringify(payload);}
  setStatus(statusEl,'저장하는 중이에요…');
  fetch(url,{method:'POST',credentials:'same-origin',headers:h,body:body}).then(function(r){
   return r.json().catch(function(){return {};}).then(function(j){if(!r.ok)throw new Error(j.message||j.detail||'');return j;});
  }).then(ok).catch(function(e){fail(e.message);});
 }
 function setStatus(s,msg,err){if(!s)return;s.textContent=msg;s.className='dd-status'+(err?' err':'');}

 // ── 탭
 var tabs=[['profile','목표·기본 정보',''],['cards','경험 카드',''],['checkin','이번 주 체크인','2분']];
 var tabBar=el('div',{class:'dd-tabs',role:'tablist','aria-label':'자기상태표 입력'});
 var panels={};
 tabs.forEach(function(t,i){
  var b=el('button',{type:'button',role:'tab',class:'dd-tab',id:name('tab-'+t[0]),'aria-controls':name('panel-'+t[0]),
   'aria-selected':'false',tabindex:'-1',onclick:function(){select(t[0]);}},[t[1],t[2]?el('small',{text:t[2]}):null]);
  b.addEventListener('keydown',function(e){var k=e.key;if(k!=='ArrowRight'&&k!=='ArrowLeft')return;e.preventDefault();
   var n=tabs[(i+(k==='ArrowRight'?1:tabs.length-1))%tabs.length][0];select(n);root.querySelector('#'+name('tab-'+n)).focus();});
  tabBar.appendChild(b);
  panels[t[0]]=el('div',{role:'tabpanel',id:name('panel-'+t[0]),'aria-labelledby':name('tab-'+t[0]),hidden:true});
 });
 function select(k){tabs.forEach(function(t){var on=t[0]===k;var b=root.querySelector('#'+name('tab-'+t[0]));
  b.setAttribute('aria-selected',on?'true':'false');b.tabIndex=on?0:-1;panels[t[0]].hidden=!on;});}

 function choice(type,group,value,label,checked,onchange,extra){
  var inp=el('input',{type:type,name:group,value:String(value),checked:!!checked,onchange:onchange});
  return el('label',{class:'dd-choice'},[inp,el('span',{},[label].concat(extra||[]))]);
 }
 function field(labelText,hint,control,id){
  return el('div',{class:'dd-row'},[el('label',{class:'dd-label',for:id,text:labelText}),hint?el('span',{class:'dd-hint',text:hint}):null,control]);
 }
 function counted(ctrl,max){var c=el('span',{class:'dd-count'});function u(){c.textContent=ctrl.value.length+' / '+max;}
  ctrl.setAttribute('maxlength',max);ctrl.addEventListener('input',u);u();return el('div',{},[ctrl,c]);}

 // ── 1) 체크인
 (function(){
  var p=panels.checkin;
  var card1=el('section',{class:'dd-card'},[el('h3',{class:'dd-card-title',text:'6축 자기평가'}),
   el('p',{class:'dd-card-desc',text:'지난주 값을 미리 채워 뒀어요. 달라진 축만 바꾸면 돼요. 단계를 고르면 그 단계가 어떤 모습인지 보여요.'})]);
  C.axes.forEach(function(a){
   var was=(C.last_ratings||{})[a.id];
   var anchor=el('p',{class:'dd-anchor','aria-live':'polite'});
   var wasEl=el('span',{class:'dd-was'});
   function upd(){var v=S.ratings[a.id];anchor.textContent='';
    if(v){anchor.appendChild(el('b',{text:v+'단계'}));anchor.appendChild(document.createTextNode(a.anchors[String(v)]));}
    else anchor.appendChild(document.createTextNode('아직 고르지 않았어요.'));
    wasEl.textContent='';if(was){if(v&&v!==was){wasEl.appendChild(document.createTextNode('지난주 '+was+' → '));wasEl.appendChild(el('b',{text:String(v)}));}
     else wasEl.textContent='지난주 '+was;}}
   var steps=el('div',{class:'dd-steps'});
   for(var i=1;i<=5;i++){(function(i){steps.appendChild(choice('radio',name('ax-'+a.id),i,String(i),S.ratings[a.id]===i,function(){S.ratings[a.id]=i;upd();}));})(i);}
   card1.appendChild(el('div',{class:'dd-axis'},[el('fieldset',{},[el('legend',{},[el('span',{text:a.name}),wasEl]),steps,anchor])]));
   upd();
  });
  p.appendChild(card1);

  if((C.milestones||[]).length){
   var card2=el('section',{class:'dd-card'},[el('h3',{class:'dd-card-title',text:'지난주 할 일'}),
    el('p',{class:'dd-card-desc',text:'못 했어도 괜찮아요. 이유를 알려 주면 다음 할 일을 더 작게 나눠 드려요.'})]);
   C.milestones.forEach(function(m){
    S.tasks[m.milestone_id]={milestone_id:m.milestone_id,title:m.title,status:null,hold_reason:null,requirement_id:m.requirement_id||null};
    var reason=el('fieldset',{class:'dd-reason',hidden:true},[el('legend',{class:'dd-hint',text:'어떤 이유였나요?'})]);
    var rc=el('div',{class:'dd-choices'});
    Object.keys(C.hold_reasons).forEach(function(k){rc.appendChild(choice('radio',name('hr-'+m.milestone_id),k,C.hold_reasons[k],false,function(){S.tasks[m.milestone_id].hold_reason=k;}));});
    reason.appendChild(rc);
    var sc=el('div',{class:'dd-choices'});
    [['done','다 했어요'],['in_progress','하는 중이에요'],['on_hold','잠시 멈췄어요']].forEach(function(o){
     sc.appendChild(choice('radio',name('ms-'+m.milestone_id),o[0],o[1],false,function(){S.tasks[m.milestone_id].status=o[0];reason.hidden=o[0]!=='on_hold';}));});
    card2.appendChild(el('div',{class:'dd-task'},[el('fieldset',{},[el('legend',{class:'dd-task-title',text:m.title}),sc,reason])]));
   });
   p.appendChild(card2);
  }

  var hc=el('div',{class:'dd-choices'});
  C.hours.forEach(function(h){hc.appendChild(choice('radio',name('hours'),h[0],h[1],false,function(){S.hours=h[0];}));});
  var cc=el('div',{class:'dd-choices'});
  C.condition.forEach(function(c){cc.appendChild(choice('radio',name('cond'),c[0],c[1],false,function(){S.condition=c[0];}));});
  var status=el('span',{class:'dd-status',role:'status','aria-live':'polite'});
  var card3=el('section',{class:'dd-card'},[
   el('fieldset',{class:'dd-row'},[el('legend',{class:'dd-label',text:'이번 주에 준비에 쓴 시간'}),el('span',{class:'dd-hint',text:'대략이면 충분해요.'}),hc]),
   el('fieldset',{class:'dd-row'},[el('legend',{class:'dd-label',text:'요즘 컨디션 (선택)'}),cc,
    el('p',{class:'dd-private',text:'나만 볼 수 있고, 진로 점수에는 쓰이지 않아요. 지친 주에는 다그치지 않고 쉬어 가기를 권해요.'})]),
   el('div',{class:'dd-actions'},[status,el('button',{type:'button',class:'dd-btn primary',text:'체크인 저장',onclick:function(){
    var miss=C.axes.filter(function(a){return !S.ratings[a.id];});
    if(miss.length){setStatus(status,miss.map(function(a){return a.name;}).join(', ')+' 단계를 골라 주세요.',true);return;}
    var tasks=Object.keys(S.tasks).map(function(k){return S.tasks[k];}).filter(function(t){return t.status;});
    save('checkin',{week:C.week,self_ratings:S.ratings,milestones:tasks,hours_spent:S.hours,condition:S.condition,missed_previous_week:!!C.missed_previous_week},status);
   }})])]);
  p.appendChild(card3);
 })();

 // ── 2) 경험 카드
 (function(){
  var p=panels.cards;
  var list=el('ul',{class:'dd-saved'});
  function renderList(){list.textContent='';
   if(!S.cards.length){list.appendChild(el('li',{},[el('span',{class:'dd-empty',text:'아직 카드가 없어요. 수업 프로젝트 하나부터 적어 봐요.'})]));return;}
   S.cards.forEach(function(c){list.appendChild(el('li',{},[el('div',{},[el('b',{text:c.title}),el('small',{text:[c.kind,c.period].filter(Boolean).join(' · ')})]),
    el('button',{type:'button',class:'dd-btn small',text:'고치기',onclick:function(){fill(c);form.scrollIntoView({behavior:'smooth',block:'start'});}})]));});}
  p.appendChild(el('section',{class:'dd-card'},[el('h3',{class:'dd-card-title',text:'내 경험 카드'}),
   el('p',{class:'dd-card-desc',text:'카드에 적은 행동이 목표 요구 항목의 근거가 돼요.'}),list]));

  // 파일로 초안
  var fileIn=el('input',{type:'file',class:'dd-sr',id:name('file'),accept:'.pdf,.hwp,.hwpx,.docx,.txt,.png,.jpg,.jpeg,.webp'});
  var dstatus=el('span',{class:'dd-status',role:'status','aria-live':'polite'});
  var drafts=el('div');
  var drop=el('label',{class:'dd-drop',for:name('file')},[el('b',{text:'포트폴리오·이력서 파일 올리기'}),
   el('small',{text:'PDF, HWP, DOCX, TXT, 사진(스캔본) · 10MB까지'}),el('small',{text:'AI가 경험별 카드 초안을 만들어요. 확인한 카드만 저장돼요.'})]);
  ['dragover','dragenter'].forEach(function(n){drop.addEventListener(n,function(e){e.preventDefault();drop.classList.add('over');});});
  ['dragleave','drop'].forEach(function(n){drop.addEventListener(n,function(){drop.classList.remove('over');});});
  drop.addEventListener('drop',function(e){e.preventDefault();if(e.dataTransfer.files[0])upload(e.dataTransfer.files[0]);});
  fileIn.addEventListener('change',function(){if(fileIn.files[0])upload(fileIn.files[0]);});
  function upload(f){
   if(f.size>10*1024*1024){setStatus(dstatus,'파일은 10MB까지 올릴 수 있어요.',true);return;}
   var fd=new FormData();fd.append('file',f);
   setStatus(dstatus,'초안을 만드는 중이에요. 사진은 글자를 읽느라 조금 더 걸려요…');
   save('draft',fd,dstatus,function(res){
    if(!res||!res.drafts){setStatus(dstatus,'파일을 보냈어요. 초안이 준비되면 여기에 보여요.');return;}
    showDrafts(res);});
  }
  function showDrafts(res){drafts.textContent='';
   setStatus(dstatus,'초안 '+res.drafts.length+'장이 나왔어요'+(res.ocr_used?' (사진에서 글자를 읽었어요)':'')+'. 확인하고 저장해 주세요.');
   res.drafts.forEach(function(d){var c=d.card;var box=el('div',{class:'dd-draft'},[el('b',{text:c.title}),
     el('p',{text:c.actions}),d.source_quote?el('p',{class:'dd-quote',text:'원문: “'+d.source_quote+'”'}):null,
     (d.questions||[]).length?el('ul',{class:'dd-qs'},d.questions.map(function(q){return el('li',{text:q});})):null,
     el('div',{class:'dd-actions'},[el('button',{type:'button',class:'dd-btn small',text:'버리기',onclick:function(){box.remove();}}),
      el('button',{type:'button',class:'dd-btn small primary',text:'고쳐서 저장',onclick:function(){fill(Object.assign({},c,{id:uid()}));box.remove();
       form.scrollIntoView({behavior:'smooth',block:'start'});}})])]);
    drafts.appendChild(box);});
   if((res.rejected||[]).length)drafts.appendChild(el('p',{class:'dd-note',text:'원문에서 확인되지 않은 초안 '+res.rejected.length+'장은 뺐어요.'}));
  }
  root.didimdolShowDrafts=showDrafts; // G7이 응답을 받아 직접 그릴 때 사용
  p.appendChild(el('section',{class:'dd-card'},[el('h3',{class:'dd-card-title',text:'파일로 시작하기'}),
   el('p',{class:'dd-card-desc',text:'직접 쓰기 어렵다면 가진 파일에서 시작해요. 이름·학교·연락처는 카드에 넣지 않아요.'}),
   drop,fileIn,el('div',{class:'dd-actions',style:'justify-content:flex-start;margin-top:8px'},[dstatus]),drafts]));

  // 직접 쓰기
  var f={};
  var kindC=el('div',{class:'dd-choices'});
  C.kinds.forEach(function(k,i){kindC.appendChild(choice('radio',name('kind'),k,k,i===0,null));});
  f.title=el('input',{type:'text',id:name('title'),placeholder:'예: 세포 독성 실험 보조'});
  f.period=el('input',{type:'text',id:name('period'),placeholder:'예: 2026.03-2026.06'});
  f.role=el('input',{type:'text',id:name('role'),placeholder:'예: 데이터 분석 담당'});
  f.actions=el('textarea',{id:name('actions'),rows:5,placeholder:'예: 선배가 정한 프로토콜대로 세포를 배양하고 MTT assay로 생존율을 측정했어요. 측정값을 엑셀로 정리해 주간 미팅에서 공유했어요.'});
  f.tools=el('input',{type:'text',id:name('tools'),placeholder:'쉼표로 구분: Python, MTT assay, Origin'});
  f.outcome=el('input',{type:'text',id:name('outcome'),placeholder:'예: 기말 보고서, 학회 포스터'});
  f.learned=el('textarea',{id:name('learned'),rows:3,placeholder:'예: 조건이 조금만 달라도 결과가 흔들린다는 걸 배웠어요.'});
  var err=el('span',{class:'dd-error',role:'alert'});
  var cstatus=el('span',{class:'dd-status',role:'status','aria-live':'polite'});
  var form=el('section',{class:'dd-card'},[el('h3',{class:'dd-card-title',text:'직접 쓰기'}),
   el('p',{class:'dd-card-desc',text:'"내가 한 행동"을 구체적으로 적을수록 정확하게 연결돼요. 누가 정한 일이었는지, 내가 직접 정한 게 있었는지도 적어 주세요.'}),
   el('fieldset',{class:'dd-row'},[el('legend',{class:'dd-label',text:'경험 유형'}),kindC]),
   field('제목','',counted(f.title,60),name('title')),
   el('div',{class:'dd-grid2'},[field('기간','',f.period,name('period')),field('내 역할','',f.role,name('role'))]),
   field('내가 한 행동','2~3문장이면 충분해요.',counted(f.actions,1000),name('actions')),
   field('쓴 도구·기법','',f.tools,name('tools')),
   field('결과·산출물 (선택)','',f.outcome,name('outcome')),
   field('배운 점·다음 질문 (선택)','',counted(f.learned,500),name('learned')),
   err,
   el('div',{class:'dd-actions'},[cstatus,el('button',{type:'button',class:'dd-btn',text:'비우기',onclick:function(){fill(null);}}),
    el('button',{type:'button',class:'dd-btn primary',text:'카드 저장',onclick:submitCard})])]);
  p.appendChild(form);

  function fill(c){S.editing=c&&c.id?c.id:null;
   ['title','period','role','actions','outcome','learned'].forEach(function(k){f[k].value=c?(c[k]||''):'';f[k].dispatchEvent(new Event('input'));});
   f.tools.value=c&&c.tools?c.tools.join(', '):'';
   var k=c&&c.kind?c.kind:C.kinds[0];root.querySelectorAll('input[name="'+name('kind')+'"]').forEach(function(r){r.checked=r.value===k;});
   err.textContent='';}
  function submitCard(){
   var kind=(root.querySelector('input[name="'+name('kind')+'"]:checked')||{}).value||C.kinds[0];
   if(!f.title.value.trim()){err.textContent='제목을 적어 주세요.';f.title.focus();return;}
   if(f.actions.value.trim().length<20){err.textContent='내가 한 행동을 조금 더 적어 주세요 (20자 이상).';f.actions.focus();return;}
   err.textContent='';
   var card={id:S.editing||uid(),kind:kind,title:f.title.value.trim(),actions:f.actions.value.trim(),role:f.role.value.trim(),
    period:f.period.value.trim(),tools:f.tools.value.split(/[,，]/).map(function(s){return s.trim();}).filter(Boolean),
    outcome:f.outcome.value.trim(),learned:f.learned.value.trim()};
   save('card',card,cstatus,function(){var i=S.cards.findIndex(function(c){return c.id===card.id;});
    if(i>=0)S.cards[i]=card;else S.cards.push(card);renderList();fill(null);});
  }
  renderList();
 })();

 // ── 1) 목표·기본 정보
 (function(){
  var p=panels.profile;var pr=S.profile;
  var st=el('div',{class:'dd-choices'});
  Object.keys(C.status).forEach(function(k){st.appendChild(choice('radio',name('status'),k,C.status[k],pr.status===k,function(){pr.status=k;}));});
  var fl=el('div',{class:'dd-choices'});
  var initialFields=(pr.interest_fields||[]).slice().sort().join(',');
  function fieldsDirty(){return (pr.interest_fields||[]).slice().sort().join(',')!==initialFields;}
  function syncPins(){
   var dirty=fieldsDirty();
   root.querySelectorAll('input[name="'+name('pin')+'"]').forEach(function(r){
    if(!r.value){if(dirty)r.checked=true;return;}
    r.disabled=dirty;
    if(!dirty&&r.value===pinned)r.checked=true;
   });
   var note=root.querySelector('#'+name('means-note'));
   if(note)note.hidden=!dirty;
   if(dirty)root.dispatchEvent(new CustomEvent('didimdol:fields',{bubbles:true,detail:{interest_fields:(pr.interest_fields||[]).slice()}}));
  }
  Object.keys(C.fields).forEach(function(k){fl.appendChild(choice('checkbox',name('fields'),k,C.fields[k],(pr.interest_fields||[]).indexOf(k)>=0,function(e){
   var s=new Set(pr.interest_fields||[]);if(e.target.checked)s.add(k);else s.delete(k);pr.interest_fields=Array.from(s);syncPins();}));});
  var hv=el('span',{class:'dd-range-val'});
  var hr=el('input',{type:'range',id:name('weekly'),min:'1',max:'20',step:'1',value:String(pr.weekly_hours||6),
   'aria-describedby':name('weekly-v'),oninput:function(){pr.weekly_hours=+hr.value;hv.textContent='한 주 '+hr.value+'시간';}});
  hv.id=name('weekly-v');hv.textContent='한 주 '+hr.value+'시간';
  var tone=el('div',{class:'dd-choices dd-tone'});
  Object.keys(C.tones).forEach(function(k){tone.appendChild(choice('radio',name('tone'),k,C.tones[k][0],pr.coach_tone===k,function(){pr.coach_tone=k;},[el('small',{text:C.tones[k][1]})]));});
  var titleEl=el('input',{type:'text',id:name('goal-title'),maxlength:'80',value:(S.goal&&S.goal.title)||'',
   placeholder:'예: 세포 실험을 스스로 설계할 수 있게 되기'});
  var wk=el('input',{type:'number',id:name('goal-weeks'),min:'1',max:'52',value:String((S.goal&&S.goal.weeks_left)||8)});
  var pinned=S.goal&&S.goal.uid?S.goal.uid+'#'+S.goal.role_index:'';
  var pinListed=(C.goal_options||[]).some(function(o){return pinned&&o.uid+'#'+o.role_index===pinned;});
  var pins=el('div',{class:'dd-choices'});
  pins.appendChild(choice('radio',name('pin'),'', '고정하지 않음', !pinListed, null));
  (C.goal_options||[]).forEach(function(o){var v=o.uid+'#'+o.role_index;
   pins.appendChild(choice('radio',name('pin'),v,o.label,pinned===v,null));});
  var status=el('span',{class:'dd-status',role:'status','aria-live':'polite'});
  function saveProfile(){
   if(!titleEl.value.trim()){setStatus(status,'목표를 한 줄로 적어 주세요.',true);titleEl.focus();return;}
   if(!(pr.interest_fields||[]).length){setStatus(status,'관심 분야를 하나 이상 골라 주세요.',true);return;}
   var g={title:titleEl.value.trim(),weeks_left:+wk.value||8,weekly_hours:pr.weekly_hours,fields:(pr.interest_fields||[]).slice()};
   var picked=(root.querySelector('input[name="'+name('pin')+'"]:checked')||{}).value||'';
   if(picked&&!fieldsDirty()){var parts=picked.split('#');g.uid=parts[0];g.role_index=+parts[1];}
   save('profile',{profile:{status:pr.status,interest_fields:pr.interest_fields,weekly_hours:pr.weekly_hours,regions:pr.regions||[],
    style_share:pr.style_share||{},include_admin:!!pr.include_admin},coach_tone:pr.coach_tone,goal:g},status);
  }
  var actions=el('div',{class:'dd-actions'},[status,el('button',{type:'button',class:'dd-btn primary',text:'저장',onclick:saveProfile})]);
  p.appendChild(el('section',{class:'dd-card'},[el('h3',{class:'dd-card-title',text:'기본 정보'}),
   el('p',{class:'dd-card-desc',text:'공고 추천과 할 일의 양을 맞추는 데 써요.'}),
   el('fieldset',{class:'dd-row'},[el('legend',{class:'dd-label',text:'지금 학적 상태'}),st]),
   el('div',{class:'dd-row'},[el('label',{class:'dd-label',for:name('weekly'),text:'한 주에 준비에 쓸 수 있는 시간'}),hr,hv]),
   el('fieldset',{class:'dd-row'},[el('legend',{class:'dd-label',text:'코치 톤'}),el('span',{class:'dd-hint',text:'피드백 말투예요. 컨디션이 낮은 주에는 톤과 상관없이 다그치지 않아요.'}),tone])]));
  p.appendChild(el('section',{class:'dd-card'},[el('h3',{class:'dd-card-title',text:'직무·분야'}),
   el('p',{class:'dd-card-desc',text:'이 선택이 추천과 육각형 목표선의 기준이 돼요.'}),
   el('fieldset',{class:'dd-row'},[el('legend',{class:'dd-label',text:'관심 연구 분야'}),el('span',{class:'dd-hint',text:'여러 개 골라도 돼요.'}),fl])]));
  var goalCard=el('section',{class:'dd-card'},[el('h3',{class:'dd-card-title',text:'목표'}),
   el('p',{class:'dd-card-desc',text:'인턴 공고가 아니어도 돼요. 이루고 싶은 것을 한 줄로 적어 주세요.'}),
   field('목표','',titleEl,name('goal-title')),
   field('목표 기한까지 남은 주','',wk,name('goal-weeks'))]);
  p.appendChild(goalCard);
  if((C.goal_options||[]).length){
   p.appendChild(el('section',{class:'dd-card',id:name('means')},[el('h3',{class:'dd-card-title',text:'관련 공고'}),
    el('p',{class:'dd-card-desc',text:'이 분야와 맞는 인턴이 있어요. 원할 때만 수단으로 고정해요. 고정하지 않아도 목표선은 이 분야의 공통 요구로 그려요.'}),
    el('fieldset',{class:'dd-row'},[el('legend',{class:'dd-label',text:'수단으로 고정'}),pins]),
    el('p',{class:'dd-note',id:name('means-note'),hidden:true,text:'분야가 바뀌었어요. 이전 공고는 고정하지 않아요. 저장한 뒤 관련 공고를 다시 불러와요.'}),
    actions]));
  }else goalCard.appendChild(actions);
 })();

 var body=root.querySelector('.dd-body');
 body.appendChild(tabBar);tabs.forEach(function(t){body.appendChild(panels[t[0]]);});
 select(C.start_tab&&panels[C.start_tab]?C.start_tab:'profile');
}
document.querySelectorAll('.dd-input:not([data-dd-ready])').forEach(function(r){r.setAttribute('data-dd-ready','1');try{Widget(r);}catch(e){console.error('didimdol input',e);}});
})();
"""

THEME_JS = """
(function(){var d=document.documentElement;if(!d.classList.contains('dark')&&d.getAttribute('data-theme')!=='light'&&
window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches){d.classList.add('dark');}})();
"""
PAGE_CSS = """html{background:#fff}html.dark{background:#101828}body{margin:0;padding:24px 16px 48px;font-family:"Pretendard Variable",
Pretendard,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans KR","Malgun Gothic",sans-serif}"""


def _json_for_script(obj) -> str:
    """<script type=application/json> 안에 넣어도 안전하게 (</script> 끊김·HTML 해석 방지)."""
    return (json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026"))


def build_config(
    week: str,
    profile: Optional[dict] = None,
    goal: Optional[dict] = None,
    goal_options: Optional[list[dict]] = None,
    last_ratings: Optional[dict] = None,
    milestones: Optional[list[dict]] = None,
    cards: Optional[list[dict]] = None,
    endpoints: Optional[dict] = None,
    start_tab: str = "profile",
    missed_previous_week: bool = False,
) -> dict:
    axes = [{"id": a["id"], "name": a["name"], "anchors": a["anchors"]} for a in load_axes()["axes"]]
    return {
        "week": week, "axes": axes, "kinds": KINDS, "fields": FIELDS, "status": STATUS, "hold_reasons": HOLD_REASONS,
        "hours": HOURS, "condition": CONDITION, "tones": {k: list(v) for k, v in TONES.items()},
        "profile": profile or {}, "goal": goal, "goal_options": goal_options or [], "last_ratings": last_ratings or {},
        "milestones": milestones or [], "cards": cards or [], "endpoints": endpoints or {}, "start_tab": start_tab,
        "missed_previous_week": missed_previous_week,
    }


def render_input_fragment(config: dict, instance_id: str = "dd1") -> str:
    """사이트 페이지에 끼워 넣는 입력 화면 조각 (<style> + <section class="dd-input"> + <script>)."""
    iid = html.escape(instance_id, quote=True)
    return (f"<style>{CSS}</style>"
            f'<section class="dd-input" data-dd-id="{iid}" aria-label="자기상태표 입력">'
            '<header class="dd-head"><h2>나의 자기상태표</h2><p>누군가와 비교하는 점수표가 아니에요. '
            '이번 주의 나를 기록하면, 목표까지 다음 한 칸을 찾아 드려요.</p></header>'
            '<div class="dd-body"><noscript>이 화면은 자바스크립트가 필요해요.</noscript></div>'
            f'<script type="application/json">{_json_for_script(config)}</script></section>'
            f"<script>{JS}</script>")


def render_input(config: dict) -> str:
    """단독으로 여는 미리보기 문서 (외부 리소스 없음)."""
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>디딤돌 자기상태표</title>'
            f"<script>{THEME_JS}</script><style>{PAGE_CSS}</style></head>"
            f"<body>{render_input_fragment(config)}</body></html>")


def demo_config(start_tab: str = "profile") -> dict:
    """예시 데이터셋(p03)을 넣은 미리보기용 설정."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "data" / "examples" / "p03_energy_h2"
    try:
        prof = json.loads((root / "profile.json").read_text(encoding="utf-8"))
        cards = [{k: v for k, v in c.items() if k != "added_week"}
                 for c in json.loads((root / "cards.json").read_text(encoding="utf-8"))["cards"]]
        req = json.loads((root / "report_request.json").read_text(encoding="utf-8"))
        last = req["history"][-1]["checkin"]["self_ratings"]
        report = json.loads((root / "report.json").read_text(encoding="utf-8"))
        ms = [{"milestone_id": f"m-{a['requirement_id']}", "title": a["title"], "requirement_id": a["requirement_id"]}
              for a in report["next_actions"][:2]]
        profile = {**prof["profile"], "coach_tone": prof.get("coach_tone", "balanced")}
        goal = {"title": report["goal"]["title"], "fields": profile.get("interest_fields") or [],
                "uid": req["goal"]["uid"], "role_index": req["goal"]["role_index"], "weeks_left": req["goal"]["weeks_left"]}
        options = [{"uid": goal["uid"], "role_index": goal["role_index"], "label": f"한국에너지기술연구원 · {report['goal']['title']}"}]
    except (OSError, KeyError, ValueError):
        prof, cards, last, ms, goal, options, profile = {}, [], {}, [], None, [], {}
    return build_config("W9", profile, goal, options, last, ms, cards, start_tab=start_tab)
