import pandas as pd
import streamlit as st
from datetime import date
import gspread

st.set_page_config(page_title="Taxi - Registro Diario", layout="wide")

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
# FORMATO PESOS COLOMBIANOS
# =========================
def formato_pesos(valor):
    try:
        valor = float(valor)
    except:
        valor = 0
    return f"$ {valor:,.0f}".replace(",", ".")

# =========================
# GOOGLE SHEETS (con gspread)
# =========================
def get_ws():
    """
    Requiere en st.secrets:
    - spreadsheet_id
    - service_account (dict con el JSON)
    - worksheet_name (opcional; por defecto "datos")
    """
    spreadsheet_id = st.secrets["spreadsheet_id"]
    worksheet_name = st.secrets.get("worksheet_name", "datos")

    # st.secrets["service_account"] debe contener el JSON completo de la cuenta de servicio
    sa_info = dict(st.secrets["service_account"])
    gc = gspread.service_account_from_dict(sa_info)

    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)
    return ws

@st.cache_data(ttl=10)
def read_sheet() -> pd.DataFrame:
    ws = get_ws()
    values = ws.get_all_values()  # lista de listas

    if not values or len(values) < 1:
        return pd.DataFrame(columns=[COL_FECHA, COL_PROD, COL_COND, COL_OBS, COL_GAST])

    headers = [h.strip() for h in values[0]]
    rows = values[1:]

    df = pd.DataFrame(rows, columns=headers)

    # Asegura columnas
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
    # Convierte fechas a texto para Sheets
    out = df.copy()
    out[COL_FECHA] = out[COL_FECHA].astype(str)

    data = [out.columns.tolist()] + out.astype(str).values.tolist()

    # Limpia y escribe
    ws.clear()
    ws.update("A1", data)

# =========================
# GUARDAR O ACTUALIZAR DÍA
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
            nueva = pd.DataFrame([{
                COL_FECHA: fecha,
                COL_PROD: producido,
                COL_COND: conductor,
                COL_OBS: obs,
                COL_GAST: gast
            }])
            df = pd.concat([df, nueva], ignore_index=True)

    # Gastos/observación del día van en JORGE (un solo gasto por día)
    set_row("JORGE", prod_jorge, observacion, gastos)
    set_row("ERIK",  prod_erik,  "",          0)

    return df.sort_values([COL_FECHA, COL_COND], na_position="last").reset_index(drop=True)

# =========================
# RESUMEN DIARIO
# =========================
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

    return resumen.sort_values(COL_FECHA).reset_index(drop=True)

# =========================
# INTERFAZ
# =========================
st.title("🚕 Sistema Taxi - Jorge y Erik")

df = read_sheet()

st.subheader("➕ Registro Diario")

with st.form("form_dia"):
    c1, c2, c3, c4 = st.columns(4)

    fecha = c1.date_input("Fecha", value=date.today())
    prod_j = c2.number_input("Producido JORGE", min_value=0)
    prod_e = c3.number_input("Producido ERIK", min_value=0)
    gastos = c4.number_input("Gastos del día", min_value=0)

    obs = st.text_area("Observación del día")

    guardar = st.form_submit_button("Guardar / Actualizar")

if guardar:
    df = upsert_day(df, fecha, prod_j, prod_e, gastos, obs)
    write_sheet(df)
    st.cache_data.clear()
    st.success("✅ Día guardado correctamente")

st.subheader("📊 Resumen Diario")

res = daily_summary(df)

if not res.empty:
    min_d = res[COL_FECHA].min()
    max_d = res[COL_FECHA].max()

    c1, c2 = st.columns(2)
    desde = c1.date_input("Desde", value=min_d)
    hasta = c2.date_input("Hasta", value=max_d)

    filtrado = res[(res[COL_FECHA] >= desde) & (res[COL_FECHA] <= hasta)].copy()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Jorge", formato_pesos(filtrado["JORGE"].sum()))
    m2.metric("Total Erik", formato_pesos(filtrado["ERIK"].sum()))
    m3.metric("Total Gastos", formato_pesos(filtrado[COL_GAST].sum()))
    m4.metric("Neto (J+E-G)", formato_pesos(filtrado["NETO"].sum()))

    tabla = filtrado.copy()
    for col in ["JORGE", "ERIK", COL_GAST, "TOTAL_PRODUCIDO", "NETO"]:
        tabla[col] = tabla[col].apply(formato_pesos)

    st.dataframe(tabla, use_container_width=True, hide_index=True)

else:
    st.info("No hay datos registrados aún.")

