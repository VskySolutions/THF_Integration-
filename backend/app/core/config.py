from functools import lru_cache

from pydantic import (
    AnyHttpUrl,
    Field,
    SecretStr,
    computed_field,
    field_validator,
)
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

    # App settings
    app_name: str = "Falcon THF Integration Services"
    app_env: str
    api_v1_prefix: str = "/api/v1"
    docs_enabled: bool = True

    # Database settings
    postgres_user: str
    postgres_password: SecretStr
    postgres_host: str
    postgres_port: int = Field(
        default=5432,
        ge=1,
        le=65535,
    )
    postgres_db: str
    database_echo: bool = False

    # Comma-separated values allow key rotation without downtime.
    api_keys: SecretStr
   
    # Maconomy integration settings
    maconomy_base_url: AnyHttpUrl = AnyHttpUrl(
        "http://localhost:8080"
    )
    maconomy_shortname: str
    maconomy_username: str
    maconomy_password: SecretStr
    maconomy_send_name_components: bool = False

    # Caseware Cloud integration settings
    caseware_cloud_base_url: AnyHttpUrl = AnyHttpUrl(
        "https://api.casewarecloud.com"
    )
    caseware_cloud_client_id: SecretStr
    caseware_cloud_client_secret: SecretStr
    caseware_cloud_language: str = "en"

    # CCH
    cch_axcess_url: AnyHttpUrl = AnyHttpUrl(
        "https://sandboxworkflow.cchaxcess.com"
    )
    cch_axcess_api_key: SecretStr
    cch_axcess_user_name: str
    cch_axcess_password: SecretStr

    # Paycor integration settings
    paycor_base_url: AnyHttpUrl = AnyHttpUrl(
        "https://apis-sandbox.paycor.com"
    )
    paycor_client_id: SecretStr
    paycor_client_secret: SecretStr
    paycor_refresh_token: SecretStr
    paycor_subscription_key: SecretStr
    paycor_legal_entity_id: str 
    paycor_tenant_id: str
    
    # SAP Concur integration settings
    sap_concur_url: AnyHttpUrl = AnyHttpUrl(
        "https://us2concursolutions.com"
    )
    sap_concur_api_base_url: AnyHttpUrl = AnyHttpUrl(
        "https://us.api.concursolutions.com"
    )
    sap_concur_client_id: SecretStr
    sap_concur_client_secret: SecretStr
    sap_concur_refresh_token: SecretStr    

    # Schedular settings
    scheduler_enabled: bool = False
    scheduler_api_base_url: AnyHttpUrl = AnyHttpUrl(
        "http://127.0.0.1:8000"
    )
    scheduler_api_key: SecretStr
    scheduler_interval_minutes: int = Field(default=5, ge=1)
    scheduler_request_timeout_seconds: float = Field(default=600, gt=0)

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        normalized = value.rstrip("/") or "/"

        if not normalized.startswith("/"):
            raise ValueError(
                "API_V1_PREFIX must start with '/'"
            )

        return normalized

    @computed_field
    @property
    def database_url(self) -> str:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=(
                self.postgres_password.get_secret_value()
            ),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)

    @computed_field
    @property
    def maconomy_url(self) -> str:
        return str(
            self.maconomy_base_url
        ).rstrip("/")

    @computed_field
    @property
    def caseware_cloud_url(self) -> str:
        return str(self.caseware_cloud_base_url).rstrip("/")

    
    @computed_field
    @property
    def paycor_url(self) -> str:
        return str(self.paycor_base_url).rstrip("/")

    @property
    def scheduler_api_url(self) -> str:
        return str(self.scheduler_api_base_url).rstrip("/")

    @property
    def accepted_api_keys(self) -> tuple[str, ...]:
        return tuple(
            key.strip()
            for key in (
                self.api_keys
                .get_secret_value()
                .split(",")
            )
            if key.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()