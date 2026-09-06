import pytest

from unbake.extraction.prompt_store import PROMPT_DIR, load_prompt

ALL_PROMPTS = [
    "generator", "blind_extractor", "description_parser", "judge", "matcher", "filter_verdict",
]


def test_모든_프롬프트가_버전과_해시를_가진다():
    for name in ALL_PROMPTS:
        prompt = load_prompt(name)
        assert prompt.version
        assert len(prompt.hash) == 16


def test_프롬프트_디렉토리에_등록_안된_파일이_없다():
    on_disk = {p.stem for p in PROMPT_DIR.glob("*.md")}
    assert on_disk == set(ALL_PROMPTS)


def test_render_치환():
    prompt = load_prompt("description_parser")
    rendered = prompt.render(DESCRIPTION="돼지고기 300g")
    assert "돼지고기 300g" in rendered
    assert "{{" not in rendered


def test_render_빠진_변수는_에러():
    prompt = load_prompt("generator")
    with pytest.raises(ValueError, match="채워지지 않은"):
        prompt.render(VIDEO_ID="x")  # DURATION_MS·DESCRIPTION 누락
