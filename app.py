import base64
import json
from datetime import datetime
from html import escape

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from database.db import Base, SessionLocal, engine
from database.models import (
    Articulo,
    Categoria,
    Combo,
    Local,
    ReporteVentaTurno,
    ReporteVentaTurnoComboDetalle,
    ReporteVentaTurnoDetalle,
    ReporteSistemaArticuloDetalle,
    ReporteSistemaCategoriaDetalle,
    ReporteSistemaComboDetalle,
    ReporteCheckCorreccion,
    VentaTurnoBorrador,
    User,
)
from services.auth import authenticate_user, create_user, delete_user, reset_user_password, update_user

st.set_page_config(page_title="ControlHavanna", layout="wide")

Base.metadata.create_all(bind=engine)


def ensure_initial_admin() -> None:
    db = SessionLocal()
    try:
        existing_user = db.scalar(select(User.id).limit(1))
        if existing_user is not None:
            return

        admin = create_user(
            db,
            username="admin",
            full_name="Administrador del sistema",
            temporary_password="admin",
            role="admin",
            is_active=True,
        )
        admin.must_change_password = True
        db.commit()
    finally:
        db.close()


ensure_initial_admin()


def has_any_user() -> bool:
    db = SessionLocal()
    try:
        return bool(db.scalar(select(User.id).limit(1)))
    finally:
        db.close()


def parse_draft_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_draft_time(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


def load_ventas_draft(username: str) -> dict | None:
    db = SessionLocal()
    try:
        draft = db.scalar(
            select(VentaTurnoBorrador).where(VentaTurnoBorrador.usuario == username)
        )
        if draft is None:
            return None

        try:
            counts = json.loads(draft.counts_json or "{}")
        except json.JSONDecodeError:
            counts = {}
        try:
            hist = json.loads(draft.hist_json or "[]")
        except json.JSONDecodeError:
            hist = []

        return {
            "local": draft.local_descripcion,
            "fecha": draft.fecha_reporte,
            "turno": int(draft.turno or 1),
            "hora_inicio": draft.hora_inicio,
            "hora_cierre": draft.hora_cierre,
            "encargado": draft.encargado,
            "counts": {str(key): int(value) for key, value in counts.items()},
            "hist": hist,
        }
    finally:
        db.close()


def restore_ventas_draft(username: str, force_page: bool = False) -> None:
    draft = load_ventas_draft(username)
    if not draft:
        return

    st.session_state.counts = draft["counts"]
    st.session_state.hist = draft["hist"]
    st.session_state.ventas_draft = draft
    st.session_state.ventas_draft_loaded = True
    st.session_state.report_success = False
    st.session_state.confirm = False
    st.session_state.require_hora_cierre = False
    if force_page:
        st.session_state.page = "Ventas por turno"


def save_ventas_draft(
    username: str | None,
    local: str,
    fecha,
    turno: int,
    hi,
    hc,
    enc: str,
) -> None:
    if not username:
        return

    counts = {
        str(key): int(value)
        for key, value in st.session_state.get("counts", {}).items()
        if int(value) != 0
    }
    hist = st.session_state.get("hist", [])
    has_content = bool(counts or hist or local or fecha or hi or hc or enc.strip())
    if not has_content:
        return

    fecha_text = fecha.isoformat() if fecha else ""
    hi_text = hi.strftime("%H:%M") if hi else ""
    hc_text = hc.strftime("%H:%M") if hc else ""

    db = SessionLocal()
    try:
        draft = db.scalar(
            select(VentaTurnoBorrador).where(VentaTurnoBorrador.usuario == username)
        )
        if draft is None:
            draft = VentaTurnoBorrador(usuario=username)
            db.add(draft)

        draft.local_descripcion = local or ""
        draft.fecha_reporte = fecha_text
        draft.turno = int(turno or 1)
        draft.hora_inicio = hi_text
        draft.hora_cierre = hc_text
        draft.encargado = enc.strip()
        draft.counts_json = json.dumps(counts)
        draft.hist_json = json.dumps(hist)
        draft.updated_at = datetime.utcnow()
        db.commit()
        st.session_state.ventas_draft_loaded = True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def clear_ventas_draft(username: str | None) -> None:
    if not username:
        return

    db = SessionLocal()
    try:
        draft = db.scalar(
            select(VentaTurnoBorrador).where(VentaTurnoBorrador.usuario == username)
        )
        if draft is not None:
            db.delete(draft)
            db.commit()
    finally:
        db.close()


def save_current_ventas_draft_from_state() -> None:
    version = st.session_state.get("ventas_form_version", 0)
    save_ventas_draft(
        st.session_state.get("username"),
        st.session_state.get(f"ventas_local_{version}", ""),
        st.session_state.get(f"ventas_fecha_{version}"),
        st.session_state.get(f"ventas_turno_{version}", 1),
        st.session_state.get(f"hora_inicio_video_{version}"),
        st.session_state.get(f"hora_cierre_video_{version}"),
        st.session_state.get(f"ventas_encargado_{version}", ""),
    )


CATEGORY_COLORS = {
    "CAFETERA": "#FFF200",
    "CAFETERIA": "#FFF200",
    "BATIDOS Y YOGURES": "#A9D0F5",
    "PRODUCTO": "#90EE90",
    "HORNO": "#FFA07A",
    "PANIFICACION Y TORTAS": "#FF0000",
    "PANIFICACIÓN Y TORTAS": "#FF0000",
    "ALMUERZO": "#4A4A4A",
    "PRODUCTOS MIXTOS": "#283593",
    "AGUAS Y GASEOSAS": "#FF00FF",
    "ACOMPAÑAMIENTO": "#D4AC0D",
    "OTROS": "#FFFFFF",
}


def get_text_color(bg: str) -> str:
    bg = bg.lstrip("#")
    r, g, b = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return "#FFFFFF" if lum < 160 else "#111111"


def render_header() -> None:
    st.markdown(
        """
        <style>
        .banner {
            background: #FFD700;
            color: #C00000;
            text-align: center;
            font-size: 26px;
            font-weight: bold;
            height: 80px;
            line-height: 80px;
            margin-top: -1rem;
            margin-bottom: 1.25rem;
        }

        .card {
            width: 100%;
            height: 192px;
            border-radius: 8px;
            padding: 10px;
            text-align: center;
            font-weight: bold;
        }

        .ventas-note {
            background: #f7f7f7;
            border: 1px solid #d0d0d0;
            border-radius: 8px;
            padding: 10px 12px;
            margin-bottom: 14px;
        }

        /* ESTILO BASE: TODOS LOS BOTONES NORMALES EN BLANCO */
        div[data-testid="stButton"] > button {
            background: #FFFFFF !important;
            color: #31333F !important;
            font-weight: 400 !important;
            border: 1px solid rgba(49, 51, 63, 0.2) !important;
            border-radius: 8px !important;
            box-shadow: none !important;
        }

        /* SOLO PRIMER BOTON: VOLVER ATRAS */
        div[data-testid="stButton"]:nth-of-type(1) > button {
            background: #198754 !important;
            color: #FFFFFF !important;
            font-weight: 700 !important;
            width: 180px !important;
            height: 50px !important;
            border: 1px solid #146C43 !important;
        }

        /* SOLO SEGUNDO BOTON: CERRAR REPORTE */
        div[data-testid="stButton"]:nth-of-type(2) > button {
            background: #FF4D4D !important;
            color: #FFFFFF !important;
            font-weight: 700 !important;
            width: 180px !important;
            height: 50px !important;
            border: 1px solid #D93636 !important;
        }

        .confirm {
            background: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            border: 2px solid #ccc;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }

        .counter-card-style + div[data-testid="stButton"] > button {
            height: 192px !important;
            min-height: 192px !important;
            width: 120px !important;
            min-width: 120px !important;
            max-width: 120px !important;
            border-radius: 8px !important;
            padding: 10px !important;
            white-space: pre-line !important;
            text-align: center !important;
            font-weight: 700 !important;
            box-shadow: none !important;
        }

        .counter-card-style + div[data-testid="stButton"] {
            display: flex !important;
            justify-content: center !important;
        }

        .counter-card-style + div[data-testid="stButton"] > button p {
            white-space: pre-line !important;
            font-size: 15px !important;
            line-height: 1.35 !important;
        }

        .counter-card-style + div[data-testid="stButton"] > button strong {
            font-size: 20px !important;
            font-weight: 800 !important;
        }
        </style>

        <div class="banner">
            SISTEMA DE CONTROL DE FACTURACION HAVANNA
        </div>
        """,
        unsafe_allow_html=True,
    )


def init() -> None:
    if "auth" not in st.session_state:
        st.session_state.auth = False
        st.session_state.username = None
        st.session_state.counts = {}
        st.session_state.hist = []
        st.session_state.confirm = False
        st.session_state.require_hora_cierre = False
        st.session_state.report_success = False
        st.session_state.ventas_form_version = 0
        st.session_state.page = "Inicio"
        st.session_state.home_menu = "Inicio"
        st.session_state.config_menu = "Seleccionar"
        st.session_state.consultas_menu = "Seleccionar"
        st.session_state.home_action = None
        st.session_state.action_success = None

    if "consultas_menu" not in st.session_state:
        st.session_state.consultas_menu = "Seleccionar"


def login() -> None:
    st.title("Ingreso al sistema")

    if not has_any_user():
        st.error(
            "No hay usuarios creados en la base local. Reinicie la aplicacion "
            "para que se genere el usuario inicial local."
        )
        return

    u = st.text_input("Usuario")
    p = st.text_input("Password", type="password")

    if st.button("Ingresar"):
        db = SessionLocal()
        try:
            user = authenticate_user(db, u, p)
        finally:
            db.close()

        if user:
            st.session_state.auth = True
            st.session_state.username = user.username
            restore_ventas_draft(user.username, force_page=True)
            st.rerun()
        else:
            st.error("Credenciales incorrectas")


def logout() -> None:
    st.session_state.clear()
    st.rerun()


FALLBACK_COLORS = [
    "#FFF200",
    "#A9D0F5",
    "#90EE90",
    "#FFA07A",
    "#FF0000",
    "#4A4A4A",
    "#283593",
    "#FF00FF",
    "#D4AC0D",
    "#FFFFFF",
    "#B8E986",
    "#F8BBD0",
]


def counter_key(item_type: str, codigo: int) -> str:
    return f"{item_type}:{codigo}"


def get_item_color(item_type: str, codigo: int, descripcion: str) -> str:
    if item_type == "cat":
        color = CATEGORY_COLORS.get(descripcion.upper())
        if color:
            return color
    return FALLBACK_COLORS[(int(codigo) - 1) % len(FALLBACK_COLORS)]


def get_group_color(item_type: str, item, index: int) -> str:
    if item_type == "cat":
        color = CATEGORY_COLORS.get(item.descripcion.upper())
        if color:
            return color
    return FALLBACK_COLORS[index % len(FALLBACK_COLORS)]


def get_combo_category_changes(combo: Combo) -> list[tuple[str, int]]:
    changes = []
    for number in (1, 2, 3, 4):
        categoria = getattr(combo, f"categ{number}")
        cantidad = getattr(combo, f"qcateg{number}")
        if categoria is not None and cantidad > 0:
            changes.append((counter_key("cat", int(categoria)), int(cantidad)))
    return changes


def apply_counter_click(item_type: str, item, key: str) -> None:
    st.session_state.counts[key] = st.session_state.counts.get(key, 0) + 1

    if item_type == "combo":
        category_changes = get_combo_category_changes(item)
        for category_key, quantity in category_changes:
            st.session_state.counts[category_key] = (
                st.session_state.counts.get(category_key, 0) + quantity
            )
        st.session_state.hist.append(
            {
                "type": "combo",
                "key": key,
                "categories": category_changes,
            }
        )
    else:
        st.session_state.hist.append(
            {
                "type": "cat",
                "key": key,
            }
        )
    save_current_ventas_draft_from_state()


def undo_last_counter_click() -> None:
    if not st.session_state.hist:
        return

    last_action = st.session_state.hist.pop()

    if isinstance(last_action, int):
        key = counter_key("cat", last_action)
        if st.session_state.counts.get(key, 0) > 0:
            st.session_state.counts[key] -= 1
        save_current_ventas_draft_from_state()
        return

    if isinstance(last_action, str):
        if st.session_state.counts.get(last_action, 0) > 0:
            st.session_state.counts[last_action] -= 1
        save_current_ventas_draft_from_state()
        return

    if last_action.get("type") == "combo":
        combo_key = last_action["key"]
        if st.session_state.counts.get(combo_key, 0) > 0:
            st.session_state.counts[combo_key] -= 1

        for category_key, quantity in last_action["categories"]:
            current = st.session_state.counts.get(category_key, 0)
            st.session_state.counts[category_key] = max(0, current - quantity)
        save_current_ventas_draft_from_state()
        return

    key = last_action.get("key")
    if key and st.session_state.counts.get(key, 0) > 0:
        st.session_state.counts[key] -= 1
    save_current_ventas_draft_from_state()


def reset_ventas_form() -> None:
    st.session_state.counts = {}
    st.session_state.hist = []
    st.session_state.ventas_draft = {}
    st.session_state.ventas_draft_loaded = False
    st.session_state.confirm = False
    st.session_state.require_hora_cierre = False
    st.session_state.report_success = True
    st.session_state.ventas_form_version = st.session_state.get("ventas_form_version", 0) + 1


def save_reporte_ventas(
    fecha_reporte,
    local: str,
    turno: int,
    hi,
    hc,
    enc: str,
    cats: list[Categoria],
    combos_list: list[Combo],
) -> None:
    category_rows = []
    combo_rows = []
    fecha_creacion = datetime.combine(fecha_reporte, datetime.min.time())

    for cat in cats:
        category_rows.append(
            {
                "codigo": cat.codigo,
                "descripcion": cat.descripcion,
                "cantidad": int(st.session_state.counts.get(counter_key("cat", cat.codigo), 0)),
            }
        )

    for combo in combos_list:
        combo_rows.append(
            {
                "codigo": combo.codigo,
                "descripcion": combo.descripcion,
                "cantidad": int(st.session_state.counts.get(counter_key("combo", combo.codigo), 0)),
            }
        )

    total_items = sum(row["cantidad"] for row in category_rows)

    db = SessionLocal()
    try:
        existing_report = db.scalar(
            select(ReporteVentaTurno).where(
                ReporteVentaTurno.fecha_creacion == fecha_creacion,
                ReporteVentaTurno.local_descripcion == local,
                ReporteVentaTurno.turno == int(turno),
            )
        )
        if existing_report is not None:
            raise ValueError(
                "Ya existe un reporte cerrado para esa fecha, local y turno. "
                "No se grabo un duplicado."
            )

        reporte = ReporteVentaTurno(
            fecha_creacion=fecha_creacion,
            local_descripcion=local,
            turno=int(turno),
            hora_inicio=hi.strftime("%H:%M"),
            hora_cierre=hc.strftime("%H:%M"),
            encargado=enc.strip(),
            usuario_cierre=st.session_state.username or "",
            total_items=total_items,
            estado="CERRADO",
        )
        db.add(reporte)
        db.flush()

        for row in category_rows:
            db.add(
                ReporteVentaTurnoDetalle(
                    reporte_id=reporte.id,
                    categoria_codigo=row["codigo"],
                    categoria_descripcion=row["descripcion"],
                    cantidad=row["cantidad"],
                )
            )

        for row in combo_rows:
            db.add(
                ReporteVentaTurnoComboDetalle(
                    reporte_id=reporte.id,
                    combo_codigo=row["codigo"],
                    combo_descripcion=row["descripcion"],
                    cantidad=row["cantidad"],
                )
            )

        db.commit()
        clear_ventas_draft(st.session_state.username)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@st.dialog("Informe Ventas por turno", width="large")
def informe_ventas_dialog(reporte_id: int) -> None:
    db = SessionLocal()
    try:
        reporte = db.get(ReporteVentaTurno, reporte_id)
        categorias_detalle = list(
            db.scalars(
                select(ReporteVentaTurnoDetalle)
                .where(ReporteVentaTurnoDetalle.reporte_id == reporte_id)
                .order_by(ReporteVentaTurnoDetalle.categoria_codigo)
            ).all()
        )
        combos_detalle = list(
            db.scalars(
                select(ReporteVentaTurnoComboDetalle)
                .where(ReporteVentaTurnoComboDetalle.reporte_id == reporte_id)
                .order_by(ReporteVentaTurnoComboDetalle.combo_codigo)
            ).all()
        )
    finally:
        db.close()

    if not reporte:
        st.error("Reporte no encontrado.")
        return

    st.subheader("Datos del reporte")
    st.dataframe(
        [
            {
                "Fecha": reporte.fecha_creacion.strftime("%d/%m/%y"),
                "Local": reporte.local_descripcion,
                "Turno": reporte.turno,
                "Hora Inicio (video)": reporte.hora_inicio,
                "Hora Cierre (video)": reporte.hora_cierre,
                "Encargada": reporte.encargado,
            }
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Categorias")
    st.dataframe(
        [
            {
                "Codigo": d.categoria_codigo,
                "Categoria": d.categoria_descripcion,
                "Unidades": d.cantidad,
            }
            for d in categorias_detalle
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Combos")
    st.dataframe(
        [
            {
                "Codigo": d.combo_codigo,
                "Combo": d.combo_descripcion,
                "Unidades": d.cantidad,
            }
            for d in combos_detalle
        ],
        use_container_width=True,
        hide_index=True,
    )


def report_button(label: str, html: str) -> None:
    report_html_b64 = base64.b64encode(html.encode("utf-8")).decode("ascii")
    report_title_json = json.dumps(label).replace("</", "<\\/")
    components.html(
        f"""
        <button id="open-report" type="button">
            {escape(label)}
        </button>
        <script>
            const reportHtmlBase64 = "{report_html_b64}";
            const reportTitle = {report_title_json};
            const button = document.getElementById("open-report");

            button.addEventListener("click", () => {{
                const bytes = Uint8Array.from(atob(reportHtmlBase64), (char) => char.charCodeAt(0));
                const reportHtml = new TextDecoder("utf-8").decode(bytes);
                const mainWindowName = "ControlHavannaMain";
                let appBaseUrl = window.location.origin + window.location.pathname;
                try {{
                    if (window.parent && window.parent !== window) {{
                        window.parent.name = mainWindowName;
                        appBaseUrl = window.parent.location.origin + window.parent.location.pathname;
                    }} else {{
                        window.name = mainWindowName;
                    }}
                }} catch (error) {{
                    window.name = mainWindowName;
                }}
                const reportWindow = window.open("", "_blank");
                if (!reportWindow) {{
                    alert("El navegador bloqueo la ventana del informe. Habilite ventanas emergentes para esta pagina.");
                    return;
                }}
                reportWindow.document.open();
                reportWindow.document.write(reportHtml);
                reportWindow.document.close();
                reportWindow.ControlHavannaAppBaseUrl = appBaseUrl;
                reportWindow.ControlHavannaMainWindowName = mainWindowName;
                reportWindow.document.title = reportTitle;
                reportWindow.focus();
            }});
        </script>
        <style>
            #open-report {{
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 170px;
                min-height: 48px;
                padding: 6px 10px;
                border: 0;
                border-radius: 8px;
                background: #198754;
                color: #FFFFFF;
                font-family: Arial, sans-serif;
                font-size: 14px;
                font-weight: 700;
                text-align: center;
                line-height: 1.25;
                cursor: pointer;
            }}
        </style>
        """,
        height=58,
    )


def printable_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <title>{escape(title)}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            color: #222;
            margin: 28px;
        }}
        h1 {{
            color: #C00000;
            text-align: center;
            margin-bottom: 24px;
        }}
        h2 {{
            margin-top: 26px;
            border-bottom: 2px solid #FFD700;
            padding-bottom: 6px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        th, td {{
            border: 1px solid #CCCCCC;
            padding: 8px 10px;
            text-align: left;
        }}
        th {{
            background: #F2F2F2;
        }}
        .total-row td {{
            background: #F2F2F2;
            font-weight: 700;
        }}
        .actions {{
            text-align: right;
            margin-bottom: 18px;
        }}
        button {{
            background: #198754;
            color: white;
            border: 0;
            border-radius: 6px;
            padding: 10px 18px;
            font-weight: 700;
            cursor: pointer;
        }}
        @media print {{
            .actions {{
                display: none;
            }}
            body {{
                margin: 12mm;
            }}
        }}
    </style>
</head>
<body>
    <div class="actions">
        <button onclick="window.print()">Imprimir</button>
    </div>
    {body}
</body>
</html>"""


def build_informe_ventas_html(reporte_id: int) -> str:
    db = SessionLocal()
    try:
        reporte = db.get(ReporteVentaTurno, reporte_id)
        categorias_detalle = list(
            db.scalars(
                select(ReporteVentaTurnoDetalle)
                .where(ReporteVentaTurnoDetalle.reporte_id == reporte_id)
                .order_by(ReporteVentaTurnoDetalle.categoria_codigo)
            ).all()
        )
        combos_detalle = list(
            db.scalars(
                select(ReporteVentaTurnoComboDetalle)
                .where(ReporteVentaTurnoComboDetalle.reporte_id == reporte_id)
                .order_by(ReporteVentaTurnoComboDetalle.combo_codigo)
            ).all()
        )
    finally:
        db.close()

    if reporte is None:
        return printable_page(
            "Reporte no encontrado",
            "<h1>Reporte no encontrado</h1>",
        )

    datos = f"""
    <h1>Informe Ventas por turno</h1>
    <h2>Datos del reporte</h2>
    <table>
        <tr><th>Fecha</th><td>{escape(reporte.fecha_creacion.strftime("%d/%m/%y"))}</td></tr>
        <tr><th>Local</th><td>{escape(reporte.local_descripcion)}</td></tr>
        <tr><th>Turno</th><td>{reporte.turno}</td></tr>
        <tr><th>Hora Inicio (video)</th><td>{escape(reporte.hora_inicio)}</td></tr>
        <tr><th>Hora Cierre (video)</th><td>{escape(reporte.hora_cierre)}</td></tr>
        <tr><th>Encargada</th><td>{escape(reporte.encargado)}</td></tr>
    </table>
    """

    categorias_rows = "".join(
        f"""
        <tr>
            <td>{detalle.categoria_codigo}</td>
            <td>{escape(detalle.categoria_descripcion)}</td>
            <td>{detalle.cantidad}</td>
        </tr>
        """
        for detalle in categorias_detalle
    )
    total_categorias = sum(int(detalle.cantidad) for detalle in categorias_detalle)
    categorias_rows += f"""
        <tr class="total-row">
            <td colspan="2">Total</td>
            <td>{total_categorias}</td>
        </tr>
    """

    combos_rows = "".join(
        f"""
        <tr>
            <td>{detalle.combo_codigo}</td>
            <td>{escape(detalle.combo_descripcion)}</td>
            <td>{detalle.cantidad}</td>
        </tr>
        """
        for detalle in combos_detalle
    )
    total_combos = sum(int(detalle.cantidad) for detalle in combos_detalle)
    combos_rows += f"""
        <tr class="total-row">
            <td colspan="2">Total</td>
            <td>{total_combos}</td>
        </tr>
    """

    body = f"""
    {datos}
    <h2>Categorias</h2>
    <table>
        <tr><th>Codigo</th><th>Categoria</th><th>Unidades</th></tr>
        {categorias_rows}
    </table>
    <h2>Combos</h2>
    <table>
        <tr><th>Codigo</th><th>Combo</th><th>Unidades</th></tr>
        {combos_rows}
    </table>
    """
    return printable_page("Informe Ventas por turno", body)


def build_check_vs_sistema_html(reporte: ReporteVentaTurno) -> str:
    db = SessionLocal()
    try:
        sistema_articulo_count = db.scalar(
            select(func.count())
            .select_from(ReporteSistemaArticuloDetalle)
            .where(ReporteSistemaArticuloDetalle.reporte_id == reporte.id)
        )
        reporte_categorias = list(
            db.scalars(
                select(ReporteVentaTurnoDetalle)
                .where(ReporteVentaTurnoDetalle.reporte_id == reporte.id)
                .order_by(ReporteVentaTurnoDetalle.categoria_codigo)
            ).all()
        )
        sistema_categorias = list(
            db.scalars(
                select(ReporteSistemaCategoriaDetalle)
                .where(ReporteSistemaCategoriaDetalle.reporte_id == reporte.id)
                .order_by(ReporteSistemaCategoriaDetalle.categoria_codigo)
            ).all()
        )
        reporte_combos = list(
            db.scalars(
                select(ReporteVentaTurnoComboDetalle)
                .where(ReporteVentaTurnoComboDetalle.reporte_id == reporte.id)
                .order_by(ReporteVentaTurnoComboDetalle.combo_codigo)
            ).all()
        )
        sistema_combos = list(
            db.scalars(
                select(ReporteSistemaComboDetalle)
                .where(ReporteSistemaComboDetalle.reporte_id == reporte.id)
                .order_by(ReporteSistemaComboDetalle.combo_codigo)
            ).all()
        )
        sistema_articulos = list(
            db.scalars(
                select(ReporteSistemaArticuloDetalle)
                .where(ReporteSistemaArticuloDetalle.reporte_id == reporte.id)
                .order_by(ReporteSistemaArticuloDetalle.articulo_codigo)
            ).all()
        )
        combos_by_code = {
            combo.codigo: combo
            for combo in db.scalars(select(Combo)).all()
        }
        articulos_no_encontrados = list(
            db.scalars(
                select(ReporteSistemaArticuloDetalle)
                .where(
                    ReporteSistemaArticuloDetalle.reporte_id == reporte.id,
                    ReporteSistemaArticuloDetalle.estado == "ARTICULO NO ENCONTRADO",
                )
                .order_by(ReporteSistemaArticuloDetalle.articulo_codigo)
            ).all()
        )
        check_correcciones = list(
            db.scalars(
                select(ReporteCheckCorreccion)
                .where(ReporteCheckCorreccion.reporte_id == reporte.id)
            ).all()
        )
    finally:
        db.close()

    datos = f"""
    <h1>Informe check vs sistema</h1>
    <h2>Datos del reporte</h2>
    <table>
        <tr><th>Fecha</th><td>{escape(reporte.fecha_creacion.strftime("%d/%m/%y"))}</td></tr>
        <tr><th>Local</th><td>{escape(reporte.local_descripcion)}</td></tr>
        <tr><th>Turno</th><td>{reporte.turno}</td></tr>
        <tr><th>Hora Inicio (video)</th><td>{escape(reporte.hora_inicio)}</td></tr>
        <tr><th>Hora Cierre (video)</th><td>{escape(reporte.hora_cierre)}</td></tr>
        <tr><th>Encargada</th><td>{escape(reporte.encargado)}</td></tr>
    </table>
    """

    if not sistema_articulo_count:
        body = f"""
        {datos}
        <div style="
            margin-top: 24px;
            padding: 16px 18px;
            border: 1px solid #F5C2C7;
            border-radius: 8px;
            background: #F8D7DA;
            color: #842029;
            font-weight: 700;">
            Este reporte todavia no tiene cargado el Control con Sistema.
            Procese primero el archivo Excel desde el boton Control con Sistema y luego vuelva a abrir este informe.
        </div>
        """
        return printable_page("Informe check vs sistema", body)

    def diff_class(reporte_value: int, sistema_value: int) -> str:
        diff = reporte_value - sistema_value
        if diff == 0:
            return "diff-ok"
        if reporte_value == 0:
            return "diff-danger"

        ratio = abs(diff) / abs(reporte_value)
        if ratio <= 0.10:
            return "diff-ok"
        if ratio <= 0.20:
            return "diff-warning"
        return "diff-danger"

    def build_category_drilldown_pages() -> dict[str, str]:
        category_names = {}
        for row in reporte_categorias:
            category_names[row.categoria_codigo] = row.categoria_descripcion
        for row in sistema_categorias:
            category_names[row.categoria_codigo] = row.categoria_descripcion

        contributions: dict[int, list[dict]] = {}
        for articulo in sistema_articulos:
            if articulo.estado != "OK":
                continue

            if articulo.es_combo:
                combo = combos_by_code.get(articulo.combo_codigo)
                if combo is None:
                    continue
                for category_key, quantity in get_combo_category_changes(combo):
                    categoria_codigo = int(category_key.split(":", 1)[1])
                    cantidad_computada = int(articulo.unidades) * int(quantity)
                    contributions.setdefault(categoria_codigo, []).append(
                        {
                            "articulo_codigo": articulo.articulo_codigo,
                            "articulo_nombre": articulo.articulo_nombre,
                            "unidades_archivo": int(articulo.unidades),
                            "multiplicador": int(quantity),
                            "cantidad_computada": cantidad_computada,
                            "origen": "Combo",
                            "combo": f"{combo.codigo} - {combo.descripcion}",
                        }
                    )
            elif articulo.categoria_codigo is not None:
                contributions.setdefault(articulo.categoria_codigo, []).append(
                    {
                        "articulo_codigo": articulo.articulo_codigo,
                        "articulo_nombre": articulo.articulo_nombre,
                        "unidades_archivo": int(articulo.unidades),
                        "multiplicador": 1,
                        "cantidad_computada": int(articulo.unidades),
                        "origen": "Articulo",
                        "combo": "",
                    }
                )

        pages = {}
        for categoria_codigo, rows in contributions.items():
            total = sum(row["cantidad_computada"] for row in rows)
            rows_html = "".join(
                f"""
                <tr>
                    <td>{row["articulo_codigo"]}</td>
                    <td>{escape(row["articulo_nombre"])}</td>
                    <td>{row["unidades_archivo"]}</td>
                    <td>{row["multiplicador"]}</td>
                    <td>{row["cantidad_computada"]}</td>
                    <td>{escape(row["origen"])}</td>
                    <td>{escape(row["combo"])}</td>
                </tr>
                """
                for row in rows
            )
            rows_html += f"""
                <tr class="total-row">
                    <td colspan="4">Total</td>
                    <td>{total}</td>
                    <td colspan="2"></td>
                </tr>
            """
            categoria_nombre = category_names.get(categoria_codigo, "")
            body = f"""
            <h1>Detalle Segun sistema de ventas</h1>
            <h2>Categoria</h2>
            <table>
                <tr><th>Codigo</th><td>{categoria_codigo}</td></tr>
                <tr><th>Descripcion</th><td>{escape(categoria_nombre)}</td></tr>
            </table>
            <h2>Articulos computados</h2>
            <table>
                <tr>
                    <th>Codigo articulo</th>
                    <th>Nombre base Articulos</th>
                    <th>Unidades archivo</th>
                    <th>Multiplicador categoria</th>
                    <th>Cantidad computada</th>
                    <th>Origen</th>
                    <th>Combo</th>
                </tr>
                {rows_html}
            </table>
            """
            pages[f"cat-{categoria_codigo}"] = printable_page(
                f"Detalle categoria {categoria_codigo}",
                body,
            )
        return pages

    def build_combo_drilldown_pages() -> dict[str, str]:
        combo_names = {}
        for row in reporte_combos:
            combo_names[row.combo_codigo] = row.combo_descripcion
        for row in sistema_combos:
            combo_names[row.combo_codigo] = row.combo_descripcion

        contributions: dict[int, list[dict]] = {}
        for articulo in sistema_articulos:
            if articulo.estado != "OK" or not articulo.es_combo or articulo.combo_codigo is None:
                continue

            combo = combos_by_code.get(articulo.combo_codigo)
            combo_descripcion = combo.descripcion if combo else combo_names.get(articulo.combo_codigo, "")
            contributions.setdefault(articulo.combo_codigo, []).append(
                {
                    "articulo_codigo": articulo.articulo_codigo,
                    "articulo_nombre": articulo.articulo_nombre,
                    "unidades_archivo": int(articulo.unidades),
                    "cantidad_computada": int(articulo.unidades),
                    "combo": f"{articulo.combo_codigo} - {combo_descripcion}".strip(),
                }
            )

        pages = {}
        for combo_codigo, rows in contributions.items():
            total = sum(row["cantidad_computada"] for row in rows)
            rows_html = "".join(
                f"""
                <tr>
                    <td>{row["articulo_codigo"]}</td>
                    <td>{escape(row["articulo_nombre"])}</td>
                    <td>{row["unidades_archivo"]}</td>
                    <td>{row["cantidad_computada"]}</td>
                    <td>{escape(row["combo"])}</td>
                </tr>
                """
                for row in rows
            )
            rows_html += f"""
                <tr class="total-row">
                    <td colspan="3">Total</td>
                    <td>{total}</td>
                    <td></td>
                </tr>
            """
            combo_nombre = combo_names.get(combo_codigo, "")
            body = f"""
            <h1>Detalle Segun sistema de ventas</h1>
            <h2>Combo</h2>
            <table>
                <tr><th>Codigo</th><td>{combo_codigo}</td></tr>
                <tr><th>Descripcion</th><td>{escape(combo_nombre)}</td></tr>
            </table>
            <h2>Articulos computados</h2>
            <table>
                <tr>
                    <th>Codigo articulo</th>
                    <th>Nombre base Articulos</th>
                    <th>Unidades archivo</th>
                    <th>Cantidad computada</th>
                    <th>Combo</th>
                </tr>
                {rows_html}
            </table>
            """
            pages[f"combo-{combo_codigo}"] = printable_page(
                f"Detalle combo {combo_codigo}",
                body,
            )
        return pages

    category_drilldown_pages = build_category_drilldown_pages()
    combo_drilldown_pages = build_combo_drilldown_pages()
    drilldown_pages = {**category_drilldown_pages, **combo_drilldown_pages}
    corrections_by_key = {
        (correccion.tipo, correccion.codigo): correccion
        for correccion in check_correcciones
    }

    def build_compare_rows(
        report_rows,
        system_rows,
        report_code_attr: str,
        report_desc_attr: str,
        system_code_attr: str,
        system_desc_attr: str,
        detail_pages: dict[str, str] | None = None,
        detail_prefix: str = "",
        correction_type: str = "",
    ) -> str:
        report_by_code = {
            getattr(row, report_code_attr): row
            for row in report_rows
        }
        system_by_code = {
            getattr(row, system_code_attr): row
            for row in system_rows
        }
        all_codes = sorted(set(report_by_code) | set(system_by_code))

        rows = []
        total_report = 0
        total_system = 0
        total_diff = 0
        for code in all_codes:
            report_row = report_by_code.get(code)
            system_row = system_by_code.get(code)
            descripcion = ""
            if report_row is not None:
                descripcion = getattr(report_row, report_desc_attr)
            elif system_row is not None:
                descripcion = getattr(system_row, system_desc_attr)

            report_qty = int(report_row.cantidad) if report_row is not None else 0
            system_qty = int(system_row.cantidad) if system_row is not None else 0
            correction = corrections_by_key.get((correction_type, code))
            corrected = correction is not None
            display_report_qty = int(correction.cantidad_corregida) if corrected else report_qty
            diff = report_qty - system_qty
            if corrected:
                diff = display_report_qty - system_qty
            total_report += display_report_qty
            total_system += system_qty
            total_diff += diff
            report_label = f"{display_report_qty}*" if corrected else str(display_report_qty)
            report_cell_class = "correction-button corrected-value" if corrected else "correction-button"
            report_cell = (
                f"<button class=\"{report_cell_class}\" type=\"button\" "
                f"onclick='openCorrection({json.dumps(correction_type)}, {int(code)})'>{report_label}</button>"
            )
            detail_key = f"{detail_prefix}-{code}" if detail_pages is not None else ""
            system_cell = str(system_qty)
            if detail_pages is not None and detail_key in detail_pages:
                system_cell = (
                    f"<button class=\"detail-button\" type=\"button\" "
                    f"onclick='openSystemDetail({json.dumps(detail_key)})'>{system_qty}</button>"
                )
            rows.append(
                f"""
                <tr>
                    <td>{code}</td>
                    <td>{escape(descripcion)}</td>
                    <td>{report_cell}</td>
                    <td>{system_cell}</td>
                    <td class="{diff_class(display_report_qty, system_qty)}">{diff}</td>
                </tr>
                """
            )
        rows.append(
            f"""
            <tr class="total-row">
                <td colspan="2">Total</td>
                <td>{total_report}</td>
                <td>{total_system}</td>
                <td>{total_diff}</td>
            </tr>
            """
        )
        return "".join(rows)

    categorias_rows = build_compare_rows(
        reporte_categorias,
        sistema_categorias,
        "categoria_codigo",
        "categoria_descripcion",
        "categoria_codigo",
        "categoria_descripcion",
        category_drilldown_pages,
        "cat",
        "cat",
    )
    combos_rows = build_compare_rows(
        reporte_combos,
        sistema_combos,
        "combo_codigo",
        "combo_descripcion",
        "combo_codigo",
        "combo_descripcion",
        combo_drilldown_pages,
        "combo",
        "combo",
    )
    observaciones_rows = "".join(
        f"""
        <tr>
            <td>{articulo.articulo_codigo}</td>
            <td>{escape(articulo.articulo_nombre)}</td>
            <td>
                El articulo codigo {articulo.articulo_codigo}
                {f" - {escape(articulo.articulo_nombre)}" if articulo.articulo_nombre else ""}
                no se encuentra en la base Articulos.
                Ese codigo no fue computado para el control en razon de no encontrarse en la base Articulos.
            </td>
        </tr>
        """
        for articulo in articulos_no_encontrados
    )
    observaciones_section = ""
    if observaciones_rows:
        observaciones_section = f"""
        <h2>Observaciones</h2>
        <table>
            <tr>
                <th>Codigo articulo</th>
                <th>Descripcion archivo</th>
                <th>Observacion</th>
            </tr>
            {observaciones_rows}
        </table>
        """
    drilldown_json = json.dumps(drilldown_pages)

    body = f"""
    <style>
        .diff-ok {{
            background: #D1E7DD;
        }}
        .diff-warning {{
            background: #FFF3CD;
        }}
        .diff-danger {{
            background: #F8D7DA;
        }}
        .detail-button {{
            width: 100%;
            min-height: 34px;
            border: 1px solid #198754;
            border-radius: 6px;
            background: #FFFFFF;
            color: #198754;
            font-weight: 700;
            cursor: pointer;
        }}
        .detail-button:hover {{
            background: #EAF6EF;
        }}
        .correction-button {{
            width: 100%;
            min-height: 34px;
            border: 1px solid #6C757D;
            border-radius: 6px;
            background: #FFFFFF;
            color: #212529;
            font-weight: 700;
            cursor: pointer;
        }}
        .correction-button:hover {{
            background: #F1F3F5;
        }}
        .corrected-value {{
            border-color: #B58100;
            background: #FFF3CD;
            color: #7A4D00;
        }}
    </style>
    <script>
        const systemDrilldownPages = {drilldown_json};
        function openSystemDetail(key) {{
            const detailHtml = systemDrilldownPages[key];
            if (!detailHtml) {{
                alert("No hay detalle disponible para esta linea.");
                return;
            }}
            const detailWindow = window.open("", "_blank");
            if (!detailWindow) {{
                alert("El navegador bloqueo la ventana del detalle. Habilite ventanas emergentes para esta pagina.");
                return;
            }}
            detailWindow.document.open();
            detailWindow.document.write(detailHtml);
            detailWindow.document.close();
            detailWindow.focus();
        }}
        function openCorrection(tipo, codigo) {{
            const baseUrl = window.ControlHavannaAppBaseUrl
                || (window.opener && window.opener.ControlHavannaAppBaseUrl)
                || (window.location.origin + window.location.pathname);
            const targetName = window.ControlHavannaMainWindowName
                || (window.opener && window.opener.ControlHavannaMainWindowName)
                || "ControlHavannaMain";
            const url = baseUrl
                + "?check_correccion=1"
                + "&reporte_id={reporte.id}"
                + "&tipo=" + encodeURIComponent(tipo)
                + "&codigo=" + encodeURIComponent(codigo);
            const correctionWindow = window.open(url, targetName);
            if (correctionWindow) {{
                correctionWindow.focus();
            }}
        }}
    </script>
    {datos}
    <h2>Categorias</h2>
    <table>
        <tr>
            <th>Codigo</th>
            <th>Categoria</th>
            <th>Segun reporte de ventas</th>
            <th>Segun sistema de ventas</th>
            <th>Diferencias</th>
        </tr>
        {categorias_rows}
    </table>
    <h2>Combos</h2>
    <table>
        <tr>
            <th>Codigo</th>
            <th>Combo</th>
            <th>Segun reporte de ventas</th>
            <th>Segun sistema de ventas</th>
            <th>Diferencias</th>
        </tr>
        {combos_rows}
    </table>
    {observaciones_section}
    """
    return printable_page("Informe check vs sistema", body)


def get_query_param(name: str) -> str | None:
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def is_check_correction_request() -> bool:
    return get_query_param("check_correccion") == "1"


def render_check_correccion_page() -> None:
    reporte_id_raw = get_query_param("reporte_id")
    tipo = get_query_param("tipo")
    codigo_raw = get_query_param("codigo")

    try:
        reporte_id = int(reporte_id_raw or "")
        codigo = int(codigo_raw or "")
    except ValueError:
        st.error("Solicitud de correccion invalida.")
        return

    if tipo not in {"cat", "combo"}:
        st.error("Tipo de correccion invalido.")
        return

    db = SessionLocal()
    try:
        reporte = db.get(ReporteVentaTurno, reporte_id)
        if reporte is None:
            st.error("Reporte no encontrado.")
            return

        if tipo == "cat":
            detalle = db.scalar(
                select(ReporteVentaTurnoDetalle).where(
                    ReporteVentaTurnoDetalle.reporte_id == reporte_id,
                    ReporteVentaTurnoDetalle.categoria_codigo == codigo,
                )
            )
            sistema = db.scalar(
                select(ReporteSistemaCategoriaDetalle).where(
                    ReporteSistemaCategoriaDetalle.reporte_id == reporte_id,
                    ReporteSistemaCategoriaDetalle.categoria_codigo == codigo,
                )
            )
            tipo_titulo = "Categoria"
            descripcion = ""
            cantidad_original = 0
            if detalle is not None:
                descripcion = detalle.categoria_descripcion
                cantidad_original = int(detalle.cantidad)
            elif sistema is not None:
                descripcion = sistema.categoria_descripcion
        else:
            detalle = db.scalar(
                select(ReporteVentaTurnoComboDetalle).where(
                    ReporteVentaTurnoComboDetalle.reporte_id == reporte_id,
                    ReporteVentaTurnoComboDetalle.combo_codigo == codigo,
                )
            )
            sistema = db.scalar(
                select(ReporteSistemaComboDetalle).where(
                    ReporteSistemaComboDetalle.reporte_id == reporte_id,
                    ReporteSistemaComboDetalle.combo_codigo == codigo,
                )
            )
            tipo_titulo = "Combo"
            descripcion = ""
            cantidad_original = 0
            if detalle is not None:
                descripcion = detalle.combo_descripcion
                cantidad_original = int(detalle.cantidad)
            elif sistema is not None:
                descripcion = sistema.combo_descripcion

        correccion_existente = db.scalar(
            select(ReporteCheckCorreccion).where(
                ReporteCheckCorreccion.reporte_id == reporte_id,
                ReporteCheckCorreccion.tipo == tipo,
                ReporteCheckCorreccion.codigo == codigo,
            )
        )
    finally:
        db.close()

    st.title("Correccion informe check vs sistema")
    st.subheader(tipo_titulo)
    st.dataframe(
        [
            {
                "Reporte": reporte_id,
                "Tipo": tipo_titulo,
                "Codigo": codigo,
                "Descripcion": descripcion,
                "Cantidad original": cantidad_original,
            }
        ],
        use_container_width=True,
        hide_index=True,
    )

    if correccion_existente is not None:
        st.warning("No se admiten mas modificaciones para esta linea.")
        st.subheader("Correccion registrada")
        st.dataframe(
            [
                {
                    "Valor original": correccion_existente.cantidad_original,
                    "Correccion": correccion_existente.correccion,
                    "Valor corregido": correccion_existente.cantidad_corregida,
                    "Explicacion": correccion_existente.detalle,
                    "Usuario": correccion_existente.usuario,
                    "Fecha": correccion_existente.created_at.strftime("%d/%m/%y %H:%M"),
                }
            ],
            use_container_width=True,
            hide_index=True,
        )
        return

    st.info("Esta correccion se puede guardar una sola vez para esta linea.")
    correccion = st.number_input(
        "Correccion (+/-)",
        step=1,
        value=0,
        key=f"check_correccion_delta_{tipo}_{codigo}",
    )
    cantidad_corregida = cantidad_original + int(correccion)
    st.write(f"Cantidad corregida: {cantidad_corregida}")
    detalle_texto = st.text_input(
        "Detalle de la correccion",
        max_chars=50,
        key=f"check_correccion_detalle_{tipo}_{codigo}",
    )

    if st.button("Guardar", key=f"guardar_check_correccion_{tipo}_{codigo}"):
        if int(correccion) == 0:
            st.error("Debe consignar una correccion distinta de cero.")
            return
        if cantidad_corregida < 0:
            st.error("La cantidad corregida no puede ser negativa.")
            return
        if not detalle_texto.strip():
            st.error("Debe consignar un detalle de la correccion.")
            return

        db = SessionLocal()
        try:
            existente = db.scalar(
                select(ReporteCheckCorreccion).where(
                    ReporteCheckCorreccion.reporte_id == reporte_id,
                    ReporteCheckCorreccion.tipo == tipo,
                    ReporteCheckCorreccion.codigo == codigo,
                )
            )
            if existente is not None:
                st.warning("No se admiten mas modificaciones para esta linea.")
                return

            db.add(
                ReporteCheckCorreccion(
                    reporte_id=reporte_id,
                    tipo=tipo,
                    codigo=codigo,
                    descripcion=descripcion,
                    cantidad_original=cantidad_original,
                    correccion=int(correccion),
                    cantidad_corregida=cantidad_corregida,
                    detalle=detalle_texto.strip(),
                    usuario=st.session_state.get("username") or "usuario no identificado",
                )
            )
            db.commit()
            st.success("Correccion guardada correctamente. Vuelva a abrir el Informe check vs sistema para ver el valor actualizado.")
            st.rerun()
        except IntegrityError:
            db.rollback()
            st.warning("No se admiten mas modificaciones para esta linea.")
        finally:
            db.close()


def normalize_excel_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(column).strip().upper() for column in out.columns]
    return out


def find_articulo_description_column(df: pd.DataFrame) -> str | None:
    candidates = [
        "NOMBRE",
        "DESCRIPCION",
        "DESCRIPCIÓN",
        "ARTICULO",
        "ARTÍCULO",
        "NOMBRE ARTICULO",
        "NOMBRE ARTÍCULO",
    ]
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return None


def process_control_sistema_excel(reporte_id: int, uploaded_file) -> dict:
    df = pd.read_excel(uploaded_file)
    df = normalize_excel_columns(df)

    required = {"CODIGO", "UNIDADES"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError("El archivo debe tener las columnas CODIGO y UNIDADES.")

    description_column = find_articulo_description_column(df)
    work_columns = ["CODIGO", "UNIDADES"]
    if description_column:
        work_columns.append(description_column)

    df = df[work_columns].dropna(subset=["CODIGO", "UNIDADES"])
    df["CODIGO"] = pd.to_numeric(df["CODIGO"], errors="coerce")
    df["UNIDADES"] = pd.to_numeric(df["UNIDADES"], errors="coerce")
    df = df.dropna(subset=["CODIGO", "UNIDADES"])
    df["CODIGO"] = df["CODIGO"].astype(int)
    df["UNIDADES"] = df["UNIDADES"].astype(int)
    df = df[df["UNIDADES"] != 0]
    if description_column:
        df[description_column] = df[description_column].fillna("").astype(str).str.strip()
    else:
        df["DESCRIPCION_ARCHIVO"] = ""
        description_column = "DESCRIPCION_ARCHIVO"

    ventas_por_articulo = df.groupby("CODIGO", as_index=False).agg(
        UNIDADES=("UNIDADES", "sum"),
        DESCRIPCION_ARCHIVO=(description_column, "first"),
    ).sort_values("CODIGO")

    db = SessionLocal()
    try:
        articulos = {
            articulo.codigo: articulo
            for articulo in db.scalars(select(Articulo)).all()
        }
        categorias = {
            categoria.codigo: categoria
            for categoria in db.scalars(select(Categoria)).all()
        }
        combos = {
            combo.codigo: combo
            for combo in db.scalars(select(Combo)).all()
        }

        db.query(ReporteSistemaArticuloDetalle).filter(
            ReporteSistemaArticuloDetalle.reporte_id == reporte_id
        ).delete()
        db.query(ReporteSistemaCategoriaDetalle).filter(
            ReporteSistemaCategoriaDetalle.reporte_id == reporte_id
        ).delete()
        db.query(ReporteSistemaComboDetalle).filter(
            ReporteSistemaComboDetalle.reporte_id == reporte_id
        ).delete()

        category_totals: dict[int, int] = {}
        combo_totals: dict[int, int] = {}
        unknown_count = 0

        for _, row in ventas_por_articulo.iterrows():
            codigo = int(row["CODIGO"])
            unidades = int(row["UNIDADES"])
            descripcion_archivo = str(row["DESCRIPCION_ARCHIVO"]).strip()
            articulo = articulos.get(codigo)

            if articulo is None:
                unknown_count += 1
                db.add(
                    ReporteSistemaArticuloDetalle(
                        reporte_id=reporte_id,
                        articulo_codigo=codigo,
                        articulo_nombre=descripcion_archivo,
                        unidades=unidades,
                        es_combo=False,
                        categoria_codigo=None,
                        combo_codigo=None,
                        estado="ARTICULO NO ENCONTRADO",
                    )
                )
                continue

            if articulo.es_combo:
                combo = combos.get(articulo.combo_codigo)
                db.add(
                    ReporteSistemaArticuloDetalle(
                        reporte_id=reporte_id,
                        articulo_codigo=codigo,
                        articulo_nombre=articulo.nombre,
                        unidades=unidades,
                        es_combo=True,
                        categoria_codigo=None,
                        combo_codigo=articulo.combo_codigo,
                        estado="OK" if combo else "COMBO NO ENCONTRADO",
                    )
                )

                if combo is None:
                    unknown_count += 1
                    continue

                combo_totals[combo.codigo] = combo_totals.get(combo.codigo, 0) + unidades
                for category_key, quantity in get_combo_category_changes(combo):
                    categoria_codigo = int(category_key.split(":", 1)[1])
                    category_totals[categoria_codigo] = (
                        category_totals.get(categoria_codigo, 0) + unidades * quantity
                    )
            else:
                db.add(
                    ReporteSistemaArticuloDetalle(
                        reporte_id=reporte_id,
                        articulo_codigo=codigo,
                        articulo_nombre=articulo.nombre,
                        unidades=unidades,
                        es_combo=False,
                        categoria_codigo=articulo.categoria_codigo,
                        combo_codigo=None,
                        estado="OK" if articulo.categoria_codigo else "CATEGORIA NO ENCONTRADA",
                    )
                )

                if articulo.categoria_codigo is None:
                    unknown_count += 1
                    continue

                category_totals[articulo.categoria_codigo] = (
                    category_totals.get(articulo.categoria_codigo, 0) + unidades
                )

        for categoria_codigo, cantidad in sorted(category_totals.items()):
            categoria = categorias.get(categoria_codigo)
            db.add(
                ReporteSistemaCategoriaDetalle(
                    reporte_id=reporte_id,
                    categoria_codigo=categoria_codigo,
                    categoria_descripcion=categoria.descripcion if categoria else "",
                    cantidad=cantidad,
                )
            )

        for combo_codigo, cantidad in sorted(combo_totals.items()):
            combo = combos.get(combo_codigo)
            db.add(
                ReporteSistemaComboDetalle(
                    reporte_id=reporte_id,
                    combo_codigo=combo_codigo,
                    combo_descripcion=combo.descripcion if combo else "",
                    cantidad=cantidad,
                )
            )

        db.commit()
        return {
            "articulos_procesados": int(len(ventas_por_articulo)),
            "categorias_generadas": int(len(category_totals)),
            "combos_generados": int(len(combo_totals)),
            "observaciones": int(unknown_count),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def count_control_sistema_rows(reporte_id: int) -> int:
    db = SessionLocal()
    try:
        articulo_count = db.scalar(
            select(func.count())
            .select_from(ReporteSistemaArticuloDetalle)
            .where(ReporteSistemaArticuloDetalle.reporte_id == reporte_id)
        )
        categoria_count = db.scalar(
            select(func.count())
            .select_from(ReporteSistemaCategoriaDetalle)
            .where(ReporteSistemaCategoriaDetalle.reporte_id == reporte_id)
        )
        combo_count = db.scalar(
            select(func.count())
            .select_from(ReporteSistemaComboDetalle)
            .where(ReporteSistemaComboDetalle.reporte_id == reporte_id)
        )
        return int((articulo_count or 0) + (categoria_count or 0) + (combo_count or 0))
    finally:
        db.close()


def current_user_is_admin() -> bool:
    username = st.session_state.get("username")
    if not username:
        return False

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == username))
        return bool(user and user.role == "admin")
    finally:
        db.close()


def delete_reporte_cerrado(reporte_id: int) -> None:
    db = SessionLocal()
    try:
        db.query(ReporteSistemaArticuloDetalle).filter(
            ReporteSistemaArticuloDetalle.reporte_id == reporte_id
        ).delete(synchronize_session=False)
        db.query(ReporteSistemaCategoriaDetalle).filter(
            ReporteSistemaCategoriaDetalle.reporte_id == reporte_id
        ).delete(synchronize_session=False)
        db.query(ReporteSistemaComboDetalle).filter(
            ReporteSistemaComboDetalle.reporte_id == reporte_id
        ).delete(synchronize_session=False)
        db.query(ReporteCheckCorreccion).filter(
            ReporteCheckCorreccion.reporte_id == reporte_id
        ).delete(synchronize_session=False)
        db.query(ReporteVentaTurnoDetalle).filter(
            ReporteVentaTurnoDetalle.reporte_id == reporte_id
        ).delete(synchronize_session=False)
        db.query(ReporteVentaTurnoComboDetalle).filter(
            ReporteVentaTurnoComboDetalle.reporte_id == reporte_id
        ).delete(synchronize_session=False)

        reporte = db.get(ReporteVentaTurno, reporte_id)
        if reporte is not None:
            db.delete(reporte)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def find_duplicate_report_cleanup_groups(reportes: list[ReporteVentaTurno]) -> list[dict]:
    grouped: dict[tuple, list[ReporteVentaTurno]] = {}
    for reporte in reportes:
        key = (reporte.fecha_creacion, reporte.local_descripcion, int(reporte.turno))
        grouped.setdefault(key, []).append(reporte)

    cleanup_groups = []
    for (fecha, local, turno), group in grouped.items():
        if len(group) <= 1:
            continue

        system_counts = {
            reporte.id: count_control_sistema_rows(int(reporte.id))
            for reporte in group
        }
        keepers = [reporte for reporte in group if system_counts[reporte.id] > 0]
        deletable = [reporte for reporte in group if system_counts[reporte.id] == 0]

        if len(keepers) == 1 and deletable:
            cleanup_groups.append(
                {
                    "fecha": fecha,
                    "local": local,
                    "turno": turno,
                    "keep": keepers[0],
                    "delete": sorted(deletable, key=lambda reporte: reporte.id),
                }
            )

    return cleanup_groups


def render_duplicate_cleanup(reportes: list[ReporteVentaTurno]) -> None:
    if not current_user_is_admin():
        return

    cleanup_groups = find_duplicate_report_cleanup_groups(reportes)
    if not cleanup_groups:
        return

    with st.expander("Limpieza de reportes duplicados"):
        st.warning(
            "Se detectaron reportes con la misma fecha, local y turno. "
            "Solo se puede eliminar automaticamente cuando existe un unico reporte "
            "con Control con Sistema y los demas no lo tienen."
        )

        for group in cleanup_groups:
            keep = group["keep"]
            delete_ids = [int(reporte.id) for reporte in group["delete"]]
            group_key = (
                f"{group['fecha'].strftime('%Y%m%d')}_"
                f"{group['local']}_{group['turno']}_{keep.id}"
            )
            st.write(
                f"{group['fecha'].strftime('%d/%m/%y')} | "
                f"{group['local']} | Turno {group['turno']} | "
                f"se conserva reporte {keep.id}; se eliminan {delete_ids}."
            )
            confirmed = st.checkbox(
                "Confirmar eliminacion",
                key=f"confirm_cleanup_{group_key}",
            )
            if st.button(
                "Eliminar duplicados sin Control con Sistema",
                key=f"delete_cleanup_{group_key}",
                disabled=not confirmed,
            ):
                try:
                    for reporte_id in delete_ids:
                        delete_reporte_cerrado(reporte_id)
                    st.success("Reportes duplicados eliminados correctamente.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"No se pudieron eliminar los duplicados: {exc}")


def process_control_sistema_and_refresh(reporte_id: int, uploaded_file) -> None:
    result = process_control_sistema_excel(reporte_id, uploaded_file)
    st.session_state.control_sistema_last_result = {
        "reporte_id": reporte_id,
        **result,
    }
    st.rerun()


@st.dialog("Control con Sistema")
def control_sistema_dialog(reporte_id: int) -> None:
    st.write("Suba el archivo Excel exportado desde el sistema de ventas.")
    uploaded_file = st.file_uploader(
        "Archivo Excel",
        type=["xlsx", "xls"],
        key=f"control_sistema_upload_{reporte_id}",
    )

    if uploaded_file is None:
        return

    existing_rows = count_control_sistema_rows(reporte_id)
    if existing_rows:
        st.warning("Archivos ya procesados, desea continuar?")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("Si", key=f"confirmar_reproceso_control_sistema_{reporte_id}"):
                try:
                    process_control_sistema_and_refresh(reporte_id, uploaded_file)
                except Exception as exc:
                    st.error(f"No se pudo procesar el archivo: {exc}")
        with col_no:
            if st.button("No", key=f"cancelar_reproceso_control_sistema_{reporte_id}"):
                st.info("No se proceso el archivo. Se conservan los datos existentes.")
        return

    if st.button("Procesar archivo", key=f"procesar_control_sistema_{reporte_id}"):
        try:
            process_control_sistema_and_refresh(reporte_id, uploaded_file)
        except Exception as exc:
            st.error(f"No se pudo procesar el archivo: {exc}")


def render_counter_group(
    title: str,
    item_type: str,
    items: list,
    columns_per_row: int = 6,
) -> None:
    with st.container(border=True):
        st.subheader(title)

        if not items:
            st.info(f"No hay {title.lower()} cargados.")
            return

        for start in range(0, len(items), columns_per_row):
            row_items = items[start : start + columns_per_row]
            cols = st.columns(columns_per_row)

            for offset, (col, item) in enumerate(zip(cols, row_items)):
                item_index = start + offset
                key = counter_key(item_type, item.codigo)
                old_category_key = item.codigo if item_type == "cat" else None
                if old_category_key is not None and old_category_key in st.session_state.counts:
                    st.session_state.counts.setdefault(
                        key,
                        st.session_state.counts[old_category_key],
                    )
                else:
                    st.session_state.counts.setdefault(key, 0)

                bg = get_group_color(item_type, item, item_index)
                txt = get_text_color(bg)
                count = st.session_state.counts[key]
                button_key = f"sumar_{item_type}_{item.codigo}"
                border = (
                    "1px solid #D0D0D0"
                    if bg.upper() == "#FFFFFF" or item.descripcion.upper() == "OTROS"
                    else "none"
                )

                with col:
                    st.markdown(
                        f"""
                        <style>
                        div[data-testid="stElementContainer"]:has(.counter-card-{item_type}-{item.codigo}),
                        div.element-container:has(.counter-card-{item_type}-{item.codigo}) {{
                            display: none !important;
                        }}

                        div[data-testid="stElementContainer"]:has(.counter-card-{item_type}-{item.codigo}) + div[data-testid="stElementContainer"] button,
                        div.element-container:has(.counter-card-{item_type}-{item.codigo}) + div.element-container button,
                        .st-key-{button_key} button,
                        .counter-card-{item_type}-{item.codigo} + div[data-testid="stButton"] > button {{
                            background: {bg} !important;
                            color: {txt} !important;
                            border: {border} !important;
                            height: 192px !important;
                            min-height: 192px !important;
                            width: 120px !important;
                            min-width: 120px !important;
                            max-width: 120px !important;
                            border-radius: 8px !important;
                            padding: 10px !important;
                            white-space: pre-line !important;
                            text-align: center !important;
                            font-weight: 700 !important;
                            box-shadow: none !important;
                        }}
                        div[data-testid="stElementContainer"]:has(.counter-card-{item_type}-{item.codigo}) + div[data-testid="stElementContainer"] div[data-testid="stButton"],
                        div.element-container:has(.counter-card-{item_type}-{item.codigo}) + div.element-container div[data-testid="stButton"],
                        .st-key-{button_key},
                        .counter-card-{item_type}-{item.codigo} + div[data-testid="stButton"] {{
                            display: flex !important;
                            justify-content: center !important;
                        }}
                        div[data-testid="stElementContainer"]:has(.counter-card-{item_type}-{item.codigo}) + div[data-testid="stElementContainer"] button p,
                        div.element-container:has(.counter-card-{item_type}-{item.codigo}) + div.element-container button p,
                        .st-key-{button_key} button p,
                        .counter-card-{item_type}-{item.codigo} + div[data-testid="stButton"] > button p {{
                            color: {txt} !important;
                            white-space: pre-line !important;
                            font-size: 15px !important;
                            line-height: 1.35 !important;
                        }}
                        div[data-testid="stElementContainer"]:has(.counter-card-{item_type}-{item.codigo}) + div[data-testid="stElementContainer"] button strong,
                        div.element-container:has(.counter-card-{item_type}-{item.codigo}) + div.element-container button strong,
                        .st-key-{button_key} button strong,
                        .counter-card-{item_type}-{item.codigo} + div[data-testid="stButton"] > button strong {{
                            color: {txt} !important;
                            font-size: 20px !important;
                            font-weight: 800 !important;
                        }}
                        div[data-testid="stElementContainer"]:has(.counter-card-{item_type}-{item.codigo}) + div[data-testid="stElementContainer"] button:hover,
                        div.element-container:has(.counter-card-{item_type}-{item.codigo}) + div.element-container button:hover,
                        .st-key-{button_key} button:hover,
                        .counter-card-{item_type}-{item.codigo} + div[data-testid="stButton"] > button:hover {{
                            filter: brightness(0.96);
                        }}
                        div[data-testid="stElementContainer"]:has(.counter-card-{item_type}-{item.codigo}) + div[data-testid="stElementContainer"] button:active,
                        div.element-container:has(.counter-card-{item_type}-{item.codigo}) + div.element-container button:active,
                        .st-key-{button_key} button:active,
                        .counter-card-{item_type}-{item.codigo} + div[data-testid="stButton"] > button:active {{
                            filter: brightness(0.92);
                        }}
                        </style>
                        <span class="counter-card-style counter-card-{item_type}-{item.codigo}"></span>
                        """,
                        unsafe_allow_html=True,
                    )

                    label = f"{item.descripcion}\n\n**{count}**"
                    if st.button(label, key=button_key):
                        apply_counter_click(item_type, item, key)
                        st.rerun()


def render_combo_quick_lookup(combos_list: list[Combo], combo_articles: list[Articulo]) -> None:
    with st.container(border=True):
        st.subheader("Consulta rapida de combos")

        if not combo_articles:
            st.info("No hay articulos vinculados a combos.")
            return

        combo_by_code = {combo.codigo: combo for combo in combos_list}

        selected_article = st.selectbox(
            "Articulo",
            combo_articles,
            format_func=lambda article: f"{article.codigo} - {article.nombre}",
            key="ventas_combo_lookup",
        )

        combo = combo_by_code.get(selected_article.combo_codigo)

        if combo:
            st.write(f"Tarjeta a clickear: {combo.codigo} - {combo.descripcion}")
        else:
            st.write("El articulo seleccionado no tiene un combo valido asociado.")


def ventas() -> None:
    st.title("Ventas por turno")
    version = st.session_state.get("ventas_form_version", 0)

    db = SessionLocal()
    try:
        cats = list(db.scalars(select(Categoria).order_by(Categoria.codigo)).all())
        combos_list = list(db.scalars(select(Combo).order_by(Combo.codigo)).all())
        locs = list(db.scalars(select(Local).order_by(Local.descripcion)).all())
        combo_articles = list(
            db.scalars(
                select(Articulo)
                .where(Articulo.es_combo == True, Articulo.combo_codigo.is_not(None))
                .order_by(Articulo.nombre)
            ).all()
        )
    finally:
        db.close()

    draft = st.session_state.get("ventas_draft") or {}
    draft_local = draft.get("local", "")
    local_options = ["", *[l.descripcion for l in locs]]
    if draft_local and draft_local not in local_options:
        local_options.append(draft_local)
    draft_fecha = parse_draft_date(draft.get("fecha", ""))
    draft_hora_inicio = parse_draft_time(draft.get("hora_inicio", ""))
    draft_hora_cierre = parse_draft_time(draft.get("hora_cierre", ""))
    draft_turno = int(draft.get("turno", 1) or 1)
    draft_encargado = draft.get("encargado", "")

    st.markdown(
        """
        <style>
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("Datos del Turno")

    if st.session_state.get("report_success"):
        st.markdown(
            """
            <div style="
                max-width: 520px;
                margin: 0 auto 18px auto;
                padding: 18px 22px;
                border: 2px solid #198754;
                border-radius: 8px;
                background: #EAF7EF;
                color: #0F5132;
                text-align: center;
                font-size: 24px;
                font-weight: 800;">
                CIERRE DE REPORTE EXITOSO
            </div>
            """,
            unsafe_allow_html=True,
        )

    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        local = st.selectbox(
            "Locales",
            local_options,
            index=local_options.index(draft_local) if draft_local in local_options else 0,
            key=f"ventas_local_{version}",
        )
    with c2:
        fecha = st.date_input(
            "Fecha",
            value=draft_fecha,
            format="DD/MM/YYYY",
            key=f"ventas_fecha_{version}",
        )
    with c3:
        turno = st.number_input(
            "Turno",
            min_value=1,
            step=1,
            value=draft_turno,
            key=f"ventas_turno_{version}",
        )
    with c4:
        hi = st.time_input(
            "Hora Inicio (video)",
            value=draft_hora_inicio,
            key=f"hora_inicio_video_{version}",
        )
    with c5:
        hc = st.time_input(
            "Hora Cierre (video)",
            value=draft_hora_cierre,
            key=f"hora_cierre_video_{version}",
        )

    if hc is not None:
        st.session_state.require_hora_cierre = False

    enc = st.text_input(
        "Encargado",
        value=draft_encargado,
        max_chars=30,
        key=f"ventas_encargado_{version}",
    )

    st.divider()

    st.markdown(
        '<div class="ventas-note">Haga clic con el mouse sobre cada categoria o combo. Cada clic suma 1 item al contador correspondiente.</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <style>
        div[data-testid="stElementContainer"]:has(.volver-atras-marker),
        div.element-container:has(.volver-atras-marker),
        div[data-testid="stElementContainer"]:has(.cerrar-reporte-marker),
        div.element-container:has(.cerrar-reporte-marker) {
            display: none !important;
        }

        div[data-testid="stElementContainer"]:has(.volver-atras-marker) + div[data-testid="stElementContainer"] button,
        div.element-container:has(.volver-atras-marker) + div.element-container button {
            background: #198754 !important;
            color: #FFFFFF !important;
            font-weight: 700 !important;
            width: 180px !important;
            height: 50px !important;
            border: 1px solid #146C43 !important;
            border-radius: 8px !important;
        }

        div[data-testid="stElementContainer"]:has(.cerrar-reporte-marker) + div[data-testid="stElementContainer"] button,
        div.element-container:has(.cerrar-reporte-marker) + div.element-container button {
            background: #FF4D4D !important;
            color: #FFFFFF !important;
            font-weight: 700 !important;
            width: 180px !important;
            height: 50px !important;
            border: 1px solid #D93636 !important;
            border-radius: 8px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col_a, col_b, _ = st.columns([1, 1, 6])

    with col_a:
        st.markdown('<span class="volver-atras-marker"></span>', unsafe_allow_html=True)
        volver = st.button("VOLVER ATRAS", key="volver_atras_ventas")

    with col_b:
        st.markdown('<span class="cerrar-reporte-marker"></span>', unsafe_allow_html=True)
        cerrar = st.button("CERRAR REPORTE", key="cerrar_reporte_ventas")

    if volver:
        undo_last_counter_click()
        st.rerun()

    if cerrar:
        if not local:
            st.warning("Debe seleccionar un local para cerrar el reporte.")
        elif fecha is None:
            st.warning("Debe completar Fecha para cerrar el reporte.")
        elif hi is None:
            st.warning("Debe completar Hora Inicio (video) para cerrar el reporte.")
        elif not enc.strip():
            st.warning("Debe completar Encargado para cerrar el reporte.")
        elif hc is None:
            st.session_state.require_hora_cierre = True
        else:
            st.session_state.confirm = True
            st.rerun()

    if st.session_state.require_hora_cierre and hc is None:
        st.warning("Debe completar Hora Cierre (video) para cerrar el reporte.")

    if st.session_state.confirm:
        _, centro, _ = st.columns([2, 4, 2])
        with centro:
            st.markdown(
                """
                <div class="confirm">
                    Esta por cerrar el reporte.<br>
                    Esta accion no puede ser vuelta atras.<br><br>
                    ¿Está seguro?
                </div>
                """,
                unsafe_allow_html=True,
            )

            s, n = st.columns(2)

            with s:
                if st.button("SI"):
                    try:
                        save_reporte_ventas(fecha, local, turno, hi, hc, enc, cats, combos_list)
                    except ValueError as exc:
                        st.session_state.confirm = False
                        st.error(str(exc))
                    except Exception as exc:
                        st.session_state.confirm = False
                        st.error(f"No se pudo cerrar el reporte: {exc}")
                    else:
                        reset_ventas_form()
                        st.rerun()

            with n:
                if st.button("NO"):
                    st.session_state.confirm = False
                    st.rerun()

    st.divider()

    render_counter_group("Categorias", "cat", cats)
    render_counter_group("Combos", "combo", combos_list)
    render_combo_quick_lookup(combos_list, combo_articles)
    save_ventas_draft(st.session_state.username, local, fecha, turno, hi, hc, enc)


def inicio() -> None:
    title_col, logout_col = st.columns([5, 1])
    with title_col:
        st.title("Inicio")
    with logout_col:
        st.write("")
        if st.button("Log out", key="logout_inicio"):
            logout()

    st.write("Seleccione una opcion del menu.")

    opciones = [
        "Inicio",
        "Ventas por turno",
        "Configuracion",
        "Consultas",
        "Reportes cerrados",
    ]

    seleccion = st.selectbox(
        "Menu Inicio",
        opciones,
        index=opciones.index(st.session_state.home_menu)
        if st.session_state.home_menu in opciones
        else 0,
    )

    st.session_state.home_menu = seleccion

    if seleccion == "Inicio":
        st.info("Seleccione una opcion del menu desplegable.")
        return

    if seleccion == "Ventas por turno":
        if st.button("Ingresar a Ventas por turno"):
            st.session_state.page = "Ventas por turno"
            st.rerun()
        return

    if seleccion == "Reportes cerrados":
        if st.button("Ver reportes cerrados"):
            st.session_state.page = "Reportes cerrados"
            st.rerun()
        return

    if seleccion == "Consultas":
        render_consultas_body()
        return

    if seleccion == "Configuracion":
        opciones_config = ["Seleccionar", "Categorias", "Articulos", "Locales", "Usuarios", "Combos"]
        config = st.selectbox(
            "Configuracion",
            opciones_config,
            index=opciones_config.index(st.session_state.config_menu)
            if st.session_state.config_menu in opciones_config
            else 0,
        )
        st.session_state.config_menu = config

        if config == "Seleccionar":
            st.info("Seleccione una opcion de configuracion.")
            return

        st.subheader(config)
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Crear", key=f"crear_{config}_config"):
                st.session_state.page = config
                st.session_state.home_action = "Crear"
                st.rerun()
        with c2:
            if st.button("Modificar", key=f"modificar_{config}_config"):
                st.session_state.page = config
                st.session_state.home_action = "Modificar"
                st.rerun()
        with c3:
            if st.button("Eliminar", key=f"eliminar_{config}_config"):
                st.session_state.page = config
                st.session_state.home_action = "Eliminar"
                st.rerun()
        return

    st.subheader(seleccion)
    c1, c2, c3 = st.columns(3)

    with c1:
        if st.button("Crear", key=f"crear_{seleccion}"):
            st.session_state.page = seleccion
            st.session_state.home_action = "Crear"
            st.rerun()

    with c2:
        if st.button("Modificar", key=f"modificar_{seleccion}"):
            st.session_state.page = seleccion
            st.session_state.home_action = "Modificar"
            st.rerun()

    with c3:
        if st.button("Eliminar", key=f"eliminar_{seleccion}"):
            st.session_state.page = seleccion
            st.session_state.home_action = "Eliminar"
            st.rerun()


def configuracion() -> None:
    st.title("Configuracion")

    opciones_config = ["Seleccionar", "Categorias", "Articulos", "Locales", "Usuarios", "Combos"]
    config = st.selectbox(
        "Configuracion",
        opciones_config,
        index=opciones_config.index(st.session_state.config_menu)
        if st.session_state.config_menu in opciones_config
        else 0,
    )
    st.session_state.config_menu = config

    if config == "Seleccionar":
        st.info("Seleccione una opcion de configuracion.")
        return

    if config == "Categorias":
        categorias()
    elif config == "Articulos":
        articulos()
    elif config == "Locales":
        locales()
    elif config == "Usuarios":
        usuarios()
    elif config == "Combos":
        combos()


def consulta_articulos_por_categoria() -> None:
    db = SessionLocal()
    try:
        categorias_list = list(db.scalars(select(Categoria).order_by(Categoria.codigo)).all())

        if not categorias_list:
            st.info("No hay categorias cargadas.")
            return

        categoria = st.selectbox(
            "Categoria",
            categorias_list,
            format_func=lambda c: f"{c.codigo} - {c.descripcion}",
            key="consulta_categoria_articulos_categoria",
        )

        articulos_list = list(
            db.scalars(
                select(Articulo)
                .where(Articulo.categoria_codigo == categoria.codigo)
                .order_by(Articulo.codigo)
            ).all()
        )
    finally:
        db.close()

    st.subheader(f"Articulos de la categoria {categoria.codigo} - {categoria.descripcion}")
    if not articulos_list:
        st.info("No hay articulos asociados a esta categoria.")
        return

    st.dataframe(
        [
            {
                "Codigo articulo": articulo.codigo,
                "Descripcion articulo": articulo.nombre,
                "Codigo categoria": categoria.codigo,
                "Descripcion categoria": categoria.descripcion,
            }
            for articulo in articulos_list
        ],
        use_container_width=True,
        hide_index=True,
    )


def consulta_categoria_por_articulo() -> None:
    db = SessionLocal()
    try:
        articulos_list = list(db.scalars(select(Articulo).order_by(Articulo.codigo)).all())
        categorias_by_code = {
            categoria.codigo: categoria
            for categoria in db.scalars(select(Categoria)).all()
        }
        combos_by_code = {
            combo.codigo: combo
            for combo in db.scalars(select(Combo)).all()
        }

        if not articulos_list:
            st.info("No hay articulos cargados.")
            return

        articulo = st.selectbox(
            "Articulo",
            articulos_list,
            format_func=lambda a: f"{a.codigo} - {a.nombre}",
            key="consulta_categoria_articulo_articulo",
        )
    finally:
        db.close()

    categoria = categorias_by_code.get(articulo.categoria_codigo)
    combo = combos_by_code.get(articulo.combo_codigo) if articulo.es_combo else None

    st.subheader("Resultado")
    st.dataframe(
        [
            {
                "Codigo articulo": articulo.codigo,
                "Descripcion articulo": articulo.nombre,
                "Codigo categoria": categoria.codigo if categoria else "",
                "Descripcion categoria": categoria.descripcion if categoria else "",
                "Es combo": "si" if articulo.es_combo else "no",
                "Codigo combo": combo.codigo if combo else "",
                "Descripcion combo": combo.descripcion if combo else "",
            }
        ],
        use_container_width=True,
        hide_index=True,
    )

    if articulo.es_combo:
        st.info(
            "Este articulo esta marcado como combo. No tiene una categoria directa; "
            "se vincula al combo indicado."
        )
    elif categoria is None:
        st.warning("Este articulo no tiene categoria asociada.")


def render_consultas_body() -> None:
    opciones_consulta = [
        "Seleccionar",
        "Consulta de Articulos por Categorias",
        "Consulta de Categorias por Articulos",
    ]
    consulta = st.selectbox(
        "Consultas",
        opciones_consulta,
        index=opciones_consulta.index(st.session_state.consultas_menu)
        if st.session_state.consultas_menu in opciones_consulta
        else 0,
    )
    st.session_state.consultas_menu = consulta

    if consulta == "Seleccionar":
        st.info("Seleccione una consulta.")
        return

    if consulta == "Consulta de Articulos por Categorias":
        consulta_articulos_por_categoria()
    elif consulta == "Consulta de Categorias por Articulos":
        consulta_categoria_por_articulo()


def consultas() -> None:
    st.title("Consultas")
    render_consultas_body()


def render_action_header(nombre: str) -> None:
    accion = st.session_state.get("home_action")
    if accion:
        st.subheader(f"{accion} {nombre}")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Crear", key=f"crear_pagina_{nombre}"):
                st.session_state.home_action = "Crear"
                st.rerun()
        with c2:
            if st.button("Modificar", key=f"modificar_pagina_{nombre}"):
                st.session_state.home_action = "Modificar"
                st.rerun()
        with c3:
            if st.button("Eliminar", key=f"eliminar_pagina_{nombre}"):
                st.session_state.home_action = "Eliminar"
                st.rerun()


def reset_action() -> None:
    st.session_state.home_action = None


def finish_action(message: str) -> None:
    st.session_state.action_success = message
    reset_action()
    st.rerun()


def show_action_success() -> None:
    message = st.session_state.get("action_success")
    if message:
        st.success(message)
        st.session_state.action_success = None


def next_codigo(db, model) -> int:
    max_codigo = db.scalar(select(func.max(model.codigo)))
    return int(max_codigo or 0) + 1


def categorias() -> None:
    st.title("Categorias")
    render_action_header("Categorias")
    show_action_success()

    db = SessionLocal()
    try:
        cats = list(db.scalars(select(Categoria).order_by(Categoria.codigo)).all())

        if st.session_state.get("home_action") == "Crear":
            codigo = next_codigo(db, Categoria)
            with st.form("crear_categoria"):
                st.number_input("Codigo", value=codigo, disabled=True)
                descripcion = st.text_input("Descripcion", max_chars=150)
                c1, c2 = st.columns(2)
                with c1:
                    guardar = st.form_submit_button("Guardar")
                with c2:
                    salir = st.form_submit_button("Salir")

            if salir:
                reset_action()
                st.rerun()
            if guardar:
                if not descripcion.strip():
                    st.error("Debe ingresar una descripcion.")
                else:
                    try:
                        db.add(Categoria(codigo=int(codigo), descripcion=descripcion.strip()))
                        db.commit()
                        finish_action("Categoria creada correctamente.")
                    except IntegrityError:
                        db.rollback()
                        st.error("No se pudo crear la categoria. Revise que el codigo y la descripcion no existan.")

        elif st.session_state.get("home_action") == "Modificar":
            if not cats:
                st.warning("No hay categorias para modificar.")
            else:
                categoria = st.selectbox(
                    "Categoria a modificar",
                    cats,
                    format_func=lambda c: f"{c.codigo} - {c.descripcion}",
                )
                with st.form("modificar_categoria"):
                    st.number_input("Codigo", value=int(categoria.codigo), disabled=True)
                    descripcion = st.text_input(
                        "Descripcion",
                        value=categoria.descripcion,
                        max_chars=150,
                    )
                    guardar = st.form_submit_button("Guardar")

                if guardar:
                    if not descripcion.strip():
                        st.error("Debe ingresar una descripcion.")
                    else:
                        try:
                            categoria_db = db.get(Categoria, int(categoria.codigo))
                            if categoria_db is None:
                                st.error("Categoria no encontrada.")
                                return
                            categoria_db.descripcion = descripcion.strip()
                            db.commit()
                            finish_action("Categoria modificada correctamente.")
                        except IntegrityError:
                            db.rollback()
                            st.error("No se pudo modificar la categoria. Revise que la descripcion no exista.")

        elif st.session_state.get("home_action") == "Eliminar":
            if not cats:
                st.warning("No hay categorias para eliminar.")
            else:
                categoria = st.selectbox(
                    "Categoria a eliminar",
                    cats,
                    format_func=lambda c: f"{c.codigo} - {c.descripcion}",
                )
                st.warning(f"Se esta eliminando la categoria: {categoria.codigo} - {categoria.descripcion}")
                c1, c2 = st.columns(2)

                with c1:
                    if st.button("NO"):
                        reset_action()
                        st.rerun()

                with c2:
                    if st.button("SI"):
                        articulos_asociados = db.scalar(
                            select(Articulo.codigo)
                            .where(Articulo.categoria_codigo == categoria.codigo)
                            .limit(1)
                        )
                        if articulos_asociados is not None:
                            st.error("No se puede eliminar la categoria porque tiene articulos asociados.")
                        else:
                            try:
                                categoria_db = db.get(Categoria, int(categoria.codigo))
                                if categoria_db is None:
                                    st.error("Categoria no encontrada.")
                                    return
                                db.delete(categoria_db)
                                db.commit()
                                finish_action("Categoria eliminada correctamente.")
                            except IntegrityError:
                                db.rollback()
                                st.error("No se pudo eliminar la categoria.")
    finally:
        db.close()

    st.dataframe(
        [{"Codigo": c.codigo, "Descripcion": c.descripcion} for c in cats],
        use_container_width=True,
        hide_index=True,
    )


def articulos() -> None:
    st.title("Articulos")
    render_action_header("Articulos")
    show_action_success()

    db = SessionLocal()
    try:
        arts = list(db.scalars(select(Articulo).order_by(Articulo.codigo)).all())
        cats = list(db.scalars(select(Categoria).order_by(Categoria.codigo)).all())
        combos_list = list(db.scalars(select(Combo).order_by(Combo.codigo)).all())

        if st.session_state.get("home_action") == "Crear":
            if not cats:
                st.error("Debe existir al menos una categoria antes de crear articulos.")
            else:
                codigo = st.number_input(
                    "Codigo",
                    min_value=1,
                    step=1,
                    key="crear_articulo_codigo",
                )
                nombre = st.text_input("Nombre", max_chars=200, key="crear_articulo_nombre")
                combo_opcion = st.selectbox("combo?", ["no", "si"], index=0, key="crear_articulo_es_combo")
                categoria = None
                combo = None
                if combo_opcion == "no":
                    categoria = st.selectbox(
                        "Categoria",
                        cats,
                        format_func=lambda c: f"{c.codigo} - {c.descripcion}",
                        key="crear_articulo_categoria",
                    )
                else:
                    if combos_list:
                        combo = st.selectbox(
                            "combos",
                            combos_list,
                            format_func=lambda c: f"{c.codigo} - {c.descripcion}",
                            key="crear_articulo_combo",
                        )
                    else:
                        st.error("No hay combos cargados para seleccionar.")

                c1, c2 = st.columns(2)
                with c1:
                    guardar = st.button("Guardar", key="guardar_crear_articulo")
                with c2:
                    salir = st.button("Salir", key="salir_crear_articulo")

                if salir:
                    reset_action()
                    st.rerun()
                if guardar:
                    if not nombre.strip():
                        st.error("Debe ingresar un nombre.")
                    elif combo_opcion == "no" and categoria is None:
                        st.error("Debe seleccionar una categoria.")
                    elif combo_opcion == "si" and combo is None:
                        st.error("Debe seleccionar un combo.")
                    else:
                        try:
                            db.add(
                                Articulo(
                                    codigo=int(codigo),
                                    nombre=nombre.strip(),
                                    categoria_codigo=(
                                        int(categoria.codigo) if combo_opcion == "no" else None
                                    ),
                                    es_combo=combo_opcion == "si",
                                    combo_codigo=int(combo.codigo) if combo_opcion == "si" else None,
                                )
                            )
                            db.commit()
                            finish_action("Articulo creado correctamente.")
                        except IntegrityError:
                            db.rollback()
                            st.error("No se pudo crear el articulo. Revise que el codigo no exista.")

        elif st.session_state.get("home_action") == "Modificar":
            if not arts:
                st.warning("No hay articulos para modificar.")
            elif not cats:
                st.error("Debe existir al menos una categoria.")
            else:
                articulo = st.selectbox(
                    "Articulo a modificar",
                    arts,
                    format_func=lambda a: f"{a.codigo} - {a.nombre}",
                )
                categoria_actual = next(
                    (i for i, c in enumerate(cats) if c.codigo == articulo.categoria_codigo),
                    0,
                )
                st.number_input(
                    "Codigo",
                    value=int(articulo.codigo),
                    disabled=True,
                    key=f"modificar_articulo_codigo_{articulo.codigo}",
                )
                nombre = st.text_input(
                    "Nombre",
                    value=articulo.nombre,
                    max_chars=200,
                    key=f"modificar_articulo_nombre_{articulo.codigo}",
                )
                combo_opcion = st.selectbox(
                    "combo?",
                    ["no", "si"],
                    index=1 if articulo.es_combo else 0,
                    key=f"modificar_articulo_es_combo_{articulo.codigo}",
                )
                categoria = None
                combo = None
                if combo_opcion == "no":
                    categoria = st.selectbox(
                        "Categoria",
                        cats,
                        index=categoria_actual,
                        format_func=lambda c: f"{c.codigo} - {c.descripcion}",
                        key=f"modificar_articulo_categoria_{articulo.codigo}",
                    )
                else:
                    if combos_list:
                        combo_actual = next(
                            (i for i, c in enumerate(combos_list) if c.codigo == articulo.combo_codigo),
                            0,
                        )
                        combo = st.selectbox(
                            "combos",
                            combos_list,
                            index=combo_actual,
                            format_func=lambda c: f"{c.codigo} - {c.descripcion}",
                            key=f"modificar_articulo_combo_{articulo.codigo}",
                        )
                    else:
                        st.error("No hay combos cargados para seleccionar.")

                guardar = st.button("Guardar", key=f"guardar_modificar_articulo_{articulo.codigo}")
                if guardar:
                    if not nombre.strip():
                        st.error("Debe ingresar un nombre.")
                    elif combo_opcion == "no" and categoria is None:
                        st.error("Debe seleccionar una categoria.")
                    elif combo_opcion == "si" and combo is None:
                        st.error("Debe seleccionar un combo.")
                    else:
                        try:
                            articulo_db = db.get(Articulo, int(articulo.codigo))
                            if articulo_db is None:
                                st.error("Articulo no encontrado.")
                                return
                            articulo_db.nombre = nombre.strip()
                            articulo_db.categoria_codigo = (
                                int(categoria.codigo) if combo_opcion == "no" else None
                            )
                            articulo_db.es_combo = combo_opcion == "si"
                            articulo_db.combo_codigo = (
                                int(combo.codigo) if combo_opcion == "si" else None
                            )
                            db.commit()
                            finish_action("Articulo modificado correctamente.")
                        except IntegrityError:
                            db.rollback()
                            st.error("No se pudo modificar el articulo.")

        elif st.session_state.get("home_action") == "Eliminar":
            if not arts:
                st.warning("No hay articulos para eliminar.")
            else:
                articulo = st.selectbox(
                    "Articulo a eliminar",
                    arts,
                    format_func=lambda a: f"{a.codigo} - {a.nombre}",
                )
                st.warning(f"Se esta eliminando el articulo: {articulo.codigo} - {articulo.nombre}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("NO"):
                        reset_action()
                        st.rerun()
                with c2:
                    if st.button("SI"):
                        try:
                            articulo_db = db.get(Articulo, int(articulo.codigo))
                            if articulo_db is None:
                                st.error("Articulo no encontrado.")
                                return
                            db.delete(articulo_db)
                            db.commit()
                            finish_action("Articulo eliminado correctamente.")
                        except IntegrityError:
                            db.rollback()
                            st.error("No se pudo eliminar el articulo.")
    finally:
        db.close()

    st.dataframe(
        [
            {
                "Codigo": a.codigo,
                "Nombre": a.nombre,
                "Categoria": a.categoria_codigo,
                "combo?": "si" if a.es_combo else "no",
                "combos": a.combo_codigo if a.es_combo else "",
            }
            for a in arts
        ],
        use_container_width=True,
        hide_index=True,
    )


def locales() -> None:
    st.title("Locales")
    render_action_header("Locales")
    show_action_success()

    db = SessionLocal()
    try:
        locs = list(db.scalars(select(Local).order_by(Local.codigo)).all())

        if st.session_state.get("home_action") == "Crear":
            codigo = next_codigo(db, Local)
            with st.form("crear_local"):
                st.number_input("Codigo", value=codigo, disabled=True)
                descripcion = st.text_input("Descripcion", max_chars=150)
                c1, c2 = st.columns(2)
                with c1:
                    guardar = st.form_submit_button("Guardar")
                with c2:
                    salir = st.form_submit_button("Salir")

            if salir:
                reset_action()
                st.rerun()
            if guardar:
                if not descripcion.strip():
                    st.error("Debe ingresar una descripcion.")
                else:
                    try:
                        db.add(Local(codigo=int(codigo), descripcion=descripcion.strip()))
                        db.commit()
                        finish_action("Local creado correctamente.")
                    except IntegrityError:
                        db.rollback()
                        st.error("No se pudo crear el local. Revise que el codigo y la descripcion no existan.")

        elif st.session_state.get("home_action") == "Modificar":
            if not locs:
                st.warning("No hay locales para modificar.")
            else:
                local = st.selectbox(
                    "Local a modificar",
                    locs,
                    format_func=lambda l: f"{l.codigo} - {l.descripcion}",
                )
                with st.form("modificar_local"):
                    st.number_input("Codigo", value=int(local.codigo), disabled=True)
                    descripcion = st.text_input(
                        "Descripcion",
                        value=local.descripcion,
                        max_chars=150,
                    )
                    guardar = st.form_submit_button("Guardar")

                if guardar:
                    if not descripcion.strip():
                        st.error("Debe ingresar una descripcion.")
                    else:
                        try:
                            local_db = db.get(Local, int(local.codigo))
                            if local_db is None:
                                st.error("Local no encontrado.")
                                return
                            local_db.descripcion = descripcion.strip()
                            db.commit()
                            finish_action("Local modificado correctamente.")
                        except IntegrityError:
                            db.rollback()
                            st.error("No se pudo modificar el local. Revise que la descripcion no exista.")

        elif st.session_state.get("home_action") == "Eliminar":
            if not locs:
                st.warning("No hay locales para eliminar.")
            else:
                local = st.selectbox(
                    "Local a eliminar",
                    locs,
                    format_func=lambda l: f"{l.codigo} - {l.descripcion}",
                )
                st.warning(f"Se esta eliminando el local: {local.codigo} - {local.descripcion}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("NO"):
                        reset_action()
                        st.rerun()
                with c2:
                    if st.button("SI"):
                        try:
                            local_db = db.get(Local, int(local.codigo))
                            if local_db is None:
                                st.error("Local no encontrado.")
                                return
                            db.delete(local_db)
                            db.commit()
                            finish_action("Local eliminado correctamente.")
                        except IntegrityError:
                            db.rollback()
                            st.error("No se pudo eliminar el local.")
    finally:
        db.close()

    st.dataframe(
        [{"Codigo": l.codigo, "Descripcion": l.descripcion} for l in locs],
        use_container_width=True,
        hide_index=True,
    )


def usuarios() -> None:
    st.title("Usuarios")
    render_action_header("Usuarios")
    show_action_success()

    db = SessionLocal()
    try:
        users = list(db.scalars(select(User).order_by(User.username)).all())

        if st.session_state.get("home_action") == "Crear":
            with st.form("crear_usuario"):
                username = st.text_input("Usuario", max_chars=50)
                full_name = st.text_input("Nombre completo", max_chars=120)
                temporary_password = st.text_input("Contrasena temporal", type="password")
                role = st.selectbox("Rol", ["user", "admin"])
                is_active = st.checkbox("Activo", value=True)
                c1, c2 = st.columns(2)
                with c1:
                    guardar = st.form_submit_button("Guardar")
                with c2:
                    salir = st.form_submit_button("Salir")

            if salir:
                reset_action()
                st.rerun()
            if guardar:
                if not username.strip() or not temporary_password:
                    st.error("Debe ingresar usuario y contrasena temporal.")
                else:
                    try:
                        create_user(
                            db,
                            username.strip(),
                            full_name.strip(),
                            temporary_password,
                            role,
                            is_active,
                        )
                        finish_action("Usuario creado correctamente.")
                    except ValueError as exc:
                        st.error(str(exc))
                    except IntegrityError:
                        db.rollback()
                        st.error("No se pudo crear el usuario.")

        elif st.session_state.get("home_action") == "Modificar":
            if not users:
                st.warning("No hay usuarios para modificar.")
            else:
                user = st.selectbox(
                    "Usuario a modificar",
                    users,
                    format_func=lambda u: f"{u.username} - {u.full_name}",
                )
                role_options = ["user", "admin"]
                role_index = role_options.index(user.role) if user.role in role_options else 0
                with st.form("modificar_usuario"):
                    st.text_input("Usuario", value=user.username, disabled=True)
                    full_name = st.text_input("Nombre completo", value=user.full_name, max_chars=120)
                    role = st.selectbox("Rol", role_options, index=role_index)
                    is_active = st.checkbox("Activo", value=user.is_active)
                    new_password = st.text_input(
                        "Nueva contrasena temporal (opcional)",
                        type="password",
                    )
                    guardar = st.form_submit_button("Guardar")

                if guardar:
                    try:
                        update_user(db, user.username, full_name, role, is_active)
                        if new_password:
                            reset_user_password(db, user.username, new_password)
                        finish_action("Usuario modificado correctamente.")
                    except ValueError as exc:
                        st.error(str(exc))
                    except IntegrityError:
                        db.rollback()
                        st.error("No se pudo modificar el usuario.")

        elif st.session_state.get("home_action") == "Eliminar":
            if not users:
                st.warning("No hay usuarios para eliminar.")
            else:
                user = st.selectbox(
                    "Usuario a eliminar",
                    users,
                    format_func=lambda u: f"{u.username} - {u.full_name}",
                )
                st.warning(f"Se esta eliminando el usuario: {user.username}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("NO"):
                        reset_action()
                        st.rerun()
                with c2:
                    if st.button("SI"):
                        if user.username == st.session_state.username:
                            st.error("No puede eliminar el usuario con la sesion activa.")
                        else:
                            try:
                                delete_user(db, user.username)
                                finish_action("Usuario eliminado correctamente.")
                            except ValueError as exc:
                                st.error(str(exc))
                            except IntegrityError:
                                db.rollback()
                                st.error("No se pudo eliminar el usuario.")
    finally:
        db.close()

    st.dataframe(
        [
            {
                "Usuario": u.username,
                "Nombre": u.full_name,
                "Rol": u.role,
                "Activo": "SI" if u.is_active else "NO",
            }
            for u in users
        ],
        use_container_width=True,
        hide_index=True,
    )


def combo_form_fields(cats: list[Categoria], combo: Combo | None = None) -> dict:
    descripcion = st.text_input(
        "Descripcion",
        value=combo.descripcion if combo else "",
        max_chars=25,
    )

    optional_cats = [None, *cats]

    def format_optional_categoria(categoria: Categoria | None) -> str:
        if categoria is None:
            return "sin categoria"
        return f"{categoria.codigo} - {categoria.descripcion}"

    def optional_categoria_index(codigo: int | None) -> int:
        if codigo is None:
            return 0
        return next((i for i, c in enumerate(optional_cats) if c and c.codigo == codigo), 0)

    def categoria_index(codigo: int | None) -> int:
        if codigo is None:
            return 0
        return next((i for i, c in enumerate(cats) if c.codigo == codigo), 0)

    c1, c2 = st.columns(2)
    with c1:
        categ1 = st.selectbox(
            "categ1",
            optional_cats,
            index=optional_categoria_index(combo.categ1 if combo else None),
            format_func=format_optional_categoria,
        )
    with c2:
        qcateg1 = st.number_input(
            "qcateg1",
            min_value=0,
            step=1,
            value=int(combo.qcateg1) if combo and combo.categ1 is not None else 0,
        )

    c3, c4 = st.columns(2)
    with c3:
        categ2 = st.selectbox(
            "categ2",
            optional_cats,
            index=optional_categoria_index(combo.categ2 if combo else None),
            format_func=format_optional_categoria,
        )
    with c4:
        qcateg2 = st.number_input(
            "qcateg2",
            min_value=0,
            step=1,
            value=int(combo.qcateg2) if combo and combo.categ2 is not None else 0,
        )

    c5, c6 = st.columns(2)
    with c5:
        categ3 = st.selectbox(
            "categ3",
            optional_cats,
            index=optional_categoria_index(combo.categ3 if combo else None),
            format_func=format_optional_categoria,
        )
    with c6:
        qcateg3 = st.number_input(
            "qcateg3",
            min_value=0,
            step=1,
            value=int(combo.qcateg3) if combo and combo.categ3 is not None else 0,
        )

    c7, c8 = st.columns(2)
    with c7:
        categ4 = st.selectbox(
            "categ4",
            optional_cats,
            index=optional_categoria_index(combo.categ4 if combo else None),
            format_func=format_optional_categoria,
        )
    with c8:
        qcateg4 = st.number_input(
            "qcateg4",
            min_value=0,
            step=1,
            value=int(combo.qcateg4) if combo and combo.categ4 is not None else 0,
        )

    return {
        "descripcion": descripcion.strip(),
        "categ1": int(categ1.codigo) if categ1 else None,
        "qcateg1": int(qcateg1) if categ1 else 0,
        "categ2": int(categ2.codigo) if categ2 else None,
        "qcateg2": int(qcateg2) if categ2 else 0,
        "categ3": int(categ3.codigo) if categ3 else None,
        "qcateg3": int(qcateg3) if categ3 else 0,
        "categ4": int(categ4.codigo) if categ4 else None,
        "qcateg4": int(qcateg4) if categ4 else 0,
    }


def validate_combo_values(values: dict) -> str | None:
    for number in (1, 2, 3, 4):
        categoria = values[f"categ{number}"]
        cantidad = values[f"qcateg{number}"]
        if categoria is None and cantidad != 0:
            return f"qcateg{number} debe quedar en 0 cuando categ{number} esta sin categoria."
        if categoria is not None and cantidad <= 0:
            return f"qcateg{number} debe ser mayor a 0 cuando categ{number} tiene categoria."

    return None


def combos() -> None:
    st.title("Combos")
    render_action_header("Combos")
    show_action_success()

    db = SessionLocal()
    try:
        combos_list = list(db.scalars(select(Combo).order_by(Combo.codigo)).all())
        cats = list(db.scalars(select(Categoria).order_by(Categoria.codigo)).all())

        if st.session_state.get("home_action") == "Crear":
            if not cats:
                st.error("Debe existir al menos una categoria antes de crear combos.")
            else:
                codigo = next_codigo(db, Combo)
                with st.form("crear_combo"):
                    st.number_input("Codigo", value=codigo, disabled=True)
                    values = combo_form_fields(cats)
                    c1, c2 = st.columns(2)
                    with c1:
                        guardar = st.form_submit_button("Guardar")
                    with c2:
                        salir = st.form_submit_button("Salir")

                if salir:
                    reset_action()
                    st.rerun()
                if guardar:
                    if not values["descripcion"]:
                        st.error("Debe ingresar una descripcion.")
                    elif validate_combo_values(values):
                        st.error(validate_combo_values(values))
                    else:
                        try:
                            db.add(Combo(codigo=int(codigo), **values))
                            db.commit()
                            finish_action("Combo creado correctamente.")
                        except IntegrityError:
                            db.rollback()
                            st.error("No se pudo crear el combo. Revise que el codigo y la descripcion no existan.")

        elif st.session_state.get("home_action") == "Modificar":
            if not combos_list:
                st.warning("No hay combos para modificar.")
            elif not cats:
                st.error("Debe existir al menos una categoria.")
            else:
                combo = st.selectbox(
                    "Combo a modificar",
                    combos_list,
                    format_func=lambda c: f"{c.codigo} - {c.descripcion}",
                )
                with st.form("modificar_combo"):
                    st.number_input("Codigo", value=int(combo.codigo), disabled=True)
                    values = combo_form_fields(cats, combo)
                    guardar = st.form_submit_button("Guardar")

                if guardar:
                    if not values["descripcion"]:
                        st.error("Debe ingresar una descripcion.")
                    elif validate_combo_values(values):
                        st.error(validate_combo_values(values))
                    else:
                        try:
                            combo_db = db.get(Combo, int(combo.codigo))
                            if combo_db is None:
                                st.error("Combo no encontrado.")
                                return
                            for field, value in values.items():
                                setattr(combo_db, field, value)
                            db.commit()
                            finish_action("Combo modificado correctamente.")
                        except IntegrityError:
                            db.rollback()
                            st.error("No se pudo modificar el combo. Revise que la descripcion no exista.")

        elif st.session_state.get("home_action") == "Eliminar":
            if not combos_list:
                st.warning("No hay combos para eliminar.")
            else:
                combo = st.selectbox(
                    "Combo a eliminar",
                    combos_list,
                    format_func=lambda c: f"{c.codigo} - {c.descripcion}",
                )
                st.warning(f"Se esta eliminando el combo: {combo.codigo} - {combo.descripcion}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("NO"):
                        reset_action()
                        st.rerun()
                with c2:
                    if st.button("SI"):
                        try:
                            combo_db = db.get(Combo, int(combo.codigo))
                            if combo_db is None:
                                st.error("Combo no encontrado.")
                                return
                            db.delete(combo_db)
                            db.commit()
                            finish_action("Combo eliminado correctamente.")
                        except IntegrityError:
                            db.rollback()
                            st.error("No se pudo eliminar el combo.")
    finally:
        db.close()

    st.dataframe(
        [
            {
                "Codigo": c.codigo,
                "Descripcion": c.descripcion,
                "categ1": c.categ1,
                "qcateg1": c.qcateg1,
                "categ2": c.categ2,
                "qcateg2": c.qcateg2,
                "categ3": c.categ3,
                "qcateg3": c.qcateg3,
                "categ4": c.categ4,
                "qcateg4": c.qcateg4,
            }
            for c in combos_list
        ],
        use_container_width=True,
        hide_index=True,
    )


def reportes_cerrados() -> None:
    st.title("Reportes cerrados")

    control_result = st.session_state.pop("control_sistema_last_result", None)
    if control_result:
        st.success(
            "Control con Sistema procesado correctamente. "
            "Los botones de informe ya fueron actualizados."
        )
        st.write(
            "Articulos procesados: "
            f"{control_result['articulos_procesados']} | "
            "Categorias generadas: "
            f"{control_result['categorias_generadas']} | "
            "Combos generados: "
            f"{control_result['combos_generados']} | "
            "Observaciones: "
            f"{control_result['observaciones']}"
        )

    db = SessionLocal()
    try:
        reportes = list(
            db.scalars(
                select(ReporteVentaTurno).order_by(ReporteVentaTurno.fecha_creacion.desc())
            ).all()
        )
    finally:
        db.close()

    if not reportes:
        st.info("No hay reportes cerrados.")
        return

    render_duplicate_cleanup(reportes)

    header = st.columns([1.2, 1.4, 0.7, 1.6, 1.5, 1.8])
    header[0].markdown("**Fecha**")
    header[1].markdown("**Local**")
    header[2].markdown("**Turno**")
    header[3].markdown("**Informe Ventas por turno**")
    header[4].markdown("**Control con Sistema**")
    header[5].markdown("**Informe check vs sistema**")

    for reporte in reportes:
        row = st.columns([1.2, 1.4, 0.7, 1.6, 1.5, 1.8])
        row[0].write(reporte.fecha_creacion.strftime("%d/%m/%y"))
        row[1].write(reporte.local_descripcion)
        row[2].write(reporte.turno)

        with row[3]:
            report_button(
                "Informe Ventas por turno",
                build_informe_ventas_html(reporte.id),
            )

        with row[4]:
            if st.button("Control con Sistema", key=f"control_sistema_{reporte.id}"):
                control_sistema_dialog(reporte.id)

        with row[5]:
            report_button(
                "Informe check vs sistema",
                build_check_vs_sistema_html(reporte),
            )


def menu_lateral() -> str:
    st.sidebar.title("Menu")
    st.sidebar.write(f"Usuario: {st.session_state.username}")

    opciones = [
        "Inicio",
        "Ventas por turno",
        "Configuracion",
        "Consultas",
        "Reportes cerrados",
    ]
    pagina = st.sidebar.selectbox(
        "Opciones",
        opciones,
        index=opciones.index(st.session_state.page)
        if st.session_state.page in opciones
        else 0,
    )

    st.session_state.page = pagina
    return pagina


def main() -> None:
    init()
    render_header()

    if is_check_correction_request():
        render_check_correccion_page()
        return

    if not st.session_state.auth:
        login()
        return

    pagina = menu_lateral()

    if pagina == "Ventas por turno":
        ventas()
    elif pagina == "Configuracion":
        configuracion()
    elif pagina == "Consultas":
        consultas()
    elif pagina == "Categorias":
        categorias()
    elif pagina == "Articulos":
        articulos()
    elif pagina == "Locales":
        locales()
    elif pagina == "Usuarios":
        usuarios()
    elif pagina == "Combos":
        combos()
    elif pagina == "Reportes cerrados":
        reportes_cerrados()
    else:
        inicio()


if __name__ == "__main__":
    main()
