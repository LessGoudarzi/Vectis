from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "Vectis Yield Spatial API Engine"
    DEBUG: bool = True
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173", "http://localhost"]
    MAPBOX_ACCESS_TOKEN: str = ""
    INDUSTRIAL_CONVERGENCE_PAYLOAD_DIR: str = "data/industrial_convergence_payloads"

    class Config:
        env_file = ".env"


settings = Settings()
