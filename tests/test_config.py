import pytest
from pydantic import ValidationError

from server.config import Settings


def valid_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "control_database_url": "postgresql://control:password@localhost:5432/atlas_control",
        "business_database_url": "postgresql://reader:password@localhost:5433/nova_retail",
        "redis_url": "redis://localhost:6379/0",
        "opensearch_url": "http://localhost:9200",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_settings_redact_connection_urls() -> None:
    settings = valid_settings()

    summary = settings.safe_summary()

    assert summary["control_database_url"] == "**********"
    assert summary["business_owner_database_url"] == "not_configured"
    assert "password" not in repr(settings)


def test_settings_redact_optional_business_owner_url() -> None:
    settings = valid_settings(
        business_owner_database_url="postgresql://owner:password@localhost:5433/nova_retail"
    )

    assert settings.safe_summary()["business_owner_database_url"] == "**********"


def test_settings_require_supported_url_scheme() -> None:
    with pytest.raises(ValidationError, match="postgresql"):
        valid_settings(control_database_url="mysql://control:password@localhost/atlas")


def test_missing_required_configuration_is_actionable() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)  # type: ignore[call-arg]

    missing_fields = {item["loc"][0] for item in error.value.errors()}
    assert missing_fields == {
        "control_database_url",
        "business_database_url",
        "redis_url",
        "opensearch_url",
    }


def test_control_and_business_databases_must_be_isolated() -> None:
    same_url = "postgresql://atlas:password@localhost:5432/atlas"
    with pytest.raises(ValidationError, match="different URLs"):
        valid_settings(control_database_url=same_url, business_database_url=same_url)
