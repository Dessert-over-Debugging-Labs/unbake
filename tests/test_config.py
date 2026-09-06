from unbake.config import DEFAULT_MODELS, ModelConfig


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
