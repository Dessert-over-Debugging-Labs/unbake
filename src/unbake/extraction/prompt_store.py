"""versioned prompt 로더 — 버전·해시가 provenance에 기록된다.

프롬프트 파일 첫 줄은 `<!-- version: x.y.z -->` 여야 한다. 내용이 바뀌면
해시가 바뀌므로, artifact 재사용·A/B 비교의 키가 된다.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

PROMPT_DIR = Path(__file__).parent / "prompts"

_VERSION_RE = re.compile(r"<!--\s*version:\s*([0-9.]+)\s*-->")
_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)\}\}")


@dataclass(frozen=True)
class Prompt:
    name: str
    text: str
    version: str
    hash: str

    def render(self, **variables: str) -> str:
        """{{KEY}} 치환. 채워지지 않은 플레이스홀더가 남으면 에러 —
        '수집하고도 안 쓰는' 사고를 구조적으로 막는다 (과거 실측)."""
        rendered = self.text
        for key, value in variables.items():
            rendered = rendered.replace("{{" + key + "}}", str(value))
        leftover = _PLACEHOLDER_RE.findall(rendered)
        if leftover:
            raise ValueError(f"프롬프트 '{self.name}'에 채워지지 않은 변수: {leftover}")
        return rendered


def load_prompt(name: str) -> Prompt:
    path = PROMPT_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    match = _VERSION_RE.search(text.split("\n", 1)[0])
    if not match:
        raise ValueError(f"프롬프트 '{name}' 첫 줄에 version 주석이 없다")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return Prompt(name=name, text=text, version=match.group(1), hash=digest)
