/* 데이터 레이어 — 검수 서버의 versioned review bundle 계약(camelCase) 전용.
   v1의 seed/localStorage 데모 폴백은 버렸다 — 이 대시보드는 항상 서버와 함께 뜬다.
   상태값·지표 표기 규칙: `영어 (한글 핵심 구절)` 병기 (docs/PLAN.md §1). */

const STATES = {
  pending_review:    { label: 'pending_review (검수 대기)',      color: '#EAA916' },
  approved:          { label: 'approved (승인됨)',               color: '#34C759' },
  rejected:          { label: 'rejected (반려)',                 color: '#FF6B61' },
  publish_failed:    { label: 'publish_failed (dev 등록 실패)',  color: '#FF3B30' },
  published_dev:     { label: 'published_dev (dev 등록됨)',      color: '#4C82F7' },
  duplicate:         { label: 'duplicate (dev 409 중복)',        color: '#6E9BF7' },
  prod_failed:       { label: 'prod_failed (prod 등록 실패)',    color: '#FF3B30' },
  published_prod:    { label: 'published_prod (prod 등록됨)',    color: '#8B5CF6' },
  evaluating:        { label: 'evaluating (평가 중)',            color: '#5AA9E6' },
  evaluation_failed: { label: 'evaluation_failed (평가 실패)',   color: '#C9880B' },
  analyzing:         { label: 'analyzing (분석 중)',             color: '#5AA9E6' },
  analyze_failed:    { label: 'analyze_failed (분석 탈락)',      color: '#8B9095' },
  queued:            { label: 'queued (대기열)',                 color: '#9AA0A6' },
  deferred:          { label: 'deferred (보류)',                 color: '#9AA0A6' },
  discovered:        { label: 'discovered (탐색됨)',             color: '#9AA0A6' },
  filtered_out:      { label: 'filtered_out (필터 탈락)',        color: '#8B9095' },
  untracked:         { label: 'untracked (이력 없음)',           color: '#8B9095' },
};

/* 사이드바 기본 노출 순서 — 나머지 상태는 항목이 있을 때만 표시 */
const STATE_ORDER = [
  'pending_review', 'approved', 'rejected',
  'publish_failed', 'published_dev', 'duplicate', 'prod_failed', 'published_prod',
];

/* ---- 평가 산출물 상태값 라벨 (영어 (한글) 병기) ---- */
const VERDICT_LABEL = {
  SUPPORTED:    'SUPPORTED (근거 있음)',
  CONTRADICTED: 'CONTRADICTED (모순)',
  UNKNOWN:      'UNKNOWN (근거 없음)',
  CONFLICT:     'CONFLICT (source끼리 충돌)',
};
const VERDICT_MARK = { SUPPORTED: '✓', CONTRADICTED: '✕', UNKNOWN: '—', CONFLICT: '⚡' };
const SEVERITY_LABEL = {
  CRITICAL: 'CRITICAL (레시피가 틀리는 수준)',
  MAJOR:    'MAJOR (사람 확인 필요)',
  MINOR:    'MINOR (참고)',
};
const ROLLUP_LABEL = {
  MATCHED:        'MATCHED (전부 일치)',
  PARTIAL:        'PARTIAL (일부만)',
  UNMATCHED:      'UNMATCHED (대응 없음)',
  ORDER_CONFLICT: 'ORDER_CONFLICT (순서 충돌)',
};
const MAPPING_LABEL = {
  MATCHED:      'MATCHED (일치)',
  UNMATCHED:    'UNMATCHED (대응 없음)',
  UNOBSERVABLE: 'UNOBSERVABLE (관찰 불가)',
};
const SOURCE_LABEL = {
  DESCRIPTION: 'DESCRIPTION (설명란)',
  AUDIO:       'AUDIO (음성)',
  VISUAL:      'VISUAL (화면)',
};
const REVISION_SOURCE_LABEL = {
  extraction: 'extraction (자동 추출)',
  human_edit: 'human_edit (사람 수정)',
};
const DIFF_LABEL = { EASY: '쉬움', NORMAL: '보통', HARD: '어려움' };

/* ---- API 클라이언트 ---- */
const Api = {
  items: [],

  async loadItems() {
    const res = await fetch('/api/items');
    if (!res.ok) throw new Error('items 로드 실패: ' + res.status);
    this.items = await res.json();
  },

  async bundle(id) {
    const res = await fetch('/api/items/' + encodeURIComponent(id));
    const body = await res.json();
    if (!res.ok) throw new Error(body.reason || ('bundle 로드 실패: ' + res.status));
    return body;
  },

  /* POST 액션 — {status, body} 반환. 실패도 body.reason으로 표준화돼 온다 */
  async action(id, name, body) {
    const res = await fetch(`/api/items/${encodeURIComponent(id)}/${name}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    let out;
    try { out = await res.json(); }
    catch (e) { out = { ok: false, reason: 'HTTP ' + res.status }; }
    return { status: res.status, body: out };
  },

  byId(id) { return this.items.find(it => it.id === id); },

  counts() {
    const c = { all: this.items.length };
    for (const it of this.items) c[it.state] = (c[it.state] || 0) + 1;
    return c;
  },
};

/* ---- 표시용 헬퍼 ---- */
function fmtSec(sec) {
  sec = Math.max(0, Math.floor(sec));
  return Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
}
function fmtMs(ms) { return fmtSec((ms || 0) / 1000); }
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function thumbUrl(videoId) {
  return `https://i.ytimg.com/vi/${encodeURIComponent(videoId)}/hqdefault.jpg`;
}

/* "1:23" / "0:05" / "83"(초) → ms. 해석 불가면 null */
function parseClockToMs(text) {
  const t = String(text || '').trim();
  if (!t) return null;
  if (/^\d+$/.test(t)) return parseInt(t, 10) * 1000;      // 초 단독 입력
  const m = t.match(/^(\d+):(\d{1,2})(?::(\d{1,2}))?$/);
  if (!m) return NaN;                                       // 형식 오류 표시용
  const [a, b, c] = [m[1], m[2], m[3]].map(x => x == null ? null : parseInt(x, 10));
  return c == null ? (a * 60 + b) * 1000 : (a * 3600 + b * 60 + c) * 1000;
}

/* 타임라인 갭 — 구간이 덮지 않는 빈 시간대 (사람이 훑어야 할 사각지대) */
function computeGaps(steps, durationMs, minGapMs = 3000) {
  const segs = (steps || [])
    .filter(s => s.startMs != null && s.endMs != null && s.endMs > s.startMs)
    .map(s => [s.startMs, s.endMs])
    .sort((x, y) => x[0] - y[0]);
  const gaps = [];
  let cursor = 0;
  for (const [start, end] of segs) {
    if (start - cursor >= minGapMs) gaps.push([cursor, start]);
    cursor = Math.max(cursor, end);
  }
  if (durationMs && durationMs - cursor >= minGapMs) gaps.push([cursor, durationMs]);
  return gaps;
}
