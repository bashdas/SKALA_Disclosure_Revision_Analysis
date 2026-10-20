from disclosure_shared.config import ServiceSettings


class Settings(ServiceSettings):
    database_url: str = ""
    rabbitmq_url: str = ""
    rabbitmq_analysis_queue: str = "analysis.tasks"
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
