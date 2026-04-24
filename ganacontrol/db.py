import mariadb
from flask import current_app


def get_connection(dictionary=False):
    """Crea una conexion centralizada a MariaDB usando la configuracion de Flask."""
    try:
        conn = mariadb.connect(
            host=current_app.config["DB_HOST"],
            port=current_app.config["DB_PORT"],
            user=current_app.config["DB_USER"],
            password=current_app.config["DB_PASSWORD"],
            database=current_app.config["DB_NAME"],
        )
        cursor = conn.cursor(dictionary=dictionary) if dictionary else conn.cursor()
        return conn, cursor
    except mariadb.Error as exc:
        print("Error de conexion:", exc)
        return None, None
