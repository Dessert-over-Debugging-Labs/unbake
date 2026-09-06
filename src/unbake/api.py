"""공개 진입점 — `make_recipe(url)`: 영상 하나가 들어가면 검증된 구조화 레시피가 나온다.

Config에서 기본 Gemini 포트(와 선택적 도메인 게이트)를 조립해 파이프라인을 돌리고,
산출물 세트를 output_dir 에 쓴다. 이 함수 아래는 전부 주입 가능하다 — 다른 provider 를
쓰려면 `unbake.pipeline.analyze_and_evaluate` 에 포트를 직접 넘기면 된다.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from unbake.config import Config
from unbake.gate import DOMAIN_CHECK_FILENAME, DomainJudgePort, GateResult, run_domain_gate
from unbake.pipeline import AnalysisArtifacts, analyze_and_evaluate, save_artifacts
from unbake.util import parse_video_id

logger = logging.getLogger(__name__)


class OffDomainError(Exception):
    """도메인 게이트가 영상을 요리 영상이 아니라고 판정했다 — 영상 호출은 일어나지 않았다."""

    def __init__(self, gate: GateResult):
        super().__init__(gate.reason)
        self.gate = gate


@dataclass
class RecipePorts:
    """③추출·④평가 포트 묶음 — 기본은 Gemini, 무엇이든 같은 시그니처면 꽂힌다."""

    generator: object
    blind_extractor: object
    description_parser: object
    judge: object
    matcher: object


def default_ports(cfg: Config) -> RecipePorts:
    """GEMINI_API_KEY 와 config.models 로 Gemini 포트를 조립한다."""
    from unbake.adapters.gemini import (
        GeminiBlindExtractor,
        GeminiClient,
        GeminiDescriptionParser,
        GeminiGenerator,
        GeminiJudge,
        GeminiMatcher,
    )

    cfg.require("gemini_api_key")
    client = GeminiClient(cfg.gemini_api_key)
    m = cfg.models
    return RecipePorts(
        generator=GeminiGenerator(client, m.generator),
        blind_extractor=GeminiBlindExtractor(client, m.blind),
        description_parser=GeminiDescriptionParser(client, m.description),
        judge=GeminiJudge(client, m.judge),
        matcher=GeminiMatcher(client, m.matcher),
    )


def default_domain_judge(cfg: Config) -> DomainJudgePort | None:
    """DOMAIN_CHECK 에 따라 OpenRouter / Gemini 판정기를 만들거나, off 면 None."""
    if cfg.domain_check == "off":
        return None
    from unbake.adapters.openrouter.domain_judge import LlmDomainJudge

    if cfg.domain_check == "gemini":
        from unbake.adapters.gemini import GeminiClient

        cfg.require("gemini_api_key")
        return LlmDomainJudge(GeminiClient(cfg.gemini_api_key), cfg.models.domain)
    from unbake.adapters.openrouter import OpenRouterClient

    cfg.require("openrouter_api_key")
    return LlmDomainJudge(OpenRouterClient(cfg.openrouter_api_key), cfg.models.domain)


def make_recipe(
    url_or_id: str,
    *,
    description: str | None = None,
    duration_ms: int | None = None,
    config: Config | None = None,
    ports: RecipePorts | None = None,
    domain_judge: DomainJudgePort | None = None,
    check_domain: bool | None = None,
    output_dir: Path | str | None = None,
    save: bool = True,
) -> AnalysisArtifacts:
    """유튜브 URL(또는 videoId) → 후보 레시피 + 교차 검증 결과.

    - description 을 주면 YouTube API 를 부르지 않는다 (duration_ms 는 없어도 된다 — 그 경우
      게이트 블록에 길이가 "(모름)" 으로 들어간다). description 이 None 이면 YOUTUBE_API_KEY 로
      제목·설명란·길이를 조회한다.
    - check_domain: None 이면 config(DOMAIN_CHECK) 를 따르되, domain_judge 를 주입했으면 쓴다.
      True 는 강제(provider 없으면 RuntimeError), False 는 생략. 탈락하면 OffDomainError —
      영상 호출은 일어나지 않는다.
    - save=True 면 <output_dir>/<videoId>/ 에 산출물 6종(candidate·blind·description-facts·
      evaluation·manifest·domain-check)과 meta.json 을 쓴다.
    """
    cfg = config or Config.load()
    video_id = parse_video_id(url_or_id)
    if not video_id:
        raise ValueError(f"유튜브 URL 을 해석하지 못했습니다: {url_or_id!r}")

    meta: dict | None = None
    if description is None:
        from unbake.adapters.youtube.videos import get_video_meta

        cfg.require("youtube_api_key")
        meta = get_video_meta(cfg.youtube_api_key, video_id)
        if meta is None:
            raise ValueError(f"영상을 찾을 수 없습니다: {video_id}")
        duration_ms = duration_ms if duration_ms is not None else meta["durationMs"]
        description = description if description is not None else meta["description"]
        logger.info("영상: %s (%s, %sms)", meta["title"], meta["channelTitle"], duration_ms)

    out = Path(output_dir) if output_dir is not None else cfg.output_dir
    artifact_dir = out if save else None

    # 영상 링크를 모델에 넣기 전 — 메타만으로 요리 영상인지 거른다
    judge: DomainJudgePort | None
    if check_domain is False:
        judge = None
    elif domain_judge is not None:
        judge = domain_judge
    elif check_domain is True or cfg.domain_check != "off":
        judge = default_domain_judge(cfg)
        if judge is None:
            raise RuntimeError("check_domain=True 인데 게이트 provider 가 없습니다 "
                               "(DOMAIN_CHECK=off, OPENROUTER_API_KEY 없음)")
    else:
        judge = None
    if judge is not None:
        gate = run_domain_gate(
            judge, video_id=video_id,
            title=(meta or {}).get("title", ""),
            channel_title=(meta or {}).get("channelTitle", ""),
            duration_ms=duration_ms, description=description or "",
            output_dir=artifact_dir,
        )
        if not gate.passed:
            raise OffDomainError(gate)

    p = ports or default_ports(cfg)
    artifacts = analyze_and_evaluate(
        video_url=f"https://www.youtube.com/watch?v={video_id}",
        video_id=video_id,
        duration_ms=duration_ms,
        description=description or "",
        generator=p.generator,
        blind_extractor=p.blind_extractor,
        description_parser=p.description_parser,
        judge=p.judge,
        matcher=p.matcher,
    )
    if save:
        target = save_artifacts(artifacts, out)
        if judge is None:
            # 성공한 저장 실행에만 적용 — 이전 실행의 판정을 새 산출물과 섞지 않는다.
            (target / DOMAIN_CHECK_FILENAME).unlink(missing_ok=True)
        if meta:
            (target / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        logger.info("저장: %s", target)
    return artifacts
