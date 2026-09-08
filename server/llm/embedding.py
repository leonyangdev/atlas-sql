"""EmbeddingProvider 抽象接口及 BGE-M3 实现。

抽象层好处：
- 单测时用 FakeEmbeddingProvider 不需要 GPU 或网络。
- 可以在 A/B 测试中并行使用两个 Provider 比较效果。
- 切换模型只需换一个 Provider 实现，不影响 Celery 任务、索引构建逻辑。

BGE-M3 返回三种向量：dense（主要用）、sparse（BM25-style）、colbert（晚期交互）。
V0 阶段只用 dense 向量；sparse 留待 V2 的混合检索阶段。

依赖安装（GPU 可选）：
  uv add "FlagEmbedding>=1.3,<2"
  uv add "torch>=2.0"   # 纯 CPU 推理不需要 GPU CUDA

由于 FlagEmbedding 体积较大，在 pyproject.toml 中将其放入可选依赖组 `embedding`。
测试和 CI 不安装此组，使用 FakeEmbeddingProvider 代替。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class EmbeddingResult:
    """单条文本的 Embedding 结果。"""

    # 密集向量，长度由模型决定（BGE-M3 为 1024）
    dense: list[float]
    # 使用的模型版本标识，写入索引用于追踪
    model_version: str


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Embedding Provider 最小协议。

    实现类只需满足此协议，不必显式继承。
    ``model_version`` 属性写入索引，用于检测 stale 向量。
    ``embed_batch`` 支持批量调用，减少每条文本单独推理的开销。
    """

    @property
    def model_version(self) -> str:
        """返回当前模型的版本标识，例如 ``'BAAI/bge-m3@v1.0'``。"""
        ...

    @property
    def dimension(self) -> int:
        """返回密集向量的维度。"""
        ...

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """批量 Embedding，返回与输入等长的结果列表。"""
        ...


class BaseEmbeddingProvider(ABC):
    """为实现类提供批量分片和维度校验的公共逻辑。"""

    @property
    @abstractmethod
    def model_version(self) -> str: ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    def _encode(self, texts: list[str]) -> list[list[float]]:
        """子类实现：对一批文本编码，返回密集向量列表。"""
        ...

    def embed_batch(self, texts: list[str], batch_size: int = 64) -> list[EmbeddingResult]:
        """分批调用 ``_encode`` 并组装结果。

        Args:
            texts: 待编码的文本列表。
            batch_size: 单次送入模型的最大文本数；过大会占用过多显存。

        Returns:
            与 texts 等长的 EmbeddingResult 列表。
        """
        if not texts:
            return []

        results: list[EmbeddingResult] = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            vectors = self._encode(chunk)
            for vec in vectors:
                results.append(EmbeddingResult(dense=vec, model_version=self.model_version))
        return results


class BGEM3EmbeddingProvider(BaseEmbeddingProvider):
    """使用 BGE-M3 模型进行中英文混合 Embedding。

    需要安装 ``FlagEmbedding`` 包：
        uv add --group embedding "FlagEmbedding>=1.3,<2"

    首次使用时会从 HuggingFace（或本地缓存）下载模型权重，约 2GB。
    模型目录可通过 ``HUGGINGFACE_HUB_CACHE`` 环境变量自定义。
    """

    MODEL_ID = "BAAI/bge-m3"
    # V0 使用官方仓库 tag，生产可固定到 commit hash
    MODEL_VERSION = "BAAI/bge-m3@v1.0"
    DENSE_DIMENSION = 1024

    def __init__(self, use_fp16: bool = True, device: str = "cpu") -> None:
        """加载 BGE-M3 模型。

        Args:
            use_fp16: 使用半精度浮点（GPU 下推荐），CPU 推理建议 False。
            device: ``"cpu"``、``"cuda"`` 或 ``"mps"``（Apple Silicon）。
        """
        try:
            from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "FlagEmbedding is not installed. "
                "Run: uv add --group embedding 'FlagEmbedding>=1.3,<2'"
            ) from exc

        self._model = BGEM3FlagModel(self.MODEL_ID, use_fp16=use_fp16, device=device)

    @property
    def model_version(self) -> str:
        return self.MODEL_VERSION

    @property
    def dimension(self) -> int:
        return self.DENSE_DIMENSION

    def _encode(self, texts: list[str]) -> list[list[float]]:
        """调用 BGE-M3 编码，只取 dense 向量并转为 Python list。"""
        output = self._model.encode(texts, return_dense=True, return_sparse=False)
        # output["dense_vecs"] 是 numpy 数组，转为 Python float list
        return [vec.tolist() for vec in output["dense_vecs"]]


class FakeEmbeddingProvider(BaseEmbeddingProvider):
    """测试用的确定性假 Embedding Provider。

    不依赖任何 ML 框架，用文本哈希生成固定维度的假向量。
    同一文本总是返回同一向量，保证测试可重复。
    """

    def __init__(self, dimension: int = 8) -> None:
        """初始化。

        Args:
            dimension: 假向量维度，默认 8（足够测试形状和索引逻辑）。
        """
        self._dimension = dimension
        self._version = f"fake@dim={dimension}"

    @property
    def model_version(self) -> str:
        return self._version

    @property
    def dimension(self) -> int:
        return self._dimension

    def _encode(self, texts: list[str]) -> list[list[float]]:
        """用文本的 ord 值之和生成确定性假向量。"""
        results = []
        for text in texts:
            seed = sum(ord(c) for c in text) % 256
            # 生成 dimension 维的归一化假向量
            vec = [(seed + i) % 256 / 255.0 for i in range(self._dimension)]
            norm = sum(v * v for v in vec) ** 0.5
            vec = [v / norm for v in vec] if norm > 0 else vec
            results.append(vec)
        return results
