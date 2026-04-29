from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, Response, send_from_directory,
    send_file, make_response, Blueprint
)
from fpdf import FPDF
from datetime import datetime
import io
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


@app.route('/static/<path:filename>')
def legacy_static(filename):
    # Compatibilidad con rutas antiguas /static/... ahora que Vercel sirve public/ desde la raiz.
    return redirect(url_for('static', filename=filename), code=307)

def conectar_bd(dictionary=False):
    return get_connection(dictionary=dictionary)

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
            rol = normalizar_rol(request.form.get("rol"))
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
        usuario = request.form["usuario"]
        contra = request.form["password"]
        rol_nombre = normalizar_rol(request.form.get("rol"))
        if rol_nombre not in ROLES_VALIDOS:
            flash("Rol inválido", "danger")
            return redirect(url_for("register"))

        conn, cursor = conectar_bd()
        if not conn:
            flash("Error al conectar con la base de datos", "danger")
            return redirect(url_for("register"))

        try:
            try:
                # Esquema legado
                cursor.execute("SELECT id_rol FROM Rol WHERE nombre=%s", (rol_nombre,))
                row = cursor.fetchone()
                if not row:
                    raise mariadb.Error("Rol no encontrado en tabla Rol")
                fk_rol = row[0]

                cursor.execute("""
                    INSERT INTO Usuarios (usuario, password, fk_rol)
                    VALUES (%s, %s, %s)
                """, (usuario, contra, fk_rol))
                conn.commit()
                id_usuario = cursor.lastrowid

                if rol_nombre == "Productor":
                    cursor.execute("""
                        INSERT INTO Productores (fk_usuario, nombre, apellido_pat, apellido_mat, RFC)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        id_usuario,
                        request.form.get("prod_nombre"),
                        request.form.get("prod_apellido_pat"),
                        request.form.get("prod_apellido_mat"),
                        request.form.get("prod_rfc")
                    ))
                    conn.commit()

                elif rol_nombre == "Veterinario":
                    cursor.execute("""
                        INSERT INTO Veterinario (fk_usuario, nombre, apellidos, cedula, direccion_consultorio, telefono)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        id_usuario,
                        request.form.get("vet_nombre"),
                        request.form.get("vet_apellidos"),
                        request.form.get("vet_cedula"),
                        request.form.get("vet_direccion") or "Consultas a domicilio",
                        request.form.get("vet_telefono")
                    ))
                    conn.commit()
            except mariadb.Error:
                conn.rollback()
                # Esquema nuevo
                prod_id = None
                if rol_nombre == "Productor":
                    cursor.execute("""
                        INSERT INTO Productores (nombre, apellido_pat, apellido_mat, UPP)
                        VALUES (%s, %s, %s, 'No inscrito')
                    """, (
                        request.form.get("prod_nombre"),
                        request.form.get("prod_apellido_pat"),
                        request.form.get("prod_apellido_mat"),
                    ))
                    conn.commit()
                    prod_id = cursor.lastrowid

                cursor.execute("""
                    INSERT INTO usuarios (usuario, password, rol, fk_productor)
                    VALUES (%s, %s, %s, %s)
                """, (usuario, contra, rol_nombre, prod_id))
                conn.commit()

            flash("Usuario registrado correctamente", "success")
            return redirect(url_for("login"))

        except mariadb.Error as e:
            flash(f"No se pudo registrar: {e}", "danger")
        finally:
            conn.close()

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
                SELECT r.arete, a.nombre
                FROM Registro_SINIGA r
                INNER JOIN Animales a ON r.fk_animal = a.pk_animal
                WHERE a.fk_productor = %s
                ORDER BY r.arete
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
                SELECT nombre, 'Sin estatus' AS estatus_actual
                FROM Animales
                WHERE fk_productor = %s
                ORDER BY nombre
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
            foto_arete = request.files.get("foto_arete")

            perfil_bytes = foto_perfil.read() if foto_perfil and foto_perfil.filename else None
            lateral_bytes = foto_lateral.read() if foto_lateral and foto_lateral.filename else None
            arete_bytes = foto_arete.read() if foto_arete and foto_arete.filename else None

            fk_prod_session = session.get("fk_productor") if session.get("rol") == "Productor" else None

            # -------- REGISTRAR --------
            if accion == "registrar":
                cursor.execute("""
                    INSERT INTO Animales
                    (nombre, fecha_nacimiento, cruze, sexo, peso_actual,
                     fk_productor, fk_raza, fk_predio, foto_perfil, foto_lateral, foto_arete)
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
                    perfil_bytes,
                    lateral_bytes,
                    arete_bytes
                ))
                conn.commit()

            # -------- MODIFICAR --------
            elif accion == "modificar":
                pk = request.form.get("pk")
                cursor.execute("""
                    UPDATE Animales SET
                        nombre=%s,
                        fecha_nacimiento=%s,
                        cruze=%s,
                        sexo=%s,
                        peso_actual=%s,
                        fk_productor=%s,
                        fk_raza=%s,
                        fk_predio=%s
                    WHERE pk_animal=%s
                """, (
                    request.form.get("nombre"),
                    request.form.get("fecha"),
                    request.form.get("cruze"),
                    request.form.get("sexo"),
                    request.form.get("peso_actual"),
                    fk_prod_session or request.form.get("fk_productor"),
                    request.form.get("fk_raza"),
                    request.form.get("fk_predio"),
                    pk
                ))

                if perfil_bytes:
                    cursor.execute("UPDATE Animales SET foto_perfil=%s WHERE pk_animal=%s", (perfil_bytes, pk))
                if lateral_bytes:
                    cursor.execute("UPDATE Animales SET foto_lateral=%s WHERE pk_animal=%s", (lateral_bytes, pk))
                if arete_bytes:
                    cursor.execute("UPDATE Animales SET foto_arete=%s WHERE pk_animal=%s", (arete_bytes, pk))

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
                       'Sin estatus' AS estatus_actual,
                       a.fk_predio, r.pk_raza, a.fk_productor
                FROM Animales a
                LEFT JOIN Productores p ON a.fk_productor=p.pk_productor
                LEFT JOIN Razas r ON a.fk_raza=r.pk_raza
                LEFT JOIN Predios pr ON a.fk_predio=pr.pk_predio
                WHERE a.fk_productor=%s
                ORDER BY a.pk_animal DESC
            """, (session.get("fk_productor"),))
        else:
            cursor.execute("""
                SELECT a.pk_animal, a.nombre, a.fecha_nacimiento, a.cruze,
                       p.nombre, r.nombre, a.sexo, a.peso_actual,
                       pr.nom_rancho,
                       'Sin estatus' AS estatus_actual,
                       a.fk_predio, r.pk_raza, a.fk_productor
                FROM Animales a
                LEFT JOIN Productores p ON a.fk_productor=p.pk_productor
                LEFT JOIN Razas r ON a.fk_raza=r.pk_raza
                LEFT JOIN Predios pr ON a.fk_predio=pr.pk_predio
                ORDER BY a.pk_animal DESC
            """)

        animales = cursor.fetchall()

        cursor.execute("SELECT pk_productor, nombre FROM Productores")
        productores = cursor.fetchall()

        cursor.execute("SELECT pk_raza, nombre FROM Razas")
        razas = cursor.fetchall()

        cursor.execute("SELECT pk_predio, nom_rancho FROM Predios ORDER BY nom_rancho")
        predios = cursor.fetchall()

        cursor.execute("""
            SELECT pk_tratamiento, nombre, impacto
            FROM tratamientos
            ORDER BY nombre
        """)
        tratamientos = cursor.fetchall()

    except Exception as e:
        flash(f"Error en Animales: {e}", "danger")
        animales, productores, razas, predios, tratamientos = [], [], [], [], []

    finally:
        if conn:
            conn.close()

    return render_template(
        "animales.html",
        animales=animales,
        productores=productores,
        razas=razas,
        predios=predios,
        tratamientos=tratamientos
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
            # Determinar fk_productor: si el usuario es Productor usar la sesión
            if session.get('rol') == 'Productor' and session.get('fk_productor'):
                fk_prod = session.get('fk_productor')
            else:
                fk_prod = request.form.get("fk_productor")  # 👈 nuevo

            sql = """
                INSERT INTO Predios (direccion, fk_estado, fk_municipio, fk_productor, nom_rancho)
                VALUES (%s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (direccion, fk_estado, fk_municipio, fk_prod, nom_rancho))
            conn.commit()

        elif accion == "modificar":
            pk = request.form.get("pk")
            direccion = request.form.get("direccion")
            fk_estado = request.form.get("fk_estado")
            fk_municipio = request.form.get("fk_municipio")
            nom_rancho = request.form.get("nom_rancho")
            # Determinar fk_productor: si el usuario es Productor usar la sesión
            if session.get('rol') == 'Productor' and session.get('fk_productor'):
                fk_prod = session.get('fk_productor')
            else:
                fk_prod = request.form.get("fk_productor")

            sql = """
                UPDATE Predios
                SET direccion=%s, fk_estado=%s, fk_municipio=%s, fk_productor=%s, nom_rancho=%s
                WHERE pk_predio=%s
            """
            cursor.execute(sql, (direccion, fk_estado, fk_municipio, fk_prod, nom_rancho, pk))
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
               e.Nombre AS estado, m.Nombre AS municipio, p.fk_productor, pr.nombre AS productor, p.nom_rancho
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
        # Título principal centrado
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'CONTROL GANADERO - REPORTE DE INCIDENCIA', 0, 1, 'C')
        
        # Subtítulo itálica
        self.set_font('Arial', 'I', 10)
        self.cell(0, 5, 'Departamento de Control Sanitario e Identificación', 0, 1, 'C')
        self.ln(20) # Espacio después del encabezado

    def footer(self):
        # Pie de página simple
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'R')

# 2. RUTA PARA MOSTRAR EL FORMULARIO
@app.route('/rearetado')
def rearetado():
    return render_template('rearetado.html')

# 3. RUTA QUE GENERA EL PDF IDÉNTICO A TU IMAGEN
@app.route('/generar_pdf_rearetado', methods=['POST'])
def generar_pdf_rearetado():
    try:
        # Obtener datos del formulario
        arete_ant = request.form.get('arete_anterior', '---')
        arete_nue = request.form.get('arete_nuevo', '---')
        motivo = request.form.get('motivo', '---')
        responsable = request.form.get('responsable', '').upper()
        fecha = request.form.get('fecha')

        # Formatear la fecha a dd/mm/aaaa si es posible
        try:
            fecha_obj = datetime.strptime(fecha, '%Y-%m-%d')
            fecha_fmt = fecha_obj.strftime('%d/%m/%Y')
        except:
            fecha_fmt = fecha

        # --- CREACIÓN DEL PDF ---
        pdf = PDFRearetado()
        pdf.add_page()
        
        # Título del Acta
        pdf.ln(5)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, 'ACTA DE RE-ARETADO / CAMBIO DE IDENTIFICADOR', 0, 1, 'C')
        pdf.ln(10)

        # Fecha alineada a la derecha
        pdf.set_font('Arial', '', 11)
        pdf.cell(0, 10, f'Fecha del suceso: {fecha_fmt}', 0, 1, 'R')
        pdf.ln(5)

        # Párrafo introductorio
        texto_intro = "Por medio de la presente se hace constar el cambio de identificación oficial del animal, debido a una incidencia reportada en el sistema."
        # Decodificar caracteres latinos
        pdf.multi_cell(0, 8, texto_intro.encode('latin-1', 'replace').decode('latin-1'))
        pdf.ln(10)

        # --- SECCIÓN DETALLES (Idéntico a tu imagen) ---
        pdf.set_font('Arial', '', 11)
        pdf.cell(0, 8, "DETALLES DEL CAMBIO:", 0, 1)
        
        # Línea punteada simulada
        pdf.cell(0, 5, "-"*65, 0, 1) 
        
        # Datos de los aretes
        pdf.ln(2)
        pdf.cell(60, 8, f"Identificador Anterior (Baja):   {arete_ant}", 0, 1)
        pdf.cell(60, 8, f"Identificador Nuevo (Alta):      {arete_nue}", 0, 1)
        pdf.ln(2)
        
        # Línea punteada cierre
        pdf.cell(0, 5, "-"*65, 0, 1)
        pdf.ln(10)

        # --- SECCIÓN MOTIVO ---
        pdf.cell(0, 8, "MOTIVO DECLARADO:", 0, 1)
        motivo_safe = motivo.encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(0, 8, motivo_safe)
        
        # --- FIRMAS AL PIE ---
        pdf.set_y(-60) # Posición fija abajo
        y_firmas = pdf.get_y()
        
        # Línea Izquierda
        pdf.line(30, y_firmas, 90, y_firmas)
        pdf.set_xy(30, y_firmas + 2)
        pdf.set_font('Arial', '', 10)
        pdf.cell(60, 5, "Firma del Responsable", 0, 0, 'C')
        # Nombre del responsable debajo de la firma
        pdf.set_xy(30, y_firmas + 7)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(60, 5, responsable, 0, 0, 'C')

        # Línea Derecha
        pdf.line(120, y_firmas, 180, y_firmas)
        pdf.set_xy(120, y_firmas + 2)
        pdf.set_font('Arial', '', 10)
        pdf.cell(60, 5, "Sello Institucional", 0, 0, 'C')
        # Salida del PDF
        pdf_data = pdf.output(dest='S')
        # pdf.output puede devolver str, bytes o bytearray según la versión de fpdf
        if isinstance(pdf_data, bytearray):
            pdf_data = bytes(pdf_data)
        if isinstance(pdf_data, (bytes, memoryview)):
            response = make_response(pdf_data)
        else:
            response = make_response(pdf_data.encode('latin-1')) 
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=Rearetado_{arete_nue}.pdf'
        return response

    except Exception as e:
        return f"Error al generar PDF: {e}"
#--------------Blog donde se hablan de tipos de razas en tabasco-------
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
    arete = request.args.get("arete")
    predio = request.args.get("predio")

    if not arete or not predio:
        return "Datos incompletos", 400

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
            FROM Registro_SINIGA r
            JOIN Animales a ON r.fk_animal = a.pk_animal
            LEFT JOIN Predios p ON p.pk_predio = %s
            LEFT JOIN Productores pr ON pr.pk_productor = a.fk_productor
            LEFT JOIN Estados e ON e.pk_estado = p.fk_estado
            LEFT JOIN Municipios m ON m.pk_municipio = p.fk_municipio
            WHERE r.arete = %s AND p.pk_predio = %s
            LIMIT 1
            """,
            (int(predio), arete, int(predio))
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
