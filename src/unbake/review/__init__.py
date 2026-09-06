"""⑥ 검수(review) — 사람 게이트 대시보드 서버.

- `service.py`: store(pipeline.db) + output/ 산출물을 review bundle로 조립하고,
  사람 수정을 새 revision으로 기록한다 (덮어쓰기 금지 — docs/architecture.md).
- `server.py`: stdlib http.server 기반 정적 파일 + JSON API. 의존성 없음.

실행: `python -m unbake.review` → http://localhost:5180/
"""

from unbake.review.server import make_server, serve
from unbake.review.service import ReviewError, ReviewService

__all__ = ["ReviewError", "ReviewService", "make_server", "serve"]
