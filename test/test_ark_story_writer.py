import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from narrative.ark_story_writer import (
    ArkConfigurationError,
    ArkResponseError,
    ArkStoryWriterClient,
)


class FakeChatModel:
    """不访问网络的聊天模型替身，用于验证适配器行为。"""

    def __init__(self, response: AIMessage) -> None:
        self.response = response
        self.messages: list[BaseMessage] | None = None

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.messages = messages
        return self.response


class CapturingChatModelFactory:
    """记录 Ark 客户端传给 ChatOpenAI 的参数，但不进行真实网络调用。"""

    def __init__(self) -> None:
        self.arguments: dict[str, object] | None = None

    def __call__(self, **kwargs: object) -> FakeChatModel:
        self.arguments = kwargs
        return FakeChatModel(AIMessage(content="{}"))


def test_generate_passes_system_and_human_messages_to_llm():
    fake_llm = FakeChatModel(AIMessage(content="{\"title\": \"雨夜来信\"}"))
    client = ArkStoryWriterClient(llm=fake_llm)

    response = client.generate(
        system_prompt="你是中文小说创作 Agent。",
        user_prompt="请写一个都市悬疑故事。",
    )

    assert response == '{"title": "雨夜来信"}'
    assert fake_llm.messages is not None
    assert len(fake_llm.messages) == 2
    assert isinstance(fake_llm.messages[0], SystemMessage)
    assert fake_llm.messages[0].content == "你是中文小说创作 Agent。"
    assert isinstance(fake_llm.messages[1], HumanMessage)
    assert fake_llm.messages[1].content == "请写一个都市悬疑故事。"


def test_generate_rejects_empty_model_response():
    client = ArkStoryWriterClient(llm=FakeChatModel(AIMessage(content="")))

    with pytest.raises(ArkResponseError, match="未返回非空文本"):
        client.generate(system_prompt="system", user_prompt="user")


def test_generate_extracts_text_from_content_blocks():
    client = ArkStoryWriterClient(
        llm=FakeChatModel(
            AIMessage(
                content=[
                    {"type": "text", "text": '{"title": '},
                    {"type": "text", "text": '"雨夜来信"}'},
                ]
            )
        )
    )

    response = client.generate(system_prompt="system", user_prompt="user")

    assert response == '{"title": "雨夜来信"}'


def test_generate_explains_response_with_reasoning_but_no_final_text():
    client = ArkStoryWriterClient(
        llm=FakeChatModel(
            AIMessage(
                content="",
                additional_kwargs={"reasoning_content": "先分析用户的要求。"},
            )
        )
    )

    with pytest.raises(ArkResponseError, match="reasoning_content"):
        client.generate(system_prompt="system", user_prompt="user")


def test_generate_reports_safe_metadata_for_empty_text_response():
    client = ArkStoryWriterClient(
        llm=FakeChatModel(
            AIMessage(
                content="",
                additional_kwargs={"refusal": "内容未通过策略。"},
                response_metadata={
                    "finish_reason": "length",
                    "model_name": "doubao-story-endpoint",
                },
            )
        )
    )

    with pytest.raises(ArkResponseError) as error:
        client.generate(system_prompt="system", user_prompt="user")

    message = str(error.value)
    assert "content 类型：str" in message
    assert "finish_reason=length" in message
    assert "model=doubao-story-endpoint" in message
    assert "refusal_detected=true" in message
    assert "内容未通过策略" not in message


def test_safe_diagnostics_include_token_counts_but_not_response_content():
    diagnostics = ArkStoryWriterClient._safe_response_diagnostics(
        {"finish_reason": "length"},
        {},
        {
            "input_tokens": 120,
            "output_tokens": 8_192,
            "total_tokens": 8_312,
            "reasoning_tokens": 8_000,
        },
    )

    assert "finish_reason=length" in diagnostics
    assert "input_tokens=120" in diagnostics
    assert "output_tokens=8192" in diagnostics
    assert "reasoning_tokens=8000" in diagnostics


def test_constructor_rejects_missing_environment_variables(monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_BASE_URL", raising=False)
    monkeypatch.delenv("ARK_STORY_MODEL", raising=False)
    monkeypatch.delenv("ARK_STORY_MAX_TOKENS", raising=False)

    with pytest.raises(ArkConfigurationError) as error:
        ArkStoryWriterClient()

    assert "缺少环境变量" in str(error.value)


def test_constructor_reads_story_model_and_max_tokens_from_environment(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "test-key")
    monkeypatch.setenv("ARK_BASE_URL", "https://ark.example.test/api/v3")
    monkeypatch.setenv("ARK_STORY_MODEL", "ep-deepseek-story")
    monkeypatch.setenv("ARK_STORY_MAX_TOKENS", "8192")
    monkeypatch.setenv("ARK_STORY_THINKING", "disabled")
    monkeypatch.setenv("ARK_STORY_TEMPERATURE", "0.2")

    factory = CapturingChatModelFactory()

    client = ArkStoryWriterClient(llm_factory=factory)

    assert client.model == "ep-deepseek-story"
    assert client.max_tokens == 8192
    assert client.thinking == "disabled"
    assert client.temperature == 0.2
    assert factory.arguments is not None
    assert factory.arguments["extra_body"] == {"thinking": {"type": "disabled"}}
    assert factory.arguments["temperature"] == 0.2


def test_constructor_rejects_invalid_story_max_tokens(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "test-key")
    monkeypatch.setenv("ARK_BASE_URL", "https://ark.example.test/api/v3")
    monkeypatch.setenv("ARK_STORY_MODEL", "ep-deepseek-story")
    monkeypatch.setenv("ARK_STORY_MAX_TOKENS", "not-a-number")

    with pytest.raises(ArkConfigurationError, match="ARK_STORY_MAX_TOKENS"):
        ArkStoryWriterClient()


def test_constructor_rejects_invalid_thinking_mode(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "test-key")
    monkeypatch.setenv("ARK_BASE_URL", "https://ark.example.test/api/v3")
    monkeypatch.setenv("ARK_STORY_MODEL", "ep-deepseek-story")
    monkeypatch.setenv("ARK_STORY_THINKING", "automatic")

    with pytest.raises(ArkConfigurationError, match="ARK_STORY_THINKING"):
        ArkStoryWriterClient(llm_factory=CapturingChatModelFactory())
