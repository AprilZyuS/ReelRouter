"""BGE-M3 Provider 的无模型单元测试。"""

import numpy as np
import pytest

from narrative.embeddings import BgeM3EmbeddingProvider


class FakeBgeM3Model:
    """模拟 BGEM3FlagModel，避免默认测试加载数 GB 模型文件。"""

    def __init__(self, vectors: np.ndarray) -> None:
        self.vectors = vectors
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def encode(self, sentences, **kwargs):
        self.calls.append((list(sentences), kwargs))
        return {"dense_vecs": self.vectors[: len(sentences)]}


def test_bge_m3_provider_encodes_documents_and_queries_as_float32():
    model = FakeBgeM3Model(np.ones((2, 1024), dtype=np.float16))
    provider = BgeM3EmbeddingProvider(
        model=model,
        batch_size=2,
        max_length=512,
    )

    document_vectors = provider.embed_documents(["第一段", "第二段"])
    query_vectors = provider.embed_queries(["查询"])

    assert document_vectors.shape == (2, 1024)
    assert document_vectors.dtype == np.float32
    assert query_vectors.shape == (1, 1024)
    assert provider.provider_id == "bge-m3-dense-v1:BAAI/bge-m3:1024d"
    assert model.calls[0][1]["batch_size"] == 2
    assert model.calls[0][1]["max_length"] == 512
    assert model.calls[0][1]["return_sparse"] is False


def test_bge_m3_provider_rejects_unexpected_vector_shape():
    provider = BgeM3EmbeddingProvider(
        model=FakeBgeM3Model(np.ones((1, 128), dtype=np.float16))
    )

    with pytest.raises(RuntimeError, match="输出形状"):
        provider.embed_documents(["错误维度"])


@pytest.mark.parametrize(
    ("batch_size", "max_length"),
    [(0, 1024), (4, 0)],
)
def test_bge_m3_provider_rejects_invalid_runtime_settings(
    batch_size: int,
    max_length: int,
):
    with pytest.raises(ValueError):
        BgeM3EmbeddingProvider(
            batch_size=batch_size,
            max_length=max_length,
        )
