"""已废弃的兼容入口：请改用 narrative.ark_story_writer。"""

from narrative.ark_story_writer import (
    ArkConfigurationError,
    ArkResponseError,
    ArkStoryWriterClient,
    ChatModel,
)

# 仅为旧代码兼容保留；新代码不得继续使用这些名字。
DoubaoConfigurationError = ArkConfigurationError
DoubaoResponseError = ArkResponseError
DoubaoStoryWriterClient = ArkStoryWriterClient
