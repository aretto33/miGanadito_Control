from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, render_template, request, make_response, send_from_directory
import mariadb
from fpdf import FPDF
from datetime import datetime


app = Flask(__name__)
app.secret_key = "SECRET_KEY_GANACONTROL_2025"

# -------------------- CONEXIÓN A LA BD --------------------
#<def conectar_bd():
 #   try:
 #       conn = mariadb.connect(
 #           host="18.188.180.142",
 #           user="arletteg",
 #           password="123456",
 #           database="Proyecto_Ganaderia"
#        )
 #       return conn, conn.cursor()
#    except mariadb.Error as e:
  #      print("Error de conexión:", e)
 #       return None, None
def conectar_bd():
    try:
        conn = mariadb.connect(
            host="18.188.180.142",
            user="arletteg",
            password="123456",
            database="Proyecto_Ganaderia"
        )
        return conn, conn.cursor()
    except mariadb.Error as e:
        print("Error de conexión:", e)
        return None, None

# -------------------- VALIDAR CREDENCIALES ----------------------
def verificar_credenciales(usuario, password, rol):
    conn, cursor = conectar_bd()
    if not conn:
        return False, "Error de conexión"

    try:
        sql = """
        SELECT id_usuario, usuario, password, rol, fk_productor
        FROM usuarios 
        WHERE usuario=%s AND rol=%s
        """
        cursor.execute(sql, (usuario, rol))
        result = cursor.fetchone()

        if result:
            id_user, db_user, db_pass, db_rol, db_fk = result
            if db_pass == password:
                return True, {"id_usuario": id_user, "rol": db_rol, "fk_productor": db_fk}
            else:
                return False, "Contraseña incorrecta"
        else:
            return False, "Usuario o rol no encontrado"

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
    conn, cursor = conectar_bd()

    # OBTENER PRODUCTORES PARA EL SELECT
    cursor.execute("SELECT pk_productor, nombre FROM Productores")
    productores = cursor.fetchall()

    if request.method == "POST":
        usuario = request.form["usuario"]
        contra = request.form["password"]
        rol = request.form["rol"]

        exito, info = verificar_credenciales(usuario, contra, rol)

        if exito:
            session["usuario"] = usuario
            session["rol"] = rol
            # SI ES PRODUCTOR, GUARDAMOS EL FK
    # guardar fk_productor tomado de la BD (devuelto en info)
        if isinstance(info, dict) and info.get("fk_productor"):
            session["fk_productor"] = info.get("fk_productor")

            flash(f"Bienvenido {usuario} ({rol})", "success")
            return redirect(url_for("dashboard"))
        else:
            flash(info, "danger")

    conn.close()

    return render_template("login.html", productores=productores)


#--------------- REGISTRAR -----------------
@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":
        usuario = request.form["usuario"]
        contra = request.form["password"]
        rol = request.form["rol"]

        prod_id = None  # Por defecto no tiene productor asignado

        conn, cursor = conectar_bd()
        if not conn:
            flash("Error al conectar con la base de datos", "danger")
            return redirect(url_for("register"))

        try:
            # SI ES PRODUCTOR, PRIMERO INSERTAR EN TABLA PRODUCTORES
            if rol == "Productor":
                nombre = request.form["prod_nombre"]
                ap_pat = request.form["prod_apellido_pat"]
                ap_mat = request.form["prod_apellido_mat"]

                sql_prod = """
                INSERT INTO Productores (nombre, apellido_pat, apellido_mat, UPP)
                VALUES (%s, %s, %s,'No inscrito')
                """
                cursor.execute(sql_prod, (nombre, ap_pat, ap_mat))
                conn.commit()

                prod_id = cursor.lastrowid

            # INSERTAR USUARIO
            sql = """
            INSERT INTO usuarios (usuario, password, rol, fk_productor)
            VALUES (%s, %s, %s, %s)
            """
            cursor.execute(sql, (usuario, contra, rol, prod_id))
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
        usuario=session["usuario"],
        rol=session["rol"],
        productor=productor_nombre
    )

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('inicio'))

# ------------------ Ventana Animales ------------------
@app.route("/animales", methods=["GET", "POST"])
def animales():
    # Requiere sesión
    if "usuario" not in session:
        flash("Debes iniciar sesión", "warning")
        return redirect(url_for("login"))

    conn = None
    cursor = None

    try:
        conn, cursor = conectar_bd()
        if not conn:
            flash("Error al conectar con la base de datos", "danger")
            return redirect(url_for("inicio"))

        if request.method == "POST":
            accion = request.form.get("accion")

            # Obtener imágenes si las mandaron
            foto_perfil = request.files.get("foto_perfil")
            foto_lateral = request.files.get("foto_lateral")

            perfil_bytes = foto_perfil.read() if foto_perfil and foto_perfil.filename else None
            lateral_bytes = foto_lateral.read() if foto_lateral and foto_lateral.filename else None

            # Determinar fk_productor según el rol del usuario (si es productor usar el suyo)
            if session.get("rol") == "Productor":
                fk_prod_session = session.get("fk_productor")
            else:
                fk_prod_session = None

            # --- REGISTRAR ---
            if accion == "registrar":
                nombre = request.form.get("nombre")
                fecha = request.form.get("fecha")
                cruze = request.form.get("cruze") or "Sin conocer"
                sexo = request.form.get("sexo") or None
                peso_actual = request.form.get("peso_actual") or None

                # Si el usuario es productor, forzamos el fk_productor desde la sesión
                if fk_prod_session:
                    fk_productor = fk_prod_session
                else:
                    fk_productor = request.form.get("fk_productor") or None

                fk_raza = request.form.get("fk_raza") or None

                cursor.execute(
                    """INSERT INTO Animales (nombre, fecha_nacimiento, cruze, sexo, peso_actual, fk_productor, fk_raza, fk_predio, fk_animal, foto_perfil, foto_lateral)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (nombre, fecha, cruze, sexo, peso_actual, fk_productor, fk_raza, request.form.get("fk_predio") or None, request.form.get("fk_madre") or None, perfil_bytes, lateral_bytes)
                )
                conn.commit()

            # --- MODIFICAR ---
            elif accion == "modificar":
                pk = request.form.get("pk")
                nombre = request.form.get("nombre")
                fecha = request.form.get("fecha")
                cruze = request.form.get("cruze")
                sexo = request.form.get("sexo")
                peso_actual = request.form.get("peso_actual") or None

                # Solo permitir cambiar fk_productor si el usuario no es productor
                if fk_prod_session:
                    fk_productor = fk_prod_session
                else:
                    fk_productor = request.form.get("fk_productor") or None

                fk_raza = request.form.get("fk_raza") or None

                cursor.execute(
                    """UPDATE Animales
                       SET nombre=%s, fecha_nacimiento=%s, cruze=%s, sexo=%s, peso_actual=%s,
                           fk_productor=%s, fk_raza=%s, fk_predio=%s, fk_animal=%s
                       WHERE pk_animal=%s""",
                    (nombre, fecha, cruze, sexo, peso_actual, fk_productor, fk_raza, request.form.get("fk_predio") or None, request.form.get("fk_madre") or None, pk)
                )

                if perfil_bytes:
                    cursor.execute("UPDATE Animales SET foto_perfil=%s WHERE pk_animal=%s", (perfil_bytes, pk))
                if lateral_bytes:
                    cursor.execute("UPDATE Animales SET foto_lateral=%s WHERE pk_animal=%s", (lateral_bytes, pk))

                conn.commit()

            # --- ELIMINAR ---
            elif accion == "eliminar":
                pk = request.form.get("pk")
                cursor.execute("DELETE FROM Animales WHERE pk_animal=%s", (pk,))
                conn.commit()

        # --- CONSULTAR LISTA ---
        # Si el usuario es 'Productor' mostrar solo sus animales
        if session.get("rol") == "Productor":
            fk = session.get("fk_productor")
            cursor.execute(
                """SELECT a.pk_animal, a.nombre, a.fecha_nacimiento, a.cruze,
                          p.nombre AS productor, r.nombre AS raza, a.sexo, a.peso_actual
                   FROM Animales a
                   LEFT JOIN Productores p ON a.fk_productor = p.pk_productor
                   LEFT JOIN Razas r ON a.fk_raza = r.pk_raza
                   WHERE a.fk_productor = %s
                   ORDER BY a.pk_animal DESC""",
                (fk,)
            )
        else:
            cursor.execute(
                """SELECT a.pk_animal, a.nombre, a.fecha_nacimiento, a.cruze,
                          p.nombre AS productor, r.nombre AS raza, a.sexo, a.peso_actual
                   FROM Animales a
                   LEFT JOIN Productores p ON a.fk_productor = p.pk_productor
                   LEFT JOIN Razas r ON a.fk_raza = r.pk_raza
                   ORDER BY a.pk_animal DESC"""
            )

        animales = cursor.fetchall()

        # Datos para selects (si el usuario es productor, puedes ocultar la lista completa si deseas)
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
        flash(f"Error en módulo Animales: {e}", "danger")
        animales = []
        productores = []
        razas = []

    finally:
        if conn:
            conn.close()

    return render_template("animales.html", animales=animales, productores=productores, razas=razas, predios=predios, madres=madres)

# ------------------ Mostrar imágenes ------------------
@app.route("/imagen_animal/<int:id>/<string:tipo>")
def imagen_animal(id, tipo):
    conn, cursor = conectar_bd()
    cursor.execute(f"SELECT {tipo} FROM Animales WHERE pk_animal=%s", (id,))
    imagen = cursor.fetchone()[0]
    conn.close()

    if imagen is None:
        return "", 404

    return Response(imagen, mimetype="image/jpeg")


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
            estado = request.form.get("estado")
            municipio = request.form.get("municipio")
            fk_prod = request.form.get("fk_productor")  # 👈 nuevo

            sql = """
                INSERT INTO Predios (direccion, estado, municipio, fk_productor)
                VALUES (%s, %s, %s, %s)
            """
            cursor.execute(sql, (direccion, estado, municipio, fk_prod))
            conn.commit()

        elif accion == "modificar":
            pk = request.form.get("pk")
            direccion = request.form.get("direccion")
            estado = request.form.get("estado")
            municipio = request.form.get("municipio")
            fk_prod = request.form.get("fk_productor")

            sql = """
                UPDATE Predios
                SET direccion=%s, estado=%s, municipio=%s, fk_productor=%s
                WHERE pk_predio=%s
            """
            cursor.execute(sql, (direccion, estado, municipio, fk_prod, pk))
            conn.commit()

        elif accion == "eliminar":
            pk = request.form.get("pk")
            cursor.execute("DELETE FROM Predios WHERE pk_predio=%s", (pk,))
            conn.commit()

        return redirect(url_for("predios"))

    # --------------------
    # GET
    # --------------------
    cursor.execute("""
        SELECT pk_predio, direccion, estado, municipio
        FROM Predios
        WHERE fk_productor=%s
    """, (fk_productor,))
    predios = cursor.fetchall()

    conn.close()

    return render_template("predios.html", predios=predios, productores=productores)

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
        upp = request.form.get("UPP")
        rfc = request.form.get("RFC")

        sql = """
            UPDATE Productores
            SET nombre=%s, apellido_pat=%s, apellido_mat=%s, UPP=%s, RFC=%s
            WHERE pk_productor=%s
        """

        try:
            cursor.execute(sql, (nombre, apellido_pat, apellido_mat, upp, rfc, fk_productor))
            conn.commit()
            flash("Datos actualizados correctamente.", "success")
        except mariadb.IntegrityError:
            flash(" El RFC ya está registrado en otro productor.", "danger")

        return redirect(url_for("mi_productor"))

    # --- OBTENER DATOS DEL PRODUCTOR LOGUEADO ---
    cursor.execute("""
        SELECT pk_productor, nombre, apellido_pat, apellido_mat, UPP, RFC
        FROM Productores
        WHERE pk_productor=%s
    """, (fk_productor,))

    productor = cursor.fetchone()
    conn.close()

    return render_template("mi_productor.html", productor=productor)

# ------------------ PESAJES ----------------------------------

@app.route("/pesajes", methods=["GET", "POST"])
def pesajes():
    conn = None
    cursor = None

    try:
        conn, cursor = conectar_bd()

        if request.method == "POST":
            accion = request.form.get("accion")

            # REGISTRAR
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

            # MODIFICAR
            elif accion == "modificar":
                pk = request.form.get("pk")
                pesaje_val = request.form.get("pesaje")
                fecha = request.form.get("fecha")
                fk_animal = request.form.get("fk_animal") or None

                cursor.execute("""
                    UPDATE Pesajes
                    SET pesaje=%s, fecha=%s, fk_animal=%s
                    WHERE pk_pesaje=%s
                """, (pesaje_val, fecha, fk_animal, pk))
                conn.commit()
                flash("Pesaje modificado correctamente", "info")

            # ELIMINAR
            elif accion == "eliminar":
                pk = request.form.get("pk")
                cursor.execute("DELETE FROM Pesajes WHERE pk_pesaje=%s", (pk,))
                conn.commit()
                flash("Pesaje eliminado", "danger")

        # CONSULTAR REGISTROS
        cursor.execute("""
            SELECT p.pk_pesaje, p.pesaje, p.fecha, a.pk_animal, a.nombre
            FROM Pesajes p
            LEFT JOIN Animales a ON p.fk_animal = a.pk_animal
            ORDER BY p.pk_pesaje DESC
        """)
        pesajes = cursor.fetchall()

        # Animales para el select
        cursor.execute("SELECT pk_animal, nombre FROM Animales")
        animales = cursor.fetchall()

    except Exception as e:
        flash(f"Error en módulo Pesajes: {e}", "danger")
        pesajes = []
        animales = []

    finally:
        if conn:
            conn.close()

    return render_template("pesajes.html", pesajes=pesajes, animales=animales)

#_-------------------------------SIINIGA-------------------------------

@app.route("/registro_siniga", methods=["GET", "POST"])
def registro_siniga():
    conn,cursor = conectar_bd()

    # ----- Registrar -----
    if request.method == "POST" and request.form["accion"] == "registrar":
        fk_animal = request.form["fk_animal"]
        arete = request.form["arete"]

        cursor.execute("""
            INSERT INTO Registro_SINIGA (fk_animal, arete)
            VALUES (%s, %s)
        """, (fk_animal, arete))
        conn.commit()

    # ----- Modificar -----
    if request.method == "POST" and request.form["accion"] == "modificar":
        pk = request.form["pk"]
        fk_animal = request.form["fk_animal"]
        arete = request.form["arete"]

        cursor.execute("""
            UPDATE Registro_SINIGA
            SET fk_animal=%s, arete=%s
            WHERE id=%s
        """, (fk_animal, arete, pk))
        conn.commit()

    # ----- Eliminar -----
    if request.method == "POST" and request.form["accion"] == "eliminar":
        pk = request.form["pk"]
        cursor.execute("DELETE FROM Registro_SINIGA WHERE id=%s", (pk,))
        conn.commit()

    # ----- Consultar -----
    cursor.execute("""
        SELECT r.id, r.fk_animal, r.arete, a.nombre
        FROM Registro_SINIGA r
        INNER JOIN Animales a ON r.fk_animal = a.pk_animal
    """)
    registros = cursor.fetchall()

    # Animales para el select
    cursor.execute("SELECT pk_animal, nombre FROM Animales")
    animales = cursor.fetchall()

    conn.close()

    return render_template("registro_siniga.html",
                           animales=animales,
                           registros=registros)



# ---------------- SEGUIMIENTO VETERINARIO ----------------

@app.route("/seguimiento", methods=["GET", "POST"])
def seguimiento():
    conn = None
    cursor = None

    if request.method == "POST":
        accion = request.form.get("accion")

        try:
            conn,cursor = conectar_bd()
            # --- Obtener campos ---
            pk = request.form.get("pk")
            fk_animal = request.form.get("fk_animal")
            tipo_tratamiento = request.form.get("tipo_tratamiento")
            fecha_actual = request.form.get("fecha_actual")
            prox_fecha = request.form.get("prox_fecha")

            # --- REGISTRAR ---
            if accion == "registrar":
                cursor.execute("""
                    INSERT INTO Seguimiento_vet (fk_animal, tipo_tratamiento, fecha_actual, prox_fecha)
                    VALUES (%s, %s, %s, %s)
                """, (fk_animal, tipo_tratamiento, fecha_actual, prox_fecha))
                conn.commit()
                flash("Seguimiento registrado correctamente", "success")

            # --- MODIFICAR ---
            elif accion == "modificar":
                cursor.execute("""
                    UPDATE Seguimiento_vet SET 
                    fk_animal=%s, tipo_tratamiento=%s, fecha_actual=%s, prox_fecha=%s
                    WHERE pk_segui_vet=%s
                """, (fk_animal, tipo_tratamiento, fecha_actual, prox_fecha, pk))
                conn.commit()
                flash("Seguimiento modificado correctamente", "info")

            # --- ELIMINAR ---
            elif accion == "eliminar":
                cursor.execute("DELETE FROM Seguimiento_vet WHERE pk_segui_vet=%s", (pk,))
                conn.commit()
                flash("Seguimiento eliminado", "danger")

        except Exception as e:
            flash(f"Error: {e}", "danger")

    # --- CONSULTAR REGISTROS ---
    conn, cursor =conectar_bd()
    cursor.execute("""
        SELECT pk_segui_vet, fk_animal, tipo_tratamiento, fecha_actual, prox_fecha
        FROM Seguimiento_vet
        ORDER BY pk_segui_vet DESC
    """)
    seguimientos = cursor.fetchall()

    # --- obtener animales para el select ---
    cursor.execute("SELECT pk_animal, nombre FROM Animales")
    animales = cursor.fetchall()

    return render_template("seguimiento.html", seguimientos=seguimientos, animales=animales)
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
                precio = request.form.get("precio")
                fecha_venta = request.form.get("fecha_venta")

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
                precio = request.form.get("precio")
                fecha_venta = request.form.get("fecha_venta")

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
        cursor.execute("""
            SELECT v.pk_venta, v.fk_animal, v.fk_pesaje, v.clave, v.precio, v.fecha_venta,
                   a.nombre AS animal_nombre, p.pesaje
            FROM Ventas v
            LEFT JOIN Animales a ON v.fk_animal = a.pk_animal
            LEFT JOIN Pesajes p ON v.fk_pesaje = p.pk_pesaje
            ORDER BY v.pk_venta DESC
        """)
        ventas_list = cursor.fetchall()

        # Animales para el select
        cursor.execute("SELECT pk_animal, nombre FROM Animales")
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
    data = request.get_json()
    animal_id = data["animal_id"]

    conn, cursor = conectar_bd()
    cursor.execute("CALL calcular_precio_animal(%s)", (animal_id,))
    resultado = cursor.fetchone()  # [Animal, Sexo, Peso, Precio_kg, Total]

    total = resultado[4]  # Total calculado

    conn.close()

    return {"precio": total}



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

                cursor.execute("""
                    UPDATE Razas
                    SET nombre=%s, origen=%s, color=%s
                    WHERE pk_raza=%s
                """, (nombre, origen, color, pk))
                conn.commit()
                flash("Raza modificada correctamente", "info")

            # ELIMINAR
            elif accion == "eliminar":
                pk = request.form.get("pk")
                cursor.execute("DELETE FROM Razas WHERE pk_raza=%s", (pk,))
                conn.commit()
                flash("Raza eliminada", "danger")

        # CONSULTAR REGISTROS
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

# -------------------- PROGRAMA PRINCIPAL --------------------
if __name__ == "__main__":
    app.run(debug=True)
