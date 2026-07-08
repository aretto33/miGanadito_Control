import os

from dotenv import load_dotenv


load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "SECRET_KEY_GANACONTROL_2025")

    # Vercel + Supabase: usar la cadena completa del pooler de transacciones.
    DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")

    # Compatibilidad con modo local MySQL/MariaDB y variables automaticas de Railway.
    DB_HOST = os.getenv("DB_HOST") or os.getenv("MYSQLHOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT") or os.getenv("MYSQLPORT", "3306"))
    DB_USER = os.getenv("DB_USER") or os.getenv("MYSQLUSER", "arletteg")
    DB_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("MYSQLPASSWORD", "123456")
    DB_NAME = os.getenv("DB_NAME") or os.getenv("MYSQLDATABASE", "Proyecto_Ganaderia2")

    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER") or MAIL_USERNAME
    MAIL_TOKEN_MAX_AGE = int(os.getenv("MAIL_TOKEN_MAX_AGE", "1800"))

    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
