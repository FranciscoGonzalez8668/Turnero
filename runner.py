import logging
import math
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

import config
from booking import intentar_sacar_turno
from state import load_state, save_state

df_lock = threading.Lock()

MAX_INTENTOS_POR_RUN = 2
COOLDOWN_BLOQUEO = timedelta(hours=2)
DELAY_MIN = 20
DELAY_MAX = 45


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


def _marcar_no_turno(df: pd.DataFrame, idx: int):
    with df_lock:
        df.loc[idx, config.COL_TURNO] = "NO"
        try:
            df.to_excel(config.EXCEL_PATH, index=False)
        except Exception as err:  # noqa: BLE001
            logging.exception("No se pudo guardar el Excel al marcar NO: %s", err)


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
        return "SKIP"
    if turno_conseguido.upper() == "SI":
        logging.info("[%s] Ya tiene turno (Turno Conseguido = SI), saltando...", usuario)
        return "SKIP"

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
    elif resultado == "PING_TIMEOUT":
        _marcar_no_turno(df, idx)
    return resultado


def run():
    _setup_logging()

    state = load_state()
    ahora = datetime.now()
    blocked_until = state.get("blocked_until")

    if blocked_until and ahora < blocked_until:
        logging.warning(
            "IP marcada como bloqueada hasta %s. Saliendo sin ejecutar bots.",
            blocked_until.strftime("%Y-%m-%d %H:%M:%S"),
        )
        save_state(blocked_until, ahora)
        return

    df = _cargar_excel()
    if df is None:
        save_state(blocked_until, ahora)
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        intentos = 0
        bloqueo_detectado = False

        for idx, row in df.iterrows():
            if intentos >= MAX_INTENTOS_POR_RUN or bloqueo_detectado:
                break

            usuario = str(row.get(config.COL_USUARIO, "")).strip()
            password = str(row.get(config.COL_PASSWORD, "")).strip()
            turno_conseguido = str(row.get(config.COL_TURNO, "")).strip()
            resultado = _procesar_fila(browser, df, idx, usuario, password, turno_conseguido)

            if resultado in ("OK", "SIN_TURNOS", "BLOQUEADO", "ERROR"):
                intentos += 1

            if resultado == "BLOQUEADO":
                bloqueo_detectado = True
                blocked_until = datetime.now() + COOLDOWN_BLOQUEO
                logging.warning(
                    "Bloqueo detectado. Activando cooldown hasta %s",
                    blocked_until.strftime("%Y-%m-%d %H:%M:%S"),
                )
                break

            if intentos < MAX_INTENTOS_POR_RUN:
                espera = random.randint(DELAY_MIN, DELAY_MAX)
                logging.info("Esperando %s segundos antes del siguiente intento", espera)
                time.sleep(espera)

        browser.close()

    save_state(blocked_until, datetime.now())
    logging.info("Proceso terminado. Excel actualizado.")
