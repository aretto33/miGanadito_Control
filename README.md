# miGanadito_Control

<img width="1920" height="350" alt="image" src="https://github.com/aretto33/miGanadito_Control/blob/main/static/banner.png?raw=true" />

Sistema web de gestion ganadera construido con Flask y plantillas Jinja. El proyecto mantiene compatibilidad local con MySQL/MariaDB y esta preparado para deploy en Vercel con Supabase Postgres.

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

3. Copia `.env.example` a `.env` y ajusta las variables segun tu entorno local.
4. Ejecuta la aplicacion:

```bash
python app.py
```

## Deploy en Vercel con Supabase

Esta aplicacion queda preparada para desplegarse en Vercel como app Flask y conectarse a Supabase Postgres usando `DATABASE_URL`.

### Variables necesarias en Vercel

```text
SECRET_KEY=pon_aqui_un_valor_seguro
FLASK_DEBUG=false
DATABASE_URL=postgres://...
```

Usa en Supabase la cadena de conexion del pooler para trafico serverless.

### Variables que NO necesitas en Vercel para este deploy

Estas no hacen la conexion a Postgres y pueden confundirte si las agregas pensando que sustituyen `DATABASE_URL`:

```text
SUPABASE_URL
SUPABASE_KEY
DB_HOST
DB_PORT
DB_USER
DB_PASSWORD
DB_NAME
```

`SUPABASE_URL` y `SUPABASE_KEY` sirven para la API de Supabase, no para que Flask se conecte a la base.

### Pasos recomendados

1. Sube este repositorio a GitHub.
2. Crea un proyecto en Supabase.
3. Copia la cadena `DATABASE_URL` desde `Connect`.
4. En Vercel importa este repositorio.
5. Agrega las variables de entorno del bloque anterior.
6. Haz `Redeploy` para que Vercel tome las variables nuevas.
7. Despliega. Vercel usara [vercel.json](vercel.json) y detectara `app.py`.

### Checklist rapido antes de hacer deploy

- `DATABASE_URL` tiene tu password real, no `[YOUR-PASSWORD]`.
- `FLASK_DEBUG` esta en `false`.
- `SECRET_KEY` ya no usa el valor de ejemplo.
- El esquema SQL ya existe en Supabase.
- El repo ya tiene subidos [vercel.json](vercel.json), [requirements.txt](requirements.txt) y [public/](/Users/arletteguzmandelacruz/miGanadito_Control/public).

### Archivos de soporte

- [vercel.json](vercel.json): configuracion de runtime y rewrites.
- [.vercelignore](.vercelignore): excluye archivos pesados o locales.
- [public/](/Users/arletteguzmandelacruz/miGanadito_Control/public): archivos estaticos para Vercel.

### Importante sobre la base de datos

- `backup2.sql` es un dump de MariaDB y no se puede importar directo en Supabase sin conversion.
- La ruta del PDF del animal ya no depende de un procedimiento almacenado de MariaDB.
- Si quieres mover tus datos reales a Supabase, lo recomendable es convertir el esquema a PostgreSQL primero.

## Siguiente refactor recomendado

- Separar rutas por modulo: autenticacion, animales, predios, ventas.
- Mover estilos inline de `templates/` a `static/css/`.
- Sacar consultas SQL complejas a funciones o servicios dedicados.
