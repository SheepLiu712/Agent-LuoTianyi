"""图像理解 Skill 的真实 VLM 集成测试。"""

import os
from pathlib import Path

import pytest

import src.domain.agent as d
from src.agent.skills.cognitive import ImageUnderstandingSkill
from src.infrastructure.media import ResolvedMedia
from src.infrastructure.models.service import LLMService
from src.utils.helpers import load_config

server_root = str(Path(__file__).resolve().parents[3])


@pytest.fixture(scope="module", autouse=True)
def server_cwd():
    old_cwd = os.getcwd()
    os.chdir(server_root)
    try:
        yield
    finally:
        os.chdir(old_cwd)


IMAGE_PATH = Path("data/images/00bbd621-e786-40e5-8ff0-6655da25daa7/2026-03-02_23-00-12..png")


@pytest.fixture(scope="module")
def full_config():
    return load_config("config/config.json")


@pytest.fixture(scope="module")
def image_understanding(full_config):
    llm_service = LLMService(full_config["llm_service"])
    resolver = type(
        "Resolver",
        (),
        {
            "resolve": lambda self, media_ref, *, owner_user_id: ResolvedMedia(
                data=IMAGE_PATH.read_bytes(),
                mime_type="image/png",
            )
        },
    )()
    return ImageUnderstandingSkill(
        full_config["agent_runtime"]["skills"]["image_understanding"],
        resolver,
        llm_service,
    )


def test_vlm_config_is_valid(full_config):
    image_cfg = full_config["agent_runtime"]["skills"]["image_understanding"]
    module_cfg = image_cfg.get("vlm_module", {})
    vlm_cfg = module_cfg.get("vlm", {})

    assert vlm_cfg.get("name") in full_config["llm_service"]["available_vlms"]
    assert module_cfg.get("prompt_name") == "vision_interaction_prompt"
    assert Path("res/agent/prompts/vision_interaction_prompt.json").exists()
    assert IMAGE_PATH.exists()


@pytest.mark.asyncio
async def test_vlm_describes_image_with_non_empty_content(image_understanding):
    _media, description = await image_understanding.understand(
        d.MediaRef(media_id="fixture-image"),
        owner_user_id="fixture-user",
    )

    assert isinstance(description, str)
    assert description.startswith("[一张图片]:")
    content = description.removeprefix("[一张图片]:").strip()
    assert content, "VLM description should contain content after the image prefix"
