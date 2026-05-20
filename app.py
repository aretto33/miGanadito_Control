from flask import (
    Flask, render_template, request, redirect, url_for, abort,
    session, flash, Response, send_from_directory,
    send_file, make_response, Blueprint
)
from fpdf import FPDF
from datetime import datetime
import io
import csv
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from PIL import Image
import os

from ganacontrol.config import Config
from ganacontrol.db_compat import db as mariadb
from ganacontrol.db import get_connection


app = Flask(__name__, static_folder="public", static_url_path="")
app.config.from_object(Config)
ROLES_VALIDOS = {"Productor", "Veterinario", "Comprador"}
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
    }
    return roles.get(rol.strip().lower())


def verificar_credenciales(usuario, password, rol_nombre):
    conn, cursor = conectar_bd()
    if not conn:
        return False, "Error de conexión"

    try:
        # Esquema legado: Usuarios + Rol
        try:
            cursor.execute("""
                SELECT u.id_usuario, u.usuario, u.password, r.nombre
                FROM Usuarios u
                JOIN Rol r ON r.id_rol = u.fk_rol
                WHERE u.usuario=%s AND r.nombre=%s
            """, (usuario, rol_nombre))
            row = cursor.fetchone()
        except mariadb.Error:
            conn.rollback()
            row = None

        if row:
            id_usuario, db_user, db_pass, db_rol = row
            if db_pass != password:
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

            return True, {"id_usuario": id_usuario, "rol": db_rol, "fk_productor": fk_productor}

        # Esquema nuevo: usuarios con columna rol y fk_productor
        cursor.execute("""
            SELECT id_usuario, usuario, password, rol, fk_productor
            FROM usuarios
            WHERE usuario=%s AND rol=%s
        """, (usuario, rol_nombre))
        row = cursor.fetchone()
        if not row:
            return False, "Usuario o rol no encontrado"

        id_usuario, db_user, db_pass, db_rol, fk_productor = row
        if db_pass != password:
            return False, "Contraseña incorrecta"

        return True, {"id_usuario": id_usuario, "rol": db_rol, "fk_productor": fk_productor}

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
            usuario = request.form["usuario"]
            contra = request.form["password"]
            rol = normalizar_rol(request.form.get("rol")) or "Productor"
            if rol not in ROLES_VALIDOS:
                flash("Rol inválido", "danger")
                return redirect(url_for("login"))

            exito, info = verificar_credenciales(usuario, contra, rol)

            if exito:
                session["usuario"] = usuario
                session["rol"] = rol
                session.pop("fk_productor", None)

                if isinstance(info, dict) and info.get("fk_productor"):
                    session["fk_productor"] = info.get("fk_productor")

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
        contra = request.form.get("password", "").strip()
        rol_nombre = normalizar_rol(request.form.get("rol")) or "Productor"

        # Validación básica
        if not usuario or not contra or not rol_nombre:
            flash("Todos los campos son obligatorios", "danger")
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

            # Insertar usuario - SIN commit aún
            cursor.execute("""
                INSERT INTO Usuarios (usuario, password, fk_rol)
                VALUES (%s, %s, %s)
                RETURNING id_usuario
            """, (usuario, contra, fk_rol))

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
    total_animales = 0
    total_predios = 0
    view = None

    fk_productor = session.get("fk_productor")
    rol = session.get("rol")

    # =========================
    # DEFINIR VIEW SEGÚN ROL
    # =========================
    if rol == "Veterinario":
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

        if fk_productor:
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
                    COALESCE((
                        SELECT t.impacto
                        FROM Seguimiento_vet s
                        JOIN tratamientos t ON t.pk_tratamiento = s.fk_tratamiento
                        WHERE s.fk_animal = a.pk_animal
                        ORDER BY s.fecha_actual DESC, s.pk_segui_vet DESC
                        LIMIT 1
                    ), 'Sin estatus') AS estatus_actual
                FROM Animales a
                WHERE a.fk_productor = %s
                ORDER BY a.nombre
            """, (fk_productor,))
            estados_animales = cursor.fetchall()
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
        estados_animales=estados_animales
    )

@app.route("/dashboard_vet")
def dashboard_vet():
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
        view="veterinario"
    )

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

    conn = None
    cursor = None

    try:
        conn, cursor = conectar_bd()

        # ================= POST =================
        if request.method == "POST":
            accion = request.form.get("accion")

            foto_perfil = request.files.get("foto_perfil")
            foto_lateral = request.files.get("foto_lateral")

            perfil_bytes = foto_perfil.read() if foto_perfil and foto_perfil.filename else None
            lateral_bytes = foto_lateral.read() if foto_lateral and foto_lateral.filename else None

            fk_prod_session = session.get("fk_productor") if session.get("rol") == "Productor" else None

            # -------- REGISTRAR --------
            if accion == "registrar":
                cursor.execute("""
                    INSERT INTO Animales
                    (nombre, fecha_nacimiento, cruze, sexo, peso_actual,
                     fk_productor, fk_raza, fk_predio, fk_animal, foto_perfil, foto_lateral)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    request.form.get("nombre"),
                    request.form.get("fecha"),
                    request.form.get("cruze") or "Sin conocer",
                    request.form.get("sexo"),
                    request.form.get("peso_actual"),
                    fk_prod_session or request.form.get("fk_productor"),
                    request.form.get("fk_raza"),
                    request.form.get("fk_predio"),
                    request.form.get("fk_madre") or None,
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
                        'fk_madre': 'fk_animal'
                    }

                    for form_key, col_name in field_map.items():
                        if form_key in request.form:
                            val = request.form.get(form_key) or None
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
                       COALESCE((
                           SELECT t.impacto
                           FROM Seguimiento_vet s
                           JOIN tratamientos t ON t.pk_tratamiento = s.fk_tratamiento
                           WHERE s.fk_animal = a.pk_animal
                           ORDER BY s.fecha_actual DESC, s.pk_segui_vet DESC
                           LIMIT 1
                       ), 'Sin estatus') AS estatus_actual,
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
        else:
            cursor.execute("""
                SELECT a.pk_animal, a.nombre, a.fecha_nacimiento, a.cruze,
                       p.nombre, r.nombre, a.sexo, a.peso_actual,
                       pr.nom_rancho,
                       rs.arete,
                       COALESCE((
                           SELECT t.impacto
                           FROM Seguimiento_vet s
                           JOIN tratamientos t ON t.pk_tratamiento = s.fk_tratamiento
                           WHERE s.fk_animal = a.pk_animal
                           ORDER BY s.fecha_actual DESC, s.pk_segui_vet DESC
                           LIMIT 1
                       ), 'Sin estatus') AS estatus_actual,
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

        cursor.execute("SELECT pk_productor, nombre FROM Productores")
        productores = cursor.fetchall()

        cursor.execute("SELECT pk_raza, nombre FROM Razas")
        razas = cursor.fetchall()

        cursor.execute("SELECT pk_predio, nom_rancho FROM Predios ORDER BY nom_rancho")
        predios = cursor.fetchall()

        if session.get("rol") == "Productor":
            cursor.execute("SELECT pk_animal, nombre FROM Animales WHERE sexo='H' AND fk_productor=%s ORDER BY nombre", (session.get("fk_productor"),))
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

    if "fk_productor" not in session:
        flash("Inicia sesión para acceder a Predios.", "warning")
        return redirect(url_for("login"))

    fk_productor = session["fk_productor"]

    conn, cursor = conectar_bd()

    # --------------------
    # Obtener productores
    # --------------------
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

            sql = """
                UPDATE Predios
                SET direccion=%s, fk_estado=%s, fk_municipio=%s, fk_productor=%s, nom_rancho=%s, upp=%s
                WHERE pk_predio=%s
            """
            cursor.execute(sql, (direccion, fk_estado, fk_municipio, fk_prod, nom_rancho, upp, pk))
            conn.commit()

        elif accion == "eliminar":
            pk = request.form.get("pk")
            cursor.execute("DELETE FROM Predios WHERE pk_predio=%s", (pk,))
            conn.commit()

        return redirect(url_for("predios"))

    # --------------------
    # GET
    # --------------------
    # Seleccionar nombres de estado y municipio a través de JOINs
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
    cursor.execute("""
        SELECT pk_productor, nombre, apellido_pat, apellido_mat, RFC
        FROM Productores
        WHERE pk_productor=%s
    """, (fk_productor,))

    productor = cursor.fetchone()
    conn.close()

    return render_template("mi_productor.html", productor=productor)

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

        # ===================== POST =====================
        if request.method == "POST":
            accion = request.form.get("accion")

            # ===== REGISTRAR =====
            if accion == "registrar":
                pesaje_val = request.form.get("pesaje")
                fecha = request.form.get("fecha")
                fk_animal = request.form.get("fk_animal") or None

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
        pesajes = cursor.fetchall()

        # ---- ANIMALES PARA EL SELECT (FILTRADOS POR PRODUCTOR) ----
        if session.get("rol") == "Productor":
            cursor.execute("""
                SELECT pk_animal, nombre
                FROM Animales
                WHERE fk_productor = %s
            """, (session.get("fk_productor"),))
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

    if "fk_productor" not in session:
        return redirect(url_for("login"))

    fk_productor = session["fk_productor"]

    conn, cursor = conectar_bd()

    # ----- REGISTRAR -----
# ----- REGISTRAR -----
    if request.method == "POST" and request.form.get("accion") == "registrar":
        fk_animal = request.form["fk_animal"]
        arete = request.form["arete"]

        try:
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
            cursor.execute("""
                UPDATE Registro_SINIGA r
                INNER JOIN Animales a ON r.fk_animal = a.pk_animal
                SET r.fk_animal = %s, r.arete = %s
                WHERE r.id = %s AND a.fk_productor = %s
            """, (fk_animal, arete, pk, fk_productor))
            conn.commit()
            flash("Registro SIINIGA modificado correctamente.", "success")

    # ----- ELIMINAR -----
    elif request.method == "POST" and request.form.get("accion") == "eliminar":
        pk = request.form["pk"]

        cursor.execute("""
            DELETE r FROM Registro_SINIGA r
            INNER JOIN Animales a ON r.fk_animal = a.pk_animal
            WHERE r.id = %s AND a.fk_productor = %s
        """, (pk, fk_productor))
        conn.commit()

    # ----- CONSULTAR (SOLO DEL PRODUCTOR) -----
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

        # ===== POST =====
        if request.method == "POST":
            accion = request.form.get("accion")
            pk = request.form.get("pk")
            fk_animal = request.form.get("fk_animal")
            fk_tratamiento = request.form.get("fk_tratamiento")
            medicamento = request.form.get("medicamento")
            fecha_actual = request.form.get("fecha_actual")
            prox_fecha = request.form.get("prox_fecha")

            if accion == "registrar":
                cursor.execute("""
                    INSERT INTO Seguimiento_vet
                    (fk_animal, fk_tratamiento, medicamento, fecha_actual, prox_fecha)
                    VALUES (%s,%s,%s,%s,%s)
                """, (fk_animal, fk_tratamiento, medicamento, fecha_actual, prox_fecha))
                conn.commit()
                flash("Seguimiento registrado", "success")

            elif accion == "modificar":
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
                cursor.execute(
                    "DELETE FROM Seguimiento_vet WHERE pk_segui_vet=%s",
                    (pk,)
                )
                conn.commit()
                flash("Seguimiento eliminado", "danger")

        # ===== LISTADO SEGUIMIENTOS =====
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
            """, (session.get("fk_productor"),))
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

        return render_template(
            "seguimiento.html",
            seguimientos=seguimientos,
            animales=animales,
            tratamientos=tratamientos
        )

    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Error: {e}", "danger")
        return redirect(url_for("seguimiento"))

    finally:
        if cursor: cursor.close()
        if conn: conn.close()



#------------------------------------------------------------------------------------------

# ----------------------VENTAS ---------------------------------------------
@app.route("/ventas", methods=["GET", "POST"])
def ventas():
    conn = None
    cursor = None

    try:
        conn, cursor = conectar_bd()

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

                cursor.execute("""
                    INSERT INTO Ventas (fk_animal, fk_pesaje, clave, precio, fecha_venta)
                    VALUES (%s, %s, %s, %s, %s)
                """, (fk_animal, fk_pesaje, clave, precio, fecha_venta))
                conn.commit()
                flash("Venta registrada correctamente", "success")

            # MODIFICAR
            elif accion == "modificar":
                pk = request.form.get("pk")
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

                cursor.execute("""
                    UPDATE Ventas
                    SET fk_animal=%s, fk_pesaje=%s, clave=%s, precio=%s, fecha_venta=%s
                    WHERE pk_venta=%s
                """, (fk_animal, fk_pesaje, clave, precio, fecha_venta, pk))
                conn.commit()
                flash("Venta modificada correctamente", "info")

            # ELIMINAR
            elif accion == "eliminar":
                pk = request.form.get("pk")
                cursor.execute("DELETE FROM Ventas WHERE pk_venta=%s", (pk,))
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


def obtener_datos_rearetado():
    datos = {"productor": None, "animales": [], "predios": []}

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
                SELECT a.pk_animal, a.nombre, COALESCE(rs.arete, ''),
                       COALESCE(p.upp, ''), COALESCE(p.direccion, ''),
                       COALESCE(p.nom_rancho, '')
                FROM Animales a
                LEFT JOIN Registro_SINIGA rs ON rs.fk_animal = a.pk_animal
                LEFT JOIN Predios p ON p.pk_predio = a.fk_predio
                WHERE a.fk_productor=%s
                ORDER BY a.nombre
            """, (session.get("fk_productor"),))
        else:
            cursor.execute("""
                SELECT a.pk_animal, a.nombre, COALESCE(rs.arete, ''),
                       COALESCE(p.upp, ''), COALESCE(p.direccion, ''),
                       COALESCE(p.nom_rancho, '')
                FROM Animales a
                LEFT JOIN Registro_SINIGA rs ON rs.fk_animal = a.pk_animal
                LEFT JOIN Predios p ON p.pk_predio = a.fk_predio
                ORDER BY a.nombre
            """)

        datos["animales"] = cursor.fetchall()
    except Exception:
        datos["animales"] = []
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
        especie = request.form.get('especie', 'BOVINO')
        dispositivo = request.form.get('dispositivo', 'BOTON')
        cantidad = request.form.get('cantidad', '1')
        arete_ant = request.form.get('arete_anterior', '')
        arete_nue = request.form.get('arete_nuevo', '')
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
        pdf.cell(28, 7, 'CLAVE DISTR.', 1, 0, 'C')
        pdf.cell(24, 7, 'ESPECIE', 1, 0, 'C')
        pdf.cell(24, 7, 'ESTADO', 1, 0, 'C')
        pdf.cell(110, 7, 'NUMERO DE IDENTIFICACION INDIVIDUAL DEL ANIMAL', 1, 1, 'C')
        pdf.set_font('Arial', '', 8)
        for i in range(6):
            valor_arete = arete_nue if i == 0 else ""
            pdf.cell(28, 8, "", 1, 0)
            pdf.cell(24, 8, especie if i == 0 else "", 1, 0, 'C')
            pdf.cell(24, 8, "", 1, 0)
            pdf.cell(110, 8, texto_pdf(valor_arete), 1, 1)

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
        response.headers['Content-Disposition'] = f'inline; filename=Solicitud_Rearetado_{arete_nue or arete_ant}.pdf'
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
                   CASE
                       WHEN EXISTS (
                           SELECT 1
                           FROM Ventas v
                           WHERE v.fk_animal = a.pk_animal
                       ) THEN 'VENDIDO'
                       ELSE 'ACTIVO (VIVO)'
                   END AS estado_animal
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

    y = 750
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "DATOS DEL ANIMAL")
    y -= 30

    c.setFont("Helvetica", 10)

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

    for campo, valor in campos:
        c.drawString(50, y, f"{campo}: {valor if valor else '---'}")
        y -= 15

    # Imagen perfil
    if animal.get("foto_perfil"):
        img = Image.open(io.BytesIO(animal["foto_perfil"]))
        img_path = "/tmp/perfil.png"
        img.save(img_path)
        c.drawImage(img_path, 380, 600, width=150, height=150)

    # Imagen lateral
    if animal.get("foto_lateral"):
        img = Image.open(io.BytesIO(animal["foto_lateral"]))
        img_path = "/tmp/lateral.png"
        img.save(img_path)
        c.drawImage(img_path, 380, 420, width=150, height=150)

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
