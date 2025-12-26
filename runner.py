import logging
import math
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

import config
from booking import intentar_sacar_turno

df_lock = threading.Lock()


def _target_slot_for_idx(idx: int) -> int:
    """Distribuye bots logarítmicamente: los primeros van al slot 0, los siguientes a slots posteriores."""
    if idx <= 0:
        return 0
    slot = int(math.log2(idx + 1))
    return min(slot, config.MAX_SLOT_INDEX)


def _crear_contexto(browser):
    ua = random.choice(config.USER_AGENTS)
    return browser.new_context(
        user_agent=ua,
        viewport={"width": 1300, "height": 900},
        accept_downloads=True,
    )


def _setup_logging() -> Path:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = config.LOG_DIR / f"{config.LOG_FILE_PREFIX}_{ts}.log"

    handlers = [
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]

    logging.basicConfig(
        level=getattr(logging, str(config.LOG_LEVEL).upper(), logging.INFO),
        format=config.LOG_FORMAT,
        handlers=handlers,
        force=True,
    )
    logging.info("Log de ejecución: %s", log_file)
    return log_file


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


def _procesar_fila(
    browser,
    df: pd.DataFrame,
    idx: int,
    usuario: str,
    password: str,
    turno_conseguido: str,
):
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
        target_slot = _target_slot_for_idx(idx)
        resultado = intentar_sacar_turno(page, usuario, password, target_slot=target_slot)
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
    _setup_logging()

    df = _cargar_excel()
    if df is None:
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        for idx, row in df.iterrows():
            usuario = str(row.get(config.COL_USUARIO, "")).strip()
            password = str(row.get(config.COL_PASSWORD, "")).strip()
            turno_conseguido = str(row.get(config.COL_TURNO, "")).strip()
            _procesar_fila(browser, df, idx, usuario, password, turno_conseguido)

        browser.close()

    logging.info("Proceso terminado. Excel actualizado.")
