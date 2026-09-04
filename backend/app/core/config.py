from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        validate_default=True,
    )

    app_name: str = "Falcon THF Integration Services"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    docs_enabled: bool = True

    postgres_user: str = "postgres"
    postgres_password: SecretStr = SecretStr("postgres")
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "falcon_thf"
    database_echo: bool = False

    # Comma-separated values allow key rotation without downtime.
    api_keys: SecretStr = Field(default=SecretStr("change-me"))

    scheduler_enabled: bool = False
    scheduler_api_base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8000")
    scheduler_api_key: SecretStr = SecretStr("change-me")
    scheduler_interval_minutes: int = Field(default=5, ge=1)
    scheduler_request_timeout_seconds: float = Field(default=600, gt=0)

    maconomy_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8080")
    maconomy_shortname: str = "d104p"
    maconomy_username: str = "admin"
    maconomy_password: SecretStr = SecretStr("admin")

    caseware_cloud_base_url: AnyHttpUrl = AnyHttpUrl("https://api.casewarecloud.com")
    caseware_cloud_client_id: str = "replace-with-your-client-id"
    caseware_cloud_client_secret: SecretStr = SecretStr(
        "replace-with-your-client-secret"
    )
    caseware_cloud_language: str = "en"

    sap_concur_url: AnyHttpUrl = AnyHttpUrl("https://us2concursolutions.com")
    sap_concur_client_id: str = "cddce98b-2b01-403d-84c6-685afe69c3c5"
    sap_concur_client_secret: SecretStr = SecretStr(
        "5acfaf42-41e9-473c-bf83-d2198d872262"
    )
    sap_concur_refresh_token: str = "replace-with-your-refresh-token"

    cch_axcess_url: AnyHttpUrl = AnyHttpUrl("https://sandboxworkflow.cchaxcess.com")
    cch_axcess_client_id: str = "replace-with-your-client-id"
    cch_axcess_client_secret: SecretStr = SecretStr(
        "replace-with-your-client-secret"    
    )


    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        normalized = value.rstrip("/") or "/"
        if not normalized.startswith("/"):
            raise ValueError("API_V1_PREFIX must start with '/'")
        return normalized

    @computed_field
    @property
    def database_url(self) -> str:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)

    @computed_field
    @property
    def maconomy_url(self) -> str:
        return str(self.maconomy_base_url).rstrip("/")

    @computed_field
    @property
    def caseware_cloud_url(self) -> str:
        return str(self.caseware_cloud_base_url).rstrip("/")

    @property
    def scheduler_api_url(self) -> str:
        return str(self.scheduler_api_base_url).rstrip("/")

    @property
    def accepted_api_keys(self) -> tuple[str, ...]:
        return tuple(
            key.strip()
            for key in self.api_keys.get_secret_value().split(",")
            if key.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
