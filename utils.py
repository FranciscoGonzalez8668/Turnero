import logging
import re
import time
from datetime import datetime, timedelta

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

import config


def calcular_proximo_horario_turnera(now: datetime | None = None) -> datetime:
    """Devuelve el próximo datetime en el que se abre la turnera según TURNERA_SLOTS."""
    if now is None:
        now = datetime.now()

    candidatos = []
    for h, m in config.TURNERA_SLOTS:
        dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if dt > now:
            candidatos.append(dt)

    if candidatos:
        return min(candidatos)

    # Ningún slot futuro hoy -> tomar el primero de mañana
    h, m = config.TURNERA_SLOTS[0]
    mañana = now + timedelta(days=1)
    return mañana.replace(hour=h, minute=m, second=0, microsecond=0)


def esperar_hasta(target: datetime):
    """Bloquea el proceso hasta el datetime target."""
    while True:
        now = datetime.now()
        if now >= target:
            break
        diff = (target - now).total_seconds()
        if diff > 60:
            time.sleep(30)
        elif diff > 10:
            time.sleep(5)
        else:
            time.sleep(0.5)


def _log_exception(usuario: str, msg: str, err: Exception):
    logging.exception("[%s] %s: %s", usuario, msg, err)


def _safe_click(page, selector: str, usuario: str, timeout: int = 30000, optional: bool = False) -> bool:
    try:
        page.click(selector, timeout=timeout)
        return True
    except PlaywrightTimeoutError:
        if optional:
            logging.info("[%s] Elemento opcional no encontrado: %s", usuario, selector)
        else:
            logging.warning("[%s] No se pudo clickear selector: %s", usuario, selector)
        return False
    except Exception as err:  # noqa: BLE001
        _log_exception(usuario, f"Error haciendo click en {selector}", err)
        return False


def _wait_selector(page, selector, usuario: str, timeout: int = 30000) -> bool:
    selectors = selector if isinstance(selector, list) else [selector]
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=timeout)
            return True
        except PlaywrightTimeoutError:
            continue
        except Exception as err:  # noqa: BLE001
            _log_exception(usuario, f"Error esperando selector {sel}", err)
            continue
    logging.warning("[%s] No se encontró selector: %s", usuario, selectors)
    return False


def _click_first_available(page, selectors, usuario: str, timeout: int = 30000) -> bool:
    for selector in selectors:
        if _safe_click(page, selector, usuario, timeout=timeout):
            return True
    logging.warning("[%s] Ningún selector funcionó: %s", usuario, selectors)
    return False


def _click_first_available_any_frame(page, selectors, usuario: str, timeout: int = 30000) -> bool:
    frames = [("page", page)] + [(f"frame:{idx}", frame) for idx, frame in enumerate(page.frames)]
    for frame_name, frame in frames:
        for selector in selectors:
            try:
                frame.click(selector, timeout=timeout)
                logging.info("[%s] Click en '%s' dentro de %s", usuario, selector, frame_name)
                return True
            except PlaywrightTimeoutError:
                continue
            except Exception as err:  # noqa: BLE001
                _log_exception(usuario, f"Error click en {selector} ({frame_name})", err)
                continue
    logging.warning("[%s] No se pudo clickear con ningún selector en ningún frame: %s", usuario, selectors)
    return False


def _contains_text_any_frame(page, textos: list[str]) -> bool:
    for frame in page.frames:
        try:
            html = frame.content()
        except Exception:
            continue
        for txt in textos:
            if txt.lower() in html.lower():
                return True
    return False


def _fill_first_available_any_frame(page, selectors, value: str, usuario: str) -> bool:
    sels = selectors if isinstance(selectors, list) else [selectors]
    for frame in page.frames:
        for selector in sels:
            try:
                frame.click(selector, timeout=3000)
                frame.fill(selector, value, timeout=5000)
                logging.info("[%s] Fill '%s' en frame %s", usuario, selector, frame.url)
                return True
            except PlaywrightTimeoutError:
                logging.debug("[%s] Selector no disponible aún: %s en frame %s", usuario, selector, frame.url)
                continue
            except Exception as err:  # noqa: BLE001
                _log_exception(usuario, f"Error llenando {selector} ({frame.url})", err)
                continue
    logging.warning("[%s] No se pudo llenar ningún selector: %s", usuario, selectors)
    return False


def _wait_for_loading_end(page, usuario: str, timeout_ms: int = 20000) -> bool:
    deadline = time.time() + timeout_ms / 1000
    loaders = config.SELECTORES["loaders"]

    while time.time() < deadline:
        loader_found = False
        for frame in page.frames:
            for sel in loaders:
                try:
                    handle = frame.query_selector(sel)
                except Exception:
                    continue
                if handle:
                    loader_found = True
                    try:
                        frame.wait_for_selector(sel, state="hidden", timeout=2000)
                    except PlaywrightTimeoutError:
                        pass
        if not loader_found:
            try:
                page.wait_for_load_state("networkidle", timeout=2000)
            except PlaywrightTimeoutError:
                pass
            return True
    logging.warning("[%s] Timeout esperando fin de loading", usuario)
    return False


def _wait_for_any_frame_selector(page, selectors, usuario: str, timeout_ms: int = 10000) -> bool:
    end = time.time() + timeout_ms / 1000
    sels = selectors if isinstance(selectors, list) else [selectors]
    while time.time() < end:
        for frame in page.frames:
            for sel in sels:
                try:
                    if frame.query_selector(sel):
                        return True
                except Exception:
                    continue
        time.sleep(0.3)
    logging.warning("[%s] Timeout esperando selectores %s en algún frame", usuario, sels)
    return False


def _get_widget_frame(page):
    for frame in page.frames:
        if "citaconsular" in frame.url or "bookitit" in frame.url:
            return frame
    return page.main_frame


def _wait_fill_in_frame(frame, selectors, value: str, usuario: str, timeout_ms: int = 10000) -> bool:
    end = time.time() + timeout_ms / 1000
    sels = selectors if isinstance(selectors, list) else [selectors]
    while time.time() < end:
        for selector in sels:
            try:
                frame.wait_for_selector(selector, timeout=2000)
                frame.click(selector, timeout=2000)
                frame.fill(selector, value, timeout=5000)
                logging.info("[%s] Fill '%s' en frame %s", usuario, selector, frame.url)
                return True
            except PlaywrightTimeoutError:
                try:
                    handle = frame.query_selector(selector)
                    if handle:
                        frame.evaluate(
                            "(el, val) => { el.focus(); el.value = val; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); }",
                            handle,
                            value,
                        )
                        logging.info("[%s] Force-filled '%s' en frame %s", usuario, selector, frame.url)
                        return True
                except Exception:
                    pass
                continue
            except Exception as err:  # noqa: BLE001
                _log_exception(usuario, f"Error llenando {selector} ({frame.url})", err)
                continue
        time.sleep(0.3)
    logging.warning("[%s] No se pudo llenar selectores en frame %s: %s", usuario, frame.url, sels)
    return False


def _formatear_dni(dni: str) -> str:
    digits = re.sub(r"\D", "", dni)
    if len(digits) == 8:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:]}"
    if len(digits) == 7:
        return f"{digits[:1]}.{digits[1:4]}.{digits[4:]}"
    return dni


def _login_desde_consultar(page, usuario: str, password: str) -> bool:
    if not _click_first_available_any_frame(
        page, [config.SELECTORES["consultar_link"]], usuario, timeout=10000
    ):
        logging.warning("[%s] No se pudo abrir 'Cancelar o consultar mis reservas'", usuario)
        return False

    _wait_for_loading_end(page, usuario, timeout_ms=15000)

    dni_fmt = _formatear_dni(usuario)
    if not _fill_first_available_any_frame(page, config.SELECTORES["consultar_dni"], dni_fmt, usuario):
        return False
    if not _fill_first_available_any_frame(page, config.SELECTORES["consultar_password"], password, usuario):
        return False

    if not _click_first_available_any_frame(
        page, config.SELECTORES["consultar_login_btn"], usuario, timeout=8000
    ):
        logging.warning("[%s] No se pudo clickear Acceder en consultar", usuario)
        return False

    _wait_for_loading_end(page, usuario, timeout_ms=15000)

    if not _click_first_available_any_frame(
        page, config.SELECTORES["consultar_back"], usuario, timeout=8000
    ):
        logging.warning("[%s] No se encontró flecha/volver a pedir cita", usuario)
        return False

    _wait_for_loading_end(page, usuario, timeout_ms=10000)
    return True


def _force_click(frame, selector: str, usuario: str) -> bool:
    try:
        frame.click(selector, timeout=2000)
        return True
    except Exception:
        try:
            el = frame.query_selector(selector)
            if el:
                frame.evaluate("(e)=>e.click()", el)
                logging.info("[%s] Click forzado en %s", usuario, selector)
                return True
        except Exception:
            pass
    return False
