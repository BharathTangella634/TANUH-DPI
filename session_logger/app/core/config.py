import os
import urllib.parse
from dotenv import load_dotenv

load_dotenv()


class Settings:
    PROJECT_NAME: str = "NHCX Session Logger API"
    PROJECT_VERSION: str = "1.0.0"

    # ── MySQL / Cloud SQL (via Cloud SQL Auth Proxy) ────────────────────
    MYSQL_USER: str = os.getenv("MYSQL_USER")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD")
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "cloud-sql-proxy")
    MYSQL_PORT: str = os.getenv("MYSQL_PORT", "3306")
    MYSQL_DB: str = os.getenv("MYSQL_DB", "dpi_session_logger")
    MYSQL_QUERY: str = os.getenv("MYSQL_QUERY", "charset=utf8mb4")

    @property
    def DATABASE_URL(self) -> str:
        password = urllib.parse.quote_plus(self.MYSQL_PASSWORD) if self.MYSQL_PASSWORD else ""
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{password}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}"
            f"?{self.MYSQL_QUERY}"
        )


settings = Settings()
