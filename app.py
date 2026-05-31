from flask import (
    Flask, render_template, request, redirect, url_for, abort,
    session, flash, Response, send_from_directory,
    send_file, make_response, Blueprint
)
from fpdf import FPDF
from datetime import datetime
from functools import wraps
import io
import csv
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from PIL import Image
import os
import hmac
from werkzeug.security import check_password_hash, generate_password_hash

from ganacontrol.config import Config
from ganacontrol.db_compat import db as mariadb
from ganacontrol.db import get_connection


app = Flask(__name__, static_folder="public", static_url_path="")
app.config.from_object(Config)
ROLES_VALIDOS = {"Productor", "Veterinario", "Comprador", "Administrador"}
ESTATUS_ANIMAL_VALIDOS = {"Activo", "Baja (Muerto)", "Vendido"}
PUBLIC_ASSET_FOLDER = "public"
ASSET_FOLDERS = (PUBLIC_ASSET_FOLDER, "static")


def _safe_asset_path(folder, filename):
    root = os.path.abspath(os.path.join(app.root_path, folder))
    candidate = os.path.abspath(os.path.join(root, filename))

    try:
        is_inside_root = os.path.commonpath([root, candidate]) == root
    except ValueError:
        return None

    if not is_inside_root or not os.path.isfile(candidate):
        return None

    return candidate


def resolve_asset_path(filename):
    for folder in ASSET_FOLDERS:
        path = _safe_asset_path(folder, filename)
        if path:
            return path

    return None


@app.route('/assets/<path:filename>')
def asset_file(filename):
    asset_path = resolve_asset_path(filename)
    if not asset_path:
        abort(404)

    directory, basename = os.path.split(asset_path)
    response = send_from_directory(directory, basename)
    response.cache_control.public = True
    response.cache_control.max_age = 0
    response.cache_control.must_revalidate = True
    return response


@app.context_processor
def inject_asset_helpers():
    def asset_url(filename):
        asset_path = resolve_asset_path(filename)
        version = int(os.path.getmtime(asset_path)) if asset_path else None

        # El CSS pasa por /assets para resolver primero public/ y mantener
        # static/ solo como compatibilidad con archivos antiguos.
        if filename.startswith("css/"):
            return url_for('asset_file', filename=filename, v=version)

        public_asset_path = _safe_asset_path(PUBLIC_ASSET_FOLDER, filename)
        if public_asset_path:
            version = int(os.path.getmtime(public_asset_path))
            return url_for('static', filename=filename, v=version)

        return url_for('asset_file', filename=filename, v=version)

    return {"asset_url": asset_url}


@app.route('/static/<path:filename>')
def legacy_static(filename):
    # Compatibilidad con rutas antiguas /static/... ahora que Vercel sirve public/ desde la raiz.
    if filename.startswith("css/"):
        return redirect(url_for('static', filename=filename), code=307)
    return redirect(url_for('static', filename=filename), code=307)

def conectar_bd(dictionary=False):
    return get_connection(dictionary=dictionary)

# Registrar rutas de prueba (solo para desarrollo). No fallar si faltan dependencias.
try:
    from temp_test_routes import register_test_routes
    register_test_routes(app, conectar_bd)
except Exception:
    pass

def normalizar_rol(rol):
    if not rol:
        return None
    roles = {
        "productor": "Productor",
        "veterinario": "Veterinario",
        "comprador": "Comprador",
        "administrador": "Administrador",
        "admin": "Administrador",
    }
    return roles.get(rol.strip().lower())


def normalizar_estatus_animal(estatus):
    if not estatus:
        return "Activo"
    estatus_map = {
        "activo": "Activo",
        "baja (muerto)": "Baja (Muerto)",
        "baja": "Baja (Muerto)",
        "muerto": "Baja (Muerto)",
        "vendido": "Vendido",
    }
    return estatus_map.get(estatus.strip().lower())


def _es_error_columna_email_faltante(error):
    mensaje = str(error).lower()
    return "email" in mensaje and (
        "unknown column" in mensaje
        or "does not exist" in mensaje
        or "no existe" in mensaje
    )


def crear_hash_contrasena(password):
    # pbkdf2 con salt corto cabe en password varchar(100) del esquema legado.
    return generate_password_hash(password, method="pbkdf2:sha256", salt_length=8)


def verificar_contrasena(password_guardada, password_ingresada):
    if not password_guardada:
        return False

    password_guardada = str(password_guardada)

    if password_guardada.startswith(("pbkdf2:", "scrypt:")) and password_guardada.count("$") >= 2:
        try:
            return check_password_hash(password_guardada, password_ingresada)
        except ValueError:
            return False

    # Compatibilidad con usuarios creados antes de guardar contraseñas con hash.
    return hmac.compare_digest(password_guardada, password_ingresada)


def _fecha_animal_a_mes(fecha):
    if not fecha:
        return None

    if hasattr(fecha, "year") and hasattr(fecha, "month"):
        return fecha.year, fecha.month

    fecha_texto = str(fecha).strip()
    for valor, formato in (
        (fecha_texto[:10], "%Y-%m-%d"),
        (fecha_texto[:19], "%Y-%m-%d %H:%M:%S"),
        (fecha_texto[:10], "%d/%m/%Y"),
    ):
        try:
            fecha_dt = datetime.strptime(valor, formato)
            return fecha_dt.year, fecha_dt.month
        except ValueError:
            continue

    return None


def construir_estadistica_nacimientos(fechas):
    meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    conteos = {}

    for row in fechas:
        fecha = row[0] if isinstance(row, (list, tuple)) else row
        mes_key = _fecha_animal_a_mes(fecha)
        if mes_key:
            conteos[mes_key] = conteos.get(mes_key, 0) + 1

    if not conteos:
        return {"items": [], "total": 0, "maximo": 0}

    meses_ordenados = sorted(conteos.keys())[-12:]
    maximo = max(conteos.values())
    items = []
    anterior = None

    for year, month in meses_ordenados:
        cantidad = conteos[(year, month)]
        diferencia = 0 if anterior is None else cantidad - anterior
        items.append({
            "mes": f"{meses[month - 1]} {year}",
            "nacimientos": cantidad,
            "porcentaje": round((cantidad / maximo) * 100) if maximo else 0,
            "diferencia": diferencia,
        })
        anterior = cantidad

    return {
        "items": items,
        "total": sum(conteos.values()),
        "maximo": maximo,
    }


def contar_registros(conn, cursor, tabla):
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {tabla}")
        row = cursor.fetchone()
        return row[0] if row else 0
    except Exception:
        conn.rollback()
        return 0


def asegurar_columna_permiso_veterinario(conn, cursor):
    columnas = (
        ("permiso_datos_completos", "BOOLEAN DEFAULT FALSE", "TINYINT(1) DEFAULT 0"),
        ("solicitud_permiso_datos", "BOOLEAN DEFAULT FALSE", "TINYINT(1) DEFAULT 0"),
    )

    for nombre, tipo_pg, tipo_mysql in columnas:
        try:
            cursor.execute(f"""
                ALTER TABLE Usuarios
                ADD COLUMN IF NOT EXISTS {nombre} {tipo_pg}
            """)
            conn.commit()
            continue
        except Exception:
            conn.rollback()

        try:
            cursor.execute(f"""
                ALTER TABLE Usuarios
                ADD COLUMN {nombre} {tipo_mysql}
            """)
            conn.commit()
        except Exception as e:
            conn.rollback()
            mensaje = str(e).lower()
            if not ("duplicate" in mensaje or "already exists" in mensaje or "existe" in mensaje):
                return False

    return True


def permiso_veterinario_activo(valor):
    if isinstance(valor, str):
        return valor.strip().lower() in {"1", "true", "t", "yes", "si", "sí"}
    return bool(valor)


def veterinario_puede_ver_todo():
    return session.get("rol") == "Veterinario" and permiso_veterinario_activo(
        session.get("permiso_datos_completos")
    )


def requiere_permiso_veterinario_datos_completos():
    if session.get("rol") == "Veterinario" and not veterinario_puede_ver_todo():
        flash("El administrador debe activar tu permiso para ver datos completos.", "warning")
        return False
    return True


def asegurar_tabla_solicitudes_veterinario(conn, cursor):
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS solicitudes_veterinario_productor (
                id_solicitud SERIAL PRIMARY KEY,
                fk_usuario_veterinario INTEGER NOT NULL,
                fk_productor INTEGER NOT NULL,
                nota TEXT,
                estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
                fecha_solicitud TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fecha_respuesta TIMESTAMP
            )
        """)
        conn.commit()
        return True
    except Exception:
        conn.rollback()

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS solicitudes_veterinario_productor (
                id_solicitud INT AUTO_INCREMENT PRIMARY KEY,
                fk_usuario_veterinario INT NOT NULL,
                fk_productor INT NOT NULL,
                nota TEXT,
                estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
                fecha_solicitud TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fecha_respuesta TIMESTAMP NULL
            )
        """)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False


def obtener_productores_autorizados_veterinario(conn, cursor, id_usuario):
    if not id_usuario:
        return []

    try:
        asegurar_tabla_solicitudes_veterinario(conn, cursor)
        cursor.execute("""
            SELECT p.pk_productor, p.nombre
            FROM solicitudes_veterinario_productor s
            JOIN Productores p ON p.pk_productor = s.fk_productor
            WHERE s.fk_usuario_veterinario=%s
              AND s.estado='aprobada'
            ORDER BY p.nombre
        """, (id_usuario,))
        return cursor.fetchall()
    except Exception:
        conn.rollback()
        return []


def actualizar_estado_permiso_veterinario(cursor, id_usuario):
    if not id_usuario:
        return

    cursor.execute("""
        SELECT COUNT(*)
        FROM solicitudes_veterinario_productor
        WHERE fk_usuario_veterinario=%s
          AND estado='pendiente'
    """, (id_usuario,))
    pendientes = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM solicitudes_veterinario_productor
        WHERE fk_usuario_veterinario=%s
          AND estado='aprobada'
    """, (id_usuario,))
    aprobadas = cursor.fetchone()[0]

    cursor.execute("""
        UPDATE Usuarios
        SET solicitud_permiso_datos=%s,
            permiso_datos_completos=%s
        WHERE id_usuario=%s
    """, (pendientes > 0, aprobadas > 0, id_usuario))


def ids_productores_autorizados_veterinario(conn, cursor):
    if session.get("rol") != "Veterinario":
        return None

    productores = obtener_productores_autorizados_veterinario(
        conn,
        cursor,
        session.get("id_usuario")
    )
    return [p[0] for p in productores]


def placeholders(valores):
    return ", ".join(["%s"] * len(valores))


def requiere_productores_autorizados_veterinario(conn, cursor):
    ids = ids_productores_autorizados_veterinario(conn, cursor)
    if ids is not None and not ids:
        flash("El administrador debe aprobarte al menos un productor para ver esos datos.", "warning")
        return None
    return ids


MEDICAMENTOS_BASE = (
    ("Ivermectina", "Desparasitante", 1.0, 0.0, 28),
    ("Oxitetraciclina", "Antibiotico", 10.0, 0.0, 21),
    ("Penicilina", "Antibiotico", 20.0, 0.0, 10),
    ("Complejo B", "Vitamina", 0.0, 0.0, 0),
    ("Vacuna clostridial", "Vacuna", 0.0, 0.0, 21),
    ("Baño garrapaticida", "Ectoparasiticida", 0.0, 0.0, 0),
)


def asegurar_catalogo_medicamentos(conn, cursor):
    try:
        cursor.execute("SELECT COUNT(*) FROM insumos_medicos")
        row = cursor.fetchone()
        if row and row[0]:
            return

        cursor.executemany("""
            INSERT INTO insumos_medicos
                (nombre, categoria, concentracion, stock_actual, dias_retiro)
            VALUES (%s, %s, %s, %s, %s)
        """, MEDICAMENTOS_BASE)
        conn.commit()
    except Exception:
        conn.rollback()


def obtener_catalogo_medicamentos(conn, cursor):
    try:
        asegurar_catalogo_medicamentos(conn, cursor)
        cursor.execute("""
            SELECT id_insumo, nombre, categoria, concentracion, stock_actual, fecha_caducidad, dias_retiro
            FROM insumos_medicos
            ORDER BY categoria, nombre
        """)
        return cursor.fetchall()
    except Exception:
        conn.rollback()
        return []


def requiere_admin(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if session.get("rol") != "Administrador":
            flash("Necesitas una sesión de Administrador para acceder a esa sección.", "warning")
            return redirect(url_for("login"))
        return func(*args, **kwargs)

    return wrapper


def usuarios_tienen_email(conn, cursor):
    try:
        cursor.execute("SELECT email FROM Usuarios LIMIT 1")
        return True
    except Exception:
        conn.rollback()
        return False


def obtener_roles(cursor):
    cursor.execute("SELECT id_rol, nombre FROM Rol ORDER BY nombre")
    return cursor.fetchall()


def obtener_id_rol(cursor, rol_nombre):
    cursor.execute("SELECT id_rol FROM Rol WHERE nombre=%s", (rol_nombre,))
    row = cursor.fetchone()
    return row[0] if row else None


def verificar_credenciales(identificador, password, rol_nombre):
    conn, cursor = conectar_bd()
    if not conn:
        return False, "Error de conexión"

    try:
        asegurar_columna_permiso_veterinario(conn, cursor)

        # Esquema legado: Usuarios + Rol
        try:
            cursor.execute("""
                SELECT u.id_usuario, u.usuario, u.password, r.nombre,
                       COALESCE(u.permiso_datos_completos, FALSE),
                       COALESCE(u.solicitud_permiso_datos, FALSE)
                FROM Usuarios u
                JOIN Rol r ON r.id_rol = u.fk_rol
                WHERE u.usuario=%s AND r.nombre=%s
            """, (identificador, rol_nombre))
            row = cursor.fetchone()
        except mariadb.Error:
            conn.rollback()
            row = None

        if not row:
            try:
                cursor.execute("""
                    SELECT u.id_usuario, u.usuario, u.password, r.nombre,
                           COALESCE(u.permiso_datos_completos, FALSE),
                           COALESCE(u.solicitud_permiso_datos, FALSE)
                    FROM Usuarios u
                    JOIN Rol r ON r.id_rol = u.fk_rol
                    WHERE u.email=%s AND r.nombre=%s
                """, (identificador, rol_nombre))
                row = cursor.fetchone()
            except mariadb.Error:
                conn.rollback()
                row = None

        if row:
            id_usuario, db_user, db_pass, db_rol, permiso_datos_completos, solicitud_permiso_datos = row
            if not verificar_contrasena(db_pass, password):
                return False, "Contraseña incorrecta"

            fk_productor = None
            if db_rol == "Productor":
                try:
                    cursor.execute(
                        "SELECT pk_productor FROM Productores WHERE fk_usuario=%s",
                        (id_usuario,)
                    )
                    p = cursor.fetchone()
                    if p:
                        fk_productor = p[0]
                except mariadb.Error:
                    conn.rollback()
                    fk_productor = None

            return True, {
                "id_usuario": id_usuario,
                "usuario": db_user,
                "rol": db_rol,
                "fk_productor": fk_productor,
                "permiso_datos_completos": permiso_veterinario_activo(permiso_datos_completos),
                "solicitud_permiso_datos": permiso_veterinario_activo(solicitud_permiso_datos),
            }

        # Esquema nuevo: usuarios con columna rol y fk_productor
        try:
            cursor.execute("""
                SELECT id_usuario, usuario, password, rol, fk_productor,
                       COALESCE(permiso_datos_completos, FALSE),
                       COALESCE(solicitud_permiso_datos, FALSE)
                FROM usuarios
                WHERE (usuario=%s OR email=%s) AND rol=%s
            """, (identificador, identificador, rol_nombre))
            row = cursor.fetchone()
        except mariadb.Error:
            conn.rollback()
            cursor.execute("""
                SELECT id_usuario, usuario, password, rol, fk_productor,
                       COALESCE(permiso_datos_completos, FALSE),
                       COALESCE(solicitud_permiso_datos, FALSE)
                FROM usuarios
                WHERE usuario=%s AND rol=%s
            """, (identificador, rol_nombre))
            row = cursor.fetchone()

        if not row:
            return False, "Usuario o rol no encontrado"

        id_usuario, db_user, db_pass, db_rol, fk_productor, permiso_datos_completos, solicitud_permiso_datos = row
        if not verificar_contrasena(db_pass, password):
            return False, "Contraseña incorrecta"

        return True, {
            "id_usuario": id_usuario,
            "usuario": db_user,
            "rol": db_rol,
            "fk_productor": fk_productor,
            "permiso_datos_completos": permiso_veterinario_activo(permiso_datos_completos),
            "solicitud_permiso_datos": permiso_veterinario_activo(solicitud_permiso_datos),
        }

    except Exception as e:
        return False, f"Error: {e}"
    finally:
        conn.close()

# -------------------- LOGIN --------------------
@app.route("/")
def inicio():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    conn = None
    productores = []

    try:
        conn, cursor = conectar_bd()
        if conn:
            try:
                cursor.execute("SELECT pk_productor, nombre FROM Productores")
                productores = cursor.fetchall()
            except Exception:
                productores = []

        if request.method == "POST":
            usuario = request.form["usuario"].strip()
            contra = request.form["password"]
            rol = normalizar_rol(request.form.get("rol")) or "Productor"
            if rol not in ROLES_VALIDOS:
                flash("Rol inválido", "danger")
                return redirect(url_for("login"))

            exito, info = verificar_credenciales(usuario, contra, rol)

            if exito:
                if isinstance(info, dict) and info.get("id_usuario"):
                    session["id_usuario"] = info.get("id_usuario")
                session["usuario"] = info.get("usuario", usuario) if isinstance(info, dict) else usuario
                session["rol"] = rol
                session.pop("fk_productor", None)

                if isinstance(info, dict) and info.get("fk_productor"):
                    session["fk_productor"] = info.get("fk_productor")
                session["permiso_datos_completos"] = bool(
                    isinstance(info, dict) and info.get("permiso_datos_completos")
                )
                session["solicitud_permiso_datos"] = bool(
                    isinstance(info, dict) and info.get("solicitud_permiso_datos")
                )

                flash(f"Bienvenido {usuario} ({rol})", "success")
                return redirect(url_for("dashboard"))

            flash(info, "danger")

    except Exception as e:
        print("Error en login:", e)
        flash("No se pudo procesar el inicio de sesión. Revisa la base de datos y vuelve a intentar.", "danger")
    finally:
        if conn:
            conn.close()

    return render_template("login.html", productores=productores)


#--------------- REGISTRAR -----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        # Obtener datos de forma segura
        usuario = request.form.get("usuario", "").strip()
        email = request.form.get("email", "").strip().lower()
        contra = request.form.get("password", "").strip()
        confirmar_contra = request.form.get("confirm_password", "").strip()
        rol_nombre = normalizar_rol(request.form.get("rol")) or "Productor"

        # Validación básica
        if not usuario or not email or not contra or not confirmar_contra or not rol_nombre:
            flash("Todos los campos son obligatorios", "danger")
            return redirect(url_for("register"))

        if "@" not in email or "." not in email.split("@")[-1]:
            flash("Ingresa un correo electrónico válido", "danger")
            return redirect(url_for("register"))

        if contra != confirmar_contra:
            flash("Las contraseñas no coinciden", "danger")
            return redirect(url_for("register"))

        if rol_nombre not in ROLES_VALIDOS:
            flash("Rol inválido", "danger")
            return redirect(url_for("register"))

        # Validar campos adicionales según rol
        if rol_nombre == "Productor":
            if not request.form.get("prod_nombre") or not request.form.get("prod_apellido_pat"):
                flash("Nombre y apellido paterno del productor son obligatorios", "danger")
                return redirect(url_for("register"))
        elif rol_nombre == "Veterinario":
            if not request.form.get("vet_nombre") or not request.form.get("vet_cedula") or not request.form.get("vet_telefono"):
                flash("Nombre, cédula y teléfono del veterinario son obligatorios", "danger")
                return redirect(url_for("register"))

        conn, cursor = conectar_bd()
        if not conn:
            flash("Error al conectar con la base de datos", "danger")
            return redirect(url_for("register"))

        try:
            # Obtener ID del rol
            cursor.execute("SELECT id_rol FROM Rol WHERE nombre=%s", (rol_nombre,))
            row = cursor.fetchone()

            if not row:
                raise Exception("Rol no encontrado en la base de datos")

            fk_rol = row[0]
            password_hash = crear_hash_contrasena(contra)

            # Insertar usuario - SIN commit aún. Si la base aún no tiene email,
            # se mantiene compatibilidad con el esquema anterior.
            try:
                cursor.execute("""
                    INSERT INTO Usuarios (usuario, email, password, fk_rol)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id_usuario
                """, (usuario, email, password_hash, fk_rol))
            except mariadb.Error as e:
                if not _es_error_columna_email_faltante(e):
                    raise
                conn.rollback()
                cursor.execute("""
                    INSERT INTO Usuarios (usuario, password, fk_rol)
                    VALUES (%s, %s, %s)
                    RETURNING id_usuario
                """, (usuario, password_hash, fk_rol))

            # Obtener el ID del INSERT
            id_usuario = cursor.fetchone()[0]

            # Insertar datos adicionales según rol
            if rol_nombre == "Productor":
                cursor.execute("""
                    INSERT INTO Productores (fk_usuario, nombre, apellido_pat, apellido_mat, RFC)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    id_usuario,
                    request.form.get("prod_nombre", "").strip(),
                    request.form.get("prod_apellido_pat", "").strip(),
                    request.form.get("prod_apellido_mat", "").strip(),
                    request.form.get("prod_rfc", "").strip()
                ))

            elif rol_nombre == "Veterinario":
                cursor.execute("""
                    INSERT INTO Veterinario (fk_usuario, nombre, apellidos, cedula, direccion_consultorio, telefono)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    id_usuario,
                    request.form.get("vet_nombre", "").strip(),
                    request.form.get("vet_apellidos", "").strip(),
                    request.form.get("vet_cedula", "").strip(),
                    request.form.get("vet_direccion", "").strip() or "Consultas a domicilio",
                    request.form.get("vet_telefono", "").strip()
                ))

            # Un único commit
            conn.commit()

            # Éxito
            flash("Usuario registrado correctamente", "success")
            return redirect(url_for("login"))

        except Exception as e:
            conn.rollback()
            print("Error en registro:", str(e))
            flash(f"No se pudo registrar: {str(e)}", "danger")
            return redirect(url_for("register"))

        finally:
            cursor.close()
            conn.close()

    # Si es GET
    return render_template("register.html")


@app.route("/admin/usuarios", methods=["GET", "POST"])
@requiere_admin
def admin_usuarios():
    conn, cursor = conectar_bd()
    if not conn:
        flash("No se pudo conectar con la base de datos.", "danger")
        return redirect(url_for("dashboard"))

    tiene_email = False
    try:
        asegurar_columna_permiso_veterinario(conn, cursor)
        asegurar_tabla_solicitudes_veterinario(conn, cursor)
        tiene_email = usuarios_tienen_email(conn, cursor)
        roles = obtener_roles(cursor)

        if request.method == "POST":
            accion = request.form.get("accion")
            id_usuario = request.form.get("id_usuario")
            usuario = request.form.get("usuario", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "").strip()
            rol_nombre = normalizar_rol(request.form.get("rol"))
            permiso_datos_completos = False

            if accion in {"aprobar_solicitud_vet", "rechazar_solicitud_vet", "revocar_productor_vet"}:
                id_solicitud = request.form.get("id_solicitud")
                if not id_solicitud:
                    flash("Selecciona un veterinario para gestionar la petición.", "danger")
                    return redirect(url_for("admin_usuarios"))

                aprobar = accion == "aprobar_solicitud_vet"
                revocar = accion == "revocar_productor_vet"
                cursor.execute("""
                    UPDATE solicitudes_veterinario_productor
                    SET estado=%s,
                        fecha_respuesta=CURRENT_TIMESTAMP
                    WHERE id_solicitud=%s
                """, ("aprobada" if aprobar else "rechazada", id_solicitud))

                cursor.execute("""
                    SELECT fk_usuario_veterinario
                    FROM solicitudes_veterinario_productor
                    WHERE id_solicitud=%s
                """, (id_solicitud,))
                row = cursor.fetchone()
                id_vet = row[0] if row else None

                if id_vet:
                    actualizar_estado_permiso_veterinario(cursor, id_vet)

                conn.commit()
                if aprobar:
                    flash("Petición veterinaria aprobada para ese productor.", "success")
                elif revocar:
                    flash("Productor retirado del veterinario.", "info")
                else:
                    flash("Petición veterinaria rechazada.", "info")

            if accion in {"crear", "modificar"}:
                if not usuario or not rol_nombre:
                    flash("Usuario y rol son obligatorios.", "danger")
                    return redirect(url_for("admin_usuarios"))

                if rol_nombre not in ROLES_VALIDOS:
                    flash("Rol inválido.", "danger")
                    return redirect(url_for("admin_usuarios"))

                fk_rol = obtener_id_rol(cursor, rol_nombre)
                if not fk_rol:
                    flash("Ese rol no existe en la tabla Rol.", "danger")
                    return redirect(url_for("admin_usuarios"))

                if accion == "crear":
                    if not password:
                        flash("La contraseña es obligatoria para crear usuarios.", "danger")
                        return redirect(url_for("admin_usuarios"))

                    password_hash = crear_hash_contrasena(password)
                    if tiene_email:
                        cursor.execute(
                            """
                            INSERT INTO Usuarios (usuario, email, password, fk_rol, permiso_datos_completos)
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (usuario, email or None, password_hash, fk_rol, permiso_datos_completos),
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO Usuarios (usuario, password, fk_rol, permiso_datos_completos)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (usuario, password_hash, fk_rol, permiso_datos_completos),
                        )
                    conn.commit()
                    flash("Usuario creado correctamente.", "success")

                elif accion == "modificar":
                    if not id_usuario:
                        flash("Selecciona un usuario para modificar.", "danger")
                        return redirect(url_for("admin_usuarios"))

                    if rol_nombre == "Veterinario":
                        cursor.execute("""
                            SELECT COUNT(*)
                            FROM solicitudes_veterinario_productor
                            WHERE fk_usuario_veterinario=%s
                              AND estado='aprobada'
                        """, (id_usuario,))
                        row = cursor.fetchone()
                        permiso_datos_completos = bool(row and row[0])

                    valores = []
                    asignaciones = ["usuario=%s", "fk_rol=%s", "permiso_datos_completos=%s"]
                    valores.extend([usuario, fk_rol, permiso_datos_completos])

                    if rol_nombre != "Veterinario" or permiso_datos_completos:
                        asignaciones.append("solicitud_permiso_datos=%s")
                        valores.append(False)

                    if tiene_email:
                        asignaciones.insert(1, "email=%s")
                        valores.insert(1, email or None)

                    if password:
                        asignaciones.append("password=%s")
                        valores.append(crear_hash_contrasena(password))

                    valores.append(id_usuario)
                    cursor.execute(
                        f"UPDATE Usuarios SET {', '.join(asignaciones)} WHERE id_usuario=%s",
                        tuple(valores),
                    )
                    conn.commit()

                    if str(session.get("id_usuario")) == str(id_usuario):
                        session["usuario"] = usuario
                        session["rol"] = rol_nombre
                        session["permiso_datos_completos"] = permiso_datos_completos
                        if rol_nombre != "Veterinario" or permiso_datos_completos:
                            session["solicitud_permiso_datos"] = False

                    flash("Usuario actualizado correctamente.", "success")

            elif accion == "eliminar":
                if not id_usuario:
                    flash("Selecciona un usuario para eliminar.", "danger")
                    return redirect(url_for("admin_usuarios"))

                if str(session.get("id_usuario")) == str(id_usuario):
                    flash("No puedes eliminar tu propio usuario administrador mientras lo estás usando.", "warning")
                    return redirect(url_for("admin_usuarios"))

                cursor.execute("SELECT usuario FROM Usuarios WHERE id_usuario=%s", (id_usuario,))
                row = cursor.fetchone()
                nombre_usuario = row[0] if row else "usuario"
                cursor.execute("DELETE FROM Usuarios WHERE id_usuario=%s", (id_usuario,))
                conn.commit()
                flash(f"Usuario {nombre_usuario} eliminado.", "success")

            return redirect(url_for("admin_usuarios"))

        if tiene_email:
            cursor.execute("""
                SELECT u.id_usuario, u.usuario, u.email, r.nombre,
                       COALESCE(u.permiso_datos_completos, FALSE),
                       COALESCE(u.solicitud_permiso_datos, FALSE)
                FROM Usuarios u
                JOIN Rol r ON r.id_rol = u.fk_rol
                ORDER BY u.id_usuario
            """)
        else:
            cursor.execute("""
                SELECT u.id_usuario, u.usuario, NULL AS email, r.nombre,
                       COALESCE(u.permiso_datos_completos, FALSE),
                       COALESCE(u.solicitud_permiso_datos, FALSE)
                FROM Usuarios u
                JOIN Rol r ON r.id_rol = u.fk_rol
                ORDER BY u.id_usuario
            """)

        usuarios = cursor.fetchall()
        cursor.execute("""
            SELECT
                s.id_solicitud,
                u.id_usuario,
                u.usuario,
                COALESCE(v.nombre, ''),
                COALESCE(v.apellidos, ''),
                p.pk_productor,
                p.nombre,
                COALESCE(s.nota, ''),
                s.fecha_solicitud
            FROM solicitudes_veterinario_productor s
            JOIN Usuarios u ON u.id_usuario = s.fk_usuario_veterinario
            LEFT JOIN Veterinario v ON v.fk_usuario = u.id_usuario
            JOIN Productores p ON p.pk_productor = s.fk_productor
            WHERE s.estado='pendiente'
            ORDER BY s.fecha_solicitud ASC, s.id_solicitud ASC
        """)
        solicitudes_veterinario = cursor.fetchall()

        cursor.execute("""
            SELECT
                s.id_solicitud,
                u.id_usuario,
                u.usuario,
                COALESCE(v.nombre, ''),
                COALESCE(v.apellidos, ''),
                p.pk_productor,
                p.nombre,
                s.fecha_respuesta
            FROM solicitudes_veterinario_productor s
            JOIN Usuarios u ON u.id_usuario = s.fk_usuario_veterinario
            LEFT JOIN Veterinario v ON v.fk_usuario = u.id_usuario
            JOIN Productores p ON p.pk_productor = s.fk_productor
            WHERE s.estado='aprobada'
            ORDER BY u.usuario, p.nombre
        """)
        productores_veterinario = cursor.fetchall()

        return render_template(
            "admin_usuarios.html",
            usuarios=usuarios,
            roles=roles,
            tiene_email=tiene_email,
            solicitudes_veterinario=solicitudes_veterinario,
            productores_veterinario=productores_veterinario,
        )

    except Exception as e:
        conn.rollback()
        flash(f"No se pudo administrar usuarios: {e}", "danger")
        return redirect(url_for("dashboard"))
    finally:
        cursor.close()
        conn.close()

#----------------- Dashboard -----------------
@app.route("/dashboard")
def dashboard():
    if "usuario" not in session:
        return redirect(url_for("login"))

    # =========================
    # VARIABLES SEGURAS
    # =========================
    productor_nombre = None
    aretes = []
    predios = []
    estados_animales = []
    estadistica_nacimientos = {"items": [], "total": 0, "maximo": 0}
    total_animales = 0
    total_predios = 0
    admin_resumen = {}
    veterinario_perfil = None
    vet_resumen = {}
    vet_proximos = []
    vet_productores = []
    vet_solicitudes = []
    productores_para_solicitud = []
    view = None

    fk_productor = session.get("fk_productor")
    rol = session.get("rol")

    # =========================
    # DEFINIR VIEW SEGÚN ROL
    # =========================
    if rol == "Administrador":
        view = "administrador"
    elif rol == "Veterinario":
        view = "veterinario"
    elif rol == "Comprador":
        view = "comprador"
    else:
        view = "productor"

    conn = None
    try:
        conn, cursor = conectar_bd()
        if not conn:
            raise RuntimeError("No se pudo establecer la conexión con la base de datos.")

        if view == "administrador":
            admin_resumen = {
                "usuarios": contar_registros(conn, cursor, "Usuarios"),
                "productores": contar_registros(conn, cursor, "Productores"),
                "veterinarios": contar_registros(conn, cursor, "Veterinario"),
                "animales": contar_registros(conn, cursor, "Animales"),
                "predios": contar_registros(conn, cursor, "Predios"),
                "pesajes": contar_registros(conn, cursor, "Pesajes"),
                "ventas": contar_registros(conn, cursor, "Ventas"),
                "seguimientos": contar_registros(conn, cursor, "Seguimiento_vet"),
                "registros_siniga": contar_registros(conn, cursor, "Registro_SINIGA"),
            }
            asegurar_columna_permiso_veterinario(conn, cursor)
            asegurar_tabla_solicitudes_veterinario(conn, cursor)
            cursor.execute("""
                SELECT COUNT(*)
                FROM solicitudes_veterinario_productor
                WHERE estado='pendiente'
            """)
            row = cursor.fetchone()
            admin_resumen["peticiones_veterinario"] = row[0] if row else 0

            cursor.execute("""
                SELECT
                    a.nombre,
                    COALESCE(a.estatus, 'Activo') AS estatus_actual
                FROM Animales a
                ORDER BY a.nombre
            """)
            estados_animales = cursor.fetchall()

            cursor.execute("""
                SELECT fecha_nacimiento
                FROM Animales
                WHERE fecha_nacimiento IS NOT NULL
                ORDER BY fecha_nacimiento
            """)
            estadistica_nacimientos = construir_estadistica_nacimientos(cursor.fetchall())
            total_animales = admin_resumen["animales"]
            total_predios = admin_resumen["predios"]

        elif view == "veterinario":
            obtener_catalogo_medicamentos(conn, cursor)
            asegurar_tabla_solicitudes_veterinario(conn, cursor)

            cursor.execute("""
                SELECT id_veterinario, nombre, apellidos, cedula, direccion_consultorio, telefono
                FROM Veterinario
                WHERE fk_usuario=%s
            """, (session.get("id_usuario"),))
            veterinario_perfil = cursor.fetchone()
            vet_productores = obtener_productores_autorizados_veterinario(conn, cursor, session.get("id_usuario"))
            session["permiso_datos_completos"] = bool(vet_productores)
            ids_vet = [p[0] for p in vet_productores]

            cursor.execute("""
                SELECT s.id_solicitud, s.fk_productor, p.nombre, s.nota, s.estado, s.fecha_solicitud
                FROM solicitudes_veterinario_productor s
                JOIN Productores p ON p.pk_productor = s.fk_productor
                WHERE s.fk_usuario_veterinario=%s
                ORDER BY s.fecha_solicitud DESC, s.id_solicitud DESC
            """, (session.get("id_usuario"),))
            vet_solicitudes = cursor.fetchall()
            session["solicitud_permiso_datos"] = any(s[4] == "pendiente" for s in vet_solicitudes)

            cursor.execute("""
                SELECT pk_productor, nombre
                FROM Productores
                ORDER BY nombre
            """)
            productores_para_solicitud = cursor.fetchall()

            total_medicamentos = contar_registros(conn, cursor, "insumos_medicos")

            total_seguimientos = 0
            proximas_citas = 0
            if ids_vet:
                filtro = placeholders(ids_vet)
                cursor.execute(f"""
                    SELECT COUNT(*)
                    FROM Seguimiento_vet s
                    JOIN Animales a ON a.pk_animal = s.fk_animal
                    WHERE a.fk_productor IN ({filtro})
                """, tuple(ids_vet))
                row = cursor.fetchone()
                total_seguimientos = row[0] if row else 0

                cursor.execute(f"""
                    SELECT COUNT(*)
                    FROM Seguimiento_vet s
                    JOIN Animales a ON a.pk_animal = s.fk_animal
                    WHERE a.fk_productor IN ({filtro})
                      AND s.prox_fecha IS NOT NULL
                      AND s.prox_fecha >= CURRENT_DATE
                """, tuple(ids_vet))
                row = cursor.fetchone()
                proximas_citas = row[0] if row else 0

            vet_resumen = {
                "seguimientos": total_seguimientos,
                "productores": len(vet_productores),
                "medicamentos": total_medicamentos,
                "proximas_citas": proximas_citas,
            }

            if ids_vet:
                filtro = placeholders(ids_vet)
                cursor.execute(f"""
                    SELECT
                        p.nombre,
                        t.nombre,
                        COALESCE(s.medicamento, ''),
                        s.fecha_actual,
                        s.prox_fecha
                    FROM Seguimiento_vet s
                    JOIN Animales a ON a.pk_animal = s.fk_animal
                    JOIN Productores p ON p.pk_productor = a.fk_productor
                    LEFT JOIN tratamientos t ON t.pk_tratamiento = s.fk_tratamiento
                    WHERE a.fk_productor IN ({filtro})
                      AND s.prox_fecha IS NOT NULL
                    ORDER BY s.prox_fecha ASC
                    LIMIT 5
                """, tuple(ids_vet))
                vet_proximos = cursor.fetchall()

        elif fk_productor:
            cursor.execute(
                "SELECT nombre FROM Productores WHERE pk_productor=%s",
                (fk_productor,)
            )
            row = cursor.fetchone()
            if row:
                productor_nombre = row[0]

            cursor.execute("""
                SELECT a.pk_animal, r.arete, a.nombre
                FROM Animales a
                LEFT JOIN Registro_SINIGA r ON r.fk_animal = a.pk_animal
                WHERE a.fk_productor = %s
                ORDER BY a.nombre
            """, (fk_productor,))
            aretes = cursor.fetchall()

            cursor.execute("""
                SELECT pk_predio, nom_rancho
                FROM Predios
                WHERE fk_productor = %s
                ORDER BY nom_rancho
            """, (fk_productor,))
            predios = cursor.fetchall()

            cursor.execute(
                "SELECT COUNT(*) FROM Animales WHERE fk_productor=%s",
                (fk_productor,)
            )
            total_animales = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM Predios WHERE fk_productor=%s",
                (fk_productor,)
            )
            total_predios = cursor.fetchone()[0]

            cursor.execute("""
                SELECT
                    a.nombre,
                    COALESCE(a.estatus, 'Activo') AS estatus_actual
                FROM Animales a
                WHERE a.fk_productor = %s
                ORDER BY a.nombre
            """, (fk_productor,))
            estados_animales = cursor.fetchall()

            cursor.execute("""
                SELECT fecha_nacimiento
                FROM Animales
                WHERE fk_productor = %s
                  AND fecha_nacimiento IS NOT NULL
                ORDER BY fecha_nacimiento
            """, (fk_productor,))
            estadistica_nacimientos = construir_estadistica_nacimientos(cursor.fetchall())
    except Exception as e:
        print("Error en dashboard:", e)
        flash("Se cargó el panel, pero faltan datos o tablas por configurar en la base.", "warning")
    finally:
        if conn:
            conn.close()

    return render_template(
        "dashboard.html",
        usuario=session["usuario"],
        rol=rol,
        view=view,
        productor=productor_nombre,
        aretes=aretes,
        predios=predios,
        total_animales=total_animales,
        total_predios=total_predios,
        estados_animales=estados_animales,
        estadistica_nacimientos=estadistica_nacimientos,
        admin_resumen=admin_resumen,
        veterinario_perfil=veterinario_perfil,
        vet_resumen=vet_resumen,
        vet_proximos=vet_proximos,
        vet_productores=vet_productores,
        vet_solicitudes=vet_solicitudes,
        productores_para_solicitud=productores_para_solicitud
    )

@app.route("/dashboard_vet")
def dashboard_vet():
    if "usuario" not in session:
        return redirect(url_for("login"))

    return redirect(url_for("dashboard"))

@app.route("/solicitar_permiso_veterinario", methods=["POST"])
def solicitar_permiso_veterinario():
    if session.get("rol") != "Veterinario" or not session.get("id_usuario"):
        flash("Solo un veterinario puede solicitar este permiso.", "warning")
        return redirect(url_for("dashboard"))

    fk_productor = request.form.get("fk_productor")
    nota = request.form.get("nota", "").strip()

    if not fk_productor or not nota:
        flash("Selecciona un productor y escribe una nota para justificar la petición.", "warning")
        return redirect(url_for("dashboard"))

    conn, cursor = conectar_bd()
    if not conn:
        flash("No se pudo conectar con la base de datos.", "danger")
        return redirect(url_for("dashboard"))

    try:
        asegurar_columna_permiso_veterinario(conn, cursor)
        asegurar_tabla_solicitudes_veterinario(conn, cursor)
        cursor.execute("""
            SELECT id_solicitud, estado
            FROM solicitudes_veterinario_productor
            WHERE fk_usuario_veterinario=%s
              AND fk_productor=%s
            ORDER BY id_solicitud DESC
            LIMIT 1
        """, (session["id_usuario"], fk_productor))
        existente = cursor.fetchone()

        if existente and existente[1] == "aprobada":
            flash("Ya tienes permiso para ese productor.", "info")
            return redirect(url_for("dashboard"))

        if existente and existente[1] == "pendiente":
            cursor.execute("""
                UPDATE solicitudes_veterinario_productor
                SET nota=%s, fecha_solicitud=CURRENT_TIMESTAMP
                WHERE id_solicitud=%s
            """, (nota, existente[0]))
        else:
            cursor.execute("""
                INSERT INTO solicitudes_veterinario_productor
                    (fk_usuario_veterinario, fk_productor, nota, estado)
                VALUES (%s, %s, %s, 'pendiente')
            """, (session["id_usuario"], fk_productor, nota))

        cursor.execute("""
            UPDATE Usuarios
            SET solicitud_permiso_datos=TRUE
            WHERE id_usuario=%s
        """, (session["id_usuario"],))
        conn.commit()
        session["solicitud_permiso_datos"] = True
        flash("Tu petición fue enviada al administrador con la nota.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"No se pudo enviar la petición: {e}", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("dashboard"))

@app.route("/dashboard_comp")
def dashboard_comp():
    if "usuario" not in session:
        return redirect(url_for("login"))

    productor_nombre = None
    if session.get("fk_productor"):
        conn, cursor = conectar_bd()
        cursor.execute("SELECT nombre FROM Productores WHERE pk_productor=%s", (session["fk_productor"],))
        row = cursor.fetchone()
        conn.close()
        if row:
            productor_nombre = row[0]

    return render_template(
        "dashboard.html",
        usuario=session.get("usuario"),
        rol=session.get("rol"),
        productor=productor_nombre,
        view="comprador"
    )

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('inicio'))

# ------------------ Ventana Animales ------------------
@app.route("/animales", methods=["GET", "POST"])
def animales():
    if "usuario" not in session:
        flash("Debes iniciar sesión", "warning")
        return redirect(url_for("login"))

    if session.get("rol") == "Veterinario":
        flash("El veterinario no tiene acceso a la tabla de animales.", "warning")
        return redirect(url_for("dashboard"))

    conn = None
    cursor = None

    try:
        conn, cursor = conectar_bd()
        ids_vet = requiere_productores_autorizados_veterinario(conn, cursor)
        if ids_vet is None and session.get("rol") == "Veterinario":
            return redirect(url_for("dashboard"))

        # ================= POST =================
        if request.method == "POST":
            accion = request.form.get("accion")

            foto_perfil = request.files.get("foto_perfil")
            foto_lateral = request.files.get("foto_lateral")

            perfil_bytes = foto_perfil.read() if foto_perfil and foto_perfil.filename else None
            lateral_bytes = foto_lateral.read() if foto_lateral and foto_lateral.filename else None

            fk_prod_session = session.get("fk_productor") if session.get("rol") == "Productor" else None
            fk_prod_form = request.form.get("fk_productor")
            if ids_vet is not None and fk_prod_form and int(fk_prod_form) not in [int(i) for i in ids_vet]:
                flash("Solo puedes registrar animales de productores aprobados.", "warning")
                return redirect(url_for("animales"))

            # -------- REGISTRAR --------
            if accion == "registrar":
                estatus = normalizar_estatus_animal(request.form.get("estatus"))
                if estatus not in ESTATUS_ANIMAL_VALIDOS:
                    flash("Estatus inválido", "danger")
                    return redirect(url_for("animales"))

                cruzes_seleccionados = [
                    cruze.strip()
                    for cruze in request.form.getlist("cruze_razas")
                    if cruze and cruze.strip()
                ]
                cruze = " / ".join(cruzes_seleccionados) if cruzes_seleccionados else "Sin conocer"

                cursor.execute("""
                    INSERT INTO Animales
                    (nombre, fecha_nacimiento, cruze, sexo, peso_actual,
                     fk_productor, fk_raza, fk_predio, fk_animal, estatus, foto_perfil, foto_lateral)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    request.form.get("nombre"),
                    request.form.get("fecha"),
                    cruze,
                    request.form.get("sexo"),
                    request.form.get("peso_actual"),
                    fk_prod_session or fk_prod_form,
                    request.form.get("fk_raza"),
                    request.form.get("fk_predio"),
                    request.form.get("fk_madre") or None,
                    estatus,
                    perfil_bytes,
                    lateral_bytes
                ))
                conn.commit()

            # -------- MODIFICAR (parcial-safe) --------
            elif accion == "modificar":
                pk = request.form.get("pk")

                # Obtener valores actuales
                cursor.execute("SELECT nombre, fecha_nacimiento, cruze, sexo, peso_actual, fk_productor, fk_raza, fk_predio, fk_animal FROM Animales WHERE pk_animal=%s", (pk,))
                current = cursor.fetchone()
                if not current:
                    flash("Animal no encontrado para modificar", "danger")
                elif ids_vet is not None and int(current[5]) not in [int(i) for i in ids_vet]:
                    flash("No puedes modificar animales de productores no aprobados.", "warning")
                else:
                    # Mapear campos y actualizar solo los presentes en el form
                    updates = []
                    params = []

                    field_map = {
                        'nombre': 'nombre',
                        'fecha': 'fecha_nacimiento',
                        'cruze': 'cruze',
                        'sexo': 'sexo',
                        'peso_actual': 'peso_actual',
                        'fk_productor': 'fk_productor',
                        'fk_raza': 'fk_raza',
                        'fk_predio': 'fk_predio',
                        'fk_madre': 'fk_animal',
                        'estatus': 'estatus'
                    }

                    for form_key, col_name in field_map.items():
                        if form_key in request.form:
                            val = request.form.get(form_key) or None
                            if col_name == 'estatus':
                                val = normalizar_estatus_animal(val)
                                if val not in ESTATUS_ANIMAL_VALIDOS:
                                    flash("Estatus inválido", "danger")
                                    return redirect(url_for("animales"))
                            # si es fk_productor y el usuario es Productor, respetar la sesión
                            if col_name == 'fk_productor' and fk_prod_session:
                                val = fk_prod_session
                            updates.append(f"{col_name}=%s")
                            params.append(val)

                    if updates:
                        sql = "UPDATE Animales SET " + ", ".join(updates) + " WHERE pk_animal=%s"
                        params.append(pk)
                        cursor.execute(sql, tuple(params))

                    # Fotos (archivo) -- se manejan independientemente
                    if perfil_bytes:
                        cursor.execute("UPDATE Animales SET foto_perfil=%s WHERE pk_animal=%s", (perfil_bytes, pk))
                    if lateral_bytes:
                        cursor.execute("UPDATE Animales SET foto_lateral=%s WHERE pk_animal=%s", (lateral_bytes, pk))

                    conn.commit()

            # -------- ELIMINAR --------
            elif accion == "eliminar":
                pk = request.form.get("pk")
                if ids_vet is not None:
                    cursor.execute("SELECT fk_productor FROM Animales WHERE pk_animal=%s", (pk,))
                    row = cursor.fetchone()
                    if not row or int(row[0]) not in [int(i) for i in ids_vet]:
                        flash("No puedes eliminar animales de productores no aprobados.", "warning")
                        return redirect(url_for("animales"))
                cursor.execute("DELETE FROM Pesajes WHERE fk_animal=%s", (pk,))
                cursor.execute("DELETE FROM Ventas WHERE fk_animal=%s", (pk,))
                cursor.execute("DELETE FROM Seguimiento_vet WHERE fk_animal=%s", (pk,))
                cursor.execute("DELETE FROM Registro_SINIGA WHERE fk_animal=%s", (pk,))
                cursor.execute("DELETE FROM Animales WHERE pk_animal=%s", (pk,))
                conn.commit()
                flash("Animal eliminado correctamente", "success")

        # ================= GET =================
        if session.get("rol") == "Productor":
            cursor.execute("""
                SELECT a.pk_animal, a.nombre, a.fecha_nacimiento, a.cruze,
                       p.nombre, r.nombre, a.sexo, a.peso_actual,
                       pr.nom_rancho,
                       rs.arete,
                       COALESCE(a.estatus, 'Activo') AS estatus_actual,
                       a.fk_predio, r.pk_raza, a.fk_productor,
                       a.fk_animal AS fk_madre,
                       m.nombre AS madre_nombre
                FROM Animales a
                LEFT JOIN Productores p ON a.fk_productor=p.pk_productor
                LEFT JOIN Razas r ON a.fk_raza=r.pk_raza
                LEFT JOIN Predios pr ON a.fk_predio=pr.pk_predio
                LEFT JOIN Animales m ON a.fk_animal = m.pk_animal
                LEFT JOIN Registro_SINIGA rs ON rs.fk_animal = a.pk_animal
                WHERE a.fk_productor=%s
                ORDER BY a.pk_animal DESC
            """, (session.get("fk_productor"),))
        elif ids_vet is not None:
            filtro = placeholders(ids_vet)
            cursor.execute(f"""
                SELECT a.pk_animal, a.nombre, a.fecha_nacimiento, a.cruze,
                       p.nombre, r.nombre, a.sexo, a.peso_actual,
                       pr.nom_rancho,
                       rs.arete,
                       COALESCE(a.estatus, 'Activo') AS estatus_actual,
                       a.fk_predio, r.pk_raza, a.fk_productor,
                       a.fk_animal AS fk_madre,
                       m.nombre AS madre_nombre
                FROM Animales a
                LEFT JOIN Productores p ON a.fk_productor=p.pk_productor
                LEFT JOIN Razas r ON a.fk_raza=r.pk_raza
                LEFT JOIN Predios pr ON a.fk_predio=pr.pk_predio
                LEFT JOIN Animales m ON a.fk_animal = m.pk_animal
                LEFT JOIN Registro_SINIGA rs ON rs.fk_animal = a.pk_animal
                WHERE a.fk_productor IN ({filtro})
                ORDER BY a.pk_animal DESC
            """, tuple(ids_vet))
        else:
            cursor.execute("""
                SELECT a.pk_animal, a.nombre, a.fecha_nacimiento, a.cruze,
                       p.nombre, r.nombre, a.sexo, a.peso_actual,
                       pr.nom_rancho,
                       rs.arete,
                       COALESCE(a.estatus, 'Activo') AS estatus_actual,
                       a.fk_predio, r.pk_raza, a.fk_productor,
                       a.fk_animal AS fk_madre,
                       m.nombre AS madre_nombre
                FROM Animales a
                LEFT JOIN Productores p ON a.fk_productor=p.pk_productor
                LEFT JOIN Razas r ON a.fk_raza=r.pk_raza
                LEFT JOIN Predios pr ON a.fk_predio=pr.pk_predio
                LEFT JOIN Animales m ON a.fk_animal = m.pk_animal
                LEFT JOIN Registro_SINIGA rs ON rs.fk_animal = a.pk_animal
                ORDER BY a.pk_animal DESC
            """)

        animales = cursor.fetchall()

        if ids_vet is not None:
            filtro = placeholders(ids_vet)
            cursor.execute(f"SELECT pk_productor, nombre FROM Productores WHERE pk_productor IN ({filtro}) ORDER BY nombre", tuple(ids_vet))
        else:
            cursor.execute("SELECT pk_productor, nombre FROM Productores")
        productores = cursor.fetchall()

        cursor.execute("SELECT pk_raza, nombre FROM Razas")
        razas = cursor.fetchall()

        if ids_vet is not None:
            filtro = placeholders(ids_vet)
            cursor.execute(f"SELECT pk_predio, nom_rancho FROM Predios WHERE fk_productor IN ({filtro}) ORDER BY nom_rancho", tuple(ids_vet))
        else:
            cursor.execute("SELECT pk_predio, nom_rancho FROM Predios ORDER BY nom_rancho")
        predios = cursor.fetchall()

        if session.get("rol") == "Productor":
            cursor.execute("SELECT pk_animal, nombre FROM Animales WHERE sexo='H' AND fk_productor=%s ORDER BY nombre", (session.get("fk_productor"),))
        elif ids_vet is not None:
            filtro = placeholders(ids_vet)
            cursor.execute(f"SELECT pk_animal, nombre FROM Animales WHERE sexo='H' AND fk_productor IN ({filtro}) ORDER BY nombre", tuple(ids_vet))
        else:
            cursor.execute("SELECT pk_animal, nombre FROM Animales WHERE sexo='H' ORDER BY nombre")
        madres = cursor.fetchall()

    except Exception as e:
        flash(f"Error en Animales: {e}", "danger")
        animales, productores, razas, predios = [], [], [], []

    finally:
        if conn:
            conn.close()

    return render_template(
        "animales.html",
        animales=animales,
        productores=productores,
        razas=razas,
        predios=predios,
        madres=madres
    )

# ------------------ Mostrar imágenes ------------------
@app.route("/imagen_animal/<int:id>/<string:tipo>")
def imagen_animal(id, tipo):
    # Validar que el tipo sea una columna esperada para evitar inyección SQL
    allowed = ("foto_perfil", "foto_lateral", "foto_arete")
    if tipo not in allowed:
        return "", 400

    conn, cursor = conectar_bd()
    cursor.execute(f"SELECT {tipo} FROM Animales WHERE pk_animal=%s", (id,))
    row = cursor.fetchone()
    conn.close()

    if not row or row[0] is None:
        return "", 404

    imagen = row[0]

    # Si la BD contiene una ruta/nombre de archivo (texto), servir desde static
    if isinstance(imagen, str):
        # permitir rutas relativas como 'uploads/ej.jpg' o solo 'ej.jpg'
        archivo = imagen
        # comprobar en carpeta static
        static_path = app.static_folder or os.path.join(app.root_path, 'static')
        posibles = [os.path.join(static_path, archivo), os.path.join(static_path, os.path.basename(archivo))]
        for p in posibles:
            if os.path.isfile(p):
                # servir archivo estático
                rel = os.path.relpath(p, static_path).replace('\\', '/')
                return send_from_directory(static_path, rel)

        # si no existe el archivo, devolver 404
        return "", 404

    # mariadb puede devolver memoryview, convertir a bytes
    try:
        if isinstance(imagen, memoryview):
            imagen = imagen.tobytes()
    except NameError:
        pass

    # Intentar detectar el tipo MIME real de la imagen
    mimetype = "application/octet-stream"
    try:
        buf = io.BytesIO(imagen)
        img = Image.open(buf)
        fmt = (img.format or '').lower()
        if fmt in ('jpeg', 'jpg'):
            mimetype = 'image/jpeg'
        elif fmt == 'png':
            mimetype = 'image/png'
        elif fmt == 'gif':
            mimetype = 'image/gif'
        else:
            mimetype = f"image/{fmt}" if fmt else mimetype
    except Exception:
        import imghdr
        kind = imghdr.what(None, h=imagen)
        if kind:
            mimetype = f"image/{kind}"

    return Response(imagen, mimetype=mimetype)


#------------------- PREDIOS -------------------
@app.route("/predios", methods=["GET", "POST"])
def predios():

    if "usuario" not in session:
        flash("Inicia sesión para acceder a Predios.", "warning")
        return redirect(url_for("login"))

    if session.get("rol") == "Veterinario":
        flash("El veterinario no tiene acceso a la tabla de predios.", "warning")
        return redirect(url_for("dashboard"))

    fk_productor = session.get("fk_productor")
    conn, cursor = conectar_bd()
    ids_vet = requiere_productores_autorizados_veterinario(conn, cursor)
    if ids_vet is None and session.get("rol") == "Veterinario":
        conn.close()
        return redirect(url_for("dashboard"))

    vista_total = session.get("rol") == "Administrador"
    if not vista_total and ids_vet is None and not fk_productor:
        flash("No tienes un productor asociado para consultar predios.", "warning")
        conn.close()
        return redirect(url_for("dashboard"))

    # --------------------
    # Obtener productores
    # --------------------
    if ids_vet is not None:
        filtro = placeholders(ids_vet)
        cursor.execute(f"SELECT pk_productor, nombre FROM Productores WHERE pk_productor IN ({filtro}) ORDER BY nombre", tuple(ids_vet))
    else:
        cursor.execute("SELECT pk_productor, nombre FROM Productores")
    productores = cursor.fetchall()

    # --------------------
    # POST
    # --------------------
    if request.method == "POST":
        accion = request.form.get("accion")

        if accion == "registrar":
            direccion = request.form.get("direccion")
            fk_estado = request.form.get("fk_estado")
            fk_municipio = request.form.get("fk_municipio")
            nom_rancho = request.form.get("nom_rancho")
            upp = request.form.get("upp")
            # Determinar fk_productor: si el usuario es Productor usar la sesión
            if session.get('rol') == 'Productor' and session.get('fk_productor'):
                fk_productor = session.get('fk_productor')

                fk_prod = session.get('fk_productor')
            else:
                fk_prod = request.form.get("fk_productor")  # 👈 nuevo
            if ids_vet is not None and int(fk_prod) not in [int(i) for i in ids_vet]:
                flash("Solo puedes registrar predios de productores aprobados.", "warning")
                return redirect(url_for("predios"))

            sql = """
                INSERT INTO Predios (direccion, fk_estado, fk_municipio, fk_productor, nom_rancho, upp)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (direccion, fk_estado, fk_municipio, fk_prod, nom_rancho, upp))
            conn.commit()

        elif accion == "modificar":
            pk = request.form.get("pk")
            direccion = request.form.get("direccion")
            fk_estado = request.form.get("fk_estado")
            fk_municipio = request.form.get("fk_municipio")
            nom_rancho = request.form.get("nom_rancho")
            upp = request.form.get("upp")
            # Determinar fk_productor: si el usuario es Productor usar la sesión
            if session.get('rol') == 'Productor' and session.get('fk_productor'):
                fk_prod = session.get('fk_productor')
            else:
                fk_prod = request.form.get("fk_productor")
            if ids_vet is not None and int(fk_prod) not in [int(i) for i in ids_vet]:
                flash("Solo puedes modificar predios de productores aprobados.", "warning")
                return redirect(url_for("predios"))

            sql = """
                UPDATE Predios
                SET direccion=%s, fk_estado=%s, fk_municipio=%s, fk_productor=%s, nom_rancho=%s, upp=%s
                WHERE pk_predio=%s
            """
            cursor.execute(sql, (direccion, fk_estado, fk_municipio, fk_prod, nom_rancho, upp, pk))
            conn.commit()

        elif accion == "eliminar":
            pk = request.form.get("pk")
            if ids_vet is not None:
                cursor.execute("SELECT fk_productor FROM Predios WHERE pk_predio=%s", (pk,))
                row = cursor.fetchone()
                if not row or int(row[0]) not in [int(i) for i in ids_vet]:
                    flash("No puedes eliminar predios de productores no aprobados.", "warning")
                    return redirect(url_for("predios"))
            cursor.execute("DELETE FROM Predios WHERE pk_predio=%s", (pk,))
            conn.commit()

        return redirect(url_for("predios"))

    # --------------------
    # GET
    # --------------------
    # Seleccionar nombres de estado y municipio a través de JOINs
    if vista_total:
        cursor.execute("""
        SELECT p.pk_predio, p.direccion, p.fk_estado, p.fk_municipio,
               e.Nombre AS estado, m.Nombre AS municipio,
               p.fk_productor, pr.nombre AS productor,
               p.nom_rancho, p.upp
            FROM Predios p
            LEFT JOIN Estados e ON p.fk_estado = e.pk_estado
            LEFT JOIN Municipios m ON p.fk_municipio = m.pk_municipio
            LEFT JOIN Productores pr ON p.fk_productor = pr.pk_productor
            ORDER BY pr.nombre, p.nom_rancho
        """)
    elif ids_vet is not None:
        filtro = placeholders(ids_vet)
        cursor.execute(f"""
        SELECT p.pk_predio, p.direccion, p.fk_estado, p.fk_municipio,
               e.Nombre AS estado, m.Nombre AS municipio,
               p.fk_productor, pr.nombre AS productor,
               p.nom_rancho, p.upp
            FROM Predios p
            LEFT JOIN Estados e ON p.fk_estado = e.pk_estado
            LEFT JOIN Municipios m ON p.fk_municipio = m.pk_municipio
            LEFT JOIN Productores pr ON p.fk_productor = pr.pk_productor
            WHERE p.fk_productor IN ({filtro})
            ORDER BY pr.nombre, p.nom_rancho
        """, tuple(ids_vet))
    else:
        cursor.execute("""
        SELECT p.pk_predio, p.direccion, p.fk_estado, p.fk_municipio,
               e.Nombre AS estado, m.Nombre AS municipio,
               p.fk_productor, pr.nombre AS productor,
               p.nom_rancho, p.upp
            FROM Predios p
            LEFT JOIN Estados e ON p.fk_estado = e.pk_estado
            LEFT JOIN Municipios m ON p.fk_municipio = m.pk_municipio
            LEFT JOIN Productores pr ON p.fk_productor = pr.pk_productor
            WHERE p.fk_productor=%s
        """, (fk_productor,))
    predios = cursor.fetchall()

    # También devolver listas para selects (estados/municipios)
    cursor.execute("SELECT pk_estado, Nombre FROM Estados")
    estados = cursor.fetchall()

    cursor.execute("SELECT pk_municipio, Nombre, fk_estado FROM Municipios")
    municipios = cursor.fetchall()

    # Obtener nombre del productor logueado para mostrar en el formulario
    productor_nombre = None
    try:
        if vista_total:
            productor_nombre = "Todos los productores"
        elif ids_vet is not None:
            productor_nombre = "Productores aprobados"
        else:
            cursor.execute("SELECT nombre FROM Productores WHERE pk_productor=%s", (fk_productor,))
            row = cursor.fetchone()
            if row:
                productor_nombre = row[0]
    except Exception:
        productor_nombre = None

    conn.close()

    return render_template("predios.html", predios=predios, productores=productores, estados=estados, municipios=municipios, productor_nombre=productor_nombre)

#----------------Modificar los datos del productor--------------
@app.route("/mi_productor", methods=["GET", "POST"])
def mi_productor():
    rol_actual = session.get("rol")
    if rol_actual == "Veterinario":
        if "id_usuario" not in session:
            flash("Debes iniciar sesión", "warning")
            return redirect(url_for("login"))

        conn, cursor = conectar_bd()

        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            apellidos = request.form.get("apellidos", "").strip()
            cedula = request.form.get("cedula", "").strip()
            direccion = request.form.get("direccion_consultorio", "").strip() or "Consultas a domicilio"
            telefono = request.form.get("telefono", "").strip()

            try:
                cursor.execute("""
                    UPDATE Veterinario
                    SET nombre=%s, apellidos=%s, cedula=%s, direccion_consultorio=%s, telefono=%s
                    WHERE fk_usuario=%s
                """, (nombre, apellidos, cedula, direccion, telefono, session["id_usuario"]))
                conn.commit()
                flash("Perfil veterinario actualizado correctamente.", "success")
            except mariadb.Error as e:
                conn.rollback()
                flash(f"No se pudo actualizar el perfil veterinario: {e}", "danger")
            finally:
                conn.close()

            return redirect(url_for("mi_productor"))

        cursor.execute("""
            SELECT
                v.id_veterinario,
                v.nombre,
                v.apellidos,
                v.cedula,
                v.direccion_consultorio,
                v.telefono,
                COALESCE(u.email, '')
            FROM Veterinario v
            LEFT JOIN Usuarios u ON u.id_usuario = v.fk_usuario
            WHERE v.fk_usuario=%s
        """, (session["id_usuario"],))
        veterinario = cursor.fetchone()
        conn.close()

        return render_template(
            "mi_productor.html",
            productor=None,
            veterinario=veterinario,
            perfil_tipo="veterinario"
        )

    if "fk_productor" not in session:
        flash("Debes iniciar sesión", "warning")
        return redirect(url_for("login"))

    fk_productor = session["fk_productor"]
    conn, cursor = conectar_bd()

    # --- GUARDAR CAMBIOS ---
    if request.method == "POST":
        nombre = request.form.get("nombre")
        apellido_pat = request.form.get("apellido_pat")
        apellido_mat = request.form.get("apellido_mat")
        rfc = request.form.get("RFC")

        # 📸 nueva imagen (fierro)
        foto_fierro = request.files.get("foto_fierro")

        if foto_fierro and foto_fierro.filename != "":
            foto_binaria = foto_fierro.read()

            sql = """
                UPDATE Productores
                SET nombre=%s, apellido_pat=%s, apellido_mat=%s, RFC=%s, foto_fierro=%s
                WHERE pk_productor=%s
            """
            valores = (nombre, apellido_pat, apellido_mat, rfc, foto_binaria, fk_productor)

        else:
            sql = """
                UPDATE Productores
                SET nombre=%s, apellido_pat=%s, apellido_mat=%s, RFC=%s
                WHERE pk_productor=%s
            """
            valores = (nombre, apellido_pat, apellido_mat, rfc, fk_productor)

        try:
            cursor.execute(sql, valores)
            conn.commit()
            flash("Datos actualizados correctamente.", "success")
        except mariadb.IntegrityError:
            flash("El RFC ya está registrado en otro productor.", "danger")

        return redirect(url_for("mi_productor"))

    # --- OBTENER DATOS ---
    try:
        cursor.execute("""
            SELECT p.pk_productor, p.nombre, p.apellido_pat, p.apellido_mat, p.RFC, COALESCE(u.email, '')
            FROM Productores p
            LEFT JOIN Usuarios u ON u.id_usuario = p.fk_usuario
            WHERE p.pk_productor=%s
        """, (fk_productor,))
    except mariadb.Error as e:
        if not _es_error_columna_email_faltante(e):
            raise
        conn.rollback()
        cursor.execute("""
            SELECT pk_productor, nombre, apellido_pat, apellido_mat, RFC, ''
            FROM Productores
            WHERE pk_productor=%s
        """, (fk_productor,))

    productor = cursor.fetchone()
    conn.close()

    return render_template(
        "mi_productor.html",
        productor=productor,
        veterinario=None,
        perfil_tipo="productor"
    )

#------------------ Mostrar imagen del fierro ------------------
@app.route("/imagen_fierro/<int:id>")
def imagen_fierro(id):
    conn, cursor = conectar_bd()
    cursor.execute("SELECT foto_fierro FROM Productores WHERE pk_productor=%s", (id,))
    fila = cursor.fetchone()
    conn.close()

    if fila and fila[0]:
        return Response(fila[0], mimetype="image/jpeg")
    return "", 404

# ------------------ PESAJES ----------------------------------

@app.route("/pesajes", methods=["GET", "POST"])
def pesajes():
    conn = None
    cursor = None

    try:
        conn, cursor = conectar_bd()
        ids_vet = ids_productores_autorizados_veterinario(conn, cursor)

        # ===================== POST =====================
        if request.method == "POST":
            accion = request.form.get("accion")

            # ===== REGISTRAR =====
            if accion == "registrar":
                pesaje_val = request.form.get("pesaje")
                fecha = request.form.get("fecha")
                fk_animal = request.form.get("fk_animal") or None
                if ids_vet is not None and fk_animal:
                    if not ids_vet:
                        flash("El administrador debe aprobarte un productor antes de registrar pesajes.", "warning")
                        return redirect(url_for("pesajes"))
                    filtro = placeholders(ids_vet)
                    cursor.execute(f"SELECT 1 FROM Animales WHERE pk_animal=%s AND fk_productor IN ({filtro})", tuple([fk_animal] + ids_vet))
                    if not cursor.fetchone():
                        flash("Solo puedes registrar pesajes de productores aprobados.", "warning")
                        return redirect(url_for("pesajes"))

                cursor.execute("""
                    INSERT INTO Pesajes (pesaje, fecha, fk_animal)
                    VALUES (%s, %s, %s)
                """, (pesaje_val, fecha, fk_animal))
                conn.commit()
                flash("Pesaje registrado correctamente", "success")

            # ===== MODIFICAR =====
            elif accion == "modificar":
                pk = request.form.get("pk")
                pesaje_val = request.form.get("pesaje")
                fecha = request.form.get("fecha")
                fk_animal = request.form.get("fk_animal") or None
                if ids_vet is not None and fk_animal:
                    if not ids_vet:
                        flash("El administrador debe aprobarte un productor antes de modificar pesajes.", "warning")
                        return redirect(url_for("pesajes"))
                    filtro = placeholders(ids_vet)
                    cursor.execute(f"SELECT 1 FROM Animales WHERE pk_animal=%s AND fk_productor IN ({filtro})", tuple([fk_animal] + ids_vet))
                    if not cursor.fetchone():
                        flash("Solo puedes modificar pesajes de productores aprobados.", "warning")
                        return redirect(url_for("pesajes"))

                cursor.execute("""
                    UPDATE Pesajes
                    SET pesaje = %s,
                        fecha = %s,
                        fk_animal = %s
                    WHERE pk_pesaje = %s
                """, (pesaje_val, fecha, fk_animal, pk))
                conn.commit()
                flash("Pesaje modificado correctamente", "info")

            # ===== ELIMINAR =====
            elif accion == "eliminar":
                pk = request.form.get("pk")
                cursor.execute(
                    "DELETE FROM Pesajes WHERE pk_pesaje = %s",
                    (pk,)
                )
                conn.commit()
                flash("Pesaje eliminado correctamente", "danger")

        # ===================== GET =====================

        # ---- LISTAR PESAJES ----
        if session.get("rol") == "Productor":
            # Solo mostrar pesajes de animales del productor actual
            cursor.execute("""
                SELECT 
                    p.pk_pesaje,
                    p.pesaje,
                    p.fecha,
                    a.pk_animal,
                    a.nombre
                FROM Pesajes p
                LEFT JOIN Animales a ON p.fk_animal = a.pk_animal
                WHERE a.fk_productor = %s
                ORDER BY p.pk_pesaje DESC
            """, (session.get("fk_productor"),))
        elif ids_vet is not None:
            if ids_vet:
                filtro = placeholders(ids_vet)
                cursor.execute(f"""
                    SELECT
                        p.pk_pesaje,
                        p.pesaje,
                        p.fecha,
                        a.pk_animal,
                        a.nombre
                    FROM Pesajes p
                    LEFT JOIN Animales a ON p.fk_animal = a.pk_animal
                    WHERE a.fk_productor IN ({filtro})
                    ORDER BY p.pk_pesaje DESC
                """, tuple(ids_vet))
            else:
                pesajes = []
        else:
            # Comprador ve todos los pesajes
            cursor.execute("""
                SELECT 
                    p.pk_pesaje,
                    p.pesaje,
                    p.fecha,
                    a.pk_animal,
                    a.nombre
                FROM Pesajes p
                LEFT JOIN Animales a ON p.fk_animal = a.pk_animal
                ORDER BY p.pk_pesaje DESC
            """)
        if not (ids_vet is not None and not ids_vet):
            pesajes = cursor.fetchall()

        # ---- ANIMALES PARA EL SELECT (FILTRADOS POR PRODUCTOR) ----
        if session.get("rol") == "Productor":
            cursor.execute("""
                SELECT pk_animal, nombre
                FROM Animales
                WHERE fk_productor = %s
                ORDER BY nombre
            """, (session.get("fk_productor"),))
            animales = cursor.fetchall()
        elif ids_vet is not None:
            if ids_vet:
                filtro = placeholders(ids_vet)
                cursor.execute(f"""
                    SELECT pk_animal, nombre
                    FROM Animales
                    WHERE fk_productor IN ({filtro})
                    ORDER BY nombre
                """, tuple(ids_vet))
                animales = cursor.fetchall()
            else:
                animales = []
        else:
            cursor.execute("""
                SELECT pk_animal, nombre
                FROM Animales
            """)
            animales = cursor.fetchall()

    except Exception as e:
        flash(f"Error en módulo Pesajes: {e}", "danger")
        pesajes = []
        animales = []

    finally:
        if conn:
            conn.close()

    return render_template(
        "pesajes.html",
        pesajes=pesajes,
        animales=animales
    )

# ---- RUTA PARA OBTENER PREDIOS Y DIRECCIÓN ----
@app.route("/obtener_predios")
def obtener_predios():
    """Devuelve lista de predios del productor actual con sus direcciones"""
    try:
        if session.get("rol") != "Productor":
            return {"predios": []}, 403
        
        fk_productor = session.get("fk_productor")
        conn, cursor = conectar_bd()
        
        cursor.execute("""
            SELECT pk_predio, nom_rancho, direccion
            FROM Predios
            WHERE fk_productor=%s
            ORDER BY nom_rancho
        """, (fk_productor,))
        
        predios = cursor.fetchall()
        conn.close()
        
        # Convertir a lista de diccionarios
        resultado = [{"id": p[0], "nombre": p[1], "direccion": p[2]} for p in predios]
        return {"predios": resultado}
    
    except Exception as e:
        print(f"Error en obtener_predios: {e}")
        return {"predios": [], "error": str(e)}, 500

#_-------------------------------SIINIGA-------------------------------


@app.route("/registro_siniga", methods=["GET", "POST"])
def registro_siniga():

    if "usuario" not in session:
        return redirect(url_for("login"))

    conn, cursor = conectar_bd()
    ids_vet = requiere_productores_autorizados_veterinario(conn, cursor)
    if ids_vet is None and session.get("rol") == "Veterinario":
        conn.close()
        return redirect(url_for("dashboard"))

    vista_total = session.get("rol") == "Administrador"
    fk_productor = session.get("fk_productor")
    if not vista_total and ids_vet is None and not fk_productor:
        flash("No tienes un productor asociado para consultar Registro SINIGA.", "warning")
        conn.close()
        return redirect(url_for("dashboard"))

    # ----- REGISTRAR -----
# ----- REGISTRAR -----
    if request.method == "POST" and request.form.get("accion") == "registrar":
        fk_animal = request.form["fk_animal"]
        arete = request.form["arete"]

        try:
            if ids_vet is not None:
                filtro = placeholders(ids_vet)
                cursor.execute(f"SELECT 1 FROM Animales WHERE pk_animal=%s AND fk_productor IN ({filtro})", tuple([fk_animal] + ids_vet))
                if not cursor.fetchone():
                    flash("Solo puedes registrar aretes de productores aprobados.", "warning")
                    return redirect(url_for("registro_siniga"))
            cursor.execute("""
                INSERT INTO Registro_SINIGA (fk_animal, arete)
                VALUES (%s, %s)
            """, (fk_animal, arete))
            conn.commit()
            flash("Registro SIINIGA creado correctamente.", "success")

        except mariadb.IntegrityError:
            flash("Este animal ya cuenta con un registro SIINIGA.", "warning")

    # ----- MODIFICAR -----
    elif request.method == "POST" and request.form.get("accion") == "modificar":
        pk = request.form["pk"]
        fk_animal = request.form["fk_animal"]
        arete = request.form["arete"]

        cursor.execute("""
        SELECT id FROM Registro_SINIGA
        WHERE fk_animal = %s AND id <> %s
    """, (fk_animal, pk))

        if cursor.fetchone():
            flash("Este animal ya tiene otro registro SIINIGA.", "warning")
        else:
            if ids_vet is not None:
                filtro = placeholders(ids_vet)
                cursor.execute(f"""
                    SELECT 1
                    FROM Animales
                    WHERE pk_animal=%s AND fk_productor IN ({filtro})
                """, tuple([fk_animal] + ids_vet))
                if not cursor.fetchone():
                    flash("No puedes modificar registros de productores no aprobados.", "warning")
                    return redirect(url_for("registro_siniga"))
            elif not vista_total:
                cursor.execute("""
                    SELECT 1
                    FROM Animales
                    WHERE pk_animal=%s AND fk_productor=%s
                """, (fk_animal, fk_productor))
                if not cursor.fetchone():
                    flash("No puedes modificar registros de otro productor.", "warning")
                    return redirect(url_for("registro_siniga"))

            cursor.execute("""
                UPDATE Registro_SINIGA
                SET fk_animal=%s, arete=%s
                WHERE id=%s
            """, (fk_animal, arete, pk))
            conn.commit()
            flash("Registro SIINIGA modificado correctamente.", "success")

    # ----- ELIMINAR -----
    elif request.method == "POST" and request.form.get("accion") == "eliminar":
        pk = request.form["pk"]

        if ids_vet is not None:
            filtro = placeholders(ids_vet)
            cursor.execute(f"""
                SELECT 1
                FROM Registro_SINIGA r
                INNER JOIN Animales a ON r.fk_animal = a.pk_animal
                WHERE r.id=%s AND a.fk_productor IN ({filtro})
            """, tuple([pk] + ids_vet))
            if not cursor.fetchone():
                flash("No puedes eliminar registros de productores no aprobados.", "warning")
                return redirect(url_for("registro_siniga"))
        elif not vista_total:
            cursor.execute("""
                SELECT 1
                FROM Registro_SINIGA r
                INNER JOIN Animales a ON r.fk_animal = a.pk_animal
                WHERE r.id=%s AND a.fk_productor=%s
            """, (pk, fk_productor))
            if not cursor.fetchone():
                flash("No puedes eliminar registros de otro productor.", "warning")
                return redirect(url_for("registro_siniga"))

        cursor.execute("DELETE FROM Registro_SINIGA WHERE id=%s", (pk,))
        conn.commit()

    # ----- CONSULTAR (SOLO DEL PRODUCTOR) -----
    if vista_total:
        cursor.execute("""
            SELECT
                r.id,
                r.fk_animal,
                r.arete,
                a.nombre
            FROM Registro_SINIGA r
            INNER JOIN Animales a ON r.fk_animal = a.pk_animal
            ORDER BY a.nombre
        """)
    elif ids_vet is not None:
        filtro = placeholders(ids_vet)
        cursor.execute(f"""
            SELECT
                r.id,
                r.fk_animal,
                r.arete,
                a.nombre
            FROM Registro_SINIGA r
            INNER JOIN Animales a ON r.fk_animal = a.pk_animal
            WHERE a.fk_productor IN ({filtro})
            ORDER BY a.nombre
        """, tuple(ids_vet))
    else:
        cursor.execute("""
            SELECT
                r.id,
                r.fk_animal,
                r.arete,
                a.nombre
            FROM Registro_SINIGA r
            INNER JOIN Animales a ON r.fk_animal = a.pk_animal
            WHERE a.fk_productor = %s
        """, (fk_productor,))
    registros = cursor.fetchall()

    # ----- ANIMALES SOLO DEL PRODUCTOR -----
    if vista_total:
        cursor.execute("""
            SELECT pk_animal, nombre
            FROM Animales
            ORDER BY nombre
        """)
    elif ids_vet is not None:
        filtro = placeholders(ids_vet)
        cursor.execute(f"""
            SELECT pk_animal, nombre
            FROM Animales
            WHERE fk_productor IN ({filtro})
            ORDER BY nombre
        """, tuple(ids_vet))
    else:
        cursor.execute("""
            SELECT pk_animal, nombre
            FROM Animales
            WHERE fk_productor = %s
        """, (fk_productor,))
    animales = cursor.fetchall()

    conn.close()

    return render_template(
        "registro_siniga.html",
        animales=animales,
        registros=registros
    )


# ---------------- SEGUIMIENTO VETERINARIO ----------------
@app.route("/seguimiento", methods=["GET", "POST"])
def seguimiento():
    if "usuario" not in session:
        return redirect(url_for("login"))

    conn = None
    cursor = None

    try:
        conn, cursor = conectar_bd()
        ids_vet = ids_productores_autorizados_veterinario(conn, cursor)

        def animal_permitido(fk_animal):
            if not fk_animal:
                return False

            if session.get("rol") == "Productor":
                cursor.execute(
                    "SELECT 1 FROM Animales WHERE pk_animal=%s AND fk_productor=%s",
                    (fk_animal, session.get("fk_productor"))
                )
                return bool(cursor.fetchone())

            if ids_vet is not None:
                if not ids_vet:
                    return False

                filtro = placeholders(ids_vet)
                cursor.execute(
                    f"SELECT 1 FROM Animales WHERE pk_animal=%s AND fk_productor IN ({filtro})",
                    tuple([fk_animal] + ids_vet)
                )
                return bool(cursor.fetchone())

            return True

        def seguimiento_permitido(pk):
            if not pk:
                return False

            if session.get("rol") == "Productor":
                cursor.execute("""
                    SELECT 1
                    FROM Seguimiento_vet s
                    JOIN Animales a ON a.pk_animal = s.fk_animal
                    WHERE s.pk_segui_vet=%s AND a.fk_productor=%s
                """, (pk, session.get("fk_productor")))
                return bool(cursor.fetchone())

            if ids_vet is not None:
                if not ids_vet:
                    return False

                filtro = placeholders(ids_vet)
                cursor.execute(f"""
                    SELECT 1
                    FROM Seguimiento_vet s
                    JOIN Animales a ON a.pk_animal = s.fk_animal
                    WHERE s.pk_segui_vet=%s AND a.fk_productor IN ({filtro})
                """, tuple([pk] + ids_vet))
                return bool(cursor.fetchone())

            return True

        # ===== POST =====
        if request.method == "POST":
            accion = request.form.get("accion")
            pk = request.form.get("pk")
            fk_animal = request.form.get("fk_animal")
            fk_tratamiento = request.form.get("fk_tratamiento")
            medicamento_catalogo = request.form.get("medicamento_catalogo", "").strip()
            medicamento_manual = request.form.get("medicamento", "").strip()
            medicamento = medicamento_manual or medicamento_catalogo
            fecha_actual = request.form.get("fecha_actual")
            prox_fecha = request.form.get("prox_fecha")

            if accion == "registrar":
                if not animal_permitido(fk_animal):
                    flash("Solo puedes usar animales permitidos para tu usuario.", "warning")
                    return redirect(url_for("seguimiento"))

                cursor.execute("""
                    INSERT INTO Seguimiento_vet
                    (fk_animal, fk_tratamiento, medicamento, fecha_actual, prox_fecha)
                    VALUES (%s,%s,%s,%s,%s)
                """, (fk_animal, fk_tratamiento, medicamento, fecha_actual, prox_fecha))
                conn.commit()
                flash("Seguimiento registrado", "success")

            elif accion == "modificar":
                if not seguimiento_permitido(pk) or not animal_permitido(fk_animal):
                    flash("Solo puedes modificar seguimientos permitidos para tu usuario.", "warning")
                    return redirect(url_for("seguimiento"))

                cursor.execute("""
                    UPDATE Seguimiento_vet SET
                        fk_animal=%s,
                        fk_tratamiento=%s,
                        medicamento=%s,
                        fecha_actual=%s,
                        prox_fecha=%s
                    WHERE pk_segui_vet=%s
                """, (fk_animal, fk_tratamiento, medicamento, fecha_actual, prox_fecha, pk))
                conn.commit()
                flash("Seguimiento actualizado", "info")

            elif accion == "eliminar":
                if not seguimiento_permitido(pk):
                    flash("Solo puedes eliminar seguimientos permitidos para tu usuario.", "warning")
                    return redirect(url_for("seguimiento"))

                cursor.execute(
                    "DELETE FROM Seguimiento_vet WHERE pk_segui_vet=%s",
                    (pk,)
                )
                conn.commit()
                flash("Seguimiento eliminado", "danger")

        # ===== LISTADO SEGUIMIENTOS =====
        if ids_vet is not None:
            if ids_vet:
                filtro = placeholders(ids_vet)
                cursor.execute(f"""
                    SELECT
                        s.pk_segui_vet,
                        s.fk_animal,
                        a.nombre,
                        t.pk_tratamiento,
                        t.nombre,
                        t.impacto,
                        s.medicamento,
                        s.fecha_actual,
                        s.prox_fecha
                    FROM Seguimiento_vet s
                    JOIN Animales a ON a.pk_animal = s.fk_animal
                    JOIN tratamientos t ON t.pk_tratamiento = s.fk_tratamiento
                    WHERE a.fk_productor IN ({filtro})
                    ORDER BY s.pk_segui_vet DESC
                """, tuple(ids_vet))
                seguimientos = cursor.fetchall()
            else:
                seguimientos = []
        elif session.get("rol") == "Productor":
            cursor.execute("""
                SELECT
                    s.pk_segui_vet,
                    s.fk_animal,
                    a.nombre,
                    t.pk_tratamiento,
                    t.nombre,
                    t.impacto,
                    s.medicamento,
                    s.fecha_actual,
                    s.prox_fecha
                FROM Seguimiento_vet s
                JOIN Animales a ON a.pk_animal = s.fk_animal
                JOIN tratamientos t ON t.pk_tratamiento = s.fk_tratamiento
                WHERE a.fk_productor=%s
                ORDER BY s.pk_segui_vet DESC
            """, (session.get("fk_productor"),))
            seguimientos = cursor.fetchall()
        else:
            cursor.execute("""
            SELECT
                s.pk_segui_vet,
                s.fk_animal,
                a.nombre,
                t.pk_tratamiento,
                t.nombre,
                t.impacto,
                s.medicamento,
                s.fecha_actual,
                s.prox_fecha
            FROM Seguimiento_vet s
            JOIN Animales a ON a.pk_animal = s.fk_animal
            JOIN tratamientos t ON t.pk_tratamiento = s.fk_tratamiento
            ORDER BY s.pk_segui_vet DESC
            """)
            seguimientos = cursor.fetchall()

        # ===== ANIMALES =====
        if session.get("rol") == "Productor":
            cursor.execute("""
                SELECT pk_animal, nombre
                FROM Animales
                WHERE fk_productor=%s
                ORDER BY nombre
            """, (session.get("fk_productor"),))
            animales = cursor.fetchall()
        elif ids_vet is not None:
            if ids_vet:
                filtro = placeholders(ids_vet)
                cursor.execute(f"""
                    SELECT pk_animal, nombre
                    FROM Animales
                    WHERE fk_productor IN ({filtro})
                    ORDER BY nombre
                """, tuple(ids_vet))
                animales = cursor.fetchall()
            else:
                animales = []
        else:
            cursor.execute("SELECT pk_animal, nombre FROM Animales")
            animales = cursor.fetchall()

        # ===== TRATAMIENTOS =====
        cursor.execute("""
            SELECT pk_tratamiento, nombre, impacto
            FROM tratamientos
            ORDER BY nombre
        """)
        tratamientos = cursor.fetchall()
        medicamentos = obtener_catalogo_medicamentos(conn, cursor)

        return render_template(
            "seguimiento.html",
            seguimientos=seguimientos,
            animales=animales,
            tratamientos=tratamientos,
            medicamentos=medicamentos,
            fecha_hoy=datetime.now().strftime("%Y-%m-%d")
        )

    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Error: {e}", "danger")
        return render_template(
            "seguimiento.html",
            seguimientos=[],
            animales=[],
            tratamientos=[],
            medicamentos=[],
            fecha_hoy=datetime.now().strftime("%Y-%m-%d")
        )

    finally:
        if cursor: cursor.close()
        if conn: conn.close()



#------------------------------------------------------------------------------------------

# ----------------------VENTAS ---------------------------------------------
@app.route("/ventas", methods=["GET", "POST"])
def ventas():
    if "usuario" not in session:
        flash("Debes iniciar sesión", "warning")
        return redirect(url_for("login"))

    conn = None
    cursor = None

    try:
        conn, cursor = conectar_bd()
        ids_vet = requiere_productores_autorizados_veterinario(conn, cursor)
        if ids_vet is None and session.get("rol") == "Veterinario":
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            accion = request.form.get("accion")

            # REGISTRAR
            if accion == "registrar":
                fk_animal = request.form.get("fk_animal") or None
                fk_pesaje = request.form.get("fk_pesaje") or None
                clave = request.form.get("clave")
                precio_raw = request.form.get("precio")
                fecha_venta = request.form.get("fecha_venta")

                # Validar y convertir precio a float o None
                if precio_raw is None or precio_raw == "":
                    flash("Precio vacío. Selecciona un animal para calcular el precio antes de registrar.", "danger")
                    return redirect(url_for("ventas"))
                try:
                    precio = float(precio_raw)
                except ValueError:
                    flash("Precio inválido.", "danger")
                    return redirect(url_for("ventas"))
                if ids_vet is not None and fk_animal:
                    filtro = placeholders(ids_vet)
                    cursor.execute(f"SELECT 1 FROM Animales WHERE pk_animal=%s AND fk_productor IN ({filtro})", tuple([fk_animal] + ids_vet))
                    if not cursor.fetchone():
                        flash("Solo puedes registrar ventas de productores aprobados.", "warning")
                        return redirect(url_for("ventas"))

                cursor.execute("""
                    INSERT INTO Ventas (fk_animal, fk_pesaje, clave, precio, fecha_venta)
                    VALUES (%s, %s, %s, %s, %s)
                """, (fk_animal, fk_pesaje, clave, precio, fecha_venta))
                if fk_animal:
                    cursor.execute(
                        "UPDATE Animales SET estatus=%s WHERE pk_animal=%s",
                        ("Vendido", fk_animal)
                    )
                conn.commit()
                flash("Venta registrada correctamente", "success")

            # MODIFICAR
            elif accion == "modificar":
                pk = request.form.get("pk")
                cursor.execute("SELECT fk_animal FROM Ventas WHERE pk_venta=%s", (pk,))
                venta_actual = cursor.fetchone()
                fk_animal_anterior = venta_actual[0] if venta_actual else None

                fk_animal = request.form.get("fk_animal") or None
                fk_pesaje = request.form.get("fk_pesaje") or None
                clave = request.form.get("clave")
                precio_raw = request.form.get("precio")
                fecha_venta = request.form.get("fecha_venta")

                # Validar precio
                if precio_raw is None or precio_raw == "":
                    flash("Precio vacío. Selecciona un animal para calcular el precio antes de modificar.", "danger")
                    return redirect(url_for("ventas"))
                try:
                    precio = float(precio_raw)
                except ValueError:
                    flash("Precio inválido.", "danger")
                    return redirect(url_for("ventas"))
                if ids_vet is not None and fk_animal:
                    filtro = placeholders(ids_vet)
                    cursor.execute(f"SELECT 1 FROM Animales WHERE pk_animal=%s AND fk_productor IN ({filtro})", tuple([fk_animal] + ids_vet))
                    if not cursor.fetchone():
                        flash("Solo puedes modificar ventas de productores aprobados.", "warning")
                        return redirect(url_for("ventas"))

                cursor.execute("""
                    UPDATE Ventas
                    SET fk_animal=%s, fk_pesaje=%s, clave=%s, precio=%s, fecha_venta=%s
                    WHERE pk_venta=%s
                """, (fk_animal, fk_pesaje, clave, precio, fecha_venta, pk))
                if fk_animal:
                    cursor.execute(
                        "UPDATE Animales SET estatus=%s WHERE pk_animal=%s",
                        ("Vendido", fk_animal)
                    )
                if fk_animal_anterior and str(fk_animal_anterior) != str(fk_animal):
                    cursor.execute("SELECT COUNT(*) FROM Ventas WHERE fk_animal=%s", (fk_animal_anterior,))
                    ventas_restantes = cursor.fetchone()[0]
                    if ventas_restantes == 0:
                        cursor.execute("""
                            UPDATE Animales
                            SET estatus=%s
                            WHERE pk_animal=%s AND estatus=%s
                        """, ("Activo", fk_animal_anterior, "Vendido"))
                conn.commit()
                flash("Venta modificada correctamente", "info")

            # ELIMINAR
            elif accion == "eliminar":
                pk = request.form.get("pk")
                cursor.execute("SELECT fk_animal FROM Ventas WHERE pk_venta=%s", (pk,))
                venta_actual = cursor.fetchone()
                fk_animal_eliminado = venta_actual[0] if venta_actual else None
                if ids_vet is not None and fk_animal_eliminado:
                    filtro = placeholders(ids_vet)
                    cursor.execute(f"SELECT 1 FROM Animales WHERE pk_animal=%s AND fk_productor IN ({filtro})", tuple([fk_animal_eliminado] + ids_vet))
                    if not cursor.fetchone():
                        flash("No puedes eliminar ventas de productores no aprobados.", "warning")
                        return redirect(url_for("ventas"))

                cursor.execute("DELETE FROM Ventas WHERE pk_venta=%s", (pk,))
                if fk_animal_eliminado:
                    cursor.execute("SELECT COUNT(*) FROM Ventas WHERE fk_animal=%s", (fk_animal_eliminado,))
                    ventas_restantes = cursor.fetchone()[0]
                    if ventas_restantes == 0:
                        cursor.execute("""
                            UPDATE Animales
                            SET estatus=%s
                            WHERE pk_animal=%s AND estatus=%s
                        """, ("Activo", fk_animal_eliminado, "Vendido"))
                conn.commit()
                flash("Venta eliminada", "danger")

        # CONSULTAR REGISTROS
        # Mostrar detalles completos: animal, pesaje, raza, productor, rancho, dirección, precio
        try:
            if session.get("rol") == "Productor":
                # Solo mostrar ventas de animales del productor actual
                cursor.execute("""
                    SELECT DISTINCT v.pk_venta, v.fk_animal, v.fk_pesaje, v.clave, v.precio, v.fecha_venta,
                           a.nombre AS animal_nombre, 
                           COALESCE(p.pesaje, (SELECT pesaje FROM Pesajes WHERE fk_animal = a.pk_animal ORDER BY fecha DESC LIMIT 1)) AS pesaje,
                           r.nombre AS raza,
                           pr.nombre AS productor, 
                           (SELECT nom_rancho FROM Predios WHERE fk_productor = pr.pk_productor LIMIT 1) AS nom_rancho,
                           (SELECT direccion FROM Predios WHERE fk_productor = pr.pk_productor LIMIT 1) AS direccion
                    FROM Ventas v
                    LEFT JOIN Animales a ON v.fk_animal = a.pk_animal
                    LEFT JOIN Pesajes p ON v.fk_pesaje = p.pk_pesaje
                    LEFT JOIN Razas r ON a.fk_raza = r.pk_raza
                    LEFT JOIN Productores pr ON a.fk_productor = pr.pk_productor
                    WHERE a.fk_productor = %s
                    ORDER BY v.pk_venta DESC
                """, (session.get("fk_productor"),))
            elif ids_vet is not None:
                filtro = placeholders(ids_vet)
                cursor.execute(f"""
                    SELECT DISTINCT v.pk_venta, v.fk_animal, v.fk_pesaje, v.clave, v.precio, v.fecha_venta,
                           a.nombre AS animal_nombre,
                           COALESCE(p.pesaje, (SELECT pesaje FROM Pesajes WHERE fk_animal = a.pk_animal ORDER BY fecha DESC LIMIT 1)) AS pesaje,
                           r.nombre AS raza,
                           pr.nombre AS productor,
                           (SELECT nom_rancho FROM Predios WHERE fk_productor = pr.pk_productor LIMIT 1) AS nom_rancho,
                           (SELECT direccion FROM Predios WHERE fk_productor = pr.pk_productor LIMIT 1) AS direccion
                    FROM Ventas v
                    LEFT JOIN Animales a ON v.fk_animal = a.pk_animal
                    LEFT JOIN Pesajes p ON v.fk_pesaje = p.pk_pesaje
                    LEFT JOIN Razas r ON a.fk_raza = r.pk_raza
                    LEFT JOIN Productores pr ON a.fk_productor = pr.pk_productor
                    WHERE a.fk_productor IN ({filtro})
                    ORDER BY v.pk_venta DESC
                """, tuple(ids_vet))
            else:
                # Comprador ve todas las ventas
                cursor.execute("""
                    SELECT DISTINCT v.pk_venta, v.fk_animal, v.fk_pesaje, v.clave, v.precio, v.fecha_venta,
                           a.nombre AS animal_nombre, 
                           COALESCE(p.pesaje, (SELECT pesaje FROM Pesajes WHERE fk_animal = a.pk_animal ORDER BY fecha DESC LIMIT 1)) AS pesaje,
                           r.nombre AS raza,
                           pr.nombre AS productor, 
                           (SELECT nom_rancho FROM Predios WHERE fk_productor = pr.pk_productor LIMIT 1) AS nom_rancho,
                           (SELECT direccion FROM Predios WHERE fk_productor = pr.pk_productor LIMIT 1) AS direccion
                    FROM Ventas v
                    LEFT JOIN Animales a ON v.fk_animal = a.pk_animal
                    LEFT JOIN Pesajes p ON v.fk_pesaje = p.pk_pesaje
                    LEFT JOIN Razas r ON a.fk_raza = r.pk_raza
                    LEFT JOIN Productores pr ON a.fk_productor = pr.pk_productor
                    ORDER BY v.pk_venta DESC
                """)
        except Exception as e:
            # Fallback: obtener pesaje del animal más reciente
            if session.get("rol") == "Productor":
                cursor.execute("""
                    SELECT DISTINCT v.pk_venta, v.fk_animal, v.fk_pesaje, v.clave, v.precio, v.fecha_venta,
                           a.nombre AS animal_nombre, 
                           (SELECT pesaje FROM Pesajes WHERE fk_animal = a.pk_animal ORDER BY fecha DESC LIMIT 1) AS pesaje,
                           r.nombre AS raza,
                           pr.nombre AS productor, 
                           (SELECT nom_rancho FROM Predios WHERE fk_productor = pr.pk_productor LIMIT 1) AS nom_rancho,
                           (SELECT direccion FROM Predios WHERE fk_productor = pr.pk_productor LIMIT 1) AS direccion
                    FROM Ventas v
                    LEFT JOIN Animales a ON v.fk_animal = a.pk_animal
                    LEFT JOIN Razas r ON a.fk_raza = r.pk_raza
                    LEFT JOIN Productores pr ON a.fk_productor = pr.pk_productor
                    WHERE a.fk_productor = %s
                    ORDER BY v.pk_venta DESC
                """, (session.get("fk_productor"),))
            elif ids_vet is not None:
                filtro = placeholders(ids_vet)
                cursor.execute(f"""
                    SELECT DISTINCT v.pk_venta, v.fk_animal, v.fk_pesaje, v.clave, v.precio, v.fecha_venta,
                           a.nombre AS animal_nombre,
                           (SELECT pesaje FROM Pesajes WHERE fk_animal = a.pk_animal ORDER BY fecha DESC LIMIT 1) AS pesaje,
                           r.nombre AS raza,
                           pr.nombre AS productor,
                           (SELECT nom_rancho FROM Predios WHERE fk_productor = pr.pk_productor LIMIT 1) AS nom_rancho,
                           (SELECT direccion FROM Predios WHERE fk_productor = pr.pk_productor LIMIT 1) AS direccion
                    FROM Ventas v
                    LEFT JOIN Animales a ON v.fk_animal = a.pk_animal
                    LEFT JOIN Razas r ON a.fk_raza = r.pk_raza
                    LEFT JOIN Productores pr ON a.fk_productor = pr.pk_productor
                    WHERE a.fk_productor IN ({filtro})
                    ORDER BY v.pk_venta DESC
                """, tuple(ids_vet))
            else:
                cursor.execute("""
                    SELECT DISTINCT v.pk_venta, v.fk_animal, v.fk_pesaje, v.clave, v.precio, v.fecha_venta,
                           a.nombre AS animal_nombre, 
                           (SELECT pesaje FROM Pesajes WHERE fk_animal = a.pk_animal ORDER BY fecha DESC LIMIT 1) AS pesaje,
                           r.nombre AS raza,
                           pr.nombre AS productor, 
                           (SELECT nom_rancho FROM Predios WHERE fk_productor = pr.pk_productor LIMIT 1) AS nom_rancho,
                           (SELECT direccion FROM Predios WHERE fk_productor = pr.pk_productor LIMIT 1) AS direccion
                    FROM Ventas v
                    LEFT JOIN Animales a ON v.fk_animal = a.pk_animal
                    LEFT JOIN Razas r ON a.fk_raza = r.pk_raza
                    LEFT JOIN Productores pr ON a.fk_productor = pr.pk_productor
                    ORDER BY v.pk_venta DESC
                """)
        ventas_list = cursor.fetchall()

        # Animales para el select
        # Para Comprador: todos los animales (de todos los productores)
        # Para Productor: solo sus animales
        if session.get("rol") == "Productor":
            fk = session.get("fk_productor")
            if fk:
                cursor.execute("SELECT pk_animal, nombre FROM Animales WHERE fk_productor=%s", (fk,))
            else:
                animales = []
                flash("Error: Productor sin ID asociado", "warning")
        elif ids_vet is not None:
            filtro = placeholders(ids_vet)
            cursor.execute(f"SELECT pk_animal, nombre FROM Animales WHERE fk_productor IN ({filtro})", tuple(ids_vet))
        else:
            # Comprador ve todos los animales
            cursor.execute("SELECT pk_animal, nombre FROM Animales")
        
        if session.get("rol") != "Productor" or session.get("fk_productor"):
            animales = cursor.fetchall()

        # Pesajes para el select
        cursor.execute("SELECT pk_pesaje, pesaje FROM Pesajes")
        pesajes = cursor.fetchall()

    except Exception as e:
        flash(f"Error en módulo Ventas: {e}", "danger")
        ventas_list = []
        animales = []
        pesajes = []

    finally:
        if conn:
            conn.close()

    return render_template("ventas.html", ventas=ventas_list, animales=animales, pesajes=pesajes)



# ------------ RUTA PARA CALCULAR PRECIO AUTOMÁTICO ----------------
@app.route("/calcular_precio", methods=["POST"])
def calcular_precio():
    try:
        data = request.get_json()
        animal_id = data.get("animal_id")
        
        if not animal_id:
            return {"precio": 0, "status": "error", "message": "Sin animal_id"}, 400

        conn, cursor = conectar_bd()
        if not conn:
            return {"precio": 0, "status": "error", "message": "Error de conexión"}, 500
        
        total = 0
        
        try:
            # Obtener el peso del animal (desde pesajes o peso_actual)
            cursor.execute("""
                SELECT COALESCE(
                    (SELECT pesaje FROM Pesajes WHERE fk_animal=%s ORDER BY fecha DESC LIMIT 1),
                    (SELECT peso_actual FROM Animales WHERE pk_animal=%s)
                ) AS peso
            """, (animal_id, animal_id))
            result = cursor.fetchone()
            peso = float(result[0]) if result and result[0] else 0
            
            # Calcular precio: peso * 100
            precio_kg = 100
            total = peso * precio_kg if peso > 0 else 0
            
            print(f"Animal ID: {animal_id}, Peso: {peso}, Precio: {total}")
            
        except Exception as e:
            print(f"Error en cálculo de precio: {e}")
            total = 0

        conn.close()
        return {"precio": float(total), "status": "success"}
    
    except Exception as e:
        print(f"Error en calcular_precio: {e}")
        return {"precio": 0, "status": "error", "message": str(e)}, 500




# ----------------------RAZAS ---------------------------------------------
@app.route("/razas", methods=["GET", "POST"])
def razas():
    conn = None
    cursor = None

    try:
        conn, cursor = conectar_bd()

        if request.method == "POST":
            accion = request.form.get("accion")

            # REGISTRAR
            if accion == "registrar":
                nombre = request.form.get("nombre")
                origen = request.form.get("origen")
                color = request.form.get("color")

                cursor.execute("""
                    INSERT INTO Razas (nombre, origen, color)
                    VALUES (%s, %s, %s)
                """, (nombre, origen, color))
                conn.commit()
                flash("Raza registrada correctamente", "success")

            # MODIFICAR
            elif accion == "modificar":
                pk = request.form.get("pk")
                nombre = request.form.get("nombre")
                origen = request.form.get("origen")
                color = request.form.get("color")

                try:
                    cursor.execute("""
                        UPDATE Razas
                        SET nombre=%s, origen=%s, color=%s
                        WHERE pk_raza=%s
                    """, (nombre, origen, color, pk))
                    conn.commit()
                    flash("Raza modificada correctamente", "info")
                except mariadb.IntegrityError as ie:
                    conn.rollback()
                    flash(f"No se pudo modificar la raza por restricción de integridad: {ie}", "danger")
                except Exception as e:
                    conn.rollback()
                    flash(f"Error al modificar raza: {e}", "danger")

            # ELIMINAR
            elif accion == "eliminar":
                pk = request.form.get("pk")
                try:
                    # Verificar si existen animales vinculados a esta raza
                    cursor.execute("SELECT COUNT(*) FROM Animales WHERE fk_raza=%s", (pk,))
                    row = cursor.fetchone()
                    contador = int(row[0]) if row and row[0] is not None else 0
                    if contador > 0:
                        flash(f"No se puede eliminar la raza: existen {contador} animal(es) vinculados. Reasigne o elimine esos animales primero.", "danger")
                    else:
                        cursor.execute("DELETE FROM Razas WHERE pk_raza=%s", (pk,))
                        conn.commit()
                        flash("Raza eliminada", "danger")
                except mariadb.IntegrityError as ie:
                    conn.rollback()
                    flash(f"No se pudo eliminar la raza por restricción de integridad: {ie}", "danger")
                except Exception as e:
                    conn.rollback()
                    flash(f"Error al eliminar raza: {e}", "danger")

        # CONSULTAR REGISTROS
        # Todos (Productor, Comprador, etc.) ven todas las razas disponibles
        cursor.execute("""
            SELECT pk_raza, nombre, origen, color
            FROM Razas
            ORDER BY pk_raza DESC
        """)
        razas_list = cursor.fetchall()

    except Exception as e:
        flash(f"Error en módulo Razas: {e}", "danger")
        razas_list = []

    finally:
        if conn:
            conn.close()

    return render_template("razas.html", razas=razas_list)

@app.route("/upp")
def upp():
    return send_from_directory(
        directory="static/pdf",
        path="solicitud_pgn.pdf",
        as_attachment = True
    )

#--------------Sección done nos describe la forma o el procedimiento para generar un pdf------------
# --- CLASE PDF PERSONALIZADA ---
class PDFRearetado(FPDF):
    def header(self):
        agricultura_logo = resolve_asset_path("logo_agricultura.jpg")
        siniiga_logo = resolve_asset_path("logo_pdf.png")
        guia_rearetado = resolve_asset_path("maxresdefault (2).jpg")

        if agricultura_logo:
            self.image(agricultura_logo, 12, 8, 42)
        if siniiga_logo:
            self.image(siniiga_logo, 96, 8, 18)
        if guia_rearetado:
            self.image(guia_rearetado, 158, 8, 40)

        self.set_xy(12, 32)
        self.set_font('Arial', 'B', 8)
        self.cell(186, 5, 'SISTEMA NACIONAL DE IDENTIFICACION INDIVIDUAL DE GANADO', 0, 1, 'C')
        self.cell(186, 5, 'SISTEMA NACIONAL DE IDENTIFICACION ANIMAL', 0, 1, 'C')
        self.cell(186, 5, 'SOLICITUD DE IDENTIFICADORES PARA REPOSICION O REARETADO', 0, 1, 'C')
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'R')


def texto_pdf(valor):
    return str(valor or "").encode("latin-1", "replace").decode("latin-1")


def dibujar_linea_dato(pdf, x, y, etiqueta, valor, ancho=180):
    pdf.set_xy(x, y)
    pdf.set_font('Arial', 'B', 8)
    pdf.cell(40, 6, texto_pdf(etiqueta), 0, 0)
    pdf.set_font('Arial', '', 8)
    pdf.cell(ancho - 40, 6, texto_pdf(valor), 'B', 0)


def dibujar_checkbox(pdf, x, y, texto, activo=False):
    pdf.rect(x, y, 4, 4)
    if activo:
        pdf.line(x + 0.7, y + 2.1, x + 1.7, y + 3.3)
        pdf.line(x + 1.7, y + 3.3, x + 3.4, y + 0.8)
    pdf.set_xy(x + 5.5, y - 1)
    pdf.set_font('Arial', '', 8)
    pdf.cell(42, 6, texto_pdf(texto), 0, 0)


def dibujar_cajas_codigo(pdf, x, y, valor, total_cajas=12, caja=6):
    valor = texto_pdf(valor).replace("-", "").replace(" ", "").upper()
    for i in range(total_cajas):
        pdf.rect(x + (i * caja), y, caja - 0.8, 5.5)
        if i < len(valor):
            pdf.set_xy(x + (i * caja), y + 0.4)
            pdf.set_font('Arial', 'B', 7)
            pdf.cell(caja - 0.8, 4, valor[i], 0, 0, 'C')


def separar_codigo_siniiga(arete):
    partes = str(arete or "").strip().upper().replace(" ", "").split("-")
    if len(partes) >= 3 and partes[0] == "MX":
        return {
            "pais": partes[0],
            "estado": partes[1].zfill(2)[:2],
            "numero": "".join(partes[2:]).replace("-", "")[:8],
        }

    digitos = "".join(ch for ch in str(arete or "") if ch.isdigit())
    if len(digitos) >= 10:
        return {"pais": "MX", "estado": digitos[:2], "numero": digitos[-8:]}

    return {"pais": "MX", "estado": "", "numero": digitos[-8:] if digitos else ""}


DISPOSITIVOS_REPOSICION = {
    "A": {"especie": "BOVINO", "codigo_especie": "BO", "dispositivo": "BOTON"},
    "B": {"especie": "BOVINO", "codigo_especie": "BO", "dispositivo": "BANDERA"},
    "C": {"especie": "BOVINO", "codigo_especie": "BO", "dispositivo": "RADIOFRECUENCIA"},
    "D": {"especie": "OVINO", "codigo_especie": "OV", "dispositivo": "BANDERA PEQ."},
    "E": {"especie": "OVINO", "codigo_especie": "OV", "dispositivo": "BANDERA GDE."},
    "F": {"especie": "OVINO", "codigo_especie": "OV", "dispositivo": "RADIOFRECUENCIA"},
    "G": {"especie": "CAPRINO", "codigo_especie": "CA", "dispositivo": "BANDERA PEQ."},
    "H": {"especie": "CAPRINO", "codigo_especie": "CA", "dispositivo": "GRAPA"},
    "I": {"especie": "CAPRINO", "codigo_especie": "CA", "dispositivo": "RADIOFRECUENCIA"},
    "J": {"especie": "COLMENAS", "codigo_especie": "CO", "dispositivo": "DISCO PEQ."},
    "K": {"especie": "COLMENAS", "codigo_especie": "CO", "dispositivo": "DISCO GDE."},
    "L": {"especie": "COLMENAS", "codigo_especie": "CO", "dispositivo": "TARJETAS"},
}


def obtener_datos_rearetado():
    datos = {"productor": None, "animales": [], "aretes": [], "predios": [], "estados": []}

    if "usuario" not in session:
        return datos

    conn, cursor = conectar_bd()
    if not conn or not cursor:
        return datos

    try:
        if session.get("rol") == "Productor" and session.get("fk_productor"):
            cursor.execute("""
                SELECT pr.pk_productor,
                       CONCAT_WS(' ', pr.nombre, pr.apellido_pat, pr.apellido_mat) AS nombre,
                       COALESCE(p.direccion, '') AS direccion,
                       COALESCE(p.upp, '') AS upp,
                       COALESCE(p.nom_rancho, '') AS rancho
                FROM Productores pr
                LEFT JOIN Predios p ON p.fk_productor = pr.pk_productor
                WHERE pr.pk_productor=%s
                ORDER BY p.pk_predio ASC
                LIMIT 1
            """, (session.get("fk_productor"),))
            datos["productor"] = cursor.fetchone()

            cursor.execute("""
                SELECT pk_predio, COALESCE(nom_rancho, ''), COALESCE(upp, ''),
                       COALESCE(direccion, ''), COALESCE(CAST(fk_estado AS TEXT), '')
                FROM Predios
                WHERE fk_productor=%s
                ORDER BY nom_rancho, pk_predio
            """, (session.get("fk_productor"),))
            datos["predios"] = cursor.fetchall()

            cursor.execute("""
                SELECT a.pk_animal, a.nombre, COALESCE(rs.arete, ''),
                       COALESCE(p.upp, ''), COALESCE(p.direccion, ''),
                       COALESCE(p.nom_rancho, ''), COALESCE(CAST(p.fk_estado AS TEXT), '')
                FROM Animales a
                LEFT JOIN Registro_SINIGA rs ON rs.fk_animal = a.pk_animal
                LEFT JOIN Predios p ON p.pk_predio = a.fk_predio
                WHERE a.fk_productor=%s
                ORDER BY a.nombre
            """, (session.get("fk_productor"),))
            datos["animales"] = cursor.fetchall()

            cursor.execute("""
                SELECT r.id, r.fk_animal, r.arete, a.nombre,
                       COALESCE(p.upp, ''), COALESCE(p.direccion, ''),
                       COALESCE(p.nom_rancho, ''), COALESCE(CAST(p.fk_estado AS TEXT), '')
                FROM Registro_SINIGA r
                INNER JOIN Animales a ON r.fk_animal = a.pk_animal
                LEFT JOIN Predios p ON p.pk_predio = a.fk_predio
                WHERE a.fk_productor=%s
                ORDER BY a.nombre, r.arete
            """, (session.get("fk_productor"),))
        else:
            cursor.execute("""
                SELECT a.pk_animal, a.nombre, COALESCE(rs.arete, ''),
                       COALESCE(p.upp, ''), COALESCE(p.direccion, ''),
                       COALESCE(p.nom_rancho, ''), COALESCE(CAST(p.fk_estado AS TEXT), '')
                FROM Animales a
                LEFT JOIN Registro_SINIGA rs ON rs.fk_animal = a.pk_animal
                LEFT JOIN Predios p ON p.pk_predio = a.fk_predio
                ORDER BY a.nombre
            """)
            datos["animales"] = cursor.fetchall()

            cursor.execute("""
                SELECT pk_predio, COALESCE(nom_rancho, ''), COALESCE(upp, ''),
                       COALESCE(direccion, ''), COALESCE(CAST(fk_estado AS TEXT), '')
                FROM Predios
                ORDER BY nom_rancho, pk_predio
            """)
            datos["predios"] = cursor.fetchall()

            cursor.execute("""
                SELECT r.id, r.fk_animal, r.arete, a.nombre,
                       COALESCE(p.upp, ''), COALESCE(p.direccion, ''),
                       COALESCE(p.nom_rancho, ''), COALESCE(CAST(p.fk_estado AS TEXT), '')
                FROM Registro_SINIGA r
                INNER JOIN Animales a ON r.fk_animal = a.pk_animal
                LEFT JOIN Predios p ON p.pk_predio = a.fk_predio
                ORDER BY a.nombre, r.arete
            """)

        datos["aretes"] = cursor.fetchall()

    except Exception:
        datos["animales"] = []
        datos["aretes"] = []

    try:
        cursor.execute("SELECT pk_estado, Nombre FROM Estados ORDER BY Nombre")
        estados = cursor.fetchall()
        datos["estados"] = [
            (estado[0], estado[1], str(estado[0]).zfill(2))
            for estado in estados
        ]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        datos["estados"] = []
    finally:
        conn.close()

    return datos

# 2. RUTA PARA MOSTRAR EL FORMULARIO
@app.route('/rearetado')
def rearetado():
    if "usuario" not in session:
        flash("Debes iniciar sesión", "warning")
        return redirect(url_for("login"))

    datos = obtener_datos_rearetado()
    return render_template(
        'rearetado.html',
        productor=datos["productor"],
        animales=datos["animales"],
        aretes=datos["aretes"],
        predios=datos["predios"],
        estados=datos["estados"],
        dispositivos_reposicion=DISPOSITIVOS_REPOSICION,
        fecha_actual=datetime.now().strftime('%Y-%m-%d')
    )

# 3. RUTA QUE GENERA EL PDF IDÉNTICO A TU IMAGEN
@app.route('/generar_pdf_rearetado', methods=['POST'])
def generar_pdf_rearetado():
    try:
        propietario = request.form.get('propietario', '')
        direccion = request.form.get('direccion', '')
        telefono = request.form.get('telefono', '')
        fecha = request.form.get('fecha')
        motivo_solicitud = request.form.get('motivo_solicitud', 'rearetado')
        causa = request.form.get('causa', '')
        upp = request.form.get('upp', '')
        psg = request.form.get('psg', '')
        clave_pg = request.form.get('clave_pg', '')
        clave_id = request.form.get('clave_id', 'A').upper()
        dispositivo_info = DISPOSITIVOS_REPOSICION.get(clave_id, DISPOSITIVOS_REPOSICION["A"])
        especie = dispositivo_info["especie"]
        especie_codigo = request.form.get('especie_codigo') or dispositivo_info["codigo_especie"]
        dispositivo = dispositivo_info["dispositivo"]
        cantidad = request.form.get('cantidad', '1')
        aretes_solicitados = [
            arete.strip()
            for arete in request.form.getlist('aretes_solicitados')
            if arete and arete.strip()
        ]
        arete_ant = request.form.get('arete_anterior', '')
        if not aretes_solicitados and arete_ant:
            aretes_solicitados = [arete_ant]
        estado_codigo = request.form.get('estado_codigo', '')
        numero_individual = request.form.get('numero_individual', '')
        codigo_arete = separar_codigo_siniiga(arete_ant)
        estado_codigo = estado_codigo or codigo_arete["estado"]
        numero_individual = numero_individual or codigo_arete["numero"]
        codigos_siniiga = []
        for arete in aretes_solicitados:
            codigo = separar_codigo_siniiga(arete)
            codigos_siniiga.append({
                "arete": arete,
                "estado": codigo["estado"] or estado_codigo,
                "numero": codigo["numero"] or numero_individual,
            })
        if not codigos_siniiga:
            codigos_siniiga.append({
                "arete": arete_ant,
                "estado": estado_codigo,
                "numero": numero_individual,
            })
        cantidad = str(len(codigos_siniiga) if len(codigos_siniiga) > 1 else (cantidad or 1))
        responsable = request.form.get('responsable', '').upper()
        observaciones = request.form.get('observaciones', '')

        # Formatear la fecha a dd/mm/aaaa si es posible
        try:
            fecha_obj = datetime.strptime(fecha, '%Y-%m-%d')
            fecha_fmt = fecha_obj.strftime('%d/%m/%Y')
        except:
            fecha_fmt = fecha

        # --- CREACIÓN DEL PDF ---
        pdf = PDFRearetado()
        pdf.add_page()

        y = 50
        dibujar_linea_dato(pdf, 12, y, "NOMBRE DEL PROPIETARIO:", propietario)
        dibujar_linea_dato(pdf, 12, y + 8, "DIRECCION:", direccion)
        dibujar_linea_dato(pdf, 12, y + 16, "TELEFONO:", telefono, 88)
        dibujar_linea_dato(pdf, 125, y + 16, "FECHA:", fecha_fmt, 72)

        y = 68
        pdf.set_xy(12, y)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(55, 6, 'MOTIVO DE LA SOLICITUD:', 0, 0)
        dibujar_checkbox(pdf, 78, y, "REPOSICION", motivo_solicitud == "reposicion")
        dibujar_checkbox(pdf, 118, y, "REARETADO (REIDENTIFICACION)", motivo_solicitud == "rearetado")

        pdf.set_xy(12, y + 10)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(55, 6, 'CAUSA:', 0, 0)
        dibujar_checkbox(pdf, 78, y + 10, "PERDIDA", causa == "perdida")
        dibujar_checkbox(pdf, 118, y + 10, "MAL FUNCIONAMIENTO", causa == "malfuncionamiento")
        dibujar_checkbox(pdf, 78, y + 18, "ROBO", causa == "robo")
        dibujar_checkbox(pdf, 118, y + 18, "DETERIORO", causa == "deterioro")

        y = 100
        pdf.set_font('Arial', 'B', 8)
        pdf.set_xy(12, y)
        pdf.cell(35, 6, 'CLAVE DE UPP:', 0, 0)
        dibujar_cajas_codigo(pdf, 48, y, upp, 12)
        pdf.set_xy(12, y + 9)
        pdf.cell(35, 6, 'CLAVE DE PSG:', 0, 0)
        dibujar_cajas_codigo(pdf, 48, y + 9, psg, 12)
        pdf.set_xy(12, y + 18)
        pdf.cell(35, 6, 'CLAVE DE PG:', 0, 0)
        dibujar_cajas_codigo(pdf, 48, y + 18, clave_pg, 9)
        pdf.set_xy(116, y + 18)
        pdf.cell(25, 6, 'PG1', 1, 0, 'C')

        y = 130
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(0, 6, 'SENALE CON UNA CRUZ EL DISPOSITIVO DE REPOSICION QUE NECESITE:', 0, 1)
        filas_dispositivo = [
            ("BOVINO", ["BOTON", "BANDERA", "RADIOFRECUENCIA"]),
            ("OVINO", ["BANDERA PEQ.", "BANDERA GDE.", "RADIOFRECUENCIA"]),
            ("CAPRINO", ["BANDERA PEQ.", "GRAPA", "RADIOFRECUENCIA"]),
            ("COLMENAS", ["DISCO PEQ.", "DISCO GDE.", "TARJETAS"]),
        ]
        for idx, (tipo, opciones) in enumerate(filas_dispositivo):
            row_y = y + 7 + (idx * 10)
            pdf.rect(12, row_y, 186, 9)
            pdf.set_xy(16, row_y + 1.6)
            pdf.set_font('Arial', 'B', 8)
            pdf.cell(30, 5, tipo, 0, 0)
            for opt_idx, opcion in enumerate(opciones):
                checked = especie == tipo and dispositivo == opcion
                dibujar_checkbox(pdf, 52 + (opt_idx * 47), row_y + 2.5, opcion, checked)

        pdf.set_xy(156, 170)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(22, 6, 'CANTIDAD:', 0, 0)
        pdf.set_font('Arial', '', 8)
        pdf.cell(18, 6, texto_pdf(cantidad), 1, 0, 'C')

        y = 178
        pdf.set_xy(12, y)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(0, 7, 'CODIGO DE IDENTIFICACION SINIIGA', 1, 1, 'C')
        pdf.set_font('Arial', 'B', 7)
        pdf.cell(28, 7, 'CLAVE DEL ID', 1, 0, 'C')
        pdf.cell(24, 7, 'ESPECIE', 1, 0, 'C')
        pdf.cell(24, 7, 'ESTADO', 1, 0, 'C')
        pdf.cell(110, 7, 'NUMERO DE IDENTIFICACION INDIVIDUAL DEL ANIMAL', 1, 1, 'C')
        pdf.set_font('Arial', '', 8)
        for i in range(6):
            codigo = codigos_siniiga[i] if i < len(codigos_siniiga) else None
            pdf.cell(28, 8, clave_id if codigo else "", 1, 0, 'C')
            pdf.cell(24, 8, especie_codigo if codigo else "", 1, 0, 'C')
            pdf.cell(24, 8, codigo["estado"] if codigo else "", 1, 0, 'C')
            pdf.cell(110, 8, texto_pdf(codigo["numero"] if codigo else ""), 1, 1)

        if observaciones:
            pdf.set_y(242)
            pdf.set_font('Arial', 'B', 8)
            pdf.cell(0, 5, 'OBSERVACIONES:', 0, 1)
            pdf.set_font('Arial', '', 8)
            pdf.multi_cell(0, 4, texto_pdf(observaciones))

        pdf.set_y(260)
        y_firmas = pdf.get_y()
        pdf.line(18, y_firmas, 82, y_firmas)
        pdf.set_xy(18, y_firmas + 2)
        pdf.set_font('Arial', '', 8)
        pdf.cell(64, 5, "FIRMA DEL PROPIETARIO", 0, 0, 'C')
        pdf.set_xy(18, y_firmas + 7)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(64, 5, texto_pdf(propietario.upper()), 0, 0, 'C')

        pdf.line(118, y_firmas, 182, y_firmas)
        pdf.set_xy(118, y_firmas + 2)
        pdf.set_font('Arial', '', 8)
        pdf.cell(64, 5, "FIRMA Y SELLO DEL PUNTO DE ATENCION", 0, 0, 'C')
        pdf.set_xy(118, y_firmas + 7)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(64, 5, texto_pdf(responsable), 0, 0, 'C')

        pdf_data = pdf.output(dest='S')
        # pdf.output puede devolver str, bytes o bytearray según la versión de fpdf
        if isinstance(pdf_data, bytearray):
            pdf_data = bytes(pdf_data)
        if isinstance(pdf_data, (bytes, memoryview)):
            response = make_response(pdf_data)
        else:
            response = make_response(pdf_data.encode('latin-1')) 
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=Solicitud_Rearetado_{arete_ant or numero_individual}.pdf'
        return response

    except Exception as e:
        return f"Error al generar PDF: {e}"
#--------------Blog donde se hablan de tipos de razas en tabasco-------
@app.route("/inventario")
def inventario():
    if "usuario" not in session:
        flash("Debes iniciar sesión", "warning")
        return redirect(url_for("login"))

    fecha_inicio = request.args.get("fecha_inicio") or ""
    fecha_fin = request.args.get("fecha_fin") or ""
    animales = []

    try:
        animales = obtener_animales_inventario(fecha_inicio, fecha_fin)
    except Exception as e:
        flash(f"Error al cargar el inventario: {e}", "danger")

    return render_template(
        "inventario.html",
        animales=animales,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
    )


def obtener_animales_inventario(fecha_inicio=None, fecha_fin=None):
    conn, cursor = conectar_bd()
    if not conn or not cursor:
        raise RuntimeError("No se pudo conectar a la base de datos")

    filtros = []
    params = []

    if session.get("rol") == "Productor":
        filtros.append("a.fk_productor=%s")
        params.append(session.get("fk_productor"))

    if fecha_inicio:
        filtros.append("a.fecha_nacimiento >= %s")
        params.append(fecha_inicio)

    if fecha_fin:
        filtros.append("a.fecha_nacimiento <= %s")
        params.append(fecha_fin)

    where_sql = f"WHERE {' AND '.join(filtros)}" if filtros else ""

    try:
        cursor.execute(f"""
            SELECT a.pk_animal, a.nombre, a.fecha_nacimiento, a.cruze,
                   p.nombre AS productor, pr.nom_rancho AS predio,
                   r.nombre AS raza, m.nombre AS madre, a.sexo,
                   a.peso_actual, rs.arete,
                   COALESCE(a.estatus, 'Activo') AS estado_animal
            FROM Animales a
            LEFT JOIN Productores p ON a.fk_productor=p.pk_productor
            LEFT JOIN Razas r ON a.fk_raza=r.pk_raza
            LEFT JOIN Predios pr ON a.fk_predio=pr.pk_predio
            LEFT JOIN Animales m ON a.fk_animal=m.pk_animal
            LEFT JOIN Registro_SINIGA rs ON rs.fk_animal=a.pk_animal
            {where_sql}
            ORDER BY a.fecha_nacimiento DESC, a.pk_animal DESC
        """, tuple(params))
        return cursor.fetchall()
    finally:
        conn.close()


@app.route("/inventario/descargar")
def descargar_inventario():
    if "usuario" not in session:
        flash("Debes iniciar sesión", "warning")
        return redirect(url_for("login"))

    fecha_inicio = request.args.get("fecha_inicio") or ""
    fecha_fin = request.args.get("fecha_fin") or ""

    try:
        animales = obtener_animales_inventario(fecha_inicio, fecha_fin)
    except Exception as e:
        flash(f"No se pudo generar el inventario: {e}", "danger")
        return redirect(url_for("inventario", fecha_inicio=fecha_inicio, fecha_fin=fecha_fin))

    salida = io.StringIO()
    writer = csv.writer(salida)
    writer.writerow([
        "ID", "Nombre", "Fecha de nacimiento", "Cruze", "Productor",
        "Predio", "Raza", "Madre", "Sexo", "Peso actual", "Arete", "Estado"
    ])

    for animal in animales:
        writer.writerow([campo if campo is not None else "" for campo in animal])

    response = make_response(salida.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=inventario_animales.csv"
    return response

@app.route("/album_razas")
def album_razas():
    return render_template("album_razas.html")

@app.route("/tabla_precio")
def tabla_precio():
    return render_template("tabla_precio.html")

@app.route("/opiniones")
def opiniones():
    return render_template("opiniones.html")
#---------------------------------------------------------------------------------------++

# ---------------- PDF ANIMAL ----------------
bp = Blueprint('pdf', __name__)

@bp.route("/pdf_animal")
def pdf_animal():
    animal_id = (request.args.get("animal_id") or "").strip()
    animal_busqueda = (request.args.get("animal") or request.args.get("arete") or "").strip()

    if not animal_id and not animal_busqueda:
        return "Selecciona o ingresa el animal", 400

    conn = None
    cursor = None

    try:
        conn, cursor = conectar_bd(dictionary=True)
        if not conn:
            return "Error al conectar a la base de datos", 500

        cursor.execute(
            """
            SELECT
                r.arete,
                a.nombre,
                a.sexo,
                a.cruze,
                a.peso_actual,
                pr.nombre AS productor,
                p.UPP,
                pr.RFC,
                p.nom_rancho,
                p.direccion,
                e.Nombre AS estado,
                m.Nombre AS municipio,
                a.foto_perfil,
                a.foto_lateral
            FROM Animales a
            LEFT JOIN Registro_SINIGA r ON r.fk_animal = a.pk_animal
            LEFT JOIN Predios p ON p.pk_predio = a.fk_predio
            LEFT JOIN Productores pr ON pr.pk_productor = a.fk_productor
            LEFT JOIN Estados e ON e.pk_estado = p.fk_estado
            LEFT JOIN Municipios m ON m.pk_municipio = p.fk_municipio
            WHERE a.pk_animal = %s OR r.arete = %s OR LOWER(a.nombre) = LOWER(%s)
            ORDER BY
                CASE
                    WHEN a.pk_animal = %s THEN 0
                    WHEN r.arete = %s THEN 0
                    WHEN LOWER(a.nombre) = LOWER(%s) THEN 1
                    ELSE 2
                END,
                a.pk_animal DESC
            LIMIT 1
            """,
            (animal_id or None, animal_busqueda, animal_busqueda, animal_id or None, animal_busqueda, animal_busqueda)
        )
        animal = cursor.fetchone()

        if not animal:
            return "Animal no encontrado", 404

        return generar_pdf_animal(animal)

    except Exception as e:
        return f"Error al generar PDF: {e}", 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def generar_pdf_animal(animal):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    page_width, page_height = letter

    c.setTitle("Datos del Animal")
    margen_x = 45
    y = page_height - 54

    c.setFont("Times-Bold", 24)
    c.drawCentredString(page_width / 2, y, "DATOS DEL ANIMAL")
    y -= 14
    c.setLineWidth(1.2)
    c.line(margen_x, y, page_width - margen_x, y)
    y -= 34

    campos = [
        ("Arete", animal.get("arete")),
        ("Nombre", animal.get("nombre")),
        ("Sexo", animal.get("sexo")),
        ("Cruza", animal.get("cruze")),
        ("Peso actual", animal.get("peso_actual")),
        ("Productor", animal.get("productor")),
        ("UPP", animal.get("UPP")),
        ("RFC", animal.get("RFC")),
        ("Predio", animal.get("nom_rancho")),
        ("Dirección", animal.get("direccion")),
        ("Estado", animal.get("estado")),
        ("Municipio", animal.get("municipio"))
    ]

    c.setFont("Times-Bold", 16)
    c.drawString(margen_x, y, "Información general")
    y -= 28

    for campo, valor in campos:
        valor_texto = str(valor) if valor not in (None, "") else "---"
        c.setFont("Times-Bold", 13)
        c.drawString(margen_x, y, f"{campo}:")
        c.setFont("Times-Roman", 13)
        c.drawString(margen_x + 105, y, valor_texto[:58])
        y -= 24

    def dibujar_foto(imagen_bytes, titulo, x, y_img, ancho=215, alto=175):
        if not imagen_bytes:
            return
        try:
            imagen = Image.open(io.BytesIO(imagen_bytes))
            imagen.thumbnail((ancho, alto))
            reader = ImageReader(imagen)
            img_w, img_h = imagen.size
            x_centrada = x + (ancho - img_w) / 2
            y_centrada = y_img + (alto - img_h) / 2

            c.setFont("Times-Bold", 14)
            c.drawCentredString(x + ancho / 2, y_img + alto + 12, titulo)
            c.roundRect(x, y_img, ancho, alto, 8, stroke=1, fill=0)
            c.drawImage(reader, x_centrada, y_centrada, width=img_w, height=img_h)
        except Exception:
            c.setFont("Times-Roman", 12)
            c.drawString(x, y_img + alto / 2, f"{titulo}: imagen no disponible")

    # Imagen perfil
    dibujar_foto(animal.get("foto_perfil"), "Foto de perfil", 355, 500)

    # Imagen lateral
    dibujar_foto(animal.get("foto_lateral"), "Foto lateral", 355, 275)

    c.setLineWidth(0.7)
    c.line(margen_x, 58, page_width - margen_x, 58)
    c.setFont("Times-Italic", 11)
    c.drawCentredString(page_width / 2, 40, "MiGanadito Control - Ficha de identificación animal")

    c.showPage()
    c.save()
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="datos_animal.pdf"
    )


app.register_blueprint(bp)

@app.route('/login_as')
def login_as():
    # Ruta temporal de prueba: crea sesión de Veterinario y redirige al dashboard_vet
    session.clear()
    session['id_usuario'] = 8
    session['usuario'] = 'test_vet'
    session['rol'] = 'Veterinario'
    session['fk_productor'] = None
    flash('Sesión creada como Veterinario de prueba (test_vet)', 'info')
    return redirect(url_for('dashboard_vet'))


# -------------------- PROGRAMA PRINCIPAL --------------------
if __name__ == "__main__":
    app.run(debug=app.config["FLASK_DEBUG"])
