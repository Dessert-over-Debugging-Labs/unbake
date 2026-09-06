"""프로젝트 설정 — .env에서 로드. 시크릿은 절대 로그에 남기지 않는다.

시크릿은 전부 환경변수(.env)로 관리한다 — 키 목록은 저장소 루트 `.env.example` 참조.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

# src layout: src/unbake/config.py → 저장소 루트는 두 단계 위(src/)의 부모
PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
}


@dataclass
class ModelConfig:
    """역할별 모델 ID — judge/matcher를 따로 바꿀 수 있다."""

    generator: str = DEFAULT_MODELS["generator"]
    blind: str = DEFAULT_MODELS["blind"]
    description: str = DEFAULT_MODELS["description"]
    judge: str = DEFAULT_MODELS["judge"]
    matcher: str = DEFAULT_MODELS["matcher"]

    @classmethod
    def from_env(cls) -> "ModelConfig":
        return cls(
            generator=os.getenv("GEMINI_MODEL_GENERATOR", DEFAULT_MODELS["generator"]),
            blind=os.getenv("GEMINI_MODEL_BLIND", DEFAULT_MODELS["blind"]),
            description=os.getenv("GEMINI_MODEL_DESCRIPTION", DEFAULT_MODELS["description"]),
            judge=os.getenv("GEMINI_MODEL_JUDGE", DEFAULT_MODELS["judge"]),
            matcher=os.getenv("GEMINI_MODEL_MATCHER", DEFAULT_MODELS["matcher"]),
        )


@dataclass
class Config:
    gemini_api_key: str = ""   # 추출 A/B · 설명란 파싱 · 판정/매칭
    youtube_api_key: str = ""  # ① 탐색 (YouTube Data API v3)
    models: ModelConfig = field(default_factory=ModelConfig)
    dev_api_host: str = ""
    dev_admin_secret: str = ""
    prod_api_host: str = ""
    prod_admin_secret: str = ""
    state_bucket: str = ""     # S3 상태 공유 버킷 (비우면 로컬 전용)

    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "output")
    tmp_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "tmp")
    db_path: Path = field(default_factory=lambda: PROJECT_ROOT / "pipeline.db")

    @classmethod
    def load(cls) -> "Config":
        _load_dotenv(PROJECT_ROOT / ".env")
        cfg = cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            youtube_api_key=os.getenv("YOUTUBE_API_KEY", ""),
            models=ModelConfig.from_env(),
            dev_api_host=os.getenv("NAEMBII_DEV_API_HOST", "https://api-dev.naembii.com"),
            dev_admin_secret=os.getenv("NAEMBII_DEV_ADMIN_SECRET", ""),
            prod_api_host=os.getenv("NAEMBII_PROD_API_HOST", "https://api.naembii.com"),
            prod_admin_secret=os.getenv("NAEMBII_PROD_ADMIN_SECRET", ""),
            state_bucket=os.getenv("NAEMBII_STATE_BUCKET", ""),
        )
        cfg.output_dir.mkdir(exist_ok=True)
        cfg.tmp_dir.mkdir(exist_ok=True)
        return cfg

    def require(self, *names: str) -> None:
        """해당 설정이 비어 있으면 명확한 에러로 중단 (fail-fast)."""
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise RuntimeError(f".env에 다음 값이 필요합니다: {', '.join(missing)}")
