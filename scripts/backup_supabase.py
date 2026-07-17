#!/usr/bin/env python3
"""Generate a logical Supabase/Postgres backup without Supabase Backups.

The output is a psql-compatible SQL file with:
- enum types
- sequences
- public table DDL
- table data using COPY
- constraints and non-constraint indexes

It connects with DATABASE_URL or SUPABASE_DB_URL from the environment/.env.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
import psycopg
from psycopg import sql


DEFAULT_SCHEMA = "public"
DEFAULT_OUTPUT_DIR = Path("backups")


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def qualified_name(schema: str, name: str) -> str:
    return f"{quote_ident(schema)}.{quote_ident(name)}"


def get_database_url() -> str:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
    if not database_url:
        raise RuntimeError("Define DATABASE_URL o SUPABASE_DB_URL para conectar con Supabase.")
    return database_url


def render_column_type(column: dict) -> str:
    data_type = column["data_type"]
    udt_name = column["udt_name"]

    if data_type == "USER-DEFINED":
        return quote_ident(udt_name)
    if data_type == "ARRAY":
        return quote_ident(udt_name)
    if data_type in {"character varying", "character"} and column["character_maximum_length"]:
        return f"{data_type}({column['character_maximum_length']})"
    if data_type == "numeric" and column["numeric_precision"]:
        if column["numeric_scale"] is not None:
            return f"numeric({column['numeric_precision']},{column['numeric_scale']})"
        return f"numeric({column['numeric_precision']})"
    if data_type.startswith("timestamp") and column["datetime_precision"] is not None:
        suffix = " with time zone" if "with time zone" in data_type else " without time zone"
        return f"timestamp({column['datetime_precision']}){suffix}"
    if data_type.startswith("time ") and column["datetime_precision"] is not None:
        suffix = " with time zone" if "with time zone" in data_type else " without time zone"
        return f"time({column['datetime_precision']}){suffix}"

    return data_type


def fetch_rows(cur, query: str, params: Iterable | None = None) -> list[dict]:
    cur.execute(query, params or ())
    return list(cur.fetchall())


def write_header(handle, schema: str) -> None:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    handle.write("-- miGanadito Supabase logical backup\n")
    handle.write(f"-- Generated at: {generated_at}\n")
    handle.write("-- Restore with: psql \"$DATABASE_URL\" -f this_file.sql\n\n")
    handle.write("BEGIN;\n")
    handle.write("SET check_function_bodies = false;\n")
    handle.write("SET client_min_messages = warning;\n")
    handle.write(f"CREATE SCHEMA IF NOT EXISTS {quote_ident(schema)};\n")
    handle.write(f"SET search_path = {quote_ident(schema)}, public;\n\n")


def write_enum_types(cur, handle, schema: str) -> None:
    enum_types = fetch_rows(
        cur,
        """
        SELECT
            n.nspname AS schema_name,
            t.typname AS type_name,
            array_agg(e.enumlabel ORDER BY e.enumsortorder) AS labels
        FROM pg_type t
        JOIN pg_enum e ON e.enumtypid = t.oid
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = %s
        GROUP BY n.nspname, t.typname
        ORDER BY t.typname
        """,
        (schema,),
    )

    for enum_type in enum_types:
        labels = ", ".join(quote_literal(label) for label in enum_type["labels"])
        handle.write(
            f"DROP TYPE IF EXISTS {qualified_name(schema, enum_type['type_name'])} CASCADE;\n"
        )
        handle.write(
            f"CREATE TYPE {qualified_name(schema, enum_type['type_name'])} AS ENUM ({labels});\n\n"
        )


def write_sequences(cur, handle, schema: str) -> None:
    sequences = fetch_rows(
        cur,
        """
        SELECT sequence_name
        FROM information_schema.sequences
        WHERE sequence_schema = %s
        ORDER BY sequence_name
        """,
        (schema,),
    )

    for sequence in sequences:
        name = sequence["sequence_name"]
        handle.write(f"DROP SEQUENCE IF EXISTS {qualified_name(schema, name)} CASCADE;\n")
        handle.write(f"CREATE SEQUENCE {qualified_name(schema, name)};\n\n")


def get_tables(cur, schema: str) -> list[str]:
    rows = fetch_rows(
        cur,
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
        (schema,),
    )
    return [row["table_name"] for row in rows]


def write_table_ddl(cur, handle, schema: str, table: str) -> None:
    columns = fetch_rows(
        cur,
        """
        SELECT
            column_name,
            data_type,
            udt_name,
            character_maximum_length,
            numeric_precision,
            numeric_scale,
            datetime_precision,
            is_nullable,
            column_default,
            identity_generation
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )

    handle.write(f"DROP TABLE IF EXISTS {qualified_name(schema, table)} CASCADE;\n")
    handle.write(f"CREATE TABLE {qualified_name(schema, table)} (\n")
    rendered_columns = []

    for column in columns:
        line = f"  {quote_ident(column['column_name'])} {render_column_type(column)}"
        if column["identity_generation"]:
            line += f" GENERATED {column['identity_generation']} AS IDENTITY"
        elif column["column_default"] is not None:
            line += f" DEFAULT {column['column_default']}"
        if column["is_nullable"] == "NO":
            line += " NOT NULL"
        rendered_columns.append(line)

    handle.write(",\n".join(rendered_columns))
    handle.write("\n);\n\n")


def write_constraints(cur, handle, schema: str) -> None:
    constraints = fetch_rows(
        cur,
        """
        SELECT
            conrelid::regclass::text AS table_name,
            conname AS constraint_name,
            pg_get_constraintdef(oid, true) AS definition
        FROM pg_constraint
        WHERE connamespace = %s::regnamespace
          AND contype IN ('p', 'u', 'f', 'c')
        ORDER BY
            CASE contype WHEN 'p' THEN 1 WHEN 'u' THEN 2 WHEN 'c' THEN 3 WHEN 'f' THEN 4 ELSE 5 END,
            conrelid::regclass::text,
            conname
        """,
        (schema,),
    )

    for constraint in constraints:
        table_name = constraint["table_name"].split(".")[-1].strip('"')
        handle.write(
            "ALTER TABLE ONLY "
            f"{qualified_name(schema, table_name)} "
            f"ADD CONSTRAINT {quote_ident(constraint['constraint_name'])} "
            f"{constraint['definition']};\n"
        )
    handle.write("\n")


def write_indexes(cur, handle, schema: str) -> None:
    indexes = fetch_rows(
        cur,
        """
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = %s
          AND indexname NOT IN (
              SELECT conname
              FROM pg_constraint
              WHERE connamespace = %s::regnamespace
          )
        ORDER BY indexname
        """,
        (schema, schema),
    )

    for index in indexes:
        handle.write(f"{index['indexdef']};\n")
    handle.write("\n")


def write_table_data(cur, handle, schema: str, table: str) -> None:
    columns = fetch_rows(
        cur,
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    if not columns:
        return

    column_list = ", ".join(quote_ident(column["column_name"]) for column in columns)
    copy_sql = sql.SQL("COPY {}.{} ({}) TO STDOUT WITH (FORMAT text)").format(
        sql.Identifier(schema),
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column["column_name"]) for column in columns),
    )

    handle.write(f"COPY {qualified_name(schema, table)} ({column_list}) FROM stdin;\n")
    with cur.copy(copy_sql) as copy:
        for row in copy:
            if isinstance(row, bytes):
                handle.write(row.decode("utf-8"))
            else:
                handle.write(row)
    handle.write("\\.\n\n")


def reset_sequences(cur, handle, schema: str) -> None:
    owned_sequences = fetch_rows(
        cur,
        """
        SELECT
            seq_ns.nspname AS sequence_schema,
            seq.relname AS sequence_name,
            tbl.relname AS table_name,
            att.attname AS column_name
        FROM pg_class seq
        JOIN pg_namespace seq_ns ON seq_ns.oid = seq.relnamespace
        JOIN pg_depend dep ON dep.objid = seq.oid
        JOIN pg_class tbl ON tbl.oid = dep.refobjid
        JOIN pg_attribute att ON att.attrelid = tbl.oid AND att.attnum = dep.refobjsubid
        WHERE seq.relkind = 'S'
          AND seq_ns.nspname = %s
          AND dep.deptype IN ('a', 'i')
        ORDER BY seq.relname
        """,
        (schema,),
    )

    for sequence in owned_sequences:
        handle.write(
            "SELECT setval("
            f"{quote_literal(qualified_name(sequence['sequence_schema'], sequence['sequence_name']))}, "
            f"COALESCE((SELECT MAX({quote_ident(sequence['column_name'])}) "
            f"FROM {qualified_name(schema, sequence['table_name'])}), 1), "
            "true);\n"
        )
    handle.write("\n")


def generate_supabase_backup(
    output_path: str | Path | None = None,
    schema: str = DEFAULT_SCHEMA,
    data_only: bool = False,
    schema_only: bool = False,
) -> Path:
    """Create a psql-compatible backup file from a Supabase/Postgres database."""
    database_url = get_database_url()

    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = DEFAULT_OUTPUT_DIR / f"supabase_backup_{timestamp}.sql"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            tables = get_tables(cur, schema)

            with output_path.open("w", encoding="utf-8", newline="\n") as handle:
                write_header(handle, schema)

                if not data_only:
                    write_enum_types(cur, handle, schema)
                    write_sequences(cur, handle, schema)
                    for table in tables:
                        write_table_ddl(cur, handle, schema, table)

                if not schema_only:
                    for table in tables:
                        write_table_data(cur, handle, schema, table)
                    reset_sequences(cur, handle, schema)

                if not data_only:
                    write_constraints(cur, handle, schema)
                    write_indexes(cur, handle, schema)

                handle.write("COMMIT;\n")

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Supabase/Postgres logical backup without Supabase Backups."
    )
    parser.add_argument("--output", "-o", help="Output .sql path. Defaults to backups/supabase_backup_TIMESTAMP.sql")
    parser.add_argument("--schema", default=DEFAULT_SCHEMA, help="Postgres schema to export. Default: public")
    parser.add_argument("--data-only", action="store_true", help="Export only COPY data, assuming schema already exists")
    parser.add_argument("--schema-only", action="store_true", help="Export only DDL without table data")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.data_only and args.schema_only:
        raise SystemExit("Usa --data-only o --schema-only, no ambos.")

    path = generate_supabase_backup(
        output_path=args.output,
        schema=args.schema,
        data_only=args.data_only,
        schema_only=args.schema_only,
    )
    print(f"Backup generado: {path}")


if __name__ == "__main__":
    main()
