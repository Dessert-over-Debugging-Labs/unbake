"""⑥ 검수 대시보드 서버 — 정적 파일 + JSON API (stdlib http.server, 의존성 없음).

  GET  /api/items                          이력 + output/ 산출물 병합 목록 (?state= 필터)
  GET  /api/items/<videoId>                review bundle
  POST /api/items/<videoId>/revise         수정 candidate → 새 revision (덮어쓰기 금지)
  POST /api/items/<videoId>/approve        지정(기본: 최신) revision 승인
  POST /api/items/<videoId>/reject         반려 {reason}
  POST /api/items/<videoId>/publish-dev    승인 revision → dev 등록
  POST /api/items/<videoId>/promote        dev 검증 완료 → prod 등록 (마지막 게이트)

POST는 전부 사람이 대시보드 버튼을 눌러야 호출된다 — 자동 등록 경로 없음.
"""

import argparse
import json
import logging
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote

from pydantic import ValidationError

from unbake.adapters.sqlite.store import InvalidTransition
from unbake.config import PROJECT_ROOT, Config
from unbake.log import setup_cli_logging
from unbake.review.service import ReviewError, ReviewService

logger = logging.getLogger(__name__)

DASHBOARD_DIR = PROJECT_ROOT / "dashboard"


class ReviewHandler(SimpleHTTPRequestHandler):
    """API 라우팅 + 정적 파일 서빙. service는 인스턴스 주입 (테스트 격리 용이)."""

    def __init__(self, *args, service: ReviewService, **kwargs):
        # BaseHTTPRequestHandler.__init__이 요청 처리까지 수행하므로 주입이 먼저다
        self.service = service
        super().__init__(*args, **kwargs)

    # ---- 공통 ----

    def _json(self, status: int, body) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _api(self, fn) -> None:
        """service 예외 → HTTP status 매핑. 한 요청의 문제로 서버가 죽지 않게 한다."""
        try:
            self._json(200, fn())
        except ReviewError as e:
            self._json(e.status, {"ok": False, "reason": e.reason})
        except InvalidTransition as e:
            self._json(409, {"ok": False, "reason": f"허용되지 않는 상태 전이: {e}"})
        except ValidationError as e:
            self._json(400, {"ok": False, "reason": f"candidate 스키마 위반: {e}"[:500]})
        except KeyError as e:
            self._json(404, {"ok": False, "reason": str(e).strip("'\"")[:300]})
        except Exception as e:  # 마지막 방어선 — 원인은 reason으로 노출
            self._json(500, {"ok": False, "reason": str(e)[:300]})

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as e:
            raise ReviewError(400, f"JSON body를 해석하지 못했습니다: {e}") from e
        if not isinstance(body, dict):
            raise ReviewError(400, "JSON 객체 body가 필요합니다")
        return body

    # ---- 라우팅 ----

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/api/items":
            state = (parse_qs(query).get("state") or [None])[0]
            return self._api(lambda: self.service.list_items(state=state))
        if path.startswith("/api/items/"):
            rest = unquote(path[len("/api/items/"):])
            if rest and "/" not in rest:
                return self._api(lambda: self.service.get_bundle(rest))
            return self._json(404, {"ok": False, "reason": "unknown endpoint"})
        if path.startswith("/api/"):
            return self._json(404, {"ok": False, "reason": "unknown endpoint"})
        return super().do_GET()  # 정적 파일 (dashboard/)

    def do_POST(self):
        parts = self.path.partition("?")[0].strip("/").split("/")
        if len(parts) != 4 or parts[:2] != ["api", "items"]:
            return self._json(404, {"ok": False, "reason": "unknown endpoint"})
        video_id, action = unquote(parts[2]), parts[3]

        def run():
            body = self._read_body()
            if action == "revise":
                return self.service.revise(video_id, body)
            if action == "approve":
                return self.service.approve(video_id, body.get("revisionId"))
            if action == "reject":
                return self.service.reject(video_id, body.get("reason", ""))
            if action == "publish-dev":
                return self.service.publish_dev(video_id)
            if action == "promote":
                return self.service.promote(video_id)
            raise ReviewError(404, f"unknown action: {action}")

        return self._api(run)

    def log_message(self, fmt, *args):  # 조용한 로그 — API 호출만 DEBUG로 남긴다
        if args and "/api/" in str(args[0]):
            logger.debug("[api] %s", args[0])


def make_server(
    service: ReviewService, port: int = 0, host: str = "127.0.0.1",
    dashboard_dir=DASHBOARD_DIR,
) -> ThreadingHTTPServer:
    """서버 생성 (port=0이면 임시 포트) — 테스트와 serve()가 공유하는 조립점."""
    handler = partial(ReviewHandler, service=service, directory=str(dashboard_dir))
    return ThreadingHTTPServer((host, port), handler)


def serve(port: int = 5180) -> None:
    cfg = Config.load()
    service = ReviewService(cfg.db_path, cfg.output_dir)
    httpd = make_server(service, port=port)
    logger.info("검수 대시보드: http://localhost:%s/  (Ctrl+C로 종료)", httpd.server_port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="unbake-review", description="⑥ 검수 대시보드 서버"
    )
    parser.add_argument("--port", type=int, default=5180)
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 로그 (API 호출 상세)")
    args = parser.parse_args(argv)
    setup_cli_logging(verbose=args.verbose)
    serve(port=args.port)
    return 0
