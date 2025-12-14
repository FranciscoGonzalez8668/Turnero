import logging
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from playwright.sync_api import sync_playwright

import config
from booking import intentar_sacar_turno

df_lock = threading.Lock()


def _crear_contexto(browser):
    ua = random.choice(config.USER_AGENTS)
    return browser.new_context(
        user_agent=ua,
        viewport={"width": 1300, "height": 900},
    )


def _cargar_excel() -> pd.DataFrame | None:
    if not config.EXCEL_PATH.exists():
        logging.error("No se encontró el Excel en %s", config.EXCEL_PATH)
        return None
    try:
        df = pd.read_excel(config.EXCEL_PATH, engine="openpyxl").fillna("")
    except Exception as err:  # noqa: BLE001
        logging.exception("No se pudo cargar el Excel: %s", err)
        return None
    if config.COL_TURNO not in df.columns:
        df[config.COL_TURNO] = ""
    return df


def _guardar_turno(df: pd.DataFrame, idx: int):
    with df_lock:
        df.loc[idx, config.COL_TURNO] = "SI"
        try:
            df.to_excel(config.EXCEL_PATH, index=False)
        except Exception as err:  # noqa: BLE001
            logging.exception("No se pudo guardar el Excel: %s", err)


def _procesar_fila(browser, df: pd.DataFrame, idx: int, usuario: str, password: str, turno_conseguido: str):
    if not usuario or not password:
        logging.warning("[FILA %s] Usuario/Contraseña vacíos, saltando...", idx)
        return
    if turno_conseguido.upper() == "SI":
        logging.info("[%s] Ya tiene turno (Turno Conseguido = SI), saltando...", usuario)
        return

    logging.info("=== Intentando sacar turno para usuario: %s ===", usuario)

    context = _crear_contexto(browser)
    page = context.new_page()

    try:
        resultado = intentar_sacar_turno(page, usuario, password)
    except Exception as err:  # noqa: BLE001
        logging.exception("[%s] EXCEPCIÓN no controlada: %s", usuario, err)
        resultado = "ERROR"
    finally:
        page.close()
        context.close()

    logging.info("[%s] Resultado: %s", usuario, resultado)

    if resultado == "OK":
        _guardar_turno(df, idx)


def run():
    logging.basicConfig(level=config.LOG_LEVEL, format=config.LOG_FORMAT)

    df = _cargar_excel()
    if df is None:
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT_BOTS) as executor:
            futures = []
            for idx, row in df.iterrows():
                usuario = str(row.get(config.COL_USUARIO, "")).strip()
                password = str(row.get(config.COL_PASSWORD, "")).strip()
                turno_conseguido = str(row.get(config.COL_TURNO, "")).strip()
                futures.append(
                    executor.submit(
                        _procesar_fila,
                        browser,
                        df,
                        idx,
                        usuario,
                        password,
                        turno_conseguido,
                    )
                )

            for future in as_completed(futures):
                future.result()

        browser.close()

    logging.info("Proceso terminado. Excel actualizado.")
