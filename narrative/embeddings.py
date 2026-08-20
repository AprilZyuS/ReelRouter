"""可替换的文本嵌入接口，以及测试与本地 BGE-M3 实现。"""

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import unicodedata
from typing import Any, Protocol

import numpy as np


class EmbeddingProvider(Protocol):
    """将文档或查询转换成固定维度向量的契约。"""

    @property
    def provider_id(self) -> str:
        """返回会影响向量语义的稳定 Provider 标识。"""
        ...

    @property
    def dimension(self) -> int:
        """返回每个向量的维度。"""
        ...

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        """编码知识库文档块，返回形状为 (文本数, dimension) 的 float32 向量。"""
        ...

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        """编码用户检索查询，返回形状为 (文本数, dimension) 的 float32 向量。"""
        ...


@dataclass(frozen=True)
class HashEmbeddingProvider:
    """基于字符 n-gram 的确定性测试嵌入，不能替代真实语义 Embedding 模型。"""

    dimension: int = 128

    def __post_init__(self) -> None:
        if self.dimension < 8:
            raise ValueError("dimension 必须不小于 8。")

    @property
    def provider_id(self) -> str:
        return f"hash-ngram-v1-{self.dimension}d"

    def _embed(self, texts: Sequence[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self.dimension), dtype=np.float32)

        for row_index, text in enumerate(texts):
            normalized = "".join(
                unicodedata.normalize("NFKC", text).casefold().split()
            )
            # 中文没有天然空格分词；字符及相邻双字符可作为稳定、零依赖的测试特征。
            features = list(normalized)
            features.extend(
                normalized[index : index + 2]
                for index in range(max(0, len(normalized) - 1))
            )

            for feature in features:
                digest = hashlib.blake2b(
                    feature.encode("utf-8"), digest_size=8
                ).digest()
                bucket = int.from_bytes(digest[:4], "big") % self.dimension
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vectors[row_index, bucket] += sign

            norm = np.linalg.norm(vectors[row_index])
            if norm > 0:
                vectors[row_index] /= norm

        return vectors

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed(texts)


class _BgeM3Model(Protocol):
    """仅描述 BGEM3FlagModel 在本项目中用到的方法，方便测试替换。"""

    def encode(self, sentences: Sequence[str], **kwargs: Any) -> dict[str, Any]:
        ...


class BgeM3EmbeddingProvider:
    """基于本地 BAAI/bge-m3 的 GPU dense-embedding Provider。"""

    dimension = 1024

    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-m3",
        batch_size: int = 4,
        max_length: int = 1024,
        use_fp16: bool = True,
        model: _BgeM3Model | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size 必须大于 0。")
        if max_length < 1:
            raise ValueError("max_length 必须大于 0。")

        self.model_name = model_name
        self.batch_size = batch_size
        self.max_length = max_length
        self.use_fp16 = use_fp16
        self._model = model

    @property
    def provider_id(self) -> str:
        # batch_size 不影响向量语义；模型名称和向量维度会影响。
        return f"bge-m3-dense-v1:{self.model_name}:{self.dimension}d"

    def _get_model(self) -> _BgeM3Model:
        if self._model is None:
            try:
                from FlagEmbedding import BGEM3FlagModel
            except ImportError as error:
                raise RuntimeError(
                    "未安装 FlagEmbedding；请先安装本地 GPU 依赖。"
                ) from error

            # Hugging Face 缓存位置由启动进程前设置的 HF_HOME 决定。
            self._model = BGEM3FlagModel(
                self.model_name,
                use_fp16=self.use_fp16,
            )
        return self._model

    def _embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)

        result = self._get_model().encode(
            list(texts),
            batch_size=self.batch_size,
            max_length=self.max_length,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        vectors = np.asarray(result["dense_vecs"], dtype=np.float32)
        expected_shape = (len(texts), self.dimension)
        if vectors.shape != expected_shape:
            raise RuntimeError(
                f"BGE-M3 输出形状应为 {expected_shape}，实际为 {vectors.shape}。"
            )
        return vectors

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        """BGE-M3 当前 dense 模式对文档不添加额外指令。"""
        return self._embed(texts)

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        """保留独立入口，未来切换带 query instruction 的模型时无需改 FAISS。"""
        return self._embed(texts)
