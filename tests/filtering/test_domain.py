"""요리 도메인 게이트 — 메타 블록 구성, 임계값 결정, 판정 실패 전파."""
import pytest

from unbake.filtering import domain as D


class FakeJudge:
    def __init__(self, verdict: D.DomainVerdict | None = None, error: Exception | None = None):
        self.verdict, self.error, self.blocks = verdict, error, []

    def judge(self, video_block: str) -> D.DomainVerdict:
        self.blocks.append(video_block)
        if self.error:
            raise self.error
        return self.verdict


def test_video_block_은_제목_채널_길이_설명란을_담는다():
    block = D.video_block(title="김치찌개 황금레시피", channel_title="집밥",
                          duration_ms=185_000, description="돼지고기 200g\n김치 1/4포기")
    assert "제목: 김치찌개 황금레시피" in block
    assert "채널: 집밥" in block
    assert "길이: 185s" in block
    assert "돼지고기 200g" in block


def test_video_block_은_빈_값을_표시하고_긴_설명란을_자른다():
    block = D.video_block(title="", channel_title="", duration_ms=None,
                          description="x" * (D.DESCRIPTION_MAX_CHARS + 500))
    assert "제목: (없음)" in block and "길이: (모름)" in block
    assert "(이하 생략)" in block
    assert len(block) < D.DESCRIPTION_MAX_CHARS + 200


def test_요리_영상이고_확신이_충분하면_통과():
    result = D.decide(D.DomainVerdict(is_cooking=True, confidence=0.9, dish_name="김치찌개"))
    assert result.passed and result.reason == ""


def test_요리_영상_아니면_off_domain_사유로_탈락():
    result = D.decide(D.DomainVerdict(is_cooking=False, confidence=0.95, reason="먹방"))
    assert not result.passed
    assert result.reason == "off_domain: 먹방"


def test_요리라_해도_확신_부족이면_탈락_임계값은_코드가_소유():
    low = D.MIN_CONFIDENCE - 0.01
    result = D.decide(D.DomainVerdict(is_cooking=True, confidence=low, reason="제목만 있음"))
    assert not result.passed
    assert result.reason.startswith("off_domain: 확신 부족")
    assert "제목만 있음" in result.reason


def test_check_domain_은_judge에_블록을_넘기고_결정을_돌려준다():
    judge = FakeJudge(D.DomainVerdict(is_cooking=True, confidence=0.8))
    result = D.check_domain(judge, title="된장찌개", channel_title="c",
                            duration_ms=60_000, description="")
    assert result.passed
    assert judge.blocks and "제목: 된장찌개" in judge.blocks[0]


def test_judge_실패는_통과가_아니라_예외_그대로():
    judge = FakeJudge(error=RuntimeError("네트워크"))
    with pytest.raises(RuntimeError, match="네트워크"):
        D.check_domain(judge, title="t", channel_title="c", duration_ms=None, description="")


def test_dump_은_camelCase_로_provenance까지_담는다():
    verdict = D.DomainVerdict(is_cooking=True, confidence=0.7, model="m",
                              prompt_version="0.1.0", prompt_hash="abc", usage={"x": 1})
    dumped = D.decide(verdict).dump()
    assert dumped["passed"] is True
    assert dumped["verdict"]["isCooking"] is True
    assert dumped["verdict"]["promptVersion"] == "0.1.0"
    assert dumped["verdict"]["usage"] == {"x": 1}
