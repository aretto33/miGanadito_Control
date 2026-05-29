import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import app, conectar_bd, crear_hash_contrasena


USUARIOS_DEMO = [
    {
        "usuario": "admin",
        "email": "admin@miganadito.local",
        "password": "AdminGanadito2026!",
        "rol": "Administrador",
    },
    {
        "usuario": "productor_demo",
        "email": "productor@miganadito.local",
        "password": "Productor2026!",
        "rol": "Productor",
        "productor": {
            "nombre": "Productor",
            "apellido_pat": "Demo",
            "apellido_mat": "Rancho",
            "RFC": "XAXX010101000",
        },
    },
    {
        "usuario": "vet_demo",
        "email": "vet@miganadito.local",
        "password": "Veterinario2026!",
        "rol": "Veterinario",
        "veterinario": {
            "nombre": "Veterinario",
            "apellidos": "Demo",
            "cedula": "VET-2026-DEMO",
            "direccion_consultorio": "Consultas a domicilio",
            "telefono": "5551234567",
        },
    },
    {
        "usuario": "comprador_demo",
        "email": "comprador@miganadito.local",
        "password": "Comprador2026!",
        "rol": "Comprador",
    },
]


def obtener_id_rol(cursor, nombre):
    cursor.execute("SELECT id_rol FROM Rol WHERE nombre=%s", (nombre,))
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute("INSERT INTO Rol (nombre) VALUES (%s)", (nombre,))
    cursor.execute("SELECT id_rol FROM Rol WHERE nombre=%s ORDER BY id_rol DESC", (nombre,))
    return cursor.fetchone()[0]


def tabla_usuarios_tiene_email(cursor):
    try:
        cursor.execute("SELECT email FROM Usuarios LIMIT 1")
        return True
    except Exception:
        return False


def obtener_id_usuario(cursor, usuario):
    cursor.execute("SELECT id_usuario FROM Usuarios WHERE usuario=%s", (usuario,))
    row = cursor.fetchone()
    return row[0] if row else None


def guardar_usuario(cursor, datos, fk_rol, tiene_email):
    password_hash = crear_hash_contrasena(datos["password"])
    id_usuario = obtener_id_usuario(cursor, datos["usuario"])

    if id_usuario:
        if tiene_email:
            cursor.execute(
                "UPDATE Usuarios SET email=%s, password=%s, fk_rol=%s WHERE id_usuario=%s",
                (datos["email"], password_hash, fk_rol, id_usuario),
            )
        else:
            cursor.execute(
                "UPDATE Usuarios SET password=%s, fk_rol=%s WHERE id_usuario=%s",
                (password_hash, fk_rol, id_usuario),
            )
        return id_usuario

    if tiene_email:
        cursor.execute(
            "INSERT INTO Usuarios (usuario, email, password, fk_rol) VALUES (%s, %s, %s, %s)",
            (datos["usuario"], datos["email"], password_hash, fk_rol),
        )
    else:
        cursor.execute(
            "INSERT INTO Usuarios (usuario, password, fk_rol) VALUES (%s, %s, %s)",
            (datos["usuario"], password_hash, fk_rol),
        )

    return obtener_id_usuario(cursor, datos["usuario"])


def guardar_productor(cursor, id_usuario, datos):
    productor = datos.get("productor")
    if not productor:
        return

    cursor.execute("SELECT pk_productor FROM Productores WHERE fk_usuario=%s", (id_usuario,))
    row = cursor.fetchone()

    if row:
        cursor.execute(
            """
            UPDATE Productores
            SET nombre=%s, apellido_pat=%s, apellido_mat=%s, RFC=%s
            WHERE fk_usuario=%s
            """,
            (
                productor["nombre"],
                productor["apellido_pat"],
                productor["apellido_mat"],
                productor["RFC"],
                id_usuario,
            ),
        )
        return

    cursor.execute(
        """
        INSERT INTO Productores (fk_usuario, nombre, apellido_pat, apellido_mat, RFC)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            id_usuario,
            productor["nombre"],
            productor["apellido_pat"],
            productor["apellido_mat"],
            productor["RFC"],
        ),
    )


def guardar_veterinario(cursor, id_usuario, datos):
    veterinario = datos.get("veterinario")
    if not veterinario:
        return

    cursor.execute("SELECT id_veterinario FROM Veterinario WHERE fk_usuario=%s", (id_usuario,))
    row = cursor.fetchone()

    valores = (
        veterinario["nombre"],
        veterinario["apellidos"],
        veterinario["cedula"],
        veterinario["direccion_consultorio"],
        veterinario["telefono"],
        id_usuario,
    )

    if row:
        cursor.execute(
            """
            UPDATE Veterinario
            SET nombre=%s, apellidos=%s, cedula=%s, direccion_consultorio=%s, telefono=%s
            WHERE fk_usuario=%s
            """,
            valores,
        )
        return

    cursor.execute(
        """
        INSERT INTO Veterinario
            (nombre, apellidos, cedula, direccion_consultorio, telefono, fk_usuario)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        valores,
    )


def main():
    with app.app_context():
        conn, cursor = conectar_bd()
        if not conn:
            raise RuntimeError("No se pudo conectar a la base de datos.")

        try:
            tiene_email = tabla_usuarios_tiene_email(cursor)
            conn.rollback()

            for datos in USUARIOS_DEMO:
                fk_rol = obtener_id_rol(cursor, datos["rol"])
                id_usuario = guardar_usuario(cursor, datos, fk_rol, tiene_email)
                guardar_productor(cursor, id_usuario, datos)
                guardar_veterinario(cursor, id_usuario, datos)

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

    print("Usuarios listos:")
    for datos in USUARIOS_DEMO:
        print(f"- {datos['rol']}: {datos['usuario']} / {datos['password']}")


if __name__ == "__main__":
    main()
