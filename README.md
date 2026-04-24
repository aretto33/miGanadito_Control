# miGanadito_Control

<img width="1920" height="350" alt="image" src="https://github.com/aretto33/miGanadito_Control/blob/main/static/banner.png?raw=true" />

Sistema web de gestion ganadera construido con Flask, plantillas Jinja y MariaDB.

## Estructura actual

```text
miGanadito_Control/
├── app.py                  # Punto de entrada principal
├── wsgi.py                 # Entrada para deploy con Gunicorn
├── requirements.txt        # Dependencias Python
├── .env.example            # Variables de entorno de referencia
├── ganacontrol/
│   ├── __init__.py
│   ├── config.py           # Configuracion centralizada
│   └── db.py               # Conexion centralizada a MariaDB
├── static/
│   ├── css/
│   ├── pdf/
│   └── *.png
├── templates/
│   └── *.html
└── backup2.sql
```

## Instalacion local

1. Crea y activa un entorno virtual.
2. Instala dependencias:

```bash
pip install -r requirements.txt
```

3. Copia `.env.example` a `.env` y ajusta tus credenciales de MariaDB.
4. Ejecuta la aplicacion:

```bash
python app.py
```

## Deploy sugerido

Para despliegue en servidores tipo Render, Railway o VPS:

```bash
gunicorn wsgi:application
```

## Deploy en Railway con MySQL

Esta aplicacion ya puede leer automaticamente las variables que Railway crea para su servicio MySQL:

- `MYSQLHOST`
- `MYSQLPORT`
- `MYSQLUSER`
- `MYSQLPASSWORD`
- `MYSQLDATABASE`

### Pasos recomendados

1. Sube este repositorio a GitHub.
2. En Railway crea un proyecto nuevo.
3. Agrega un servicio `MySQL` desde `+ New`.
4. Agrega tu repositorio como servicio web en el mismo proyecto.
5. Railway detectara el `Dockerfile` y construira la app automaticamente.
6. En el servicio web agrega al menos estas variables:

```text
SECRET_KEY=pon_aqui_un_valor_seguro
FLASK_DEBUG=false
```

7. Si Railway no enlaza automaticamente el puerto, usa como Start Command:

```bash
gunicorn --bind 0.0.0.0:$PORT wsgi:application
```

### Base de datos

- La app tomara las credenciales desde las variables `MYSQL...` del servicio MySQL.
- Importa tu esquema y datos usando `backup2.sql`.
- Haz respaldos periodicos, porque la base en Railway no sustituye una estrategia formal de backup.

## Siguiente refactor recomendado

- Separar rutas por modulo: autenticacion, animales, predios, ventas.
- Mover estilos inline de `templates/` a `static/css/`.
- Sacar consultas SQL complejas a funciones o servicios dedicados.
