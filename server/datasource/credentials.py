"""凭据引用解析器。

数据源的 ``credential_ref`` 字段只允许以下格式：
- ``env:VAR_NAME``  —— 从当前进程环境变量读取
- ``vault:path/to/secret``  —— 预留给 HashiCorp Vault 或 AWS Secrets Manager（V4 接入）

解析器返回实际连接串；调用方不应把返回值写入日志或响应体。

安全约束：
- 解析结果不缓存，每次同步前临时获取，减少内存中明文存留时间。
- 只允许白名单格式，不接受 ``literal:`` 前缀（明文硬编码）。
"""

import os


class CredentialError(ValueError):
    """凭据引用格式错误或找不到对应值时抛出。"""


def resolve_credential(credential_ref: str) -> str:
    """把凭据引用字符串解析为实际连接串。

    Args:
        credential_ref: 如 ``env:ATLAS_BUSINESS_OWNER_DATABASE_URL``。

    Returns:
        明文连接串，调用方需负责避免泄露。

    Raises:
        CredentialError: 格式不合法或环境变量未设置。
    """
    if credential_ref.startswith("env:"):
        var_name = credential_ref[4:]
        if not var_name:
            raise CredentialError("env credential_ref must specify a variable name")
        value = os.environ.get(var_name)
        if value is None:
            raise CredentialError(f"environment variable {var_name!r} is not set")
        return value

    if credential_ref.startswith("vault:"):
        # V4 阶段接入 Vault；目前返回明确错误而不是静默失败
        raise CredentialError(
            "vault credentials are not yet supported; configure env: reference instead"
        )

    raise CredentialError(
        f"unsupported credential_ref format: {credential_ref!r}; "
        "expected 'env:VAR_NAME' or 'vault:path'"
    )


def check_min_privileges(credential_ref: str) -> None:
    """检查凭据是否符合最小权限要求（只读身份）。

    V0 阶段实现简单的启发式检查：连接串中如果出现 owner/admin/superuser 等关键字作为
    用户名，则警告日志提示，但不阻断同步（因为 DBA 可能故意使用高权限账户进行首次采集）。

    生产强制要求在 V4 权限管理阶段实现。
    """
    try:
        url = resolve_credential(credential_ref)
    except CredentialError:
        return  # 格式校验在 sync 前执行，此处不重复

    from urllib.parse import urlsplit

    parts = urlsplit(url)
    username = (parts.username or "").lower()
    high_privilege_hints = ("owner", "admin", "superuser", "root", "postgres")
    if any(hint in username for hint in high_privilege_hints):
        import logging

        logging.getLogger(__name__).warning(
            "credential may have elevated privileges (username=%r); "
            "consider using a read-only account for metadata sync",
            username,
        )
