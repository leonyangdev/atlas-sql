"""LLM 与 Embedding 抽象层。

业务代码不直接调用 OpenAI / BGE-M3 SDK，而是通过这里的 Provider 接口操作。
这样可以在不修改业务逻辑的前提下切换模型厂商或对比不同模型的效果。
"""
