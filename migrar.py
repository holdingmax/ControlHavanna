import os
import sqlite3
from sqlalchemy import create_engine, text

SQLITE_URL = "sqlite:///database/schema.db"
POSTGRES_URL = "postgresql://controlhavanna_db_user:cWSuxGUz6ldz7GFDf3KuhtE80AfMlGiy@dpg-d8uk5r6rnols739o0390-a.oregon-postgres.render.com/controlhavanna_db"  # <-- pegá la URL de Render

sqlite_engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
pg_engine = create_engine(POSTGRES_URL)

# Crear las tablas en PostgreSQL
from database.db import Base
import database.models  # asegura que los modelos estén registrados
Base.metadata.create_all(bind=pg_engine)

# Migrar tabla por tabla
from sqlalchemy.orm import Session

tablas = Base.metadata.sorted_tables

for tabla in tablas:
    print(f"Migrando tabla: {tabla.name}")
    with sqlite_engine.connect() as sqlite_conn:
        filas = sqlite_conn.execute(tabla.select()).fetchall()
        columnas = tabla.columns.keys()

    if not filas:
        print(f"  (vacía, se omite)")
        continue

    with Session(pg_engine) as pg_session:
        for fila in filas:
            datos = dict(zip(columnas, fila))
            try:
                pg_session.execute(tabla.insert().values(**datos))
                pg_session.commit()
            except Exception:
                pg_session.rollback()
                print(f"  (fila duplicada omitida)")
    print(f"  {len(filas)} filas migradas")

print("\n✅ Migración completada.")