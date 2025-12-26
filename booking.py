import logging
import time
from datetime import timedelta
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

import config
from utils import (
    _click_first_available_any_frame,
    _force_click,
    _formatear_dni,
    _get_widget_frame,
    _log_exception,
    _safe_click,
    _wait_fill_in_frame,
    _wait_for_any_frame_selector,
    _wait_for_loading_end,
    _wait_selector,
)


def _esperar_turnos_disponibles(page, usuario: str, max_intentos: int = 50) -> bool:
    sin_turnos_textos = ["no hay horas disponibles", "no tienes ninguna cita"]

    for intento in range(max_intentos):
        arrow_clicked = _click_first_available_any_frame(page, config.SELECTORES["back_arrow"], usuario, timeout=8000)
        if not arrow_clicked:
            for frame in page.frames:
                for sel in config.SELECTORES["back_arrow"]:
                    if _force_click(frame, sel, usuario):
                        arrow_clicked = True
                        break
                if arrow_clicked:
                    break

        if not arrow_clicked:
            logging.info("[%s] Flecha no clickeada; intentando ciclo via 'Ver historial' primero", usuario)
            _click_first_available_any_frame(page, config.SELECTORES["ver_historial"], usuario, timeout=8000)
            _wait_for_loading_end(page, usuario, timeout_ms=8000)
            _click_first_available_any_frame(page, config.SELECTORES["back_arrow"], usuario, timeout=8000)
            logging.info("[%s] Esperando 60s tras ciclo Ver historial ↔︎ Flecha", usuario)
            time.sleep(60)

        _wait_for_loading_end(page, usuario, timeout_ms=12000)

        try:
            if page.query_selector(config.SELECTORES["tabla_turnos"]):
                logging.info("[%s] Tabla de turnos detectada en intento %s", usuario, intento + 1)
                return True
            if page.query_selector_all(config.SELECTORES["servicio_card"]):
                logging.info("[%s] Servicio visible (tarjeta), avanzando a selección", usuario)
                return True
        except Exception as err:  # noqa: BLE001
            _log_exception(usuario, "Error buscando tabla/servicio", err)

        try:
            html = page.content().lower()
            if any(txt in html for txt in sin_turnos_textos):
                logging.info("[%s] Sin turnos. Esperando 30s antes de reintentar (intento %s/%s)", usuario, intento + 1, max_intentos)
                time.sleep(30)
                _click_first_available_any_frame(page, config.SELECTORES["ver_historial"], usuario, timeout=8000)
                _wait_for_loading_end(page, usuario, timeout_ms=12000)
                continue
        except Exception as err:  # noqa: BLE001
            _log_exception(usuario, "Error leyendo HTML para detectar sin turnos", err)

        time.sleep(3)

    logging.warning("[%s] Máximos intentos sin ver turnos disponibles", usuario)
    return False


def _seleccionar_boton_turno(botones_turno, target_slot: int, usuario: str):
    if not botones_turno:
        return None
    idx_elegido = min(target_slot, len(botones_turno) - 1)
    logging.info(
        "[%s] Elegiendo botón de turno #%s (target %s, total %s)",
        usuario,
        idx_elegido,
        target_slot,
        len(botones_turno),
    )
    return botones_turno[idx_elegido]


def _buscar_botones_turno(page, usuario: str):
    for selector in config.SELECTORES["botones_turno"]:
        try:
            botones = page.query_selector_all(selector)
            if botones:
                logging.info("[%s] %s botones encontrados con selector %s", usuario, len(botones), selector)
                return botones
        except Exception as err:  # noqa: BLE001
            _log_exception(usuario, f"Error listando botones de turno con {selector}", err)
    logging.warning("[%s] No se encontraron botones de turno con los selectores configurados", usuario)
    return []


def _esperar_lista_horarios(page, usuario: str, timeout_ms: int = 25000) -> bool:
    _wait_for_loading_end(page, usuario, timeout_ms=timeout_ms)
    return _wait_selector(page, config.SELECTORES["slots_contenedor"], usuario, timeout=timeout_ms)


def _descargar_comprobante(page, usuario: str) -> bool:
    if not _wait_selector(page, config.SELECTORES["confirmacion_ok"], usuario, timeout=20000):
        logging.warning("[%s] No se detectó confirmación de reserva", usuario)
        return False

    _wait_for_loading_end(page, usuario, timeout_ms=8000)

    for selector in config.SELECTORES["print_icon"]:
        try:
            with page.expect_download(timeout=15000) as download_info:
                if not _click_first_available_any_frame(page, [selector], usuario, timeout=8000):
                    continue
            download = download_info.value
            nombre = download.suggested_filename or f"turno_{usuario}.pdf"
            destino = Path.cwd() / nombre
            download.save_as(str(destino))
            logging.info("[%s] Comprobante descargado en %s", usuario, destino)
            return True
        except PlaywrightTimeoutError:
            logging.warning("[%s] Timeout esperando descarga con selector %s", usuario, selector)
            continue
        except Exception as err:  # noqa: BLE001
            _log_exception(usuario, f"Error al descargar comprobante con {selector}", err)
            continue

    logging.warning("[%s] No se pudo descargar el comprobante", usuario)
    return False


def intentar_sacar_turno(page, usuario: str, password: str, target_slot: int = 0) -> str:
    page.set_default_timeout(30000)
    page.set_default_navigation_timeout(60000)

    page.goto(config.URL_PRINCIPAL, wait_until="load", timeout=60000)

    _safe_click(page, config.SELECTORES["fecha_y_hora"], usuario)
    _safe_click(page, config.SELECTORES["popup_aceptar"], usuario, timeout=5000, optional=True)

    work_page = page
    try:
        new_page = page.context.wait_for_event("page", timeout=15000)
        work_page = new_page
        work_page.wait_for_load_state("load")
        logging.info("[%s] Se abrió nueva pestaña para el widget: %s", usuario, work_page.url)
    except PlaywrightTimeoutError:
        work_page.wait_for_load_state("load")
        logging.info("[%s] Sin nueva pestaña; seguimos en la actual: %s", usuario, work_page.url)

    logging.info("[%s] URL tras popup: %s", usuario, work_page.url)
    for idx, frame in enumerate(work_page.frames):
        logging.info("[%s] Frame %s: %s", usuario, idx, frame.url)

    _wait_for_any_frame_selector(work_page, config.SELECTORES["landing_continuar"], usuario, timeout_ms=20000)
    if not _click_first_available_any_frame(work_page, config.SELECTORES["landing_continuar"], usuario, timeout=20000):
        logging.info("[%s] Reintentando click en Continuar con espera extra", usuario)
        _wait_for_any_frame_selector(work_page, config.SELECTORES["landing_continuar"], usuario, timeout_ms=10000)
        _click_first_available_any_frame(work_page, config.SELECTORES["landing_continuar"], usuario, timeout=20000)
    work_page.wait_for_load_state("load")
    _wait_for_loading_end(work_page, usuario, timeout_ms=25000)

    page = work_page
    widget_frame = _get_widget_frame(page)

    try:
        _wait_for_any_frame_selector(page, [config.SELECTORES["consultar_link"]], usuario, timeout_ms=20000)
        _click_first_available_any_frame(page, [config.SELECTORES["consultar_link"]], usuario, timeout=12000)
        _wait_for_loading_end(page, usuario, timeout_ms=12000)

        if not _wait_fill_in_frame(widget_frame, config.SELECTORES["login_usuario"], _formatear_dni(usuario), usuario, timeout_ms=12000):
            raise PlaywrightTimeoutError("No se pudo ubicar campo usuario")

        if not _wait_fill_in_frame(widget_frame, config.SELECTORES["login_password"], password, usuario, timeout_ms=12000):
            raise PlaywrightTimeoutError("No se pudo ubicar campo contraseña")

        _click_first_available_any_frame(page, config.SELECTORES["login_submit"], usuario, timeout=12000)
    except PlaywrightTimeoutError:
        try:
            for idx, frame in enumerate(page.frames):
                html = frame.content()[:5000]
                logging.warning("[%s] DEBUG frame %s (url %s) snippet: %s", usuario, idx, frame.url, html)
        except Exception as err:  # noqa: BLE001
            _log_exception(usuario, "No se pudo leer HTML para debug", err)
        return "ERROR"

    try:
        page.wait_for_selector(config.SELECTORES["login_error"], timeout=5000)
        return "ERROR"
    except PlaywrightTimeoutError:
        pass

    if not _esperar_turnos_disponibles(page, usuario):
        return "SIN_TURNOS"

    servicio_visible = False
    try:
        servicio_visible = _click_first_available_any_frame(page, config.SELECTORES["servicio_card"], usuario, timeout=12000)
        if servicio_visible:
            _wait_for_loading_end(page, usuario, timeout_ms=20000)
    except Exception as err:  # noqa: BLE001
        _log_exception(usuario, "Error intentando clickear servicio", err)

    if not servicio_visible:
        if not _wait_selector(page, config.SELECTORES["tabla_turnos"], usuario, timeout=20000):
            html = page.content()
            if "bloqueado" in html or "demasiados intentos" in html:
                return "BLOQUEADO"
            return "SIN_TURNOS"

    _esperar_lista_horarios(page, usuario, timeout_ms=30000)

    botones_turno = _buscar_botones_turno(page, usuario)
    if not botones_turno:
        _wait_for_loading_end(page, usuario, timeout_ms=12000)
        _esperar_lista_horarios(page, usuario, timeout_ms=12000)
        botones_turno = _buscar_botones_turno(page, usuario)

    if not botones_turno:
        html = page.content()
        if "bloqueado" in html or "demasiados intentos" in html:
            return "BLOQUEADO"
        return "SIN_TURNOS"

    boton_elegido = _seleccionar_boton_turno(botones_turno, target_slot, usuario)
    if not boton_elegido:
        return "SIN_TURNOS"
    try:
        boton_elegido.click(timeout=8000)
    except Exception as err:  # noqa: BLE001
        _log_exception(usuario, "Error haciendo click en botón de horario", err)
        return "SIN_TURNOS"

    _wait_for_loading_end(page, usuario, timeout_ms=15000)
    _click_first_available_any_frame(page, [config.SELECTORES["confirmar"]], usuario, timeout=12000)
    _wait_for_loading_end(page, usuario, timeout_ms=15000)

    _descargar_comprobante(page, usuario)

    return "OK"
