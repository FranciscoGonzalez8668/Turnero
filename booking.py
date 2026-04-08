import logging
import re
import signal
import time
from datetime import datetime
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
    calcular_proxima_ventana_pingpong,
    _wait_fill_in_frame,
    _wait_for_any_frame_selector,
    _wait_for_loading_end,
    _wait_selector,
    calcular_ventana_pingpong,
    esperar_hasta,
)


_dump_state: dict[str, object] = {"page": None, "usuario": None}
_signals_registrados = False


def _safe_fragment(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value)).strip("_")
    return cleaned or "N_A"


def _save_runtime_screenshot(page, destino: Path, usuario: str, etiqueta: str):
    try:
        page.screenshot(path=str(destino), full_page=True)
        logging.info("[%s] Screenshot runtime (%s) guardado en %s", usuario, etiqueta, destino)
    except Exception as err:  # noqa: BLE001
        _log_exception(usuario, f"No se pudo guardar screenshot runtime ({etiqueta})", err)


def _dump_memoria(page, usuario: str, etiqueta: str):
    """Guarda un dump HTML específico para la pantalla de Memoria Democrática."""
    try:
        if page is None or page.is_closed():
            logging.warning("[%s] Dump memoria (%s) omitido: page no disponible", usuario, etiqueta)
            return
        destino_dir = Path("logs_memorias")
        destino_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        etiqueta_segura = _safe_fragment(etiqueta)
        destino_html = destino_dir / f"dump_memoria_{usuario}_{ts}_{etiqueta_segura}.html"
        destino_png = destino_dir / f"screenshot_memoria_{usuario}_{ts}_{etiqueta_segura}.png"
        destino_html.write_text(page.content(), encoding="utf-8")
        logging.info("[%s] Dump memoria (%s) guardado en %s", usuario, etiqueta, destino_html)
        _save_runtime_screenshot(page, destino_png, usuario, etiqueta)
    except Exception as err:  # noqa: BLE001
        _log_exception(usuario, f"No se pudo guardar dump memoria ({etiqueta})", err)


def _dump_html_snapshot(motivo: str):
    page = _dump_state.get("page")
    usuario = _dump_state.get("usuario") or "N/A"
    if page is None:
        logging.warning("Dump HTML solicitado (%s) pero no hay page activa", motivo)
        return
    try:
        if page.is_closed():
            logging.warning("Dump HTML (%s) omitido: la página ya está cerrada", motivo)
            return
        # Si el context/browser ya se cerró, no forzar espera.
        ctx = page.context
        if ctx is None or ctx.browser is None:
            logging.warning("Dump HTML (%s) omitido: contexto o browser no disponible", motivo)
            return
    except Exception:
        logging.warning("Dump HTML (%s) omitido: no se pudo verificar estado de página", motivo)
        return
    try:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        motivo_seguro = _safe_fragment(motivo)
        destino = config.LOG_DIR / f"dump_{usuario}_{ts}.html"
        destino_png = config.LOG_DIR / f"screenshot_{usuario}_{ts}_{motivo_seguro}.png"
        html = page.content()
        destino.write_text(html, encoding="utf-8")
        logging.warning("[%s] Dump HTML (%s) guardado en %s", usuario, motivo, destino)
        _save_runtime_screenshot(page, destino_png, str(usuario), motivo)
    except Exception as err:  # noqa: BLE001
        _log_exception(str(usuario), f"No se pudo guardar dump HTML por {motivo}", err)


def _signal_dump_handler(signum, frame):  # noqa: ANN001
    motivo = f"signal_{signum}"
    _dump_html_snapshot(motivo)
    raise SystemExit(0)


def _registrar_dump_html(page, usuario: str):
    global _signals_registrados
    _dump_state["page"] = page
    _dump_state["usuario"] = usuario
    if not _signals_registrados:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _signal_dump_handler)
            except Exception:
                continue
        _signals_registrados = True


def _esperar_turnos_disponibles(
    page, usuario: str, max_intentos: int = 50, deadline: datetime | None = None
) -> tuple[bool, bool]:
    sin_turnos_textos = ["no hay horas disponibles", "no tienes ninguna cita"]

    def _sleep_with_deadline(segundos: float) -> bool:
        if deadline is None:
            time.sleep(segundos)
            return True
        restante = (deadline - datetime.now()).total_seconds()
        if restante <= 0:
            return False
        time.sleep(min(segundos, max(0, restante)))
        return datetime.now() < deadline

    for intento in range(max_intentos):
        if deadline and datetime.now() >= deadline:
            logging.warning("[%s] Ventana de pingpong cerrada a las %s", usuario, deadline.strftime("%H:%M:%S"))
            _dump_html_snapshot("pingpong_deadline")
            return False, True

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
            _wait_for_loading_end(page, usuario, timeout_ms=None, deadline=deadline)
            _click_first_available_any_frame(page, config.SELECTORES["back_arrow"], usuario, timeout=8000)
            logging.info("[%s] Ciclo Ver historial ↔︎ Flecha completado sin pausa fija", usuario)

        _wait_for_loading_end(page, usuario, timeout_ms=None, deadline=deadline)

        if intento % 3 == 0:
            _dump_memoria(page, usuario, f"pingpong_intento_{intento + 1}")

        try:
            # Buscar tabla_turnos en todos los frames
            for frame in page.frames:
                try:
                    if frame.query_selector(config.SELECTORES["tabla_turnos"]):
                        logging.info("[%s] Tabla de turnos detectada en intento %s (frame %s)", usuario, intento + 1, frame.url)
                        return True, False
                except Exception:
                    continue

            # Buscar servicio_card en todos los frames
            servicio_selectors = config.SELECTORES["servicio_card"]
            sels = servicio_selectors if isinstance(servicio_selectors, (list, tuple, set)) else [servicio_selectors]
            cartel_encontrado = False
            for frame in page.frames:
                for sel in sels:
                    try:
                        if frame.query_selector_all(sel):
                            logging.info("[%s] Servicio visible (tarjeta) con selector %s en frame %s, avanzando a selección", usuario, sel, frame.url)
                            cartel_encontrado = True
                            return True, False
                    except Exception:
                        continue
            if not cartel_encontrado:
                # Chequeo secundario: esperar brevemente por el texto en el DOM de cada frame.
                # Usa MutationObserver internamente — se dispara en el instante que aparece,
                # sin depender de la estructura HTML del cartel.
                for frame in page.frames:
                    try:
                        frame.wait_for_function(
                            "() => document.body.innerText.toLowerCase().includes('memoria democrática')",
                            timeout=1500,
                        )
                        logging.info("[%s] Cartel detectado via texto en frame %s (intento %s)", usuario, frame.url, intento + 1)
                        return True, False
                    except PlaywrightTimeoutError:
                        continue
                    except Exception as err:  # noqa: BLE001
                        _log_exception(usuario, "Error en wait_for_function cartel", err)
                        continue
                logging.info("[%s] Cartel Memoria Democrática no visible (intento %s/%s)", usuario, intento + 1, max_intentos)
        except Exception as err:  # noqa: BLE001
            _log_exception(usuario, "Error buscando tabla/servicio", err)

        try:
            html = page.content().lower()
            if any(txt in html for txt in sin_turnos_textos):
                logging.info("[%s] Sin turnos. Reintentando pronto (intento %s/%s)", usuario, intento + 1, max_intentos)
                if datetime.now() >= deadline:
                    logging.warning("[%s] Ventana de pingpong terminada durante espera de reintento", usuario)
                    return False, True
                _click_first_available_any_frame(page, config.SELECTORES["ver_historial"], usuario, timeout=8000)
                continue
        except Exception as err:  # noqa: BLE001
            _log_exception(usuario, "Error leyendo HTML para detectar sin turnos", err)

        if deadline and datetime.now() >= deadline:
            logging.warning("[%s] Ventana de pingpong terminada durante espera corta", usuario)
            _dump_html_snapshot("pingpong_deadline")
            return False, True

    if deadline and datetime.now() >= deadline:
        logging.warning("[%s] Ventana de pingpong cerrada antes de ver turnos disponibles", usuario)
        _dump_html_snapshot("pingpong_deadline")
        return False, True

    logging.warning("[%s] Máximos intentos sin ver turnos disponibles", usuario)
    _dump_html_snapshot("max_intentos_sin_turnos")
    return False, False


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


def _buscar_botones_turno(page, usuario: str, quiet: bool = False):
    for selector in config.SELECTORES["botones_turno"]:
        try:
            botones = page.query_selector_all(selector)
            if botones:
                logging.info("[%s] %s botones encontrados con selector %s", usuario, len(botones), selector)
                return botones
        except Exception as err:  # noqa: BLE001
            _log_exception(usuario, f"Error listando botones de turno con {selector}", err)
    if not quiet:
        logging.warning("[%s] No se encontraron botones de turno con los selectores configurados", usuario)
    return []


def _esperar_lista_horarios(page, usuario: str, timeout_ms: int = 25000, use_networkidle: bool = True) -> bool:
    _wait_for_loading_end(page, usuario, timeout_ms=timeout_ms, use_networkidle=use_networkidle)
    return _wait_selector(page, config.SELECTORES["slots_contenedor"], usuario, timeout=timeout_ms)


def _descargar_comprobante(page, usuario: str) -> bool:
    if not _wait_selector(page, config.SELECTORES["confirmacion_ok"], usuario, timeout=30000):
        logging.warning("[%s] No se detectó confirmación de reserva", usuario)
        return False

    _wait_for_loading_end(page, usuario, timeout_ms=12000)

    for selector in config.SELECTORES["print_icon"]:
        try:
            with page.expect_download(timeout=20000) as download_info:
                if not _click_first_available_any_frame(page, [selector], usuario, timeout=12000):
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
        new_page = page.context.wait_for_event("page", timeout=25000)
        work_page = new_page
        work_page.wait_for_load_state("load")
        logging.info("[%s] Se abrió nueva pestaña para el widget: %s", usuario, work_page.url)
    except PlaywrightTimeoutError:
        work_page.wait_for_load_state("load")
        logging.info("[%s] Sin nueva pestaña; seguimos en la actual: %s", usuario, work_page.url)

    _registrar_dump_html(work_page, usuario)

    logging.info("[%s] URL tras popup: %s", usuario, work_page.url)
    for idx, frame in enumerate(work_page.frames):
        logging.info("[%s] Frame %s: %s", usuario, idx, frame.url)

    if not _wait_for_any_frame_selector(work_page, config.SELECTORES["landing_continuar"], usuario, timeout_ms=30000):
        _dump_html_snapshot("landing_continuar_timeout")
    if not _click_first_available_any_frame(work_page, config.SELECTORES["landing_continuar"], usuario, timeout=30000):
        logging.info("[%s] Reintentando click en Continuar con espera extra", usuario)
        _wait_for_any_frame_selector(work_page, config.SELECTORES["landing_continuar"], usuario, timeout_ms=15000)
        if not _click_first_available_any_frame(work_page, config.SELECTORES["landing_continuar"], usuario, timeout=30000):
            _dump_html_snapshot("landing_continuar_click_fail")
    work_page.wait_for_load_state("load")
    _wait_for_loading_end(work_page, usuario, timeout_ms=35000)

    page = work_page
    widget_frame = _get_widget_frame(page)
    inicio_pingpong, fin_pingpong = calcular_proxima_ventana_pingpong()

    try:
        restante_ms = int((fin_pingpong - datetime.now()).total_seconds() * 1000)
        if restante_ms <= 0:
            logging.warning(
                "[%s] Ventana de pingpong vencida antes de mostrar login (%s >= %s)",
                usuario,
                datetime.now().strftime("%H:%M:%S"),
                fin_pingpong.strftime("%H:%M:%S"),
            )
            return "PING_TIMEOUT"

        if not _wait_for_any_frame_selector(
            page, [config.SELECTORES["consultar_link"]], usuario, timeout_ms=restante_ms
        ):
            _dump_html_snapshot("consultar_link_timeout")
            return "PING_TIMEOUT"

        _click_first_available_any_frame(page, [config.SELECTORES["consultar_link"]], usuario, timeout=20000)
        _wait_for_loading_end(page, usuario, timeout_ms=20000)

        if not _wait_fill_in_frame(widget_frame, config.SELECTORES["login_usuario"], _formatear_dni(usuario), usuario, timeout_ms=20000):
            raise PlaywrightTimeoutError("No se pudo ubicar campo usuario")

        if not _wait_fill_in_frame(widget_frame, config.SELECTORES["login_password"], password, usuario, timeout_ms=20000):
            raise PlaywrightTimeoutError("No se pudo ubicar campo contraseña")

        _click_first_available_any_frame(page, config.SELECTORES["login_submit"], usuario, timeout=20000)
    except PlaywrightTimeoutError:
        try:
            for idx, frame in enumerate(page.frames):
                html = frame.content()[:5000]
                logging.warning("[%s] DEBUG frame %s (url %s) snippet: %s", usuario, idx, frame.url, html)
        except Exception as err:  # noqa: BLE001
            _log_exception(usuario, "No se pudo leer HTML para debug", err)
        _dump_html_snapshot("login_timeout")
        return "ERROR"

    try:
        page.wait_for_selector(config.SELECTORES["login_error"], timeout=5000)
        return "ERROR"
    except PlaywrightTimeoutError:
        pass

    ahora = datetime.now()
    if ahora < inicio_pingpong:
        logging.info("[%s] Esperando hasta %s para iniciar pingpong", usuario, inicio_pingpong.strftime("%H:%M:%S"))
        esperar_hasta(inicio_pingpong)
    else:
        logging.info("[%s] Minuto 10 alcanzado, iniciando pingpong enseguida", usuario)

    turnos_disponibles, deadline_hit = _esperar_turnos_disponibles(
        page, usuario, deadline=fin_pingpong, max_intentos=50
    )
    if not turnos_disponibles:
        if deadline_hit:
            return "PING_TIMEOUT"
        return "SIN_TURNOS"

    servicio_visible = False
    memoria_click_ts: float | None = None
    dump_10seg_realizado = False
    try:
        servicio_visible = _click_first_available_any_frame(page, config.SELECTORES["servicio_card"], usuario, timeout=3000)
        if servicio_visible:
            _wait_for_loading_end(page, usuario, timeout_ms=30000, use_networkidle=False)
            _dump_memoria(page, usuario, "instantaneo")
            memoria_click_ts = time.monotonic()
    except Exception as err:  # noqa: BLE001
        _log_exception(usuario, "Error intentando clickear servicio", err)

    if not servicio_visible:
        if not _wait_selector(page, config.SELECTORES["tabla_turnos"], usuario, timeout=30000):
            html = page.content()
            if "bloqueado" in html or "demasiados intentos" in html:
                return "BLOQUEADO"
            return "SIN_TURNOS"

    # Polling continuo de slots sin bloqueos largos: mantiene al bot atento a
    # botones nuevos dentro de la ventana activa.
    botones_turno = []
    while datetime.now() < fin_pingpong:
        if memoria_click_ts and not dump_10seg_realizado and (time.monotonic() - memoria_click_ts) >= 10:
            _dump_memoria(page, usuario, "10seg")
            dump_10seg_realizado = True

        botones_turno = _buscar_botones_turno(page, usuario, quiet=True)
        if botones_turno:
            break

        html = page.content().lower()
        if "bloqueado" in html or "demasiados intentos" in html:
            return "BLOQUEADO"

        _wait_for_loading_end(
            page,
            usuario,
            timeout_ms=1500,
            deadline=fin_pingpong,
            use_networkidle=False,
        )
        time.sleep(0.25)

    if not botones_turno:
        botones_turno = _buscar_botones_turno(page, usuario, quiet=False)

    if not botones_turno:
        html = page.content()
        if "bloqueado" in html or "demasiados intentos" in html:
            return "BLOQUEADO"
        return "SIN_TURNOS"

    boton_elegido = _seleccionar_boton_turno(botones_turno, target_slot, usuario)
    if not boton_elegido:
        return "SIN_TURNOS"
    try:
        boton_elegido.click(timeout=12000)
    except Exception as err:  # noqa: BLE001
        _log_exception(usuario, "Error haciendo click en botón de horario", err)
        return "SIN_TURNOS"

    _wait_for_loading_end(page, usuario, timeout_ms=25000)
    _click_first_available_any_frame(page, [config.SELECTORES["confirmar"]], usuario, timeout=20000)
    _wait_for_loading_end(page, usuario, timeout_ms=25000)

    _descargar_comprobante(page, usuario)

    return "OK"
