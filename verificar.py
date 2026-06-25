from sqlalchemy import create_engine, text

POSTGRES_URL = "postgresql://controlhavanna_db_user:cWSuxGUz6ldz7GFDf3KuhtE80AfMlGiy@dpg-d8uk5r6rnols739o0390-a.oregon-postgres.render.com/controlhavanna_db"

engine = create_engine(POSTGRES_URL)

tablas = ["articulos", "categorias", "locales", "reportes_ventas_turno", "users", "combos"]

with engine.connect() as conn:
    for tabla in tablas:
        resultado = conn.execute(text(f"SELECT COUNT(*) FROM {tabla}"))
        count = resultado.scalar()
        print(f"{tabla}: {count} filas")