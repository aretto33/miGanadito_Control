from flask import current_app
from psycopg.rows import dict_row

from ganacontrol.db_compat import db


def get_connection(dictionary=False):
    """Crea una conexion centralizada a MariaDB o Postgres segun la configuracion."""
    try:
        database_url = current_app.config.get("DATABASE_URL")

        if database_url:
            # En Supabase/Vercel se recomienda usar el pooler para trafico serverless.
            connect_kwargs = {
                "conninfo": database_url,
                "prepare_threshold": None,
            }
            if dictionary:
                connect_kwargs["row_factory"] = dict_row

            conn = db.connect(**connect_kwargs)
            cursor = conn.cursor(row_factory=dict_row) if dictionary else conn.cursor()
            return conn, cursor

        connect_kwargs = {
            "host": current_app.config["DB_HOST"],
            "port": current_app.config["DB_PORT"],
            "user": current_app.config["DB_USER"],
            "password": current_app.config["DB_PASSWORD"],
            "database": current_app.config["DB_NAME"],
        }

        if dictionary:
            connect_kwargs["cursorclass"] = db.DictCursor

        conn = db.connect(**connect_kwargs)
        cursor = conn.cursor()
        return conn, cursor
    except db.Error as exc:
        print("Error de conexion:", exc)
        return None, None
