"""워크플로우 통합 — 실제 Gemini adapter를 fake 클라이언트로 태워 전 구간을 검증한다."""

import json
import re

from unbake.adapters.gemini import (
    GeminiBlindExtractor,
    GeminiDescriptionParser,
    GeminiGenerator,
    GeminiJudge,
    GeminiMatcher,
)
from unbake.workflow.analyze import analyze_and_evaluate, save_artifacts

CANDIDATE_JSON = {
    "videoId": "ignored-by-adapter",
    "dishName": "애호박볶음",
    "ingredients": [
        {"group": "MAIN", "name": "애호박", "amount": "1개"},
        {"group": "SEASONING", "name": "소금", "amount": None},
    ],
    "steps": [
        {
            "title": "절이기",
            "startMs": 0,
            "endMs": 20000,
            "subSteps": [{"text": "애호박을 채 썬다"}, {"text": "소금 1작은술을 넣고 버무린다"}],
        }
    ],
    "extraFieldFromLlm": "무시되어야 함",
}

BLIND_JSON = {
    "audioFacts": [
        {"kind": "AMOUNT", "text": "소금은 한 작은술", "name": "소금", "amount": "1작은술"}
    ],
    "visualFacts": [],
    "actions": [
        {"description": "애호박을 썬다", "startMs": 0, "endMs": 10000},
        {"description": "소금을 뿌리고 버무린다", "startMs": 10000, "endMs": 19000},
    ],
}

DESC_JSON = {"facts": [{"kind": "INGREDIENT", "text": "애호박 1개", "name": "애호박", "amount": "1개"}]}


class FakeGeminiClient:
    """프롬프트 내용으로 어떤 호출인지 판별해 결정적으로 응답한다."""

    def __init__(self):
        self.calls: list[dict] = []

    def generate_json(self, model, prompt, video_url=None, temperature=0.0):
        self.calls.append({"model": model, "video": video_url is not None})
        usage = {"promptTokenCount": 10, "candidatesTokenCount": 5}
        if "관찰 기록자" in prompt:
            assert video_url, "B는 영상을 첨부해야 한다"
            assert "설명란" not in prompt.split("# 출력")[0], "B 프롬프트에 설명란이 섞이면 blind 위반"
            return BLIND_JSON, usage
        if "판정관" in prompt:
            claim_ids = re.findall(r'"claimId": "(c\d+)"', prompt)
            return [
                {"claimId": cid, "verdict": "SUPPORTED", "factRefs": [], "reason": "ok"}
                for cid in dict.fromkeys(claim_ids)
            ], usage
        if "매칭 전문가" in prompt:
            sub_ids = re.findall(r'"subStepId": "(s\d+[a-z]+)"', prompt)
            action_ids = re.findall(r'"actionId": "(a\d+)"', prompt)
            return [
                {"subStepId": sid, "status": "MATCHED", "actionIds": [action_ids[min(i, len(action_ids) - 1)]]}
                for i, sid in enumerate(dict.fromkeys(sub_ids))
            ], usage
        if "설명란 텍스트만" in prompt:
            return DESC_JSON, usage
        assert video_url, "A는 영상을 첨부해야 한다"
        return CANDIDATE_JSON, usage


def test_analyze_and_evaluate_end_to_end(tmp_path):
    client = FakeGeminiClient()
    artifacts = analyze_and_evaluate(
        video_url="https://www.youtube.com/watch?v=abc123def45",
        video_id="abc123def45",
        duration_ms=60_000,
        description="애호박 1개로 만드는 반찬",
        generator=GeminiGenerator(client, "fake-pro"),
        blind_extractor=GeminiBlindExtractor(client, "fake-pro"),
        description_parser=GeminiDescriptionParser(client, "fake-flash"),
        judge=GeminiJudge(client, "fake-flash"),
        matcher=GeminiMatcher(client, "fake-flash"),
    )

    # adapter가 videoId를 실제 값으로 고정한다
    assert artifacts.candidate.video_id == "abc123def45"
    # LLM이 덧붙인 계약 밖 필드는 무시된다
    assert not hasattr(artifacts.candidate, "extraFieldFromLlm")

    # 호출 구조: 영상 입력 2회(A·B, 비쌈) + 텍스트 5회(설명란·판정3·매칭, 저렴)
    assert sum(1 for c in client.calls if c["video"]) == 2
    assert len(client.calls) == 7

    # 평가가 끝까지 돌았다
    assert artifacts.evaluation.summary.matched_step_count == 1
    assert artifacts.evaluation.summary.contradiction_count == 0

    # provenance: 추출 3 + 판정 3 + 매칭 1
    purposes = [c.purpose for c in artifacts.manifest.calls]
    assert purposes == [
        "extract_a", "extract_b", "parse_description",
        "judge_description", "judge_audio", "judge_visual", "match_steps",
    ]
    assert artifacts.manifest.input_hash

    # 산출물 저장
    target = save_artifacts(artifacts, tmp_path)
    saved = {p.name for p in target.iterdir()}
    assert saved == {
        "candidate.json", "description-facts.json", "blind.json",
        "evaluation.json", "manifest.json",
    }
    evaluation = json.loads((target / "evaluation.json").read_text(encoding="utf-8"))
    assert evaluation["summary"]["matchedStepCount"] == 1  # camelCase 계약
