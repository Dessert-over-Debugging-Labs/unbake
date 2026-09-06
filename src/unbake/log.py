"""로깅 설정 — print 금지. 라이브러리 모듈은 `logging.getLogger(__name__)`만 쓴다.

라이브러리로 임포트될 때는 아무 핸들러도 붙이지 않는다 — 출력 형식은 호출자
(애플리케이션)의 몫이다. CLI로 실행될 때만 setup_cli_logging()이 콘솔 핸들러를 붙인다.
"""

import logging
import sys


class _MaxLevelFilter(logging.Filter):
    """지정 레벨 이하만 통과 — stdout/stderr 분리에 쓴다."""

    def __init__(self, max_level: int):
        super().__init__()
        self._max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self._max_level


def setup_cli_logging(verbose: bool = False) -> None:
    """INFO 이하는 stdout(메시지만), WARNING 이상은 stderr(레벨 표시)."""
    root = logging.getLogger("unbake")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.addFilter(_MaxLevelFilter(logging.INFO))
    stdout_handler.setFormatter(logging.Formatter("%(message)s"))

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

    root.handlers = [stdout_handler, stderr_handler]
    root.propagate = False
