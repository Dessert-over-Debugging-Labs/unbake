/* YouTube 정식 IFrame Player API 래퍼 (v1에서 그대로 이식).
   로컬 카운터 추정 대신 getCurrentTime() 폴링으로 실제 재생 위치를 읽는다 —
   검수는 타임스탬프 정확도가 생명. */

const Player = (() => {
  let yt = null;            // YT.Player 인스턴스
  let apiReady = false;
  let pendingVideoId = null;
  let pollTimer = null;
  let onTick = null;        // (currentSec) => void

  // IFrame API 스크립트 로드
  const tag = document.createElement('script');
  tag.src = 'https://www.youtube.com/iframe_api';
  document.head.appendChild(tag);

  window.onYouTubeIframeAPIReady = () => {
    apiReady = true;
    if (pendingVideoId) { create(pendingVideoId); pendingVideoId = null; }
  };

  function create(videoId) {
    yt = new YT.Player('ytPlayer', {
      videoId,
      playerVars: { rel: 0, playsinline: 1, origin: location.origin },
      events: { onReady: startPolling },
    });
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(() => {
      if (!yt || typeof yt.getCurrentTime !== 'function') return;
      const t = yt.getCurrentTime();
      if (onTick && typeof t === 'number') onTick(t);
    }, 250);
  }
  function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

  return {
    load(videoId) {
      if (!apiReady) { pendingVideoId = videoId; return; }
      if (yt) yt.cueVideoById(videoId);
      else create(videoId);
    },
    seekTo(sec, play = true) {
      if (!yt || typeof yt.seekTo !== 'function') return;
      yt.seekTo(sec, true);
      if (play && typeof yt.playVideo === 'function') yt.playVideo();
    },
    setOnTick(cb) { onTick = cb; },
    destroy() {
      stopPolling();
      if (yt && typeof yt.destroy === 'function') { yt.destroy(); yt = null; }
    },
  };
})();
