import pytest

from unbake.config import DEFAULT_MODELS, ModelConfig, resolve_domain_check


def test_기본_모델은_DEFAULT_MODELS_단일_출처(monkeypatch):
    for key in ("GENERATOR", "BLIND", "DESCRIPTION", "JUDGE", "MATCHER"):
        monkeypatch.delenv(f"GEMINI_MODEL_{key}", raising=False)
    models = ModelConfig.from_env()
    assert models.generator == DEFAULT_MODELS["generator"]
    assert models.judge == DEFAULT_MODELS["judge"]


def test_env로_역할별_모델_교체(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL_JUDGE", "some-other-judge-model")
    monkeypatch.delenv("GEMINI_MODEL_MATCHER", raising=False)
    models = ModelConfig.from_env()
    # judge만 바꾸고 matcher는 기본값 유지 — 역할별 독립 설정
    assert models.judge == "some-other-judge-model"
    assert models.matcher == DEFAULT_MODELS["matcher"]


def test_모델ID_latest_별칭_금지():
    # 기본값에 latest 별칭이 섞이면 재현성 계약 위반
    assert all("latest" not in model_id for model_id in DEFAULT_MODELS.values())


# ── 도메인 게이트 설정 — 키가 있을 때만 켜지고, 오타는 조용히 꺼지지 않는다 ──

def test_DOMAIN_CHECK_비어있으면_OpenRouter_키_유무로_결정():
    assert resolve_domain_check(None, has_openrouter_key=True) == "openrouter"
    assert resolve_domain_check("", has_openrouter_key=False) == "off"


def test_DOMAIN_CHECK_명시값은_세_가지만():
    assert resolve_domain_check("gemini", has_openrouter_key=False) == "gemini"
    assert resolve_domain_check("OFF", has_openrouter_key=True) == "off"
    with pytest.raises(RuntimeError, match="DOMAIN_CHECK"):
        resolve_domain_check("openai", has_openrouter_key=True)


def test_도메인_모델은_DOMAIN_MODEL로_교체(monkeypatch):
    monkeypatch.delenv("DOMAIN_MODEL", raising=False)
    assert ModelConfig.from_env().domain == DEFAULT_MODELS["domain"]
    monkeypatch.setenv("DOMAIN_MODEL", "some/cheap-model")
    assert ModelConfig.from_env().domain == "some/cheap-model"
