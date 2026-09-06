"""`python -m unbake.review` — 검수 대시보드 서버 실행."""

import sys

from unbake.review.server import main

if __name__ == "__main__":
    sys.exit(main())
