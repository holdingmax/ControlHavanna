from datetime import datetime

from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Categoria(Base):
    __tablename__ = "categorias"

    codigo: Mapped[int] = mapped_column(Integer, primary_key=True)
    descripcion: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)


class Articulo(Base):
    __tablename__ = "articulos"

    codigo: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    categoria_codigo: Mapped[Optional[int]] = mapped_column(ForeignKey("categorias.codigo"), nullable=True)
    es_combo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    combo_codigo: Mapped[Optional[int]] = mapped_column(ForeignKey("combos.codigo"), nullable=True)


class Local(Base):
    __tablename__ = "locales"

    codigo: Mapped[int] = mapped_column(Integer, primary_key=True)
    descripcion: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)


class Combo(Base):
    __tablename__ = "combos"

    codigo: Mapped[int] = mapped_column(Integer, primary_key=True)
    descripcion: Mapped[str] = mapped_column(String(25), nullable=False, unique=True)
    categ1: Mapped[Optional[int]] = mapped_column(ForeignKey("categorias.codigo"), nullable=True)
    qcateg1: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    categ2: Mapped[Optional[int]] = mapped_column(ForeignKey("categorias.codigo"), nullable=True)
    qcateg2: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    categ3: Mapped[Optional[int]] = mapped_column(ForeignKey("categorias.codigo"), nullable=True)
    qcateg3: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    categ4: Mapped[Optional[int]] = mapped_column(ForeignKey("categorias.codigo"), nullable=True)
    qcateg4: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ReporteVentaTurno(Base):
    __tablename__ = "reportes_ventas_turno"
    __table_args__ = (
        UniqueConstraint("fecha_creacion", "local_descripcion", "turno", name="uq_reporte_fecha_local_turno"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    local_descripcion: Mapped[str] = mapped_column(String(150), nullable=False)
    turno: Mapped[int] = mapped_column(Integer, nullable=False)
    hora_inicio: Mapped[str] = mapped_column(String(10), nullable=False)
    hora_cierre: Mapped[str] = mapped_column(String(10), nullable=False)
    encargado: Mapped[str] = mapped_column(String(30), nullable=False)
    usuario_cierre: Mapped[str] = mapped_column(String(50), nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="CERRADO")


class VentaTurnoBorrador(Base):
    __tablename__ = "ventas_turno_borradores"
    __table_args__ = (
        UniqueConstraint("usuario", name="uq_ventas_turno_borrador_usuario"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usuario: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    local_descripcion: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    fecha_reporte: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    turno: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    hora_inicio: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    hora_cierre: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    encargado: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    counts_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    hist_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ReporteVentaTurnoDetalle(Base):
    __tablename__ = "reportes_ventas_turno_detalle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reporte_id: Mapped[int] = mapped_column(ForeignKey("reportes_ventas_turno.id"), nullable=False, index=True)
    categoria_codigo: Mapped[int] = mapped_column(Integer, nullable=False)
    categoria_descripcion: Mapped[str] = mapped_column(String(150), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ReporteVentaTurnoComboDetalle(Base):
    __tablename__ = "reportes_ventas_turno_combo_detalle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reporte_id: Mapped[int] = mapped_column(ForeignKey("reportes_ventas_turno.id"), nullable=False, index=True)
    combo_codigo: Mapped[int] = mapped_column(Integer, nullable=False)
    combo_descripcion: Mapped[str] = mapped_column(String(25), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ReporteSistemaArticuloDetalle(Base):
    __tablename__ = "reportes_sistema_articulo_detalle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reporte_id: Mapped[int] = mapped_column(ForeignKey("reportes_ventas_turno.id"), nullable=False, index=True)
    articulo_codigo: Mapped[int] = mapped_column(Integer, nullable=False)
    articulo_nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    unidades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    es_combo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    categoria_codigo: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    combo_codigo: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estado: Mapped[str] = mapped_column(String(50), nullable=False, default="OK")


class ReporteSistemaCategoriaDetalle(Base):
    __tablename__ = "reportes_sistema_categoria_detalle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reporte_id: Mapped[int] = mapped_column(ForeignKey("reportes_ventas_turno.id"), nullable=False, index=True)
    categoria_codigo: Mapped[int] = mapped_column(Integer, nullable=False)
    categoria_descripcion: Mapped[str] = mapped_column(String(150), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ReporteSistemaComboDetalle(Base):
    __tablename__ = "reportes_sistema_combo_detalle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reporte_id: Mapped[int] = mapped_column(ForeignKey("reportes_ventas_turno.id"), nullable=False, index=True)
    combo_codigo: Mapped[int] = mapped_column(Integer, nullable=False)
    combo_descripcion: Mapped[str] = mapped_column(String(25), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ReporteCheckCorreccion(Base):
    __tablename__ = "reportes_check_correcciones"
    __table_args__ = (
        UniqueConstraint("reporte_id", "tipo", "codigo", name="uq_reporte_check_correccion_linea"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reporte_id: Mapped[int] = mapped_column(ForeignKey("reportes_ventas_turno.id"), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)
    codigo: Mapped[int] = mapped_column(Integer, nullable=False)
    descripcion: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    cantidad_original: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correccion: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cantidad_corregida: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detalle: Mapped[str] = mapped_column(String(50), nullable=False)
    usuario: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
