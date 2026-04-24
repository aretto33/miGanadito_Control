import os

from dotenv import load_dotenv


load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "SECRET_KEY_GANACONTROL_2025")

    # Compatibilidad con variables locales y variables automaticas de Railway MySQL.
    DB_HOST = os.getenv("DB_HOST") or os.getenv("MYSQLHOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT") or os.getenv("MYSQLPORT", "3306"))
    DB_USER = os.getenv("DB_USER") or os.getenv("MYSQLUSER", "arletteg")
    DB_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("MYSQLPASSWORD", "123456")
    DB_NAME = os.getenv("DB_NAME") or os.getenv("MYSQLDATABASE", "Proyecto_Ganaderia2")

    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "true").lower() == "true"
