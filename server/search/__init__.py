"""检索基础设施模块。

封装 OpenSearch（词法检索）、Milvus（向量检索）和 Redis 缓存的底层操作。
业务层通过 SearchRepository 访问，不能直接引用这里的具体客户端。

V0-S05 建立索引结构、Embedding 抽象和 Redis 命名空间约定。
V2 阶段在此基础上实现 RRF 融合与 Reranker。
"""
