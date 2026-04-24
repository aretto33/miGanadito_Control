import os


SUPABASE_MODE = bool(os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL"))

if SUPABASE_MODE:
    import psycopg

    class _CompatDB:
        connect = psycopg.connect
        Error = psycopg.Error
        IntegrityError = psycopg.IntegrityError

    db = _CompatDB()
else:
    import pymysql
    from pymysql.cursors import DictCursor

    class _CompatDB:
        connect = pymysql.connect
        Error = pymysql.MySQLError
        IntegrityError = pymysql.IntegrityError
        DictCursor = DictCursor

    db = _CompatDB()
