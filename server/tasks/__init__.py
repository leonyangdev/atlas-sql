"""后台任务模块。

使用 Celery + Redis 执行元数据同步、Embedding 构建等异步任务。
Celery 应用由 celery_app.py 创建，其他模块从那里导入 ``celery_app``，
避免循环导入和重复初始化。
"""
