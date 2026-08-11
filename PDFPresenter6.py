import sys
import os
import threading
import queue
import traceback
import fitz
import json
import uuid
import hashlib
from collections import OrderedDict
from datetime import datetime, timedelta
import numpy as np
import NDIlib as ndi
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QFileDialog,
    QVBoxLayout, QHBoxLayout, QProgressBar, QComboBox, QSizePolicy, QStackedWidget,
    QScrollArea, QMessageBox, QFrame, QGridLayout, QProgressDialog, QLineEdit, QDialog,
    QAction, QCheckBox, QInputDialog, QSplitter, QRadioButton
)
from PyQt5.QtCore import Qt, QSize, QTime, QTimer, QMimeData, QDateTime, QThread, pyqtSignal
from PyQt5.QtGui import (
    QGuiApplication, QPixmap, QImage, QIcon, QFont, QDrag,
    QPainter, QColor, QRadialGradient, QCursor, QPen, QBrush
)
from PyQt5.QtPrintSupport import QPrinter, QPrintDialog

# ------- Registro de Windows -------
import winreg

REG_PATH = r"Software\PDFPresenter"
REG_KEY_LICENSE = "LicenseStatus"
REG_KEY_TRIAL_EXP = "TrialExpiration"

DOC_DRAG_MIME = "application/x-pdfpresenter-doc-index"


def resource_path(name):
    """Resuelve la ruta de un recurso, tanto en desarrollo como dentro del .exe (PyInstaller)."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def read_registry(key, default=None):
    try:
        reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(reg, key)
        winreg.CloseKey(reg)
        return value
    except Exception:
        return default


def write_registry(key, value):
    try:
        reg = winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PATH)
        winreg.SetValueEx(reg, key, 0, winreg.REG_SZ, str(value))
        winreg.CloseKey(reg)
        return True
    except Exception:
        return False


def delete_registry(key):
    try:
        reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(reg, key)
        winreg.CloseKey(reg)
    except Exception:
        pass


class RenderWorker(QThread):
    """Hilo que renderiza páginas en segundo plano para no congelar la interfaz.

    Los pedidos se procesan en serie (cola FIFO). El acceso a los documentos
    fitz queda serializado por el lock de la ventana principal, así que nunca
    hay acceso concurrente a los mismos documentos.
    """
    rendered = pyqtSignal(int, object)  # request_id, QImage

    def __init__(self, render_cb, parent=None):
        super().__init__(parent)
        self._render_cb = render_cb
        self._queue = queue.Queue()
        self._stop_event = threading.Event()

    def submit(self, request_id, doc_idx, page_in_doc, scale):
        self._queue.put((request_id, doc_idx, page_in_doc, scale))

    def stop(self):
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)  # despertar el hilo
        except Exception:
            pass

    def run(self):
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                break
            if self._stop_event.is_set():
                break
            request_id, doc_idx, page_in_doc, scale = item
            try:
                img = self._render_cb(request_id, doc_idx, page_in_doc, scale)
            except Exception:
                img = None
            self.rendered.emit(request_id, img)


class ToggleSwitch(QWidget):
    def __init__(self, parent=None, checked=False):
        super().__init__(parent)
        self._checked = checked
        self._enabled = True
        self.setFixedSize(50, 26)
        self._toggle_pos = 26 if checked else 2
        self.setCursor(Qt.PointingHandCursor if self._enabled else Qt.ForbiddenCursor)
        self.callback = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._enabled:
            self._checked = not self._checked
            self._toggle_pos = 26 if self._checked else 2
            self.update()
            if self.callback:
                self.callback(self._checked)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self._enabled:
            track_color = QColor("#34C759") if self._checked else QColor("#E5E5EA")
            circle_color = QColor("#FFFFFF")
            circle_border = QColor("#DDDDDD")
        else:
            track_color = QColor("#555555") if self._checked else QColor("#444444")
            circle_color = QColor("#888888")
            circle_border = QColor("#666666")

        painter.setBrush(QBrush(track_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 13, 13)

        painter.setBrush(QBrush(circle_color))
        painter.setPen(QPen(circle_border, 1))
        painter.drawEllipse(int(self._toggle_pos), 2, 22, 22)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = checked
        self._toggle_pos = 26 if checked else 2
        self.update()

    def setEnabled(self, enabled):
        self._enabled = enabled
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ForbiddenCursor)
        self.update()

    def isEnabled(self):
        return self._enabled

    def setToolTip(self, text):
        super().setToolTip(text)


class DocumentItem(QFrame):
    """Tarjeta de documento en la vista de selección.

    Emite una señal 'clicked' al hacer clic (si no se arrastró) y permite
    arrastrar el documento para reordenarlo dentro de la grilla.
    """
    clicked = pyqtSignal(int)

    def __init__(self, doc_index, doc_name, thumbnail_pixmap=None, parent=None):
        super().__init__(parent)
        self.doc_index = doc_index
        self.doc_name = doc_name
        self.thumbnail_pixmap = thumbnail_pixmap
        self.start_drag_pos = None
        self._dragging = False
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setLineWidth(2)
        self.setCursor(Qt.OpenHandCursor)
        self.setMinimumSize(180, 150)
        self.setMaximumWidth(200)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setFixedSize(160, 120)
        if self.thumbnail_pixmap:
            self.set_thumbnail(self.thumbnail_pixmap)
        else:
            self.thumbnail_label.setText("Cargando…")
            self.thumbnail_label.setStyleSheet("color: #888; border: 1px dashed #ccc;")
        self.name_label = QLabel(self.doc_name)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setFont(QFont("Helvetica Neue", 10))
        layout.addWidget(self.thumbnail_label)
        layout.addWidget(self.name_label)

    def set_thumbnail(self, pixmap):
        try:
            if pixmap:
                scaled = pixmap.scaled(
                    self.thumbnail_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.thumbnail_label.setPixmap(scaled)
                self.thumbnail_pixmap = pixmap
        except RuntimeError:
            pass

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_drag_pos = event.pos()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.start_drag_pos is not None:
            if (event.pos() - self.start_drag_pos).manhattanLength() > QApplication.startDragDistance():
                self._dragging = True
                self.start_drag()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and not self._dragging:
            self.clicked.emit(self.doc_index)
        self.start_drag_pos = None
        self._dragging = False
        super().mouseReleaseEvent(event)

    def start_drag(self):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(DOC_DRAG_MIME, str(self.doc_index).encode("utf-8"))
        mime.setText(str(self.doc_index))
        drag.setMimeData(mime)
        if self.thumbnail_pixmap:
            drag.setPixmap(self.thumbnail_pixmap.scaled(
                64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
        drag.exec_(Qt.MoveAction)
        self.start_drag_pos = None


class PDFPresenter(QMainWindow):
    _license_key_hash = "e7db87424219e5499a35947365a9a014345ebadc01d37fd7e51a583c6dae369b"
    # Hash para claves ligadas a la máquina: sha256(key + machine_id).
    # Para generar una:  hashlib.sha256(f"TU_CLAVE{hex(uuid.getnode())}".encode()).hexdigest()
    _license_key_hash_machine = ""
    _trial_duration_secs = 15 * 60
    _theme_setting_file = "pdf_presenter_theme_settings.json"
    _page_cache_max = 60

    def __init__(self):
        super().__init__()
        self.ndi_enabled = False
        self.ndi_sender = None
        self.ndi_source_name = "PDF Presenter Output"
        self.setWindowTitle("PDF Presenter")
        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        self.pdf_documents = []
        self.current_doc_index = 0
        self.current_page = 0
        self.total_pages = 0
        self.presenter_window = None
        self.laser_label = None
        self.laser_enabled = True
        self.available_screens = QGuiApplication.screens()
        self.selected_screen_index = 1 if len(self.available_screens) > 1 else 0
        self.presentation_time = QTime(0, 0, 0)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timer)
        self._trial_active = False
        self._trial_expiration = QDateTime()
        self._trial_timer = QTimer(self)
        self._trial_timer.timeout.connect(self._check_trial_status)
        self._full_license_activated = False
        self._machine_id = self._generate_machine_id()
        self.page_cache = OrderedDict()
        self.hidden_pages = {}  # doc_index -> set(páginas ocultas, 0-based dentro del doc)
        self._gallery_widget = None
        self._current_theme = "light"
        # ---- Infraestructura de renderizado en segundo plano ----
        self._render_lock = threading.Lock()
        self._render_seq = 0
        self._structure_version = 0
        self._thumb_version = 0
        self._pending_renders = {}
        self._thumb_pending = {}
        self._preview_requests = {}
        self._last_ndi_pixmap = None
        self.load_theme_setting()
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        self.license_banner = QLabel("⚠️  LICENCIA INACTIVA - Active la licencia para presentar y usar NDI  ⚠️")
        self.license_banner.setAlignment(Qt.AlignCenter)
        self.license_banner.setStyleSheet(
            "background-color: #cc0000; color: white; font-size: 14px; font-weight: bold; padding: 8px;"
        )
        self.license_banner.hide()

        self.time_label = QLabel("00:00:00")
        self.time_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.time_label.setAlignment(Qt.AlignCenter)
        self.trial_label = QLabel("Licencia de prueba: Inactiva")
        self.trial_label.setStyleSheet("font-size: 14px; color: #cc0000; font-weight: bold;")
        self.trial_label.setAlignment(Qt.AlignCenter)
        self.doc_combo = QComboBox()
        self.screen_combo = QComboBox()
        self.current_preview = QLabel()
        self.next_preview = QLabel()
        self.slide_info = QLabel("0 de 0")
        self.progress = QProgressBar()
        self.export_checkboxes = []
        self.init_initial_ui()
        self.selector_index = 0
        self.setAcceptDrops(True)
        self.load_license_from_registry()
        app_instance = QApplication.instance()
        if app_instance:
            app_instance.screenAdded.connect(self.on_screen_added_or_removed)
            app_instance.screenRemoved.connect(self.on_screen_added_or_removed)
        self.presentation_status_label = QLabel()
        self.presentation_status_label.setAlignment(Qt.AlignCenter)
        self.presentation_status_label.hide()
        self.toggle_laser = None
        self.toggle_ndi = None
        self.toggle_theme = None
        self._ndi_timer = QTimer(self)
        self._ndi_timer.timeout.connect(self._send_ndi_pulse)
        self._ndi_timer.setInterval(33)  # ~30 fps
        self._worker = RenderWorker(self._render_qimage, self)
        self._worker.rendered.connect(self._on_render_done)
        self._worker.start()

    # ---------- Utilidades ----------
    def _log_error(self, context, exc):
        try:
            with open("pdf_presenter_error.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat()}] {context}: {exc}\n")
                traceback.print_exc(file=f)
        except Exception:
            pass

    def _cache_put(self, key, value):
        if key in self.page_cache:
            self.page_cache.move_to_end(key)
        self.page_cache[key] = value
        if len(self.page_cache) > self._page_cache_max:
            self.page_cache.popitem(last=False)

    def _generate_machine_id(self):
        return hex(uuid.getnode())

    def _validate_key(self, key):
        k = key.encode()
        if hashlib.sha256(k).hexdigest() == self._license_key_hash:
            return True
        # Claves ligadas a la máquina (para claves nuevas)
        if self._license_key_hash_machine:
            if hashlib.sha256(k + self._machine_id.encode()).hexdigest() == self._license_key_hash_machine:
                return True
        return False

    def _resolve_page(self, page_number):
        """Convierte un número de página global en (doc_idx, página dentro del doc)."""
        if page_number < 0 or page_number >= self.total_pages or not self.pdf_documents:
            return None
        rem = page_number
        for i, doc in enumerate(self.pdf_documents):
            if rem < doc.page_count:
                return (i, rem)
            rem -= doc.page_count
        return None

    def _resolve_cache_key(self, page_number, scale):
        resolved = self._resolve_page(page_number)
        if resolved is None:
            return None
        doc_idx, rem = resolved
        return (doc_idx, rem, scale)

    def _hidden_for(self, doc_idx=None):
        """Set de páginas ocultas del documento indicado (0-based, dentro del doc)."""
        if doc_idx is None:
            doc_idx = self.current_doc_index
        return self.hidden_pages.setdefault(doc_idx, set())

    def _doc_selection_index(self):
        """Índice real del gestor de documentos dentro del stack (los widgets se
        eliminan y re-agregan al recargar PDFs, así que los índices varían)."""
        if hasattr(self, 'document_selection_widget'):
            return self.stacked_widget.indexOf(self.document_selection_widget)
        return self.selector_index

    def _moderator_index(self):
        """Índice real del moderador dentro del stack."""
        if hasattr(self, 'moderator_widget'):
            return self.stacked_widget.indexOf(self.moderator_widget)
        return 2

    # ---------- Renderizado (hilo de fondo) ----------
    def _render_qimage(self, request_id, doc_idx, page_in_doc, scale):
        with self._render_lock:
            try:
                doc = self.pdf_documents[doc_idx]
                page = doc[page_in_doc]
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                data = bytes(pix.samples)
                img = QImage(data, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                return img.copy()  # despegar los píxeles de `data`
            except Exception as e:
                self._log_error("render", e)
                return None

    def _on_render_done(self, rid, qimage):
        info = self._pending_renders.pop(rid, None)
        thumb = self._thumb_pending.pop(rid, None)
        if qimage is None:
            return
        if info is not None:
            slot, key, version = info
            if version == self._structure_version:
                qp = QPixmap.fromImage(qimage)
                self._cache_put(key, qp)
                if slot is not None and self._preview_requests.get(slot) == rid:
                    self._apply_slot(slot, qp)
        if thumb is not None:
            label, key, version = thumb
            if version == self._thumb_version:
                qp = QPixmap.fromImage(qimage)
                self._cache_put(key, qp)
                self._set_thumb(label, qp)

    def render_page_sync(self, page_number, scale=1):
        """Render síncrono (solo para NDI, impresión y exportación)."""
        key = self._resolve_cache_key(page_number, scale)
        if key is None:
            return None
        if key in self.page_cache:
            self.page_cache.move_to_end(key)
            return self.page_cache[key]
        doc_idx, rem, _ = key
        img = self._render_qimage(None, doc_idx, rem, scale)
        if img is None:
            return None
        qp = QPixmap.fromImage(img)
        self._cache_put(key, qp)
        return qp

    def _submit_slot(self, slot, page_number, scale):
        """Pide el render de una página y la aplica al slot ('current'/'next'/'presenter')."""
        self._preview_requests.pop(slot, None)
        key = self._resolve_cache_key(page_number, scale)
        if key is None:
            self._apply_slot(slot, None)
            return
        if key in self.page_cache:
            self.page_cache.move_to_end(key)
            self._apply_slot(slot, self.page_cache[key])
            return
        self._render_seq += 1
        rid = self._render_seq
        self._preview_requests[slot] = rid
        self._pending_renders[rid] = (slot, key, self._structure_version)
        doc_idx, rem, _ = key
        self._worker.submit(rid, doc_idx, rem, scale)

    def _submit_thumbnail(self, label, doc_idx, page_in_doc, version):
        key = (doc_idx, page_in_doc, 0.5)
        if key in self.page_cache:
            self.page_cache.move_to_end(key)
            self._set_thumb(label, self.page_cache[key])
            return
        self._render_seq += 1
        rid = self._render_seq
        self._thumb_pending[rid] = (label, key, version)
        self._worker.submit(rid, doc_idx, page_in_doc, 0.5)

    def _set_thumb(self, label, pixmap):
        try:
            if pixmap and label is not None:
                label.setPixmap(pixmap.scaled(
                    label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))
        except RuntimeError:
            pass

    def _apply_slot(self, slot, pixmap):
        try:
            if slot == 'current':
                if pixmap is None or self.current_preview.width() <= 10:
                    return
                self.current_preview.setPixmap(pixmap.scaled(
                    self.current_preview.width(), self.current_preview.height(),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation))
            elif slot == 'next':
                if pixmap is None or self.next_preview.width() <= 10:
                    return
                self.next_preview.setPixmap(pixmap.scaled(
                    self.next_preview.width(), self.next_preview.height(),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation))
            elif slot == 'presenter':
                if pixmap is None or not (self.presenter_window and self.presenter_window.isVisible()):
                    return
                geo = self.presenter_window.size()
                self.presenter_label.setPixmap(pixmap.scaled(
                    geo.width(), geo.height(),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except RuntimeError:
            pass

    # ---------- Licencia ----------
    def load_license_from_registry(self):
        status = read_registry(REG_KEY_LICENSE)
        if status == "activated":
            self._full_license_activated = True
            self._trial_timer.stop()
        elif status == "trial":
            exp_str = read_registry(REG_KEY_TRIAL_EXP)
            if exp_str:
                exp = QDateTime.fromString(exp_str, Qt.ISODate)
                if exp.isValid() and QDateTime.currentDateTime() < exp:
                    self._trial_active = True
                    self._trial_expiration = exp
                    self._trial_timer.start(1000)
                else:
                    self._clear_license()
            else:
                self._clear_license()
        else:
            self._clear_license()
        self._update_license_ui()

    def save_license_to_registry(self):
        if self._full_license_activated:
            write_registry(REG_KEY_LICENSE, "activated")
            delete_registry(REG_KEY_TRIAL_EXP)
        elif self._trial_active:
            write_registry(REG_KEY_LICENSE, "trial")
            write_registry(REG_KEY_TRIAL_EXP, self._trial_expiration.toString(Qt.ISODate))
        else:
            write_registry(REG_KEY_LICENSE, "inactive")
            delete_registry(REG_KEY_TRIAL_EXP)
        self._update_license_ui()

    def _clear_license(self):
        self._full_license_activated = False
        self._trial_active = False
        self._trial_timer.stop()
        self._trial_expiration = QDateTime()
        write_registry(REG_KEY_LICENSE, "inactive")
        delete_registry(REG_KEY_TRIAL_EXP)
        self._update_license_ui()

    def _activate_license(self):
        self._full_license_activated = True
        self._trial_active = False
        self._trial_timer.stop()
        self.save_license_to_registry()
        self.update_moderator_view()
        self._update_ndi_toggle_state()

    def _start_trial(self):
        self._trial_active = True
        self._trial_expiration = QDateTime.currentDateTime().addSecs(self._trial_duration_secs)
        self._trial_timer.start(1000)
        self.save_license_to_registry()
        QMessageBox.information(self, "Modo de Prueba", "15 minutos de presentación activados. NDI no disponible en modo prueba.")
        self.update_moderator_view()
        self._update_ndi_toggle_state()

    def _check_trial_status(self):
        if self._trial_active and QDateTime.currentDateTime() >= self._trial_expiration:
            self._clear_license()
            self.end_presentation()
            QMessageBox.warning(self, "Fin de la Prueba", "El tiempo de prueba ha finalizado.")
        if hasattr(self, 'moderator_widget') and self.stacked_widget.currentWidget() == self.moderator_widget:
            self.update_moderator_view()
        else:
            self._update_trial_label_only()

    def _update_license_ui(self):
        if self._full_license_activated:
            self.trial_label.setText("Licencia: Completa")
            self.trial_label.setStyleSheet("font-size: 14px; color: #008000; font-weight: bold;")
            self.license_banner.hide()
            if hasattr(self, 'btn_activate_license'):
                self.btn_activate_license.hide()
        elif self._trial_active:
            self.license_banner.hide()
            if hasattr(self, 'btn_activate_license'):
                self.btn_activate_license.hide()
        else:
            self.trial_label.setText("Licencia: Inactiva")
            self.trial_label.setStyleSheet("font-size: 14px; color: #cc0000; font-weight: bold;")
            self.license_banner.show()
            if hasattr(self, 'btn_activate_license'):
                self.btn_activate_license.show()

    def _update_ndi_toggle_state(self):
        if self.toggle_ndi is not None:
            if self._full_license_activated:
                self.toggle_ndi.setEnabled(True)
                self.toggle_ndi.setToolTip("Activar/desactivar salida NDI")
            else:
                if self.ndi_enabled:
                    self.stop_ndi_sender()
                self.toggle_ndi.setChecked(False)
                self.toggle_ndi.setEnabled(False)
                self.toggle_ndi.setToolTip("NDI requiere licencia completa")

    def _update_trial_label_only(self):
        if self._full_license_activated:
            self.trial_label.setText("Licencia: Completa")
            self.trial_label.setStyleSheet("font-size: 14px; color: #008000; font-weight: bold;")
        elif self._trial_active:
            rem = max(0, QDateTime.currentDateTime().secsTo(self._trial_expiration))
            mm, ss = divmod(rem, 60)
            self.trial_label.setText(f"Licencia de prueba: {mm:02d}:{ss:02d}")
            self.trial_label.setStyleSheet("font-size: 14px; color: #cc0000; font-weight: bold;")
        else:
            self.trial_label.setText("Licencia: Inactiva")
            self.trial_label.setStyleSheet("font-size: 14px; color: #cc0000; font-weight: bold;")

    def update_timer(self):
        if (self.presenter_window and self.presenter_window.isVisible()) or self.ndi_enabled:
            self.presentation_time = self.presentation_time.addSecs(1)
            self.time_label.setText(self.presentation_time.toString("hh:mm:ss"))

    # ---------- Tema ----------
    def load_theme_setting(self):
        if os.path.exists(self._theme_setting_file):
            try:
                with open(self._theme_setting_file, 'r') as f:
                    self._current_theme = json.load(f).get("theme", "light")
            except Exception:
                self._current_theme = "light"
        self.apply_theme()

    def save_theme_setting(self):
        try:
            with open(self._theme_setting_file, 'w') as f:
                json.dump({"theme": self._current_theme}, f, indent=4)
        except Exception as e:
            self._log_error("save_theme", e)

    def apply_theme(self):
        self.setStyleSheet(self.get_light_style() if self._current_theme == "light" else self.get_dark_style())

    def _on_theme_toggle(self, checked):
        self._current_theme = "dark" if checked else "light"
        self.apply_theme()
        self.save_theme_setting()

    def get_light_style(self):
        return """
            QMainWindow { background-color: #f2f2f5; color: #333; font-family: 'Segoe UI', sans-serif; }
            QPushButton { background-color: #e0e0e5; border-radius: 8px; padding: 8px 16px; font-size: 14px; border: none; margin: 4px; color: #333; }
            QPushButton:hover { background-color: #d0d0d5; }
            QPushButton#btn_end_presentation { background-color: #cc0000; color: white; }
            QPushButton#btn_end_presentation:hover { background-color: #ff3333; }
            QPushButton#btn_present_active { background-color: #cc0000; color: white; font-weight: bold; }
            QPushButton#btn_present_inactive { background-color: #1e7b3e; color: white; font-weight: bold; }
            QComboBox { padding: 6px; border-radius: 6px; background-color: #f9f9fb; border: 1px solid #ccc; font-size: 14px; color: #333; }
            QProgressBar { height: 12px; border-radius: 6px; background-color: #e0e0e5; border: 1px solid #ccc; }
            QProgressBar::chunk { background-color: #7676ff; border-radius: 5px; }
            QLabel { color: #333; }
            QLineEdit { background-color: #ffffff; border: 1px solid #ccc; color: #333; padding: 5px; border-radius: 5px; }
            QDialog { background-color: #f2f2f5; color: #333; }
            QScrollArea { border: none; }
            QCheckBox { color: #333; }
            QRadioButton { color: #333; }
            QSplitter::handle { background-color: #ccc; width: 3px; }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #333333;
                selection-background-color: #7676ff;
                selection-color: white;
                font-size: 14px;
                padding: 4px;
            }
            QComboBox QAbstractItemView::item {
                padding: 6px;
                min-height: 24px;
            }
            DocumentItem {
                background-color: #ffffff;
                border: 1px solid #ddd;
                border-radius: 10px;
                margin: 5px;
                padding: 10px;
                color: #333;
            }
            DocumentItem:hover {
                background-color: #f0f0f5;
                border: 1px solid #bbb;
            }
        """

    def get_dark_style(self):
        return """
            QMainWindow { background-color: #2e2e2e; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; }
            QPushButton { background-color: #4a4a4a; border-radius: 8px; padding: 8px 16px; font-size: 14px; border: none; margin: 4px; color: #e0e0e0; }
            QPushButton:hover { background-color: #5a5a5a; }
            QPushButton#btn_end_presentation { background-color: #cc0000; color: white; }
            QPushButton#btn_end_presentation:hover { background-color: #ff3333; }
            QPushButton#btn_present_active { background-color: #cc0000; color: white; font-weight: bold; }
            QPushButton#btn_present_inactive { background-color: #1e7b3e; color: white; font-weight: bold; }
            QComboBox { padding: 6px; border-radius: 6px; background-color: #3a3a3a; border: 1px solid #555; font-size: 14px; color: #e0e0e0; }
            QProgressBar { height: 12px; border-radius: 6px; background-color: #4a4a4a; border: 1px solid #555; }
            QProgressBar::chunk { background-color: #007bff; border-radius: 5px; }
            QLabel { color: #e0e0e0; }
            QLineEdit { background-color: #3a3a3a; border: 1px solid #555; color: #e0e0e0; padding: 5px; border-radius: 5px; }
            QDialog { background-color: #2e2e2e; color: #e0e0e0; }
            QScrollArea { border: none; }
            QCheckBox { color: #e0e0e0; }
            QRadioButton { color: #e0e0e0; }
            QSplitter::handle { background-color: #555; width: 3px; }
            QComboBox QAbstractItemView {
                background-color: #3a3a3a;
                color: #e0e0e0;
                selection-background-color: #007bff;
                selection-color: white;
                font-size: 14px;
                padding: 4px;
            }
            QComboBox QAbstractItemView::item {
                padding: 6px;
                min-height: 24px;
            }
            DocumentItem {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 10px;
                margin: 5px;
                padding: 10px;
                color: #e0e0e0;
            }
            DocumentItem:hover {
                background-color: #4a4a4a;
                border: 1px solid #777;
            }
        """

    def init_initial_ui(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.license_banner)
        label = QLabel("PDF Presenter")
        label.setStyleSheet("font-size: 28px; font-weight: bold; margin-bottom: 20px;")
        layout.addWidget(label, alignment=Qt.AlignCenter)
        theme_layout = QHBoxLayout()
        theme_layout.setAlignment(Qt.AlignCenter)
        theme_label = QLabel("☀️  Tema   🌙")
        theme_label.setStyleSheet("font-size: 14px; margin-right: 10px;")
        self.toggle_theme = ToggleSwitch(checked=(self._current_theme == "dark"))
        self.toggle_theme.callback = self._on_theme_toggle
        theme_layout.addWidget(theme_label)
        theme_layout.addWidget(self.toggle_theme)
        layout.addLayout(theme_layout)
        layout.addSpacing(20)
        self.btn_activate_license = QPushButton("Activar Licencia")
        self.btn_activate_license.setStyleSheet("font-size: 14px; padding: 8px 16px; background-color: #007bff; color: white;")
        self.btn_activate_license.clicked.connect(self.show_license_activation_dialog)
        layout.addWidget(self.btn_activate_license, alignment=Qt.AlignCenter)
        layout.addSpacing(10)
        load_btn = QPushButton("Cargar Presentación(es)")
        load_btn.setStyleSheet("font-size: 16px; padding: 12px 24px;")
        load_btn.clicked.connect(lambda: self.load_multiple_pdfs(append=False))
        layout.addWidget(load_btn, alignment=Qt.AlignCenter)
        self.stacked_widget.addWidget(w)
        self.menuBar().hide()

    def show_license_activation_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Activar Licencia")
        lay = QVBoxLayout(dlg)
        if self._trial_active:
            rem = max(0, QDateTime.currentDateTime().secsTo(self._trial_expiration))
            mm, ss = divmod(rem, 60)
            lay.addWidget(QLabel(f"Modo prueba activo - Tiempo restante: {mm:02d}:{ss:02d}"))
        lay.addWidget(QLabel("Introduce la clave de licencia para activación permanente:"))
        inp = QLineEdit()
        inp.setPlaceholderText("Clave de licencia")
        lay.addWidget(inp)
        btns = QHBoxLayout()
        btn_ok = QPushButton("Activar")
        btn_ok.clicked.connect(lambda: self._activate_with_key(inp.text(), dlg))
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(dlg.reject)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        lay.addLayout(btns)
        dlg.exec_()

    def _activate_with_key(self, key, dlg):
        if self._validate_key(key):
            self._activate_license()
            QMessageBox.information(self, "Licencia Activada", "¡Licencia activada correctamente! NDI ahora disponible.")
            dlg.accept()
        else:
            QMessageBox.warning(self, "Clave Inválida", "La clave de licencia introducida es incorrecta.")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(url.toLocalFile().lower().endswith('.pdf') for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        pdfs = [u.toLocalFile() for u in urls if u.toLocalFile().lower().endswith('.pdf')]
        if pdfs:
            self.load_multiple_pdfs(file_paths=pdfs, append=True)

    def load_multiple_pdfs(self, file_paths=None, append=False):
        if not file_paths:
            file_paths, _ = QFileDialog.getOpenFileNames(self, "Seleccionar PDF(s)", "", "PDF files (*.pdf)")
        if file_paths:
            try:
                new_docs = [fitz.open(p) for p in file_paths]
                with self._render_lock:
                    if append:
                        self.pdf_documents.extend(new_docs)
                    else:
                        for doc in self.pdf_documents:
                            doc.close()
                        self.pdf_documents = new_docs
                        self.current_doc_index = 0
                        self.current_page = 0
                        self.page_cache = OrderedDict()
                        self.hidden_pages = {}
                self._structure_version += 1
                self._thumb_version += 1
                self._preview_requests.clear()
                self.total_pages = sum(doc.page_count for doc in self.pdf_documents)
                self.setup_document_selection_view()
                self.stacked_widget.setCurrentIndex(self._doc_selection_index())
                self.update_moderator_view()
                if hasattr(self, 'doc_combo'):
                    self.doc_combo.clear()
                    self.doc_combo.addItems([os.path.basename(d.name) for d in self.pdf_documents])
                    self.doc_combo.setCurrentIndex(self.current_doc_index)
            except Exception as e:
                self._log_error("load_multiple_pdfs", e)
                QMessageBox.critical(self, "Error", f"No se pudieron cargar los PDFs: {e}")

    # ============ VISTA DE SELECCIÓN (con reordenado por arrastre) ============
    def setup_document_selection_view(self):
        if hasattr(self, 'document_selection_widget'):
            self.stacked_widget.removeWidget(self.document_selection_widget)
            self.document_selection_widget.deleteLater()
        self.document_selection_widget = QWidget()
        layout = QVBoxLayout(self.document_selection_widget)
        title = QLabel("Selecciona y Reordena Documentos")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: bold; margin-bottom: 20px;")
        layout.addWidget(title)
        self.doc_scroll = QScrollArea()
        self.doc_scroll.setWidgetResizable(True)
        self.doc_container = QWidget()
        self.doc_grid = QGridLayout(self.doc_container)
        self.doc_scroll.setWidget(self.doc_container)
        layout.addWidget(self.doc_scroll)
        btn_layout = QHBoxLayout()
        btn_add = QPushButton("Añadir PDFs")
        btn_add.clicked.connect(lambda: self.load_multiple_pdfs(append=True))
        btn_join = QPushButton("Unir todos")
        btn_join.clicked.connect(self.join_all_loaded_pdfs)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_join)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        self.stacked_widget.addWidget(self.document_selection_widget)
        self.update_document_selection_view()
        self.doc_container.setAcceptDrops(True)
        self.doc_container.dragEnterEvent = self._doc_grid_drag_enter
        self.doc_container.dragMoveEvent = self._doc_grid_drag_move
        self.doc_container.dropEvent = self._doc_grid_drop

    def update_document_selection_view(self):
        while self.doc_grid.count():
            item = self.doc_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        cols = 3
        self._thumb_version += 1
        for i, doc in enumerate(self.pdf_documents):
            name = os.path.basename(doc.name)
            doc_item = DocumentItem(i, name, None)
            doc_item.clicked.connect(self._select_doc_from_list)
            self.doc_grid.addWidget(doc_item, i // cols, i % cols)
            self._submit_thumbnail(doc_item.thumbnail_label, i, 0, self._thumb_version)

    def _select_doc_from_list(self, doc_idx):
        self.current_doc_index = doc_idx
        self.current_page = sum(d.page_count for d in self.pdf_documents[:doc_idx])
        self.setup_moderator_view()
        self.update_moderator_view()
        self.stacked_widget.setCurrentIndex(self._moderator_index())

    def _doc_grid_drag_enter(self, event):
        if self._accepts_drop(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def _doc_grid_drag_move(self, event):
        if self._accepts_drop(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def _accepts_drop(self, md):
        if md.hasFormat(DOC_DRAG_MIME):
            return True
        return md.hasUrls() and all(u.toLocalFile().lower().endswith('.pdf') for u in md.urls())

    def _doc_grid_drop(self, event):
        md = event.mimeData()
        if md.hasFormat(DOC_DRAG_MIME):
            try:
                src = int(bytes(md.data(DOC_DRAG_MIME)).decode("utf-8"))
            except Exception:
                src = None
            if src is not None and 0 <= src < len(self.pdf_documents):
                target = self._drop_target_index(event.pos())
                self._reorder_document(src, target)
                event.acceptProposedAction()
            return
        urls = md.urls()
        paths = [u.toLocalFile() for u in urls if u.toLocalFile().lower().endswith('.pdf')]
        if paths:
            self.load_multiple_pdfs(file_paths=paths, append=True)

    def _drop_target_index(self, pos):
        w = self.doc_container.childAt(pos)
        if isinstance(w, DocumentItem):
            return w.doc_index
        return len(self.pdf_documents)

    def _reorder_document(self, src, target):
        n = len(self.pdf_documents)
        if not (0 <= src < n and 0 <= target <= n):
            return
        if src == target:
            return
        with self._render_lock:
            doc = self.pdf_documents.pop(src)
            self.pdf_documents.insert(target, doc)

        def remap(old_i):
            if old_i == src:
                return target
            if target > src and src < old_i <= target:
                return old_i - 1
            if target < src and target <= old_i < src:
                return old_i + 1
            return old_i

        self.hidden_pages = {remap(k): v for k, v in self.hidden_pages.items()}
        self.current_doc_index = self.pdf_documents.index(doc)
        self.current_page = sum(d.page_count for d in self.pdf_documents[:self.current_doc_index])
        self.total_pages = sum(d.page_count for d in self.pdf_documents)
        self._structure_version += 1
        self._thumb_version += 1
        self._preview_requests.clear()
        self.page_cache.clear()
        # Reconstruir la grilla después de que termine el drag (evento anidado)
        QTimer.singleShot(0, self.update_document_selection_view)
        if hasattr(self, 'moderator_widget') and self.stacked_widget.indexOf(self.moderator_widget) != -1:
            try:
                self.doc_combo.blockSignals(True)
                self.doc_combo.clear()
                self.doc_combo.addItems([os.path.basename(d.name) for d in self.pdf_documents])
                self.doc_combo.setCurrentIndex(self.current_doc_index)
                self.doc_combo.blockSignals(False)
            except Exception:
                pass
            self.update_moderator_view()

    def join_all_loaded_pdfs(self):
        if not self.pdf_documents:
            return QMessageBox.warning(self, "Nada que unir", "No hay documentos cargados.")
        path, _ = QFileDialog.getSaveFileName(self, "Guardar PDF unificado", "unificado.pdf", "*.pdf")
        if path:
            merged = fitz.open()
            try:
                with self._render_lock:
                    for doc in self.pdf_documents:
                        merged.insert_pdf(doc)
                merged.save(path)
            finally:
                merged.close()
            QMessageBox.information(self, "Unión completada", f"Archivo guardado en:\n{path}")

    # ============ VISTA MODERADOR ============
    def setup_moderator_view(self):
        if hasattr(self, 'moderator_widget'):
            self.stacked_widget.removeWidget(self.moderator_widget)
            self.moderator_widget.deleteLater()
        self.moderator_widget = QWidget()
        layout = QVBoxLayout(self.moderator_widget)
        layout.addWidget(self.license_banner)

        top_bar = QHBoxLayout()
        self.btn_end = QPushButton("Finalizar")
        self.btn_end.setObjectName("btn_end_presentation")
        self.btn_end.clicked.connect(self.end_presentation)
        self.doc_combo.blockSignals(True)
        self.doc_combo.clear()
        self.doc_combo.addItems([os.path.basename(d.name) for d in self.pdf_documents])
        self.doc_combo.setCurrentIndex(self.current_doc_index)
        self.doc_combo.blockSignals(False)
        try:
            self.doc_combo.currentIndexChanged.disconnect()
        except Exception:
            pass
        self.doc_combo.currentIndexChanged.connect(self.change_document)
        self.update_screen_selector()
        top_bar.addWidget(self.btn_end)
        top_bar.addStretch()
        top_bar.addWidget(self.time_label)
        top_bar.addWidget(self.trial_label)
        top_bar.addWidget(self.doc_combo)
        top_bar.addWidget(self.screen_combo)
        layout.addLayout(top_bar)

        split_layout = QHBoxLayout()

        self.current_preview.setAlignment(Qt.AlignCenter)
        self.current_preview.setStyleSheet("background-color: black; border: 2px solid #555; border-radius: 10px;")
        self.current_preview.setMinimumSize(400, 300)
        self.current_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.current_preview.setScaledContents(False)

        self.next_preview.setAlignment(Qt.AlignCenter)
        self.next_preview.setStyleSheet("background-color: black; border: 2px solid #555; border-radius: 10px;")
        self.next_preview.setMinimumSize(150, 100)
        self.next_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.next_preview.setScaledContents(False)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.current_preview)
        splitter.addWidget(self.next_preview)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([500, 200])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.splitterMoved.connect(self._on_splitter_moved)
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        split_layout.addWidget(splitter)
        layout.addLayout(split_layout, 1)

        self.slide_info.setAlignment(Qt.AlignCenter)
        self.slide_info.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.slide_info)
        layout.addWidget(self.progress)

        bottom_bar = QHBoxLayout()
        self.btn_prev = QPushButton("◀ Ant")
        self.btn_prev.clicked.connect(self.prev_page)
        self.btn_gallery = QPushButton("Galería")
        self.btn_gallery.clicked.connect(self.show_thumbnail_gallery)
        self.btn_print = QPushButton("Imprimir")
        self.btn_print.clicked.connect(self.show_print_dialog)

        laser_group = QHBoxLayout()
        laser_label = QLabel("🔴 Láser:")
        laser_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        self.toggle_laser = ToggleSwitch(checked=self.laser_enabled)
        self.toggle_laser.callback = self._on_laser_changed
        laser_group.addWidget(laser_label)
        laser_group.addWidget(self.toggle_laser)

        ndi_group = QHBoxLayout()
        ndi_label = QLabel("📡 NDI:")
        ndi_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        self.toggle_ndi = ToggleSwitch(checked=self.ndi_enabled)
        self.toggle_ndi.callback = self._on_ndi_changed
        ndi_group.addWidget(ndi_label)
        ndi_group.addWidget(self.toggle_ndi)

        self._update_ndi_toggle_state()

        self.btn_present = QPushButton("Iniciar Presentación")
        self.btn_present.setObjectName("btn_present_inactive")
        self.btn_present.clicked.connect(self.toggle_presentation)
        self.btn_next = QPushButton("Sig ▶")
        self.btn_next.clicked.connect(self.next_page)

        bottom_bar.addWidget(self.btn_prev)
        bottom_bar.addWidget(self.btn_gallery)
        bottom_bar.addWidget(self.btn_print)
        bottom_bar.addStretch()
        bottom_bar.addLayout(laser_group)
        bottom_bar.addSpacing(20)
        bottom_bar.addLayout(ndi_group)
        bottom_bar.addStretch()
        bottom_bar.addWidget(self.btn_present)
        bottom_bar.addStretch()
        bottom_bar.addWidget(self.btn_next)
        layout.addLayout(bottom_bar)

        layout.addWidget(self.presentation_status_label)
        self.stacked_widget.addWidget(self.moderator_widget)
        self._update_presentation_button_style()
        self.timer.start(1000)

    def resizeEvent(self, event):
        """Actualiza las previews cuando la ventana cambia de tamaño"""
        super().resizeEvent(event)
        if hasattr(self, 'moderator_widget') and self.stacked_widget.currentWidget() == self.moderator_widget:
            QTimer.singleShot(100, self._refresh_previews)

    def _refresh_previews(self):
        """Pide en segundo plano las previews actual y siguiente."""
        if not self.pdf_documents:
            return
        cur_doc = self.pdf_documents[self.current_doc_index]
        prev_pages = sum(d.page_count for d in self.pdf_documents[:self.current_doc_index])
        page_in_doc = self.current_page - prev_pages

        self._submit_slot('current', self.current_page, 2)

        hidden = self._hidden_for()
        next_visible = None
        for p in range(page_in_doc + 1, cur_doc.page_count):
            if p not in hidden:
                next_visible = p
                break

        if next_visible is not None:
            self._submit_slot('next', prev_pages + next_visible, 2)
        else:
            self._preview_requests.pop('next', None)
            try:
                self.next_preview.clear()
            except RuntimeError:
                pass

    def _on_splitter_moved(self, pos, index):
        """Limita que la preview siguiente no ocupe más del 50% del ancho total"""
        splitter = self.sender()
        total_width = splitter.width()
        max_next_width = total_width // 2
        sizes = splitter.sizes()
        if len(sizes) == 2 and sizes[1] > max_next_width:
            splitter.blockSignals(True)
            splitter.setSizes([total_width - max_next_width, max_next_width])
            splitter.blockSignals(False)

    def _on_laser_changed(self, checked):
        self.laser_enabled = checked
        if self.presenter_window and self.presenter_window.isVisible():
            if self.laser_enabled:
                self.presenter_window.setCursor(Qt.BlankCursor)
            else:
                self.presenter_window.setCursor(Qt.ArrowCursor)
                if self.laser_label:
                    self.laser_label.hide()

    def _on_ndi_changed(self, checked):
        if checked and not self._full_license_activated:
            QMessageBox.warning(self, "NDI no disponible", "La función NDI requiere licencia completa.")
            if self.toggle_ndi:
                self.toggle_ndi.setChecked(False)
            return
        if checked:
            self.start_ndi_sender()
        else:
            self.stop_ndi_sender()
        if self.toggle_ndi:
            self.toggle_ndi.setChecked(self.ndi_enabled)

    def update_screen_selector(self):
        self.screen_combo.clear()
        self.screen_combo.addItem("Deshabilitar", -1)
        for i, s in enumerate(self.available_screens):
            self.screen_combo.addItem(f"Monitor {i+1} - {s.name()}", i)
        if len(self.available_screens) >= 2:
            self.screen_combo.setCurrentIndex(2)
        elif len(self.available_screens) == 1:
            self.screen_combo.setCurrentIndex(1)
        else:
            self.screen_combo.setCurrentIndex(0)

    def change_document(self, index):
        if 0 <= index < len(self.pdf_documents):
            self.current_doc_index = index
            self.current_page = sum(d.page_count for d in self.pdf_documents[:index])
            self.update_moderator_view()

    def update_moderator_view(self):
        self._update_trial_label_only()
        if not hasattr(self, 'moderator_widget') or self.stacked_widget.indexOf(self.moderator_widget) == -1:
            return
        if not self.pdf_documents:
            self.current_preview.clear()
            self.next_preview.clear()
            self.slide_info.setText("0 de 0")
            self.progress.setValue(0)
            return

        cur_doc = self.pdf_documents[self.current_doc_index]
        prev_pages = sum(d.page_count for d in self.pdf_documents[:self.current_doc_index])
        page_in_doc = self.current_page - prev_pages

        hidden = self._hidden_for()
        visible_pages = [p for p in range(cur_doc.page_count) if p not in hidden]
        if visible_pages and page_in_doc not in visible_pages:
            self.current_page = prev_pages + min(visible_pages, key=lambda x: abs(x - page_in_doc))
            page_in_doc = self.current_page - prev_pages

        self._refresh_previews()

        if self.ndi_enabled:
            cur_pix = self.render_page_sync(self.current_page, scale=1)
            if cur_pix:
                self._last_ndi_pixmap = cur_pix
                self.update_ndi_frame(cur_pix)

        self.slide_info.setText(f"Diapositiva {page_in_doc + 1} de {cur_doc.page_count} ({len(visible_pages)} visibles)")
        self.progress.setRange(0, cur_doc.page_count)
        self.progress.setValue(page_in_doc + 1)
        self.update_button_states()
        if self.presenter_window and self.presenter_window.isVisible():
            self.update_presentation()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F5:
            self.start_presentation()
        elif event.key() == Qt.Key_Escape:
            if self.presenter_window and self.presenter_window.isVisible():
                self.end_presentation()
            elif hasattr(self, 'moderator_widget') and self.stacked_widget.currentWidget() == self.moderator_widget:
                # Volver del moderador al gestor de documentos
                self.stacked_widget.setCurrentIndex(self._doc_selection_index())
            elif self._gallery_widget is not None and self.stacked_widget.currentWidget() == self._gallery_widget:
                # Volver de la galería al moderador
                self.stacked_widget.setCurrentIndex(self._moderator_index())
        elif event.key() in (Qt.Key_PageDown, Qt.Key_Right, Qt.Key_Down, Qt.Key_Space):
            self.next_page()
        elif event.key() in (Qt.Key_PageUp, Qt.Key_Left, Qt.Key_Up):
            self.prev_page()
        else:
            super().keyPressEvent(event)

    def next_page(self):
        prev_pages = sum(d.page_count for d in self.pdf_documents[:self.current_doc_index])
        cur = self.pdf_documents[self.current_doc_index]
        page_in_doc = self.current_page - prev_pages
        hidden = self._hidden_for()
        for p in range(page_in_doc + 1, cur.page_count):
            if p not in hidden:
                self.current_page = prev_pages + p
                self.update_moderator_view()
                return

    def prev_page(self):
        prev_pages = sum(d.page_count for d in self.pdf_documents[:self.current_doc_index])
        page_in_doc = self.current_page - prev_pages
        hidden = self._hidden_for()
        for p in range(page_in_doc - 1, -1, -1):
            if p not in hidden:
                self.current_page = prev_pages + p
                self.update_moderator_view()
                return

    def update_button_states(self):
        if not hasattr(self, 'btn_prev') or not self.pdf_documents:
            return
        prev_pages = sum(d.page_count for d in self.pdf_documents[:self.current_doc_index])
        cur = self.pdf_documents[self.current_doc_index]
        page_in_doc = self.current_page - prev_pages
        hidden = self._hidden_for()
        has_prev = any(p not in hidden for p in range(page_in_doc - 1, -1, -1))
        has_next = any(p not in hidden for p in range(page_in_doc + 1, cur.page_count))
        self.btn_prev.setEnabled(has_prev)
        self.btn_next.setEnabled(has_next)

    # ============ GALERÍA CON EXPORTACIÓN ============
    def show_thumbnail_gallery(self):
        if not self.pdf_documents:
            return QMessageBox.warning(self, "No hay PDFs", "Cargá un PDF primero.")
        if self._gallery_widget is not None:
            self.stacked_widget.removeWidget(self._gallery_widget)
            self._gallery_widget.deleteLater()
            self._gallery_widget = None

        scroll = QScrollArea()
        cont = QWidget()
        grid = QGridLayout(cont)
        scroll.setWidget(cont)
        scroll.setWidgetResizable(True)
        self._build_gallery_grid(grid)

        btn_back = QPushButton("Volver al moderador")
        btn_back.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(self._moderator_index()))
        btn_export_sel = QPushButton("Exportar seleccionadas")
        btn_export_sel.clicked.connect(self.export_selected_slides)
        btn_export_all = QPushButton("Exportar todas")
        btn_export_all.clicked.connect(self.export_all_slides)
        btn_print = QPushButton("Imprimir")
        btn_print.clicked.connect(self.show_print_dialog)

        hbox = QHBoxLayout()
        hbox.addWidget(btn_back)
        hbox.addStretch()
        hbox.addWidget(btn_print)
        hbox.addWidget(btn_export_sel)
        hbox.addWidget(btn_export_all)

        lay = QVBoxLayout()
        lay.addWidget(scroll)
        lay.addLayout(hbox)

        gal = QWidget()
        gal.setLayout(lay)
        self._gallery_widget = gal
        self.stacked_widget.addWidget(gal)
        self.stacked_widget.setCurrentWidget(gal)

    def _build_gallery_grid(self, grid):
        """Construye (o reconstruye) la grilla de miniaturas del documento actual."""
        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.export_checkboxes = []
        cur_doc = self.pdf_documents[self.current_doc_index]
        prev = sum(d.page_count for d in self.pdf_documents[:self.current_doc_index])
        hidden = self._hidden_for()
        self._thumb_version += 1
        cols = 4

        for i in range(cur_doc.page_count):
            global_i = prev + i
            container = QVBoxLayout()

            thumb = QLabel()
            thumb.setFixedSize(120, 90)
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setText(f"{i+1}")

            vis_toggle = ToggleSwitch(checked=(i not in hidden))
            vis_toggle.callback = lambda checked, p=i: self._toggle_page_vis(self.current_doc_index, p, checked)

            lbl = QLabel(f"Pág. {i+1}")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("font-weight: bold;")

            export_chk = QCheckBox("Exp.")
            export_chk.setChecked(False)
            self.export_checkboxes.append((global_i, export_chk))

            move_layout = QHBoxLayout()
            btn_up = QPushButton("▲")
            btn_down = QPushButton("▼")
            btn_up.setFixedSize(30, 25)
            btn_down.setFixedSize(30, 25)
            btn_up.clicked.connect(lambda checked, p=i: self.move_page_up(p))
            btn_down.clicked.connect(lambda checked, p=i: self.move_page_down(p))
            move_layout.addWidget(btn_up)
            move_layout.addWidget(btn_down)

            container.addWidget(thumb)
            container.addWidget(vis_toggle)
            container.addWidget(lbl)
            container.addWidget(export_chk)
            container.addLayout(move_layout)

            item = QWidget()
            item.setLayout(container)
            item.mousePressEvent = lambda e, p=global_i: self.select_slide_and_return(p)
            grid.addWidget(item, i // cols, i % cols)
            self._submit_thumbnail(thumb, self.current_doc_index, i, self._thumb_version)

    def _refresh_gallery_grid(self):
        if self._gallery_widget is None:
            return
        scroll = self._gallery_widget.findChild(QScrollArea)
        if scroll is None or scroll.widget() is None:
            self.show_thumbnail_gallery()
            return
        grid = scroll.widget().findChild(QGridLayout)
        if grid is None:
            self.show_thumbnail_gallery()
            return
        self._build_gallery_grid(grid)

    def _toggle_page_vis(self, doc_idx, page_index, visible):
        hidden = self.hidden_pages.setdefault(doc_idx, set())
        if visible:
            hidden.discard(page_index)
        else:
            hidden.add(page_index)
        self._structure_version += 1
        self.page_cache.clear()

    def move_page_up(self, page_index):
        if page_index > 0:
            prev = sum(d.page_count for d in self.pdf_documents[:self.current_doc_index])
            cur_doc = self.pdf_documents[self.current_doc_index]
            with self._render_lock:
                cur_doc.move_page(page_index, page_index - 1)
            self._swap_hidden(page_index, page_index - 1)
            self._swap_current_page(prev + page_index, prev + page_index - 1)
            self._after_page_move()

    def move_page_down(self, page_index):
        cur_doc = self.pdf_documents[self.current_doc_index]
        if page_index < cur_doc.page_count - 1:
            prev = sum(d.page_count for d in self.pdf_documents[:self.current_doc_index])
            with self._render_lock:
                cur_doc.move_page(page_index + 1, page_index)
            self._swap_hidden(page_index, page_index + 1)
            self._swap_current_page(prev + page_index, prev + page_index + 1)
            self._after_page_move()

    def _swap_hidden(self, a, b):
        hidden = self._hidden_for()
        ha = a in hidden
        hb = b in hidden
        if ha:
            hidden.add(b)
        else:
            hidden.discard(b)
        if hb:
            hidden.add(a)
        else:
            hidden.discard(a)

    def _swap_current_page(self, g1, g2):
        """Si la página actual es una de las dos posiciones que se intercambiaron,
        actualiza current_page para que siga apuntando al mismo contenido."""
        if self.current_page == g1:
            self.current_page = g2
        elif self.current_page == g2:
            self.current_page = g1

    def _after_page_move(self):
        self._structure_version += 1
        self._thumb_version += 1
        self._preview_requests.clear()
        self.page_cache.clear()
        self.total_pages = sum(doc.page_count for doc in self.pdf_documents)
        self._refresh_gallery_grid()

    def select_slide_and_return(self, page):
        self.current_page = page
        self.update_moderator_view()
        self.stacked_widget.setCurrentIndex(self._moderator_index())

    def export_selected_slides(self):
        if not self.export_checkboxes:
            QMessageBox.information(self, "Sin selección", "No hay diapositivas para exportar.")
            return
        selected = [page for page, chk in self.export_checkboxes if chk.isChecked()]
        if not selected:
            QMessageBox.information(self, "Ninguna seleccionada", "Marcá al menos una diapositiva con el checkbox 'Exp.'.")
            return
        self._export_pages(selected)

    def export_all_slides(self):
        cur_doc = self.pdf_documents[self.current_doc_index]
        prev = sum(d.page_count for d in self.pdf_documents[:self.current_doc_index])
        all_pages = list(range(prev, prev + cur_doc.page_count))
        self._export_pages(all_pages)

    def _export_pages(self, page_list):
        current_doc = self.pdf_documents[self.current_doc_index]
        base_name = os.path.splitext(os.path.basename(current_doc.name))[0]
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de destino")
        if not folder:
            return
        export_dir = os.path.join(folder, f"{base_name}_export")
        os.makedirs(export_dir, exist_ok=True)
        progress = QProgressDialog("Exportando diapositivas...", "Cancelar", 0, len(page_list), self)
        progress.setWindowTitle("Exportando")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QApplication.processEvents()
        for idx, global_page in enumerate(page_list):
            if progress.wasCanceled():
                break
            resolved = self._resolve_page(global_page)
            if resolved is None:
                continue
            doc_idx, rem = resolved
            filename = f"{base_name}_{global_page + 1:03d}.png"
            with self._render_lock:
                try:
                    page = self.pdf_documents[doc_idx][rem]
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    pix.save(os.path.join(export_dir, filename))
                except Exception as e:
                    self._log_error("export", e)
            progress.setValue(idx + 1)
            QApplication.processEvents()
        progress.close()
        QMessageBox.information(self, "Exportación completada", f"{len(page_list)} diapositivas guardadas en:\n{export_dir}")

    # ============ IMPRESIÓN ============
    def show_print_dialog(self):
        if not self.pdf_documents:
            return QMessageBox.warning(self, "Sin PDFs", "Cargá al menos un PDF.")
        cur_doc = self.pdf_documents[self.current_doc_index]
        prev = sum(d.page_count for d in self.pdf_documents[:self.current_doc_index])
        total = cur_doc.page_count
        if total <= 0:
            return QMessageBox.warning(self, "Sin páginas", "El documento no tiene páginas para imprimir.")

        checked = [pg - prev + 1 for pg, chk in self.export_checkboxes if chk.isChecked()]
        checked = sorted(p for p in checked if 1 <= p <= total)

        dlg = QDialog(self)
        dlg.setWindowTitle("Imprimir")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"Documento: {os.path.basename(cur_doc.name)}  ({total} páginas)"))
        rb_all = QRadioButton("Documento completo")
        rb_sel = QRadioButton("Hojas seleccionadas")
        lay.addWidget(rb_all)
        lay.addWidget(rb_sel)
        edt = QLineEdit()
        edt.setPlaceholderText("ej: 1,3,5-9")
        if checked:
            rb_sel.setChecked(True)
            edt.setText(",".join(str(p) for p in checked))
        else:
            rb_all.setChecked(True)
            edt.setEnabled(False)
        rb_all.toggled.connect(lambda on: edt.setEnabled(not on))
        lay.addWidget(QLabel("Páginas a imprimir (1 = primera):"))
        lay.addWidget(edt)
        btns = QHBoxLayout()
        btn_ok = QPushButton("Imprimir…")
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(dlg.reject)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        lay.addLayout(btns)
        if dlg.exec_() != QDialog.Accepted:
            return
        if rb_all.isChecked():
            pages = list(range(1, total + 1))
        else:
            pages = self._parse_page_spec(edt.text(), total)
            if pages is None:
                return
        self._print_pages(prev, pages)

    def _parse_page_spec(self, text, total):
        pages = set()
        for part in text.replace(';', ',').split(','):
            part = part.strip()
            if not part:
                continue
            if '-' in part:
                a, b = part.split('-', 1)
                try:
                    start, end = int(a), int(b)
                except ValueError:
                    QMessageBox.warning(self, "Páginas inválidas", f"No se entendió: '{part}'")
                    return None
                if start > end:
                    start, end = end, start
                for p in range(max(1, start), min(total, end) + 1):
                    pages.add(p)
            else:
                try:
                    p = int(part)
                except ValueError:
                    QMessageBox.warning(self, "Páginas inválidas", f"No se entendió: '{part}'")
                    return None
                if 1 <= p <= total:
                    pages.add(p)
        if not pages:
            QMessageBox.warning(self, "Páginas inválidas", "No hay páginas válidas en el rango del documento.")
            return None
        return sorted(pages)

    def _print_pages(self, prev, pages_1based):
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(os.path.basename(self.pdf_documents[self.current_doc_index].name))
        print_dlg = QPrintDialog(printer, self)
        print_dlg.setWindowTitle("Imprimir PDF Presenter")
        if print_dlg.exec_() != QDialog.Accepted:
            return

        scale = min(printer.resolution() / 72.0, 4.0)
        progress = QProgressDialog("Imprimiendo páginas...", "Cancelar", 0, len(pages_1based), self)
        progress.setWindowTitle("Imprimiendo")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        QApplication.processEvents()

        painter = QPainter()
        if not painter.begin(printer):
            return
        try:
            for idx, p1 in enumerate(pages_1based):
                if progress.wasCanceled():
                    break
                try:
                    pix = self.render_page_sync(prev + p1 - 1, scale=scale)
                    if pix is not None:
                        # pageRect devuelve QRectF (flotante): convertir a enteros
                        pr = printer.pageRect(QPrinter.DevicePixel)
                        pr_w = int(pr.width())
                        pr_h = int(pr.height())
                        scaled = pix.scaled(pr_w, pr_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        x = int(pr.x()) + (pr_w - scaled.width()) // 2
                        y = int(pr.y()) + (pr_h - scaled.height()) // 2
                        painter.drawPixmap(x, y, scaled)
                except Exception as e:
                    # Una página con problemas no debe cortar el trabajo ni cerrar la app
                    self._log_error(f"print page {p1}", e)
                if idx < len(pages_1based) - 1:
                    printer.newPage()
                progress.setValue(idx + 1)
                QApplication.processEvents()
        finally:
            painter.end()
        progress.close()

    # ============ PRESENTACIÓN ============
    def toggle_presentation(self):
        if self.presenter_window and self.presenter_window.isVisible():
            self.end_presentation()
        else:
            self.start_presentation()

    def start_presentation(self):
        if not self.pdf_documents:
            return QMessageBox.warning(self, "Sin PDFs", "Cargá al menos un PDF.")
        if self._full_license_activated or self._trial_active:
            self.create_presentation_window()
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Activar Presentación")
        lay = QVBoxLayout(dlg)
        if self._trial_active:
            rem = max(0, QDateTime.currentDateTime().secsTo(self._trial_expiration))
            mm, ss = divmod(rem, 60)
            lay.addWidget(QLabel(f"Modo prueba activo - Tiempo restante: {mm:02d}:{ss:02d}"))
        lay.addWidget(QLabel("Introduce la clave de licencia o inicia la prueba gratuita (15 min):"))
        inp = QLineEdit()
        inp.setPlaceholderText("Clave de licencia")
        lay.addWidget(inp)
        btns = QHBoxLayout()
        btn_trial = QPushButton("Iniciar Prueba")
        btn_trial.clicked.connect(lambda: self._start_presentation_with_trial(dlg))
        btn_act = QPushButton("Activar Licencia")
        btn_act.clicked.connect(lambda: self._start_presentation_with_key(inp.text(), dlg))
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(dlg.reject)
        btns.addWidget(btn_trial)
        btns.addWidget(btn_act)
        btns.addWidget(btn_cancel)
        lay.addLayout(btns)
        dlg.exec_()

    def _start_presentation_with_trial(self, dlg):
        self._start_trial()
        if self._trial_active:
            dlg.accept()
            self.create_presentation_window()

    def _start_presentation_with_key(self, key, dlg):
        if self._validate_key(key):
            self._activate_license()
            dlg.accept()
            self.create_presentation_window()
        else:
            QMessageBox.warning(self, "Clave Inválida", "La clave es incorrecta.")
            dlg.reject()

    def create_presentation_window(self):
        screen_data = self.screen_combo.currentData()
        if screen_data == -1:
            if self.presenter_window:
                self.presenter_window.close()
                self.presenter_window = None
            self.presentation_status_label.hide()
            self._update_presentation_button_style()
            return
        if self.presenter_window:
            self.presenter_window.close()
        self.presenter_window = QWidget()
        self.presenter_window.setWindowTitle("Presentación")
        self.presenter_window.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.presenter_window.setStyleSheet("background-color: black;")
        screen = self.available_screens[screen_data]
        self.presenter_window.setGeometry(screen.geometry())
        self.presenter_window.showFullScreen()
        if self.laser_enabled:
            self.presenter_window.setCursor(Qt.BlankCursor)
        else:
            self.presenter_window.setCursor(Qt.ArrowCursor)
        self.presenter_label = QLabel(self.presenter_window)
        self.presenter_label.setAlignment(Qt.AlignCenter)
        self.presenter_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout()
        layout.addWidget(self.presenter_label)
        layout.setContentsMargins(0, 0, 0, 0)
        self.presenter_window.setLayout(layout)
        self.laser_label = QLabel(self.presenter_window)
        self.laser_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.laser_label.setAttribute(Qt.WA_TranslucentBackground)
        self.laser_label.setStyleSheet("background: transparent;")
        self.laser_label.hide()
        laser_size = 40
        laser_pix = QPixmap(laser_size, laser_size)
        laser_pix.fill(Qt.transparent)
        painter = QPainter(laser_pix)
        painter.setRenderHint(QPainter.Antialiasing)
        grad = QRadialGradient(laser_size/2, laser_size/2, laser_size/2)
        grad.setColorAt(0, QColor(255, 0, 0, 255))
        grad.setColorAt(0.4, QColor(255, 0, 0, 200))
        grad.setColorAt(0.8, QColor(255, 0, 0, 50))
        grad.setColorAt(1, QColor(255, 0, 0, 0))
        painter.setBrush(grad)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, laser_size, laser_size)
        painter.end()
        self.laser_label.setPixmap(laser_pix)
        self.laser_label.setFixedSize(laser_size, laser_size)
        self.presenter_window.installEventFilter(self)
        self.presenter_window.grabKeyboard()
        self.presenter_window.setFocus()
        self.presenter_window.activateWindow()
        self.update_presentation()
        self.presentation_status_label.setText("▶ Presentación en curso")
        self.presentation_status_label.show()
        self._update_presentation_button_style()

    def _update_presentation_button_style(self):
        if not hasattr(self, 'btn_present'):
            return
        if self.presenter_window and self.presenter_window.isVisible():
            self.btn_present.setText("Detener")
            self.btn_present.setObjectName("btn_present_active")
        elif self.ndi_enabled:
            self.btn_present.setText("NDI activo")
            self.btn_present.setObjectName("btn_present_active")
        else:
            self.btn_present.setText("Iniciar Presentación")
            self.btn_present.setObjectName("btn_present_inactive")
        self.btn_present.style().unpolish(self.btn_present)
        self.btn_present.style().polish(self.btn_present)

    def update_presentation(self):
        if self.presenter_window and self.presenter_window.isVisible():
            self._submit_slot('presenter', self.current_page, 2)

    def end_presentation(self):
        if self.presenter_window:
            try:
                self.presenter_window.releaseKeyboard()
            except Exception:
                pass
            self.presenter_window.close()
            self.presenter_window = None
            self.laser_label = None
        if hasattr(self, 'document_selection_widget'):
            self.stacked_widget.setCurrentIndex(self._doc_selection_index())
        else:
            self.stacked_widget.setCurrentIndex(self.selector_index)
        self.presentation_time = QTime(0, 0, 0)
        self.time_label.setText("00:00:00")
        self.update_moderator_view()
        self.presentation_status_label.hide()
        self._update_presentation_button_style()

    def eventFilter(self, obj, event):
        if obj == self.presenter_window:
            if event.type() == event.KeyPress:
                if event.key() == Qt.Key_Escape:
                    self.end_presentation()
                    return True
                elif event.key() in (Qt.Key_Right, Qt.Key_Down, Qt.Key_PageDown, Qt.Key_Space):
                    self.next_page()
                    return True
                elif event.key() in (Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp):
                    self.prev_page()
                    return True
            elif event.type() == event.MouseMove:
                if self.laser_enabled and self.laser_label:
                    pos = event.pos()
                    self.laser_label.move(pos.x() - 20, pos.y() - 20)
                    self.laser_label.show()
                return True
            elif event.type() == event.MouseButtonPress:
                return True
        return super().eventFilter(obj, event)

    def on_screen_added_or_removed(self):
        self.available_screens = QGuiApplication.screens()
        self.update_screen_selector()

    # ---------- NDI ----------
    def start_ndi_sender(self):
        if not self._full_license_activated:
            QMessageBox.warning(self, "NDI no disponible", "La función NDI requiere licencia completa.")
            return
        if not self.pdf_documents:
            return
        self.stop_ndi_sender()
        try:
            if not ndi.initialize():
                QMessageBox.critical(self, "Error NDI", "No se pudo inicializar NDI.")
                return
            send = ndi.SendCreate()
            send.ndi_name = self.ndi_source_name
            self.ndi_sender = ndi.send_create(send)
            if self.ndi_sender is None:
                raise Exception("No se pudo crear el sender NDI")
            self.ndi_enabled = True
            self._last_ndi_pixmap = self.render_page_sync(self.current_page, scale=1)
            if self._last_ndi_pixmap:
                self.update_ndi_frame(self._last_ndi_pixmap)
            self._ndi_timer.start()
        except Exception as e:
            self._log_error("ndi_start", e)
            QMessageBox.critical(self, "Error NDI", str(e))
            self.ndi_enabled = False
            self.ndi_sender = None
            self._ndi_timer.stop()

    def update_ndi_frame(self, pixmap=None):
        if not self.ndi_enabled or not self.ndi_sender:
            return
        if pixmap is None:
            pixmap = self._last_ndi_pixmap
        if pixmap is None:
            return
        self._last_ndi_pixmap = pixmap
        qimg = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
        w, h = qimg.width(), qimg.height()
        if w <= 0 or h <= 0:
            return
        ptr = qimg.bits()
        ptr.setsize(qimg.byteCount())
        arr = np.array(ptr).reshape((h, w, 4))
        vf = ndi.VideoFrameV2()
        vf.data = arr
        vf.xres, vf.yres = w, h
        vf.FourCC = ndi.FOURCC_VIDEO_TYPE_RGBA
        ndi.send_send_video_v2(self.ndi_sender, vf)

    def _send_ndi_pulse(self):
        """Mantiene el flujo NDI constante (~30 fps) aunque la página no cambie."""
        if not self.ndi_enabled or self.ndi_sender is None:
            self._ndi_timer.stop()
            return
        self.update_ndi_frame(self._last_ndi_pixmap)

    def stop_ndi_sender(self):
        self._ndi_timer.stop()
        self._last_ndi_pixmap = None
        if self.ndi_sender is not None:
            try:
                ndi.send_destroy(self.ndi_sender)
            except Exception:
                pass
            self.ndi_sender = None
        self.ndi_enabled = False

    def closeEvent(self, event):
        self._worker.stop()
        self._worker.wait(2000)
        self.end_presentation()
        self.stop_ndi_sender()
        with self._render_lock:
            for doc in self.pdf_documents:
                try:
                    doc.close()
                except Exception:
                    pass
        event.accept()


if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        win = PDFPresenter()
        pdf_args = [a for a in sys.argv[1:] if a.lower().endswith('.pdf')]
        if pdf_args:
            win.load_multiple_pdfs(file_paths=pdf_args, append=False)
        win.resize(800, 600)
        win.show()
        sys.exit(app.exec_())
    except Exception as e:
        QMessageBox.critical(None, "Error de Inicio", str(e))
        sys.exit(1)
