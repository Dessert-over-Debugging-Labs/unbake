"""모델 공통 베이스."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

# 평가 산출물 스키마 버전 — 계약이 바뀌면 올리고, artifact manifest에 기록한다
SCHEMA_VERSION = "1.0.0"


class ApiModel(BaseModel):
    """직렬화 계약용 베이스 — JSON은 camelCase, 파이썬은 snake_case."""

    # extra="ignore": LLM 출력이 계약 밖 필드를 덧붙여도 파싱이 깨지지 않게 한다.
    # 필수 필드 누락·타입 오류는 여전히 ValidationError로 잡힌다.
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )

    def dump(self) -> dict:
        """계약 표기(camelCase)로 직렬화한다."""
        return self.model_dump(by_alias=True, exclude_none=True)
