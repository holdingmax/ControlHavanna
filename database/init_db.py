from pathlib import Path

import pandas as pd
from sqlalchemy import select

from database.db import Base, SessionLocal, engine
from database.models import Articulo, Categoria, Local, User
from services.auth import get_user_by_username, hash_password


BASE_DIR = Path(__file__).resolve().parent.parent


def _find_input_file(candidates: list[str]) -> Path:
    for name in candidates:
        path = BASE_DIR / name
        if path.exists():
            return path
    raise FileNotFoundError(
        "No se encontró ninguno de estos archivos en la carpeta raíz del proyecto: "
        + ", ".join(candidates)
    )


def _seed_admin(db):
    admin_user = get_user_by_username(db, "admin")
    if not admin_user:
        user = User(
            username="admin",
            full_name="Administrador del sistema",
            password_hash=hash_password("admin123"),
            role="admin",
            is_active=True,
            must_change_password=False,
        )
        db.add(user)
        db.commit()
        print("Usuario admin creado.")
        print("Usuario: admin")
        print("Contraseña inicial: admin123")
    else:
        print("El usuario admin ya existe. No se modifica.")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    return out


def _reload_categorias(db):
    file_path = _find_input_file(["Categorias.xlsx", "Categorias(1).xlsx"])
    df = pd.read_excel(file_path)
    df = _normalize_columns(df)

    if "codigo" not in df.columns or "descripcion" not in df.columns:
        raise ValueError("El archivo de categorías debe tener las columnas: Codigo y Descripcion.")

    df = df[["codigo", "descripcion"]].dropna()
    df["codigo"] = pd.to_numeric(df["codigo"], errors="coerce")
    df["descripcion"] = df["descripcion"].astype(str).str.strip()
    df = df.dropna(subset=["codigo"])
    df["codigo"] = df["codigo"].astype(int)
    df = df[df["descripcion"] != ""]

    db.query(Categoria).delete()
    db.commit()

    for _, row in df.iterrows():
        db.add(Categoria(codigo=int(row["codigo"]), descripcion=row["descripcion"]))

    db.commit()
    print(f"Categorías restauradas desde: {file_path.name} ({len(df)} registros)")


def _reload_articulos(db):
    file_path = _find_input_file(["Articulos.xlsx", "Articulos(1).xlsx"])
    df = pd.read_excel(file_path)
    df = _normalize_columns(df)

    categoria_col = None
    for c in df.columns:
        if c in {"categoria", "categorias", "categoria_codigo"}:
            categoria_col = c
            break

    if "codigo" not in df.columns or "nombre" not in df.columns or not categoria_col:
        raise ValueError("El archivo de artículos debe tener las columnas: codigo, nombre y Categoria.")

    df = df[["codigo", "nombre", categoria_col]].dropna()
    df["codigo"] = pd.to_numeric(df["codigo"], errors="coerce")
    df[categoria_col] = pd.to_numeric(df[categoria_col], errors="coerce")
    df["nombre"] = df["nombre"].astype(str).str.strip()
    df = df.dropna(subset=["codigo", categoria_col])
    df["codigo"] = df["codigo"].astype(int)
    df[categoria_col] = df[categoria_col].astype(int)
    df = df[df["nombre"] != ""]

    db.query(Articulo).delete()
    db.commit()

    for _, row in df.iterrows():
        db.add(
            Articulo(
                codigo=int(row["codigo"]),
                nombre=row["nombre"],
                categoria_codigo=int(row[categoria_col]),
            )
        )

    db.commit()
    print(f"Artículos restaurados desde: {file_path.name} ({len(df)} registros)")


def _ensure_locales(db):
    locales_base = [
        (1, "HILTON"),
        (2, "24 DE SEPTIEMBRE"),
        (3, "25 DE MAYO"),
        (4, "TRIBUNALES"),
        (5, "PORTAL"),
        (6, "YENNY"),
        (7, "JOCKEY"),
        (8, "OPEN PLAZA"),
    ]

    existing = db.scalar(select(Local.codigo).limit(1))
    if existing is None:
        for codigo, descripcion in locales_base:
            db.add(Local(codigo=codigo, descripcion=descripcion))
        db.commit()
        print("Locales cargados inicialmente.")
    else:
        print("La tabla Locales ya tiene datos. No se modifica.")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        _seed_admin(db)
        _reload_categorias(db)
        _reload_articulos(db)
        _ensure_locales(db)
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
