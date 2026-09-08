from pydantic import SecretStr

from server.db import sqlalchemy_url


def test_sqlalchemy_url_adds_asyncpg_driver() -> None:
    result = sqlalchemy_url(SecretStr("postgresql://user:password@localhost/database"))

    assert result == "postgresql+asyncpg://user:password@localhost/database"


def test_sqlalchemy_url_preserves_explicit_async_driver() -> None:
    url = "postgresql+asyncpg://user:password@localhost/database"

    assert sqlalchemy_url(SecretStr(url)) == url
