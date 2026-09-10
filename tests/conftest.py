"""pytest 全局 fixture 与环境配置。"""

import os

# 测试时禁止 app.py 拉起 Celery worker 子进程，避免干扰测试和 CI
os.environ.setdefault("ATLAS_SKIP_WORKER", "1")
