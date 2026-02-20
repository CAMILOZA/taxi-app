import pandas as pd
import streamlit as st
from datetime import date
import gspread

# =========================
# CONFIG PÁGINA (nombre/ícono)
# =========================
st.set_page_config(
    page_title="Taxi Camilo",
    page_icon="🚕",
    layout="centered",
)

# =========================
# ESTILO (mejor en celular)
# =========================
st.markdown(
    """
<style>
.block-container {padding-top: 1rem; padding-bottom: 2rem;}
.stButton button {width: 100%; padding: 0.85rem 1rem; font-size: 1.05rem; border-radius: 14px;}
div[data-baseweb="input"] input, textarea {border-radius: 12px;}
.card {
  border: 1px solid rgba(49, 51, 63, 0.15);
  border-radius: 18px;
  padding: 14px 16px;
  background: rgba(255,255,255,0.02);
}
.small {opacity: 0.75; font-size: 0.92rem;}
.big {font-size: 1.25rem; font-weight: 700;}
hr {margin: 0.6rem 0 1.0rem 0;}
</style>
""",
    unsafe_allow_html=True
)

# =========================
# CONFIGURACIÓN
# =========================
COL_FECHA = "FECHA"
COL_PROD = "PRODUCIDO"
COL_COND = "CONDUCTOR"
COL_OBS = "OBSERVACION"
COL_GAST = "GASTOS"

CONDUCTORES = ["JORGE", "ERIK"]

# =========================
# FECHAS EN ESPAÑOL
# =========================
MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
}
DIAS_ES = {
    0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves",
    4: "viernes", 5: "sábado", 6: "domingo"
}

def fecha_es(d):
    if d is None or pd.isna(d):
        return ""
    return f"{DIAS_ES[d.weekday()]} {d.day} {MESES_ES[d.month]} {d.year}"

# =========================
# FORMATO PESOS COLOMBIANOS
# =========================
def formato_pesos(valor):
    try:
        valor = float(valor)
    except Exception:
        valor = 0.0
    return f"$ {valor:,.0f}".replace(",", ".")

# =========================
# GOOGLE SHEETS (gspread)
# =========================
def get_ws():
    # Deben existir en st.secrets:
    # spreadsheet_id = "..."
    # worksheet_name = "datos"
    # [service_account] ... (contenido del JSON)
    spreadsheet_id = st.secrets["spreadsheet_id"]
    worksheet_name = st.secrets.get("worksheet_name", "datos")

    sa_info = dict(st.secrets["service_account"])
    gc = gspread.service_account_from_dict(sa_info)
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)
    return ws

@st.cache_data(ttl=15)
def read_sheet() -> pd.DataFrame:
    ws = get_ws()
    values = ws.get_all_values()

    if not values or len(values) < 1:
        return pd.DataFrame(columns=[COL_FECHA, COL_PROD, COL_COND, COL_OBS, COL_GAST])

    headers = [h.strip() for h in values[0]]
    rows = values[1:]
    df = pd.DataFrame(rows, columns=headers)

    for c in [COL_FECHA, COL_PROD, COL_COND, COL_OBS, COL_GAST]:
        if c not in df.columns:
            df[c] = None

    df = df[[COL_FECHA, COL_PROD, COL_COND, COL_OBS, COL_GAST]].copy()
    df = df.dropna(how="all")

    df[COL_FECHA] = pd.to_datetime(df[COL_FECHA], errors="coerce").dt.date
    df[COL_PROD] = pd.to_numeric(df[COL_PROD], errors="coerce").fillna(0)
    df[COL_GAST] = pd.to_numeric(df[COL_GAST], errors="coerce").fillna(0)
    df[COL_COND] = df[COL_COND].astype(str).str.upper().str.strip()
    df[COL_OBS] = df[COL_OBS].fillna("")

    return df.sort_values([COL_FECHA, COL_COND], na_position="last").reset_index(drop=True)

def write_sheet(df: pd.DataFrame):
    ws = get_ws()
    out = df.copy()
    out[COL_FECHA] = out[COL_FECHA].astype(str)

    data = [out.columns.tolist()] + out.astype(str).values.tolist()
    ws.clear()
    ws.update("A1", data)

# =========================
# LÓGICA DE REGISTRO (1 gasto por día)
# =========================
def upsert_day(df, fecha, prod_jorge, prod_erik, gastos, observacion):
    df = df.copy()

    def set_row(conductor, producido, obs, gast):
        nonlocal df
        mask = (df[COL_FECHA] == fecha) & (df[COL_COND] == conductor)
        if mask.any():
            df.loc[mask, COL_PROD] = producido
            df.loc[mask, COL_OBS] = obs
            df.loc[mask, COL_GAST] = gast
        else:
            df = pd.concat([df, pd.DataFrame([{
                COL_FECHA: fecha,
                COL_PROD: producido,
                COL_COND: conductor,
                COL_OBS: obs,
                COL_GAST: gast
            }])], ignore_index=True)

    # Gastos y observación del día: se guardan en la fila de JORGE (solo 1 por día)
    set_row("JORGE", prod_jorge, observacion, gastos)
    set_row("ERIK",  prod_erik,  "",          0)

    return df.sort_values([COL_FECHA, COL_COND], na_position="last").reset_index(drop=True)

def daily_summary(df):
    if df.empty:
        return pd.DataFrame()

    pivot = df.pivot_table(
        index=COL_FECHA,
        columns=COL_COND,
        values=COL_PROD,
        aggfunc="sum",
        fill_value=0
    ).reset_index()

    for c in CONDUCTORES:
        if c not in pivot.columns:
            pivot[c] = 0

    gastos = df.groupby(COL_FECHA)[COL_GAST].max().reset_index()
    obs = df.groupby(COL_FECHA)[COL_OBS].max().reset_index()

    resumen = pivot.merge(gastos, on=COL_FECHA, how="left").merge(obs, on=COL_FECHA, how="left")
    resumen[COL_GAST] = resumen[COL_GAST].fillna(0)
    resumen[COL_OBS] = resumen[COL_OBS].fillna("")

    resumen["TOTAL_PRODUCIDO"] = resumen["JORGE"] + resumen["ERIK"]
    resumen["NETO"] = resumen["TOTAL_PRODUCIDO"] - resumen[COL_GAST]

    # ✅ ORDEN: más reciente arriba
    return resumen.sort_values(COL_FECHA, ascending=False).reset_index(drop=True)

# =========================
# UI
# =========================
st.title("🚕 Taxi Camilo")
st.caption("Registro diario • Jorge y Erik • Gastos: 1 por día • Valores en COP")

# Inicializa estado del formulario (para limpiar después de guardar)
if "prod_j" not in st.session_state:
    st.session_state.prod_j = 0
if "prod_e" not in st.session_state:
    st.session_state.prod_e = 0
if "gastos" not in st.session_state:
    st.session_state.gastos = 0
if "obs" not in st.session_state:
    st.session_state.obs = ""
if "fecha" not in st.session_state:
    st.session_state.fecha = date.today()

df = read_sheet()

tab1, tab2 = st.tabs(["➕ Registrar día", "📊 Resumen diario"])

with tab1:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Ingreso del día")

    cA, cB = st.columns(2)

    with cA:
        fecha = st.date_input("Fecha", value=st.session_state.fecha, key="fecha")
        st.number_input("Producido JORGE", min_value=0, step=1000, key="prod_j")
        st.number_input("Gastos del día (solo 1)", min_value=0, step=1000, key="gastos")

    with cB:
        st.number_input("Producido ERIK", min_value=0, step=1000, key="prod_e")
        st.text_area("Observación del día", height=110, key="obs")

    guardar = st.button("Guardar / Actualizar ✅")
    st.markdown('</div>', unsafe_allow_html=True)

    if guardar:
        # Captura valores actuales
        f = st.session_state.fecha
        pj = st.session_state.prod_j
        pe = st.session_state.prod_e
        g = st.session_state.gastos
        o = st.session_state.obs

        df2 = upsert_day(df, f, pj, pe, g, o)
        write_sheet(df2)
        st.cache_data.clear()

        # ✅ Mensaje claro (incluye "CONFIRMADO ERIK")
        st.success("✅ CONFIRMADO ERIK — Información guardada/actualizada correctamente.")
        st.info(
            f"📌 Guardado:\n"
            f"- Fecha: {fecha_es(f)}\n"
            f"- Jorge: {formato_pesos(pj)}\n"
            f"- Erik: {formato_pesos(pe)}\n"
            f"- Gastos: {formato_pesos(g)}\n"
            f"- Observación: {o if o else '—'}"
        )

        # ✅ Limpia el formulario
        st.session_state.prod_j = 0
        st.session_state.prod_e = 0
        st.session_state.gastos = 0
        st.session_state.obs = ""

        # Recarga para ver datos actualizados
        st.rerun()

with tab2:
    res = daily_summary(df)

    if res.empty:
        st.info("No hay datos registrados aún.")
    else:
        # Rango
        max_d = res[COL_FECHA].max()
        min_d = res[COL_FECHA].min()

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Rango de fechas")
        r1, r2 = st.columns(2)
        desde = r1.date_input("Desde", value=min_d)
        hasta = r2.date_input("Hasta", value=max_d)
        st.markdown('</div>', unsafe_allow_html=True)

        filtrado = res[(res[COL_FECHA] >= desde) & (res[COL_FECHA] <= hasta)].copy()

        # Métricas
        m1, m2 = st.columns(2)
        m3, m4 = st.columns(2)
        m1.metric("Total Jorge", formato_pesos(filtrado["JORGE"].sum()))
        m2.metric("Total Erik", formato_pesos(filtrado["ERIK"].sum()))
        m3.metric("Total Gastos", formato_pesos(filtrado[COL_GAST].sum()))
        m4.metric("Neto (J+E-G)", formato_pesos(filtrado["NETO"].sum()))

        st.markdown("<hr/>", unsafe_allow_html=True)

        # Tabla (fecha en español)
        tabla = filtrado.copy()
        tabla = tabla.rename(columns={
            COL_FECHA: "FECHA",
            COL_GAST: "GASTOS",
            COL_OBS: "OBSERVACION"
        })

        tabla["FECHA"] = tabla["FECHA"].apply(fecha_es)

        for col in ["JORGE", "ERIK", "GASTOS", "TOTAL_PRODUCIDO", "NETO"]:
            tabla[col] = tabla[col].apply(formato_pesos)

        st.dataframe(
            tabla[["FECHA", "JORGE", "ERIK", "GASTOS", "TOTAL_PRODUCIDO", "NETO", "OBSERVACION"]],
            use_container_width=True,
            hide_index=True
        )

        if st.button("🔄 Actualizar datos"):
            st.cache_data.clear()
            st.rerun()
