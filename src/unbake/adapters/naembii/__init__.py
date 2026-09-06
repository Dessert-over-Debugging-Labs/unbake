"""냄비(Naembii) 백엔드 adapter — RecipeCreateRequest 계약 + 등록 클라이언트.

다른 백엔드를 쓰려면 이 adapter만 교체하면 된다 (docs/architecture.md).
"""
from .client import NaembiiClient, PublishResult, publish_and_verify
from .schema import RecipeCreateRequest, soft_warnings

__all__ = [
    "NaembiiClient",
    "PublishResult",
    "publish_and_verify",
    "RecipeCreateRequest",
    "soft_warnings",
]
