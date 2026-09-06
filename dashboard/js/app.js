/* 검수 대시보드 앱 — 목록(상태 필터) → 검수 뷰.
   좌: 플레이어 + 구간 타임라인(갭 시각화) + 평가 패널(claim 행렬/단계 매칭/temporal/누락)
      + candidate 인라인 편집(저장 = 새 revision) + revision 체인
   우: 폰 프레임 앱 프리뷰 (상세/조리 모드)

   렌더 기준 데이터가 둘로 나뉜다는 점이 핵심:
   - cur.working  = 편집 중인 candidate (최신 revision 기반) → 타임라인·프리뷰·편집기
   - evaluationContext = 평가 시점 원본 candidate·claim·fact → 평가 패널 (수정과 섞지 않는다) */

let currentFilter = 'all';
let cur = null;       // { id, bundle, working, dirty }
let activeStep = -1;  // 현재 선택/재생 중인 단계 (working 기준)
let loopSeg = null;   // 구간 반복 대상 {start,end} (초)

const $ = id => document.getElementById(id);
const deep = o => JSON.parse(JSON.stringify(o));
const icons = () => { if (window.lucide) lucide.createIcons(); };

/* ===== 사이드바 ===== */
function renderSidebar() {
  const counts = Api.counts();
  // 핵심 상태는 항상, 그 외(파이프라인 중간 상태·untracked)는 항목이 있을 때만
  const extras = Object.keys(STATES).filter(k => !STATE_ORDER.includes(k) && counts[k]);
  const rows = [
    { key: 'all', label: '전체', color: '#9AA0A6', cnt: counts.all || 0 },
    ...[...STATE_ORDER, ...extras].map(k =>
      ({ key: k, label: STATES[k].label, color: STATES[k].color, cnt: counts[k] || 0 })),
  ];
  $('navStates').innerHTML = rows.map(it =>
    `<button class="nav-item${currentFilter === it.key ? ' active' : ''}" data-k="${it.key}">
       <span class="dot" style="background:${it.color}"></span><span class="nav-label">${esc(it.label)}</span>
       <span class="cnt">${it.cnt}</span>
     </button>`).join('');
  $('navStates').querySelectorAll('.nav-item').forEach(btn =>
    btn.addEventListener('click', () => { currentFilter = btn.dataset.k; showList(); }));
}

/* ===== 목록 ===== */
function badgeHTML(state) {
  const st = STATES[state] || { label: state, color: '#9AA0A6' };
  return `<span class="state-badge" style="background:${st.color}22;color:${st.color};border:1px solid ${st.color}55">${esc(st.label)}</span>`;
}

function summaryFlagsHTML(s) {
  if (!s) return '<span class="flag muted">평가 산출물 없음</span>';
  const bad = (s.contradictionCount || 0) + (s.sourceConflictCount || 0)
    + (s.unmatchedStepCount || 0) + (s.orderConflictCount || 0);
  const warn = (s.suspectSegmentCount || 0) + (s.unverifiedSegmentCount || 0);
  const parts = [];
  if (bad) parts.push(`<span class="flag bad">모순·충돌 ${bad}</span>`);
  if (warn) parts.push(`<span class="flag warn">구간 의심·미검증 ${warn}</span>`);
  if (s.omissionCount) parts.push(`<span class="flag warn">누락 후보 ${s.omissionCount}</span>`);
  if (!parts.length) parts.push('<span class="flag good">문제 신호 없음</span>');
  return parts.join('');
}

function showList() {
  closeReview();
  renderSidebar();
  const list = currentFilter === 'all'
    ? Api.items : Api.items.filter(it => it.state === currentFilter);
  $('listTitle').textContent = currentFilter === 'all'
    ? '전체' : (STATES[currentFilter]?.label || currentFilter);
  $('listCount').textContent = list.length + '개';
  $('cardGrid').innerHTML = list.length ? list.map(it => `
    <div class="vcard" data-id="${esc(it.id)}">
      <div class="thumb">
        <img src="${thumbUrl(it.id)}" alt="" onerror="this.style.display='none'">
        <span class="st">${badgeHTML(it.state)}</span>
        ${it.durationMs ? `<span class="dur">${fmtMs(it.durationMs)}</span>` : ''}
      </div>
      <div class="cap">
        <b>${esc(it.dishName || it.title || it.id)}</b>
        <small>${esc(it.channelTitle || '채널 정보 없음')} · ${it.stepCount || 0}단계 · rev ${it.revisionCount}</small>
        <span class="flags">${summaryFlagsHTML(it.summary)}</span>
        ${it.reason ? `<span class="reason${['rejected', 'analyze_failed', 'publish_failed', 'prod_failed', 'filtered_out', 'evaluation_failed'].includes(it.state) ? ' bad' : ''}">${esc(it.reason)}</span>` : ''}
      </div>
    </div>`).join('') : '<div class="empty">해당 상태의 항목이 없어요</div>';
  $('cardGrid').querySelectorAll('.vcard').forEach(c =>
    c.addEventListener('click', () => openReview(c.dataset.id)));
  $('listView').hidden = false;
  $('reviewView').hidden = true;
  icons();
}

function closeReview() {
  cur = null;
  Player.setOnTick(null);
}

/* ===== 검수 뷰 ===== */
async function openReview(id, loadVideo = true) {
  let bundle;
  try { bundle = await Api.bundle(id); }
  catch (e) { alert('불러오기 실패: ' + e.message); return; }
  cur = {
    id, bundle,
    working: bundle.candidate ? deep(bundle.candidate) : null,
    dirty: false,
  };
  activeStep = -1;
  loopSeg = null;
  renderReview(loadVideo);
  $('listView').hidden = true;
  $('reviewView').hidden = false;
  icons();
}

function canEdit() {
  const v = cur.bundle.video;
  return v.tracked && cur.working
    && !['published_dev', 'published_prod', 'duplicate'].includes(v.state);
}

function renderReview(loadVideo) {
  const v = cur.bundle.video;
  const w = cur.working;
  $('rvDish').textContent = (w && w.dishName) || v.title || v.videoId;
  $('rvVideoTitle').textContent = `${v.channelTitle || '채널 미상'} · ${v.title || v.videoId}`;
  $('rvState').outerHTML = badgeHTML(v.state).replace('<span', '<span id="rvState"');

  const note = $('rvNote');
  if (!v.tracked) {
    note.hidden = false;
    note.textContent = 'untracked (이력 없음) — pipeline.db에 없는 산출물이라 열람만 가능합니다. 수정·승인·반려는 파이프라인 등록 후에.';
  } else if (!w) {
    note.hidden = false;
    note.textContent = '산출물(candidate.json)이 없습니다 — 분석·평가가 끝나면 여기서 검수할 수 있습니다.';
  } else if (v.reason) {
    note.hidden = false;
    note.textContent = v.reason;
  } else note.hidden = true;

  updateActionButtons();

  if (loadVideo) {
    Player.load(v.videoId);
    Player.setOnTick(onPlayerTick);
    $('loopChk').checked = true;   // 구간 반복 기본 ON (앱 기본값과 동일)
  }

  renderSummary();
  renderTimeline();
  renderClaimMatrix();
  renderMatching();
  renderTemporal();
  renderOmissions();
  renderEditor();
  renderRevisions();
  renderPreviews();
  icons();
}

function updateActionButtons() {
  const v = cur.bundle.video;
  const tracked = v.tracked;
  const st = v.state;
  $('approveBtn').hidden = !tracked || !['pending_review', 'rejected', 'publish_failed'].includes(st);
  $('rejectBtn').hidden = !tracked || st !== 'pending_review';
  $('publishBtn').hidden = !tracked || !['approved', 'publish_failed'].includes(st);
  $('promoteBtn').hidden = !tracked || !['published_dev', 'prod_failed'].includes(st);
}

/* ===== summary 카운트 헤더 — 단일 종합 점수 없음 (불가침) ===== */
function renderSummary() {
  const s = cur.bundle.evaluation?.summary;
  if (!s) { $('sumHead').innerHTML = ''; return; }
  const chips = [
    ['CONTRADICTED (모순)', s.contradictionCount, 'bad'],
    ['CONFLICT (source 충돌)', s.sourceConflictCount, 'bad'],
    ['UNKNOWN (근거 없음)', s.unknownClaimCount, 'warn'],
    ['UNMATCHED 대단계 (대응 없음)', s.unmatchedStepCount, 'bad'],
    ['ORDER_CONFLICT (순서 충돌)', s.orderConflictCount, 'bad'],
    ['PARTIAL 대단계 (일부만)', s.partialStepCount, 'warn'],
    ['suspect 구간 (시간 의심)', s.suspectSegmentCount, 'warn'],
    ['unverified 구간 (확인 불가)', s.unverifiedSegmentCount, 'warn'],
    ['omission (누락 후보)', s.omissionCount, 'warn'],
    ['UNOBSERVABLE (관찰 불가 — 패널티 아님)', s.unobservableSubStepCount, 'neutral'],
  ];
  const extra = s.medianTemporalIou != null
    ? `<span class="sum-chip neutral zero"><b>${s.medianTemporalIou}</b>median tIoU (진단용)</span>` : '';
  $('sumHead').innerHTML = chips.map(([label, val, cls]) =>
    `<span class="sum-chip ${cls}${val ? '' : ' zero'}"><b>${val || 0}</b>${esc(label)}</span>`
  ).join('') + extra;
}

/* ===== 타임라인 (구간 + 갭 시각화) ===== */
function workingDuration() {
  const w = cur.working;
  return cur.bundle.video.durationMs || (w && w.durationMs)
    || Math.max(...((w?.steps) || []).map(s => s.endMs || 0), 1);
}

function renderTimeline() {
  const w = cur.working;
  const tl = $('timeline');
  if (!w) { tl.innerHTML = ''; $('tlDur').textContent = '0:00'; return; }
  const dur = workingDuration();
  const segs = w.steps.map((s, i) => {
    if (s.startMs == null || s.endMs == null) return '';
    const left = s.startMs / dur * 100, width = (s.endMs - s.startMs) / dur * 100;
    return `<div class="tl-seg" data-i="${i}" style="left:${left}%;width:${width}%" title="${esc(s.title)} (${fmtMs(s.startMs)}~${fmtMs(s.endMs)})">${i + 1}</div>`;
  }).join('');
  const gaps = computeGaps(w.steps, dur).map(([a, b]) =>
    `<div class="tl-gap" style="left:${a / dur * 100}%;width:${(b - a) / dur * 100}%" title="갭 ${fmtMs(a)}~${fmtMs(b)} — 어떤 단계도 덮지 않는 구간"></div>`
  ).join('');
  tl.innerHTML = gaps + segs + '<div class="tl-marker" id="tlMarker" style="left:0"></div>';
  tl.querySelectorAll('.tl-seg').forEach(seg =>
    seg.addEventListener('click', e => { e.stopPropagation(); jumpToStep(+seg.dataset.i); }));
  tl.onclick = e => {
    const rect = tl.getBoundingClientRect();
    Player.seekTo((e.clientX - rect.left) / rect.width * dur / 1000);
  };
  $('tlDur').textContent = fmtMs(dur);
}

function jumpToStep(i, seek = true) {
  const s = cur.working?.steps[i];
  if (!s) return;
  activeStep = i;
  if (s.startMs != null && s.endMs != null) {
    loopSeg = { start: s.startMs / 1000, end: s.endMs / 1000 };
    if (seek) Player.seekTo(loopSeg.start);
  }
  syncActiveStep();
}

function syncActiveStep() {
  $('timeline').querySelectorAll('.tl-seg').forEach(el =>
    el.classList.toggle('active', +el.dataset.i === activeStep));
  layoutCookCarousel();
}

function onPlayerTick(sec) {
  if (!cur || !cur.working) return;
  $('tlNow').textContent = fmtSec(sec);
  $('cookNow').textContent = fmtSec(sec);
  const dur = workingDuration() / 1000;
  const marker = $('tlMarker');
  if (marker) marker.style.left = Math.min(100, sec / dur * 100) + '%';

  if ($('loopChk').checked && loopSeg && sec > loopSeg.end - 0.15) {
    Player.seekTo(loopSeg.start);
    return;
  }
  if (!$('loopChk').checked || !loopSeg) {
    const idx = cur.working.steps.findIndex(s =>
      s.startMs != null && sec * 1000 >= s.startMs && sec * 1000 < s.endMs);
    if (idx !== -1 && idx !== activeStep) { activeStep = idx; syncActiveStep(); }
  }
}

/* ===== 평가 컨텍스트 조회 (평가 시점 원본 기준) ===== */
function ctxIndex() {
  const ctx = cur.bundle.evaluationContext;
  if (!ctx) return null;
  const facts = {};
  for (const f of (ctx.descriptionFacts?.facts || [])) facts[f.factId] = f;
  for (const f of (ctx.blind?.audioFacts || [])) facts[f.factId] = f;
  for (const f of (ctx.blind?.visualFacts || [])) facts[f.factId] = f;
  const actions = {};
  for (const a of (ctx.blind?.actions || [])) actions[a.actionId] = a;
  const steps = {}, subs = {};
  (ctx.candidate?.steps || []).forEach((s, i) => {
    steps[s.stepId] = { ...s, no: i + 1 };
    (s.subSteps || []).forEach(b => { subs[b.subStepId] = b; });
  });
  const claims = {};
  for (const c of (ctx.claims || [])) claims[c.claimId] = c;
  return { ctx, facts, actions, steps, subs, claims };
}

function factChip(f, id) {
  if (!f) return `<span class="fact-chip ghost">${esc(id)} (존재하지 않는 참조)</span>`;
  const time = f.startMs != null
    ? ` <button class="fact-jump" data-ms="${f.startMs}">${fmtMs(f.startMs)}~${fmtMs(f.endMs)}</button>` : '';
  return `<span class="fact-chip"><b>${esc(f.factId)}</b> ${esc(f.text)}${time}</span>`;
}

/* ===== ① claim 판정 행렬 ===== */
function renderClaimMatrix() {
  const box = $('claimMatrix');
  const ev = cur.bundle.evaluation;
  const idx = ctxIndex();
  if (!ev || !ev.claimEvaluations?.length || !idx) {
    box.innerHTML = '<div class="panel-empty">claim 평가 산출물이 없습니다</div>';
    return;
  }
  const sources = ['DESCRIPTION', 'AUDIO', 'VISUAL'];
  const rows = ev.claimEvaluations.map(ce => {
    const claim = idx.claims[ce.claimId];
    const cells = sources.map(src => {
      const j = (ce.bySource || {})[src];
      const verdict = j?.verdict || 'UNKNOWN';
      return `<td class="vcell v-${verdict}" title="${esc(VERDICT_LABEL[verdict] || verdict)}${j?.reason ? ' — ' + esc(j.reason) : ''}">${VERDICT_MARK[verdict] || '—'}</td>`;
    }).join('');
    const hot = ce.fused === 'CONFLICT' || ce.fused === 'CONTRADICTED';
    const detail = sources.map(src => {
      const j = (ce.bySource || {})[src];
      if (!j) return '';
      return `<div class="mxd-src">
        <div class="mxd-head"><b>${esc(SOURCE_LABEL[src])}</b>
          <span class="vtag v-${j.verdict}">${esc(VERDICT_LABEL[j.verdict] || j.verdict)}</span></div>
        ${j.observedValue ? `<div class="mxd-observed">source가 본 값: <b>${esc(j.observedValue)}</b></div>` : ''}
        ${j.reason ? `<div class="mxd-reason">${esc(j.reason)}</div>` : ''}
        ${(j.factRefs || []).length ? `<div class="mxd-facts">${j.factRefs.map(r => factChip(idx.facts[r], r)).join('')}</div>` : ''}
      </div>`;
    }).join('');
    return `
      <tr class="mx-row${hot ? ' hot' : ''}" data-c="${esc(ce.claimId)}">
        <td class="mx-claim"><b>${esc(ce.claimId)}</b> ${esc(claim?.text || '(claim 텍스트 없음)')}
          ${claim ? `<small>${esc(claim.aspect)}${claim.evidenceRefs?.length ? ' · 근거 ' + claim.evidenceRefs.join(', ') : ''}</small>` : ''}</td>
        ${cells}
        <td class="fcell f-${ce.fused}">${esc(ce.fused)}</td>
        <td class="scell${ce.severity ? ' s-' + ce.severity : ''}" title="${ce.severity ? esc(SEVERITY_LABEL[ce.severity]) : ''}">${ce.severity || '—'}</td>
      </tr>
      <tr class="mx-detail" hidden><td colspan="6">${detail || '<div class="panel-empty">판정 상세 없음</div>'}</td></tr>`;
  }).join('');

  box.innerHTML = `<table class="matrix">
    <thead><tr><th>claim</th><th>DESC<small>설명란</small></th><th>AUDIO<small>음성</small></th><th>VISUAL<small>화면</small></th><th>fused<small>최종</small></th><th>severity</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <div class="mx-legend">✓ SUPPORTED (근거 있음) · ✕ CONTRADICTED (모순) · — UNKNOWN (근거 없음) · fused CONFLICT = source끼리 충돌</div>`;

  box.querySelectorAll('.mx-row').forEach(tr =>
    tr.addEventListener('click', () => {
      const d = tr.nextElementSibling;
      if (d) d.hidden = !d.hidden;
      tr.classList.toggle('open', d && !d.hidden);
    }));
  bindJumpButtons(box);
}

/* ===== ② 단계 매칭 패널 ===== */
function renderMatching() {
  const box = $('matchList');
  const ev = cur.bundle.evaluation;
  const idx = ctxIndex();
  if (!ev || !ev.stepRollups?.length || !idx) {
    box.innerHTML = '<div class="panel-empty">매칭 산출물이 없습니다</div>';
    return;
  }
  const mapBySub = {};
  for (const m of (ev.subStepMappings || [])) mapBySub[m.subStepId] = m;

  box.innerHTML = ev.stepRollups.map(r => {
    const step = idx.steps[r.stepId];
    const subs = (step?.subSteps || []).map(b => {
      const m = mapBySub[b.subStepId];
      const status = m?.status || 'UNMATCHED';
      const actions = (m?.actionIds || []).map(aid => {
        const a = idx.actions[aid];
        if (!a) return `<span class="fact-chip ghost">${esc(aid)} (없는 action)</span>`;
        return `<button class="axn" data-ms="${a.startMs}" title="클릭하면 이 동작 구간으로 점프">
          <b>${esc(aid)}</b> ${esc(a.description)} <span>${fmtMs(a.startMs)}~${fmtMs(a.endMs)}</span></button>`;
      }).join('');
      return `<div class="sub-row m-${status}">
        <span class="sub-id">${esc(b.subStepId)}</span>
        <div class="sub-bd">
          <div class="sub-text">${esc(b.text)}</div>
          ${actions ? `<div class="sub-actions">${actions}</div>` : ''}
          ${(m?.violations || []).length ? `<div class="sub-viol">위반: ${m.violations.map(esc).join(', ')}</div>` : ''}
        </div>
        <span class="map-tag m-${status}" title="${esc(MAPPING_LABEL[status] || status)}">${esc(MAPPING_LABEL[status] || status)}</span>
      </div>`;
    }).join('');
    const counts = `일치 ${r.matchedCount || 0} · 대응없음 ${r.unmatchedCount || 0} · 관찰불가 ${r.unobservableCount || 0}`;
    return `<div class="roll r-${r.status}">
      <div class="roll-head">
        <span class="no">${step ? step.no : '?'}</span>
        <b>${esc(step?.title || r.stepId)}</b>
        <small>${counts}${r.unobservableOnly ? ' · 관찰 가능한 세부 단계 없음 (패널티 없음)' : ''}</small>
        <span class="roll-tag r-${r.status}">${esc(ROLLUP_LABEL[r.status] || r.status)}</span>
      </div>
      ${subs}
    </div>`;
  }).join('') + '<div class="mx-legend">UNOBSERVABLE (관찰 불가 — 대기·방치형)는 패널티 집계에서 제외됩니다</div>';
  bindJumpButtons(box);
}

/* ===== ③ temporal 패널 ===== */
function fmtDelta(ms) {
  if (ms == null) return '—';
  const s = (ms / 1000).toFixed(1);
  return (ms > 0 ? '+' : '') + s + 's';
}

function renderTemporal() {
  const box = $('temporalList');
  const ev = cur.bundle.evaluation;
  const idx = ctxIndex();
  const suspectTiou = cur.bundle.evaluationContext?.suspectTiou ?? 0.3;
  $('temporalMeta').textContent =
    `suspect = tIoU < ${suspectTiou} · unverified = 매칭 동작 없음/구간 무효`;
  if (!ev || !ev.temporalEvaluations?.length || !idx) {
    box.innerHTML = '<div class="panel-empty">temporal 산출물이 없습니다</div>';
    return;
  }
  box.innerHTML = ev.temporalEvaluations.map(te => {
    const step = idx.steps[te.stepId];
    const unverified = te.temporalIou == null;
    const suspect = !unverified && te.temporalIou < suspectTiou;
    const cls = unverified ? 'unverified' : suspect ? 'suspect' : 'ok';
    const tag = unverified ? 'unverified (확인 불가)' : suspect ? 'suspect (시간 의심)' : 'ok';
    const bar = unverified ? '' :
      `<div class="iou-bar"><div class="iou-fill" style="width:${Math.round(te.temporalIou * 100)}%"></div><span>tIoU ${te.temporalIou}</span></div>`;
    const jump = te.candidateStartMs != null
      ? `<button class="fact-jump" data-ms="${te.candidateStartMs}">구간 재생</button>` : '';
    return `<div class="tmp-row t-${cls}">
      <span class="no">${step ? step.no : '?'}</span>
      <div class="tmp-bd">
        <b>${esc(step?.title || te.stepId)}</b>
        <small>A 구간 ${te.candidateStartMs != null ? `${fmtMs(te.candidateStartMs)}~${fmtMs(te.candidateEndMs)}` : '없음/무효'}
          · B 동작 span ${te.actionSpanStartMs != null ? `${fmtMs(te.actionSpanStartMs)}~${fmtMs(te.actionSpanEndMs)}` : '없음'}
          · Δstart ${fmtDelta(te.startDeltaMs)} · Δend ${fmtDelta(te.endDeltaMs)}</small>
        ${bar}
      </div>
      ${jump}
      <span class="tmp-tag t-${cls}">${esc(tag)}</span>
    </div>`;
  }).join('');
  bindJumpButtons(box);
}

/* ===== ④ 누락 후보 · validation issues ===== */
function renderOmissions() {
  const box = $('omissionList');
  const ev = cur.bundle.evaluation;
  const idx = ctxIndex();
  if (!ev) { box.innerHTML = '<div class="panel-empty">평가 산출물이 없습니다</div>'; return; }
  const omis = (ev.detectedOmissions || []).map(o => `
    <div class="om-row">
      <span class="om-tag">${esc((SOURCE_LABEL[o.source] || o.source))}</span>
      <span class="om-kind">${esc(o.kind)}</span>
      <div class="om-bd">${esc(o.text)}
        ${(o.factRefs || []).length && idx ? `<div class="mxd-facts">${o.factRefs.map(r => factChip(idx.facts[r], r)).join('')}</div>` : ''}
      </div>
    </div>`).join('');
  const issues = (ev.validationIssues || []).map(i => `
    <div class="om-row issue">
      <span class="om-tag bad">${esc(i.code)}</span>
      ${i.ref ? `<span class="om-kind">${esc(i.ref)}</span>` : ''}
      <div class="om-bd">${esc(i.message)}</div>
    </div>`).join('');
  box.innerHTML = (omis || issues)
    ? omis + issues
    : '<div class="panel-empty">누락 후보·검증 이슈 없음</div>';
  bindJumpButtons(box);
}

function bindJumpButtons(box) {
  box.querySelectorAll('[data-ms]').forEach(b =>
    b.addEventListener('click', e => {
      e.stopPropagation();
      loopSeg = null;   // 평가 근거 확인은 반복 구간을 해제하고 본다
      Player.seekTo(+b.dataset.ms / 1000);
    }));
}

/* ===== ⑤ candidate 편집 → revise → approve ===== */
function markDirty() {
  if (!cur) return;
  cur.dirty = true;
  $('saveBar').hidden = false;
}

function refreshDerived() {
  renderTimeline();
  renderPreviews();
  $('rvDish').textContent = (cur.working && cur.working.dishName) || cur.bundle.video.title || cur.id;
  icons();
}

function clockInput(value, s, field) {
  return `<input class="ed-clock" data-s="${s}" data-cf="${field}" value="${value != null ? fmtMs(value) : ''}" placeholder="m:ss">`;
}

function renderEditor() {
  const box = $('editorBody');
  const w = cur.working;
  $('saveBar').hidden = !cur.dirty;
  if (!w) {
    box.innerHTML = '<div class="panel-empty">편집할 candidate가 없습니다</div>';
    return;
  }
  if (!canEdit()) {
    box.innerHTML = `<div class="panel-empty">${cur.bundle.video.tracked
      ? '등록이 끝난 레시피는 수정할 수 없습니다'
      : 'untracked (이력 없음) 산출물은 열람만 가능합니다'}</div>`;
    return;
  }

  const basic = `
    <div class="ed-grid">
      <label>요리명<input data-f="dishName" value="${esc(w.dishName || '')}"></label>
      <label>제목<input data-f="title" value="${esc(w.title || '')}"></label>
      <label>분량<input data-f="servings" value="${esc(w.servings || '')}"></label>
      <label>조리시간(분)<input data-f="cookTimeMin" type="number" min="0" value="${w.cookTimeMin ?? ''}"></label>
      <label>난이도<select data-f="difficulty">
        ${['', 'EASY', 'NORMAL', 'HARD'].map(d =>
          `<option value="${d}"${(w.difficulty || '') === d ? ' selected' : ''}>${d ? `${d} (${DIFF_LABEL[d]})` : '—'}</option>`).join('')}
      </select></label>
      <label class="ed-wide">요약<textarea data-f="summary" rows="2">${esc(w.summary || '')}</textarea></label>
    </div>`;

  const ings = `
    <div class="ed-sec">재료 <small>${(w.ingredients || []).length}개</small></div>
    ${(w.ingredients || []).map((g, i) => `
      <div class="ed-ing" data-i="${i}">
        <select data-if="group" data-i="${i}">
          ${['MAIN', 'SEASONING'].map(x => `<option${g.group === x ? ' selected' : ''}>${x}</option>`).join('')}
        </select>
        <input data-if="name" data-i="${i}" value="${esc(g.name || '')}" placeholder="재료명">
        <input data-if="amount" data-i="${i}" value="${esc(g.amount || '')}" placeholder="분량 (미확인이면 비움)">
        <button class="ic-btn sm" data-act="del-ing" data-i="${i}" title="재료 삭제"><i data-lucide="trash-2"></i></button>
      </div>`).join('')}
    <button class="ghost-btn sm" data-act="add-ing"><i data-lucide="plus"></i>재료 추가</button>`;

  const steps = `
    <div class="ed-sec">대단계 <small>${(w.steps || []).length}개 — 시간은 m:ss (또는 초)</small></div>
    ${(w.steps || []).map((s, si) => `
      <div class="ed-step" data-s="${si}">
        <div class="ed-step-head">
          <span class="no">${si + 1}</span>
          <input class="ed-title" data-sf="title" data-s="${si}" value="${esc(s.title || '')}" placeholder="단계 제목">
          ${clockInput(s.startMs, si, 'startMs')}<span class="tilde">~</span>${clockInput(s.endMs, si, 'endMs')}
          <button class="ic-btn sm" data-act="jump" data-s="${si}" title="구간 재생"><i data-lucide="play"></i></button>
          <button class="ic-btn sm" data-act="del-step" data-s="${si}" title="대단계 삭제"><i data-lucide="trash-2"></i></button>
        </div>
        ${(s.subSteps || []).map((b, bi) => `
          <div class="ed-sub" data-s="${si}" data-b="${bi}">
            <input data-bf="text" data-s="${si}" data-b="${bi}" value="${esc(b.text || '')}" placeholder="세부 단계 문장">
            <button class="ic-btn sm" data-act="del-sub" data-s="${si}" data-b="${bi}" title="세부 단계 삭제"><i data-lucide="x"></i></button>
          </div>`).join('')}
        <button class="ghost-btn sm" data-act="add-sub" data-s="${si}"><i data-lucide="plus"></i>세부 단계</button>
      </div>`).join('')}
    <button class="ghost-btn sm" data-act="add-step"><i data-lucide="plus"></i>대단계 추가</button>`;

  box.innerHTML = basic + ings + steps;
  icons();
}

/* 편집기 이벤트 — #editorBody에 1회만 위임 바인딩 (재렌더에도 중복되지 않게).
   working 참조는 이벤트 시점의 cur에서 읽는다. */
function bindEditorEvents() {
  const box = $('editorBody');

  box.addEventListener('input', e => {
    const w = cur?.working;
    if (!w) return;
    const t = e.target;
    if (t.dataset.f) {                          // 기본 정보
      if (t.dataset.f === 'cookTimeMin') {
        w.cookTimeMin = t.value === '' ? null : Math.max(0, parseInt(t.value, 10) || 0);
      } else w[t.dataset.f] = t.value || null;
      markDirty();
    } else if (t.dataset.if) {                  // 재료 (amount 비움 = null — 추측 분량 금지)
      const g = w.ingredients[+t.dataset.i];
      if (g) { g[t.dataset.if] = (t.dataset.if === 'amount' && t.value === '') ? null : t.value; markDirty(); }
    } else if (t.dataset.sf) {                  // 대단계 제목
      const s = w.steps[+t.dataset.s];
      if (s) { s[t.dataset.sf] = t.value; markDirty(); }
    } else if (t.dataset.bf) {                  // 세부 단계 문장
      const b = w.steps[+t.dataset.s]?.subSteps[+t.dataset.b];
      if (b) { b.text = t.value; markDirty(); }
    }
  });

  box.addEventListener('change', e => {
    const w = cur?.working;
    if (!w) return;
    const t = e.target;
    if (t.dataset.cf) {                         // 구간 시간 (m:ss)
      const ms = parseClockToMs(t.value);
      t.classList.toggle('bad', Number.isNaN(ms));
      if (!Number.isNaN(ms)) {
        const s = w.steps[+t.dataset.s];
        if (s) { s[t.dataset.cf] = ms; markDirty(); }
      }
    }
    refreshDerived();                            // 블러 시점에만 타임라인·프리뷰 갱신
  });

  box.addEventListener('click', e => {
    const w = cur?.working;
    if (!w) return;
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;
    const si = +btn.dataset.s, bi = +btn.dataset.b, ii = +btn.dataset.i;
    if (act === 'jump') { jumpToStep(si); return; }
    if (act === 'del-ing') w.ingredients.splice(ii, 1);
    if (act === 'add-ing') (w.ingredients ||= []).push({ group: 'MAIN', name: '', amount: null });
    if (act === 'del-sub') w.steps[si].subSteps.splice(bi, 1);
    if (act === 'add-sub') (w.steps[si].subSteps ||= []).push({ text: '' });
    if (act === 'del-step') w.steps.splice(si, 1);
    if (act === 'add-step') (w.steps ||= []).push({ title: '', startMs: null, endMs: null, subSteps: [{ text: '' }] });
    markDirty();
    renderEditor();      // 구조 변경은 편집기 재렌더
    refreshDerived();
  });
}

async function saveRevision() {
  if (!cur?.dirty) return;
  const w = cur.working;
  if (!w.dishName?.trim()) { alert('요리명(dishName)은 비울 수 없습니다'); return; }
  $('saveBtn').disabled = true;
  try {
    const { body } = await Api.action(cur.id, 'revise', { candidate: w });
    if (!body.ok) { alert('저장 실패: ' + (body.reason || '')); return; }
    await Api.loadItems();
    await openReview(cur.id, false);   // 새 revision이 반영된 bundle 재로드 (영상 유지)
    renderSidebar();
  } finally {
    $('saveBtn').disabled = false;
  }
}

function revertEdits() {
  if (!cur) return;
  cur.working = cur.bundle.candidate ? deep(cur.bundle.candidate) : null;
  cur.dirty = false;
  $('saveBar').hidden = true;
  renderEditor();
  refreshDerived();
}

/* ===== revision 체인 ===== */
function renderRevisions() {
  const b = cur.bundle;
  const revs = b.revisions || [];
  if (!revs.length) {
    $('revisionList').innerHTML =
      '<div class="panel-empty">아직 revision이 없습니다 — 승인하면 원본이 extraction revision으로 등록됩니다</div>';
    return;
  }
  $('revisionList').innerHTML = [...revs].reverse().map(r => {
    const current = b.candidateRevisionId === r.revisionId;
    const approved = b.video.approvedRevisionId === r.revisionId;
    return `<div class="rev-item${current ? ' cur' : ''}">
      <div class="rev-head">
        <code>${esc(r.revisionId)}</code>
        <span class="rev-src ${esc(r.source)}">${esc(REVISION_SOURCE_LABEL[r.source] || r.source)}</span>
        ${current ? '<span class="rev-badge cur">표시 중 · 승인 대상</span>' : ''}
        ${approved ? '<span class="rev-badge ok">approved (승인됨)</span>' : ''}
      </div>
      <small>${esc((r.createdAt || '').replace('T', ' ').slice(0, 19))}${r.parentRevisionId ? ' · parent ' + esc(r.parentRevisionId) : ' · 최초'}</small>
    </div>`;
  }).join('');
}

/* ===== 앱 프리뷰 ===== */
function renderPreviews() {
  const w = cur.working;
  if (!w) {
    $('pvTitle').textContent = '산출물 없음';
    ['pvSummary', 'pvIngs', 'pvSteps', 'pvTags', 'cookTrack', 'cookProgress'].forEach(id => { $(id).innerHTML = ''; });
    return;
  }
  $('pvThumb').src = thumbUrl(cur.id);
  $('pvTitle').textContent = w.title || w.dishName;
  $('pvSummary').textContent = w.summary || '';
  $('pvTime').textContent = w.cookTimeMin != null ? w.cookTimeMin + '분' : '—';
  $('pvServings').textContent = w.servings || '—';
  $('pvDiff').textContent = DIFF_LABEL[w.difficulty] || '—';
  const main = (w.ingredients || []).filter(i => i.group !== 'SEASONING');
  const season = (w.ingredients || []).filter(i => i.group === 'SEASONING');
  $('pvIngTitle').textContent = `재료 ${(w.ingredients || []).length}개`;
  const grp = (label, arr) => arr.length
    ? `<div class="ing-group-label">${label}</div><div class="ings">${arr.map(x =>
        `<div class="ing"><div class="n">${esc(x.name)}</div><div class="q">${esc(x.amount || '')}</div></div>`).join('')}</div>`
    : '';
  $('pvIngs').innerHTML = grp('주재료', main) + grp('양념', season);
  $('pvSteps').innerHTML = (w.steps || []).map((s, i) =>
    `<div class="rstep">
       <div class="rstep-h"><span class="rstep-no">${i + 1}</span><b>${esc(s.title)}</b>
         ${s.startMs != null ? `<span class="rstep-time"><i data-lucide="play"></i>${fmtMs(s.startMs)} ~ ${fmtMs(s.endMs)}</span>` : ''}</div>
       <ul class="rstep-subs">${(s.subSteps || []).map(b => `<li>${esc(b.text)}</li>`).join('')}</ul>
     </div>`).join('');
  $('pvTags').innerHTML = (w.tags || []).map(t => `<span>#${esc(t.name || t)}</span>`).join('');

  // 조리 모드
  $('cookThumb').src = thumbUrl(cur.id);
  $('cookProgress').innerHTML = (w.steps || []).map(() => '<div class="seg"></div>').join('');
  $('cookTrack').innerHTML = (w.steps || []).map((s, i) =>
    `<div class="scard" data-i="${i}">
       <div class="side-label"></div>
       <div class="sc-head"><div class="sc-title">${esc(s.title)}</div>
         <div class="sc-badge">${i + 1} / ${w.steps.length}</div></div>
       <div class="sc-range">${s.startMs != null ? fmtMs(s.startMs) + ' ~ ' + fmtMs(s.endMs) : '구간 없음'}</div>
       <ul class="sub-list">${(s.subSteps || []).map(b => `<li>${esc(b.text)}</li>`).join('')}</ul>
     </div>`).join('');
  $('cookTrack').querySelectorAll('.scard').forEach(c =>
    c.addEventListener('click', () => jumpToStep(+c.dataset.i)));
  layoutCookCarousel();
}

/* v1 조리모드 캐러셀 계산식 그대로 — translateY/scale/opacity 값 동일 */
function layoutCookCarousel() {
  const curStep = Math.max(0, activeStep);
  document.querySelectorAll('#cookTrack .scard').forEach(card => {
    const i = +card.dataset.i, o = i - curStep, ao = Math.abs(o);
    let y, sc, op;
    if (o === 0) { y = 0; sc = 1; op = 1; }
    else {
      const dir = o < 0 ? -1 : 1, dist = ao === 1 ? 128 : 128 + (ao - 1) * 52;
      y = dir * dist; sc = ao === 1 ? 0.9 : 0.82; op = ao === 1 ? 0.62 : (ao === 2 ? 0.16 : 0);
    }
    card.style.transform = `translateY(calc(-50% + ${y}px)) scale(${sc})`;
    card.style.opacity = op;
    card.style.zIndex = 100 - ao;
    card.style.pointerEvents = op > 0 ? 'auto' : 'none';
    card.classList.toggle('active', o === 0);
    const lbl = card.querySelector('.side-label');
    if (lbl) lbl.textContent = o < 0 ? '이전 단계' : o > 0 ? '다음 단계' : '';
  });
  document.querySelectorAll('#cookProgress .seg').forEach((seg, i) => {
    seg.className = 'seg' + (i < curStep ? ' done' : i === curStep ? ' cur' : '');
  });
}

/* ===== 액션 ===== */
async function doApprove() {
  if (cur.dirty && !confirm('저장하지 않은 수정이 있습니다.\n수정 없이(마지막 저장본으로) 승인할까요?')) return;
  const revs = cur.bundle.revisions || [];
  const target = revs.length ? revs[revs.length - 1].revisionId : '원본 candidate (extraction revision으로 등록됨)';
  if (!confirm(`승인할까요?\n대상 revision: ${target}`)) return;
  $('approveBtn').disabled = true;
  const { body } = await Api.action(cur.id, 'approve');
  $('approveBtn').disabled = false;
  if (!body.ok) { alert('승인 실패: ' + (body.reason || '')); return; }
  await Api.loadItems();
  await openReview(cur.id, false);
  renderSidebar();
}

async function doReject() {
  const reason = $('rejectReason').value.trim();
  const { body } = await Api.action(cur.id, 'reject', { reason });
  $('rejectDlg').close();
  if (!body.ok) { alert('반려 실패: ' + (body.reason || '')); return; }
  await Api.loadItems();
  showList();
}

async function doPublish(action, label) {
  if (!confirm(`${label}을 실행할까요? (사람 게이트 — 되돌릴 수 없습니다)`)) return;
  const { status, body } = await Api.action(cur.id, action);
  if (!body.ok) { alert(`${label} 실패: ${body.reason || 'HTTP ' + status}`); return; }
  alert(`${label} 완료 — ${body.status}${body.recipeId ? ' (recipeId: ' + body.recipeId + ')' : ''}`);
  await Api.loadItems();
  showList();
}

/* ===== 이벤트 바인딩 ===== */
function bindEvents() {
  $('backBtn').addEventListener('click', showList);

  // 프리뷰 탭 전환
  document.querySelectorAll('.ptab').forEach(tab =>
    tab.addEventListener('click', () => {
      document.querySelectorAll('.ptab').forEach(t => t.classList.toggle('active', t === tab));
      $('pvDetail').hidden = tab.dataset.tab !== 'detail';
      $('pvCook').hidden = tab.dataset.tab !== 'cook';
      if (tab.dataset.tab === 'cook') layoutCookCarousel();
    }));

  // 조리 프리뷰: 휠로 단계 이동
  let wheelLock = false;
  $('pvCook').addEventListener('wheel', e => {
    if (wheelLock || !cur?.working) return;
    const steps = cur.working.steps || [];
    if (e.deltaY > 12 && activeStep < steps.length - 1) { wheelLock = true; jumpToStep(activeStep + 1); }
    else if (e.deltaY < -12 && activeStep > 0) { wheelLock = true; jumpToStep(activeStep - 1); }
    setTimeout(() => wheelLock = false, 500);
  }, { passive: true });

  $('approveBtn').addEventListener('click', doApprove);
  $('rejectBtn').addEventListener('click', () => { $('rejectReason').value = ''; $('rejectDlg').showModal(); });
  $('rejectConfirm').addEventListener('click', doReject);
  $('rejectClose').addEventListener('click', () => $('rejectDlg').close());
  $('publishBtn').addEventListener('click', () => doPublish('publish-dev', 'dev 등록'));
  $('promoteBtn').addEventListener('click', () => doPublish('promote', 'prod 등록'));

  $('saveBtn').addEventListener('click', saveRevision);
  $('revertBtn').addEventListener('click', revertEdits);
  bindEditorEvents();

  $('jsonBtn').addEventListener('click', () => {
    $('jsonPre').textContent = JSON.stringify(cur?.working ?? cur?.bundle?.candidate, null, 2);
    $('jsonDlg').showModal();
  });
  $('jsonClose').addEventListener('click', () => $('jsonDlg').close());
}

/* ===== 부팅 ===== */
(async () => {
  bindEvents();
  try {
    await Api.loadItems();
  } catch (e) {
    $('cardGrid').innerHTML =
      `<div class="empty">서버에 연결하지 못했습니다 — <code>python -m recipe_agent.review</code>로 서버를 띄워주세요<br><small>${esc(e.message)}</small></div>`;
    renderSidebar();
    return;
  }
  showList();
})();
