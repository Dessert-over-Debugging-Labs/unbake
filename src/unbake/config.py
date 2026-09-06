"""프로젝트 설정 — .env에서 로드. 시크릿은 절대 로그에 남기지 않는다.

시크릿은 전부 환경변수(.env)로 관리한다 — 키 목록은 저장소 루트 `.env.example` 참조.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """의존성 없는 최소 .env 로더 — `KEY=VALUE` 줄만 읽는다.

    이미 설정된 환경변수는 덮지 않는다 (셸/CI 주입 값이 우선).
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


# 역할별 기본 모델 ID — 이 dict가 코드베이스에서 모델 ID가 적히는 유일한 곳이다.
# .env(GEMINI_MODEL_*)로 언제든 교체 가능. `latest` 별칭 금지 — 정확한 ID를 고정한다
# (docs/architecture.md: 독립성은 아키텍처로, 기본 모델 변경은 측정 결과로).
DEFAULT_MODELS = {
    # 2026-09-05 models.list + 응답 프로브로 확정 (3.8·3.6-flash는 당시 지속 503)
    "generator": "gemini-3.1-pro-preview",  # A — 영상 입력 (과거 설계 기록)
    "blind": "gemini-3.1-pro-preview",      # B — 영상 입력
    "description": "gemini-3.7-flash",      # 설명란 파싱 (텍스트만)
    "judge": "gemini-3.7-flash",            # 판정 (텍스트만)
    "matcher": "gemini-3.7-flash",          # 매칭 (텍스트만)
    # 요리 도메인 게이트 (텍스트만, 영상 호출 전) — OpenRouter 모델 ID.
    # DOMAIN_CHECK=gemini 이고 DOMAIN_MODEL 이 비어 있으면 judge 모델을 대신 쓴다.
    "domain": "openai/gpt-5.4-nano",
}

DOMAIN_CHECK_MODES = ("openrouter", "gemini", "off")


@dataclass
class ModelConfig:
    """역할별 모델 ID — judge/matcher를 따로 바꿀 수 있다."""

    generator: str = DEFAULT_MODELS["generator"]
    blind: str = DEFAULT_MODELS["blind"]
    description: str = DEFAULT_MODELS["description"]
    judge: str = DEFAULT_MODELS["judge"]
    matcher: str = DEFAULT_MODELS["matcher"]
    domain: str = DEFAULT_MODELS["domain"]  # 도메인 게이트 — provider 중립 이름 (DOMAIN_MODEL)

    @classmethod
    def from_env(cls) -> "ModelConfig":
        return cls(
            generator=os.getenv("GEMINI_MODEL_GENERATOR", DEFAULT_MODELS["generator"]),
            blind=os.getenv("GEMINI_MODEL_BLIND", DEFAULT_MODELS["blind"]),
            description=os.getenv("GEMINI_MODEL_DESCRIPTION", DEFAULT_MODELS["description"]),
            judge=os.getenv("GEMINI_MODEL_JUDGE", DEFAULT_MODELS["judge"]),
            matcher=os.getenv("GEMINI_MODEL_MATCHER", DEFAULT_MODELS["matcher"]),
            domain=os.getenv("DOMAIN_MODEL", DEFAULT_MODELS["domain"]),
        )


def resolve_domain_check(value: str | None, *, has_openrouter_key: bool) -> str:
    """DOMAIN_CHECK 해석 — 비어 있으면 OpenRouter 키가 있을 때만 켠다.

    명시값은 openrouter | gemini | off 만 허용한다 (오타로 게이트가 조용히 꺼지지 않게).
    """
    if not value:
        return "openrouter" if has_openrouter_key else "off"
    mode = value.strip().lower()
    if mode not in DOMAIN_CHECK_MODES:
        raise RuntimeError(
            f"DOMAIN_CHECK 값이 잘못됐습니다: {value!r} (허용: {', '.join(DOMAIN_CHECK_MODES)})"
        )
    return mode


@dataclass
class Config:
    gemini_api_key: str = ""   # 추출 A/B · 설명란 파싱 · 판정/매칭
    youtube_api_key: str = ""  # ① 탐색 (YouTube Data API v3)
    openrouter_api_key: str = ""  # 요리 도메인 게이트 (텍스트만) — 없으면 게이트는 꺼진다
    domain_check: str = "off"  # openrouter | gemini | off — 영상 호출 전 도메인 게이트
    models: ModelConfig = field(default_factory=ModelConfig)

    # 산출물 폴더 — UNBAKE_OUTPUT_DIR, 기본은 현재 작업 디렉토리의 ./output
    output_dir: Path = field(default_factory=lambda: Path.cwd() / "output")

    @classmethod
    def load(cls, dotenv: Path | None = None) -> "Config":
        """환경변수(+ .env)에서 읽는다. dotenv 기본은 현재 작업 디렉토리의 .env — 라이브러리로
        임포트될 때 호출자의 프로젝트 설정을 읽기 위함이다. 이미 설정된 환경변수가 우선."""
        _load_dotenv(dotenv if dotenv is not None else Path.cwd() / ".env")
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
        cfg = cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            youtube_api_key=os.getenv("YOUTUBE_API_KEY", ""),
            openrouter_api_key=openrouter_api_key,
            domain_check=resolve_domain_check(
                os.getenv("DOMAIN_CHECK"), has_openrouter_key=bool(openrouter_api_key)
            ),
            models=ModelConfig.from_env(),
            output_dir=Path(os.getenv("UNBAKE_OUTPUT_DIR") or Path.cwd() / "output"),
        )
        if cfg.domain_check == "gemini" and not os.getenv("DOMAIN_MODEL"):
            # Gemini로 게이트를 돌릴 때 OpenRouter 모델 ID는 무의미 — 판정 모델을 그대로 쓴다
            cfg.models.domain = cfg.models.judge
        return cfg

    def require(self, *names: str) -> None:
        """해당 설정이 비어 있으면 명확한 에러로 중단 (fail-fast)."""
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise RuntimeError(f".env에 다음 값이 필요합니다: {', '.join(missing)}")
