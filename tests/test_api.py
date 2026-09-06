"""make_recipe — 공개 진입점. 포트·게이트 주입, 메타 조회 생략, 산출물 저장, 탈락 예외."""
import json

import pytest

from tests.evaluation.conftest import FakeJudge, FakeMatcher, make_candidate
from unbake import OffDomainError, RecipePorts, make_recipe
from unbake.config import Config
from unbake.gate import DomainVerdict
from unbake.models import BlindExtraction, DescriptionFacts, LlmCallRecord, VideoAction

VID = "abc123def45"


def _rec(purpose: str) -> LlmCallRecord:
    return LlmCallRecord(call_id=f"{purpose}-1", purpose=purpose, model="fake",
                         prompt_version="t", prompt_hash="h")


class FakeGenerator:
    def __init__(self):
        self.calls = []

    def extract_candidate(self, video_url, video_id, duration_ms, description):
        self.calls.append((video_url, video_id, duration_ms, description))
        candidate = make_candidate(
            [("절이기", (0, 20_000), ["애호박을 채 썬다"])], ingredients=[("애호박", "1개")]
        ).model_copy(update={"video_id": video_id, "duration_ms": duration_ms})
        return candidate, _rec("extract_a")


class FakeBlind:
    def extract_facts(self, video_url, duration_ms):
        blind = BlindExtraction(
            actions=[VideoAction(description="채 썬다", start_ms=0, end_ms=18_000)]
        )
        return blind, _rec("extract_b")


class FakeDescParser:
    def parse(self, description):
        return DescriptionFacts(), _rec("parse_description")


class FakeDomainJudge:
    def __init__(self, is_cooking=True, confidence=0.9):
        self.verdict = DomainVerdict(is_cooking=is_cooking, confidence=confidence,
                                     reason="테스트", model="fake")
        self.calls = 0

    def judge(self, video_block):
        self.calls += 1
        return self.verdict


def _ports(generator=None) -> RecipePorts:
    return RecipePorts(
        generator=generator or FakeGenerator(),
        blind_extractor=FakeBlind(),
        description_parser=FakeDescParser(),
        judge=FakeJudge(),
        matcher=FakeMatcher({"s1a": ("MATCHED", ["a1"])}),
    )


@pytest.fixture
def cfg(tmp_path):
    # 키 없음 — 포트를 주입하므로 Gemini/YouTube 를 부르면 안 된다
    return Config(output_dir=tmp_path / "out")


def test_설명란과_길이를_주면_메타_조회_없이_돌고_산출물을_쓴다(cfg):
    generator = FakeGenerator()
    artifacts = make_recipe(
        f"https://www.youtube.com/watch?v={VID}", description="애호박 1개", duration_ms=60_000,
        config=cfg, ports=_ports(generator), check_domain=False,
    )
    assert artifacts.candidate.video_id == VID
    assert generator.calls[0][0] == f"https://www.youtube.com/watch?v={VID}"
    out = cfg.output_dir / VID
    assert {p.name for p in out.iterdir()} >= {
        "candidate.json", "blind.json", "description-facts.json", "evaluation.json", "manifest.json",
    }
    assert not (out / "domain-check.json").exists()
    assert not (out / "meta.json").exists()   # 메타를 조회하지 않았으므로


def test_순수_videoId도_받는다_save_False면_아무것도_안_쓴다(cfg):
    artifacts = make_recipe(VID, description="", duration_ms=None, config=cfg,
                            ports=_ports(), check_domain=False, save=False)
    assert artifacts.evaluation.summary is not None
    assert not cfg.output_dir.exists()


def test_잘못된_URL은_ValueError(cfg):
    with pytest.raises(ValueError, match="해석"):
        make_recipe("not a url", description="", duration_ms=1, config=cfg, ports=_ports(),
                    check_domain=False)


def test_게이트_탈락은_OffDomainError_이고_영상_포트를_부르지_않는다(cfg):
    generator = FakeGenerator()
    judge = FakeDomainJudge(is_cooking=False)
    with pytest.raises(OffDomainError) as exc:
        make_recipe(VID, description="뮤직비디오", duration_ms=1000, config=cfg,
                    ports=_ports(generator), domain_judge=judge)
    assert exc.value.gate.reason.startswith("off_domain")
    assert generator.calls == [] and judge.calls == 1
    check = json.loads((cfg.output_dir / VID / "domain-check.json").read_text(encoding="utf-8"))
    assert check["passed"] is False and check["verdict"]["model"] == "fake"


def test_게이트_통과는_산출물에_domain_check가_남는다(cfg):
    judge = FakeDomainJudge(is_cooking=True)
    make_recipe(VID, description="김치찌개 레시피", duration_ms=1000, config=cfg,
                ports=_ports(), domain_judge=judge)
    assert (cfg.output_dir / VID / "domain-check.json").exists()


def test_check_domain_False면_주입된_judge도_부르지_않는다(cfg):
    judge = FakeDomainJudge(is_cooking=False)
    make_recipe(VID, description="", duration_ms=1000, config=cfg, ports=_ports(),
                domain_judge=judge, check_domain=False)
    assert judge.calls == 0


def test_config가_off면_judge_조립_없이_진행(cfg):
    # domain_check 기본값 "off" + 주입 없음 → default_domain_judge 가 None 을 돌려준다
    assert cfg.domain_check == "off"
    artifacts = make_recipe(VID, description="", duration_ms=1000, config=cfg, ports=_ports())
    assert artifacts.candidate.video_id == VID


def test_check_domain_True인데_provider가_없으면_RuntimeError(cfg):
    with pytest.raises(RuntimeError, match="provider"):
        make_recipe(VID, description="", duration_ms=1, config=cfg, ports=_ports(),
                    check_domain=True)


def test_산출물과_반환_객체에_코드가_부여한_ID가_실린다(cfg):
    artifacts = make_recipe(VID, description="", duration_ms=1000, config=cfg, ports=_ports())
    assert [st.step_id for st in artifacts.candidate.steps] == ["s1"]
    assert artifacts.candidate.steps[0].sub_steps[0].sub_step_id == "s1a"
    assert artifacts.candidate.ingredients[0].ingredient_id == "i1"
    assert artifacts.blind.actions[0].action_id == "a1"
    saved = json.loads((cfg.output_dir / VID / "candidate.json").read_text(encoding="utf-8"))
    assert saved["steps"][0]["stepId"] == "s1"
    # evaluation 이 가리키는 ID 와 같은 값
    assert artifacts.evaluation.step_rollups[0].step_id == "s1"


@pytest.mark.parametrize("confidence", ["NaN", float("nan"), True, 3, None])
def test_invalid_gate_confidence_never_reaches_video_ports(cfg, confidence):
    from unittest.mock import Mock

    from tests.adapters.test_openrouter_domain_judge import FakeClient
    from unbake.adapters.openrouter.domain_judge import LlmDomainJudge
    from unbake.evaluation.recovery import LlmParseError

    ports = _ports()
    ports.generator = Mock()
    ports.blind_extractor = Mock()
    judge = LlmDomainJudge(FakeClient({"isCooking": True, "confidence": confidence}), "fake")
    with pytest.raises(LlmParseError, match="confidence"):
        make_recipe(VID, description="recipe", config=cfg, ports=ports, domain_judge=judge)
    ports.generator.extract_candidate.assert_not_called()
    ports.blind_extractor.extract_facts.assert_not_called()
    assert not cfg.output_dir.exists()


@pytest.mark.parametrize("check_domain", [False, None])
@pytest.mark.parametrize("previous_passed", [False, True])
def test_successful_skipped_run_removes_previous_gate(cfg, check_domain, previous_passed):
    try:
        make_recipe(VID, description="recipe", config=cfg, ports=_ports(),
                    domain_judge=FakeDomainJudge(previous_passed))
    except OffDomainError:
        assert not previous_passed
    target = cfg.output_dir / VID
    assert (target / "domain-check.json").exists()

    result = make_recipe(VID, description="recipe", config=cfg, ports=_ports(),
                         check_domain=check_domain)
    assert not (target / "domain-check.json").exists()
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest == result.manifest.dump()


@pytest.mark.parametrize("save", [False, True])
def test_unsaved_or_failed_skipped_run_preserves_previous_gate(cfg, save):
    from unittest.mock import Mock

    make_recipe(VID, description="recipe", config=cfg, ports=_ports(),
                domain_judge=FakeDomainJudge())
    target = cfg.output_dir / VID
    previous = {p.name: p.read_bytes() for p in target.iterdir()}
    ports = _ports()
    if save:
        ports.generator = Mock()
        ports.generator.extract_candidate.side_effect = RuntimeError("extraction failed")
        with pytest.raises(RuntimeError, match="extraction failed"):
            make_recipe(VID, description="recipe", config=cfg, ports=ports, check_domain=False)
    else:
        make_recipe(VID, description="recipe", config=cfg, ports=ports,
                    check_domain=False, save=False)
    assert {p.name: p.read_bytes() for p in target.iterdir()} == previous
