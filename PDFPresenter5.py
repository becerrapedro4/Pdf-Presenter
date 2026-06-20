import sys
import os
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
    QAction
)
from PyQt5.QtCore import Qt, QSize, QTime, QTimer, QMimeData, QDateTime, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import (
    QGuiApplication, QPixmap, QImage, QIcon, QFont, QDrag,
    QPainter, QColor, QRadialGradient, QCursor, QPen, QBrush
)

# ------- Registro de Windows -------
import winreg

REG_PATH = r"Software\PDFPresenter"
REG_KEY_LICENSE = "LicenseStatus"
REG_KEY_TRIAL_EXP = "TrialExpiration"

def read_registry(key, default=None):
    try:
        reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(reg, key)
        winreg.CloseKey(reg)
        return value
    except:
        return default

def write_registry(key, value):
    try:
        reg = winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PATH)
        winreg.SetValueEx(reg, key, 0, winreg.REG_SZ, str(value))
        winreg.CloseKey(reg)
        return True
    except:
        return False

def delete_registry(key):
    try:
        reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(reg, key)
        winreg.CloseKey(reg)
    except:
        pass


# ------- Toggle Switch -------
class ToggleSwitch(QWidget):
    def __init__(self, parent=None, checked=False):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(50, 26)
        self._toggle_pos = 2 if checked else 26
        self.setCursor(Qt.PointingHandCursor)
        self.callback = None
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._checked = not self._checked
            self._toggle_pos = 2 if self._checked else 26
            self.update()
            if self.callback:
                self.callback(self._checked)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track_color = QColor("#34C759") if self._checked else QColor("#E5E5EA")
        painter.setBrush(QBrush(track_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 13, 13)
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.setPen(QPen(QColor("#DDDDDD"), 1))
        painter.drawEllipse(int(self._toggle_pos), 2, 22, 22)
    
    def isChecked(self):
        return self._checked
    
    def setChecked(self, checked):
        self._checked = checked
        self._toggle_pos = 2 if checked else 26
        self.update()


class DocumentItem(QFrame):
    def __init__(self, doc_index, doc_name, thumbnail_pixmap, parent=None):
        super().__init__(parent)
        self.doc_index = doc_index
        self.doc_name = doc_name
        self.thumbnail_pixmap = thumbnail_pixmap
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
            scaled = self.thumbnail_pixmap.scaled(
                self.thumbnail_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.thumbnail_label.setPixmap(scaled)
        else:
            self.thumbnail_label.setText("No Preview")
            self.thumbnail_label.setStyleSheet("color: #888; border: 1px dashed #ccc;")
        self.name_label = QLabel(self.doc_name)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setFont(QFont("Helvetica Neue", 10))
        layout.addWidget(self.thumbnail_label)
        layout.addWidget(self.name_label)
        self.start_drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_drag_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.start_drag_pos:
            if (event.pos() - self.start_drag_pos).manhattanLength() > QApplication.startDragDistance():
                self.start_drag()
        super().mouseMoveEvent(event)

    def start_drag(self):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(str(self.doc_index))
        drag.setMimeData(mime)
        if self.thumbnail_pixmap:
            drag.setPixmap(self.thumbnail_pixmap.scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        drag.exec_(Qt.MoveAction)
        self.start_drag_pos = None


class PDFPresenter(QMainWindow):
    _license_key_hash = "e7db87424219e5499a35947365a9a014345ebadc01d37fd7e51a583c6dae369b"
    _trial_duration_secs = 15 * 60
    _theme_setting_file = "pdf_presenter_theme_settings.json"
    _page_cache_max = 60

    def __init__(self):
        super().__init__()
        self.ndi_enabled = False
        self.ndi_sender = None
        self.ndi_source_name = "PDF Presenter Output"
        self.setWindowTitle("PDF Presenter")
        self.setWindowIcon(QIcon("icono.ico"))
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
        self._gallery_widget = None
        self._current_theme = "light"
        self.load_theme_setting()
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)
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
        self.hidden_pages = set()
        self.init_initial_ui()
        self.selector_index = 0
        self.document_selection_index = 1
        self.moderator_index = 2
        self.gallery_index = 3
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

    def _cache_put(self, key, value):
        if key in self.page_cache:
            self.page_cache.move_to_end(key)
        self.page_cache[key] = value
        if len(self.page_cache) > self._page_cache_max:
            self.page_cache.popitem(last=False)

    def _generate_machine_id(self):
        return hex(uuid.getnode())

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

    def _clear_license(self):
        self._full_license_activated = False
        self._trial_active = False
        self._trial_timer.stop()
        self._trial_expiration = QDateTime()
        write_registry(REG_KEY_LICENSE, "inactive")
        delete_registry(REG_KEY_TRIAL_EXP)

    def _activate_license(self):
        self._full_license_activated = True
        self._trial_active = False
        self._trial_timer.stop()
        self.save_license_to_registry()
        self.update_moderator_view()

    def _start_trial(self):
        self._trial_active = True
        self._trial_expiration = QDateTime.currentDateTime().addSecs(self._trial_duration_secs)
        self._trial_timer.start(1000)
        self.save_license_to_registry()
        QMessageBox.information(self, "Modo de Prueba", "15 minutos activados.")
        self.update_moderator_view()

    def _check_trial_status(self):
        if self._trial_active and QDateTime.currentDateTime() >= self._trial_expiration:
            self._clear_license()
            self.end_presentation()
            QMessageBox.warning(self, "Fin de la Prueba", "El tiempo de prueba ha finalizado.")
        if hasattr(self, 'moderator_widget') and self.stacked_widget.currentWidget() == self.moderator_widget:
            self.update_moderator_view()
        else:
            self._update_trial_label_only()

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

    def load_theme_setting(self):
        if os.path.exists(self._theme_setting_file):
            try:
                with open(self._theme_setting_file, 'r') as f:
                    self._current_theme = json.load(f).get("theme", "light")
            except:
                self._current_theme = "light"
        self.apply_theme()

    def save_theme_setting(self):
        try:
            with open(self._theme_setting_file, 'w') as f:
                json.dump({"theme": self._current_theme}, f, indent=4)
        except:
            pass

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
        """

    def init_initial_ui(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignCenter)
        
        label = QLabel("PDF Presenter")
        label.setStyleSheet("font-size: 28px; font-weight: bold; margin-bottom: 20px;")
        layout.addWidget(label, alignment=Qt.AlignCenter)
        
        theme_layout = QHBoxLayout()
        theme_layout.setAlignment(Qt.AlignCenter)
        theme_label = QLabel("☀️  Tema claro  🌙")
        theme_label.setStyleSheet("font-size: 14px; margin-right: 10px;")
        self.toggle_theme = ToggleSwitch(checked=(self._current_theme == "dark"))
        self.toggle_theme.callback = self._on_theme_toggle
        theme_layout.addWidget(theme_label)
        theme_layout.addWidget(self.toggle_theme)
        layout.addLayout(theme_layout)
        
        layout.addSpacing(20)
        
        load_btn = QPushButton("Cargar Presentación(es)")
        load_btn.setStyleSheet("font-size: 16px; padding: 12px 24px;")
        load_btn.clicked.connect(lambda: self.load_multiple_pdfs(append=False))
        layout.addWidget(load_btn, alignment=Qt.AlignCenter)
        
        self.stacked_widget.addWidget(w)
        self.menuBar().hide()

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
                if append:
                    self.pdf_documents.extend(new_docs)
                else:
                    for doc in self.pdf_documents:
                        doc.close()
                    self.pdf_documents = new_docs
                    self.current_doc_index = 0
                    self.current_page = 0
                    self.page_cache = OrderedDict()
                    self.hidden_pages = set()
                self.total_pages = sum(doc.page_count for doc in self.pdf_documents)
                self.setup_document_selection_view()
                self.stacked_widget.setCurrentIndex(self.document_selection_index)
                self.update_moderator_view()
                if hasattr(self, 'doc_combo'):
                    self.doc_combo.clear()
                    self.doc_combo.addItems([os.path.basename(d.name) for d in self.pdf_documents])
                    self.doc_combo.setCurrentIndex(self.current_doc_index)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudieron cargar los PDFs: {e}")

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
        self.doc_container.dragEnterEvent = lambda e: e.acceptProposedAction() if e.mimeData().hasUrls() else e.ignore()
        self.doc_container.dropEvent = self._doc_grid_drop

    def update_document_selection_view(self):
        while self.doc_grid.count():
            item = self.doc_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        cols = 3
        for i, doc in enumerate(self.pdf_documents):
            pix = self.render_page_for_selection(i, 0, 0.5)
            name = os.path.basename(doc.name)
            doc_item = DocumentItem(i, name, pix)
            doc_item.mousePressEvent = lambda e, idx=i: self._select_doc_from_list(e, idx)
            self.doc_grid.addWidget(doc_item, i // cols, i % cols)

    def _select_doc_from_list(self, event, idx):
        if event.button() == Qt.LeftButton:
            self.current_doc_index = idx
            self.current_page = sum(d.page_count for d in self.pdf_documents[:idx])
            self.setup_moderator_view()
            self.update_moderator_view()
            self.stacked_widget.setCurrentIndex(self.moderator_index)

    def _doc_grid_drop(self, event):
        urls = event.mimeData().urls()
        paths = [u.toLocalFile() for u in urls if u.toLocalFile().lower().endswith('.pdf')]
        if paths:
            self.load_multiple_pdfs(file_paths=paths, append=True)

    def join_all_loaded_pdfs(self):
        if not self.pdf_documents:
            return QMessageBox.warning(self, "Nada que unir", "No hay documentos cargados.")
        path, _ = QFileDialog.getSaveFileName(self, "Guardar PDF unificado", "unificado.pdf", "*.pdf")
        if path:
            merged = fitz.open()
            for doc in self.pdf_documents:
                merged.insert_pdf(doc)
            merged.save(path)
            merged.close()
            QMessageBox.information(self, "Unión completada", f"Archivo guardado en:\n{path}")

    def render_page_for_selection(self, doc_idx, page_idx, scale=0.5):
        key = (doc_idx, page_idx, scale)
        if key in self.page_cache:
            self.page_cache.move_to_end(key)
            return self.page_cache[key]
        try:
            page = self.pdf_documents[doc_idx][page_idx]
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            img = QImage.fromData(pix.tobytes("png"))
            if img.isNull():
                return None
            qp = QPixmap.fromImage(img)
            self._cache_put(key, qp)
            return qp
        except:
            return None

    # ============ VISTA MODERADOR ============
    def setup_moderator_view(self):
        if hasattr(self, 'moderator_widget'):
            self.stacked_widget.removeWidget(self.moderator_widget)
            self.moderator_widget.deleteLater()
        self.moderator_widget = QWidget()
        layout = QVBoxLayout(self.moderator_widget)
        
        top_bar = QHBoxLayout()
        self.btn_end = QPushButton("Finalizar")
        self.btn_end.setObjectName("btn_end_presentation")
        self.btn_end.clicked.connect(self.end_presentation)
        self.doc_combo.clear()
        self.doc_combo.addItems([os.path.basename(d.name) for d in self.pdf_documents])
        try:
            self.doc_combo.currentIndexChanged.disconnect()
        except:
            pass
        self.doc_combo.currentIndexChanged.connect(self.change_document)
        self.doc_combo.setCurrentIndex(self.current_doc_index)
        self.update_screen_selector()
        top_bar.addWidget(self.btn_end)
        top_bar.addStretch()
        top_bar.addWidget(self.time_label)
        top_bar.addWidget(self.trial_label)
        top_bar.addWidget(self.doc_combo)
        top_bar.addWidget(self.screen_combo)
        layout.addLayout(top_bar)
        
        preview_box = QHBoxLayout()
        self.current_preview.setAlignment(Qt.AlignCenter)
        self.current_preview.setStyleSheet("background-color: black; border: 2px solid #555; border-radius: 10px;")
        self.current_preview.setMinimumSize(600, 400)
        self.current_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.next_preview.setAlignment(Qt.AlignCenter)
        self.next_preview.setStyleSheet("background-color: black; border: 2px solid #555; border-radius: 10px;")
        self.next_preview.setFixedSize(200, 150)
        preview_box.addWidget(self.current_preview, 3)
        preview_box.addWidget(self.next_preview, 1)
        layout.addLayout(preview_box)
        
        self.slide_info.setAlignment(Qt.AlignCenter)
        self.slide_info.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.slide_info)
        layout.addWidget(self.progress)
        
        bottom_bar = QHBoxLayout()
        
        self.btn_prev = QPushButton("◀ Ant")
        self.btn_prev.clicked.connect(self.prev_page)
        self.btn_gallery = QPushButton("Galería")
        self.btn_gallery.clicked.connect(self.show_thumbnail_gallery)
        
        # Grupo Láser
        laser_group = QHBoxLayout()
        laser_label = QLabel("🔴 Láser:")
        laser_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        self.toggle_laser = ToggleSwitch(checked=self.laser_enabled)
        self.toggle_laser.callback = self._on_laser_changed
        laser_group.addWidget(laser_label)
        laser_group.addWidget(self.toggle_laser)
        
        # Grupo NDI
        ndi_group = QHBoxLayout()
        ndi_label = QLabel("📡 NDI:")
        ndi_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        self.toggle_ndi = ToggleSwitch(checked=self.ndi_enabled)
        self.toggle_ndi.callback = self._on_ndi_changed
        ndi_group.addWidget(ndi_label)
        ndi_group.addWidget(self.toggle_ndi)
        
        self.btn_present = QPushButton("Iniciar Presentación")
        self.btn_present.setObjectName("btn_present_inactive")
        self.btn_present.clicked.connect(self.toggle_presentation)
        
        self.btn_next = QPushButton("Sig ▶")
        self.btn_next.clicked.connect(self.next_page)
        
        bottom_bar.addWidget(self.btn_prev)
        bottom_bar.addWidget(self.btn_gallery)
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
        
        visible_pages = [p for p in range(cur_doc.page_count) if p not in self.hidden_pages]
        if visible_pages and page_in_doc not in visible_pages:
            self.current_page = prev_pages + min(visible_pages, key=lambda x: abs(x - page_in_doc))
            page_in_doc = self.current_page - prev_pages
        
        cur_pix = self.render_page(self.current_page, scale=1)
        if cur_pix:
            self.current_preview.setPixmap(cur_pix.scaled(
                self.current_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            if self.ndi_enabled:
                self.update_ndi_frame(cur_pix)
        
        next_visible = None
        for p in range(page_in_doc + 1, cur_doc.page_count):
            if p not in self.hidden_pages:
                next_visible = p
                break
        if next_visible is not None:
            next_pix = self.render_page(prev_pages + next_visible, scale=1)
            if next_pix:
                self.next_preview.setPixmap(next_pix.scaled(self.next_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.next_preview.clear()
        else:
            self.next_preview.clear()
        
        self.slide_info.setText(f"Diapositiva {page_in_doc + 1} de {cur_doc.page_count} ({len(visible_pages)} visibles)")
        self.progress.setRange(0, cur_doc.page_count)
        self.progress.setValue(page_in_doc + 1)
        self.update_button_states()
        if self.presenter_window and self.presenter_window.isVisible():
            self.update_presentation()

    def render_page(self, page_number, scale=1):
        if page_number >= self.total_pages or page_number < 0:
            return None
        doc_idx = 0
        rem = page_number
        for i, doc in enumerate(self.pdf_documents):
            if rem < doc.page_count:
                doc_idx = i
                break
            rem -= doc.page_count
        cache_key = (doc_idx, rem, scale)
        if cache_key in self.page_cache:
            self.page_cache.move_to_end(cache_key)
            return self.page_cache[cache_key]
        try:
            page = self.pdf_documents[doc_idx][rem]
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            img = QImage.fromData(pix.tobytes("png"))
            if img.isNull():
                return None
            qp = QPixmap.fromImage(img)
            self._cache_put(cache_key, qp)
            return qp
        except:
            return None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F5:
            self.start_presentation()
        elif event.key() == Qt.Key_Escape:
            if self.presenter_window and self.presenter_window.isVisible():
                self.end_presentation()
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
        for p in range(page_in_doc + 1, cur.page_count):
            if p not in self.hidden_pages:
                self.current_page = prev_pages + p
                self.update_moderator_view()
                return

    def prev_page(self):
        prev_pages = sum(d.page_count for d in self.pdf_documents[:self.current_doc_index])
        page_in_doc = self.current_page - prev_pages
        for p in range(page_in_doc - 1, -1, -1):
            if p not in self.hidden_pages:
                self.current_page = prev_pages + p
                self.update_moderator_view()
                return

    def update_button_states(self):
        if not hasattr(self, 'btn_prev') or not self.pdf_documents:
            return
        prev_pages = sum(d.page_count for d in self.pdf_documents[:self.current_doc_index])
        cur = self.pdf_documents[self.current_doc_index]
        page_in_doc = self.current_page - prev_pages
        has_prev = any(p not in self.hidden_pages for p in range(page_in_doc - 1, -1, -1))
        has_next = any(p not in self.hidden_pages for p in range(page_in_doc + 1, cur.page_count))
        self.btn_prev.setEnabled(has_prev)
        self.btn_next.setEnabled(has_next)

    def show_thumbnail_gallery(self):
        if not self.pdf_documents:
            return QMessageBox.warning(self, "No hay PDFs", "Cargá un PDF primero.")
        if self._gallery_widget is not None:
            self.stacked_widget.removeWidget(self._gallery_widget)
            self._gallery_widget.deleteLater()
            self._gallery_widget = None
        
        cur_doc = self.pdf_documents[self.current_doc_index]
        prev = sum(d.page_count for d in self.pdf_documents[:self.current_doc_index])
        
        scroll = QScrollArea()
        cont = QWidget()
        grid = QGridLayout(cont)
        cols = 4
        
        for i in range(cur_doc.page_count):
            global_i = prev + i
            container = QVBoxLayout()
            
            thumb = QLabel()
            thumb.setFixedSize(120, 90)
            thumb.setAlignment(Qt.AlignCenter)
            pix = self.render_page(global_i, scale=1)
            if pix:
                thumb.setPixmap(pix.scaled(thumb.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                thumb.setText(f"{i+1}")
            
            vis_toggle = ToggleSwitch(checked=(i not in self.hidden_pages))
            vis_toggle.callback = lambda checked, p=i: self._toggle_page_vis(p, checked)
            
            lbl = QLabel(f"Pág. {i+1}")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("font-weight: bold;")
            
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
            container.addLayout(move_layout)
            
            item = QWidget()
            item.setLayout(container)
            item.mousePressEvent = lambda e, p=global_i: self.select_slide_and_return(p)
            grid.addWidget(item, i // cols, i % cols)
        
        scroll.setWidget(cont)
        scroll.setWidgetResizable(True)
        
        btn_back = QPushButton("Volver al moderador")
        btn_back.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(self.moderator_index))
        
        lay = QVBoxLayout()
        lay.addWidget(scroll)
        lay.addWidget(btn_back)
        
        gal = QWidget()
        gal.setLayout(lay)
        self._gallery_widget = gal
        self.stacked_widget.addWidget(gal)
        self.stacked_widget.setCurrentWidget(gal)

    def _toggle_page_vis(self, page_index, visible):
        if visible:
            self.hidden_pages.discard(page_index)
        else:
            self.hidden_pages.add(page_index)
        self.page_cache.clear()

    def move_page_up(self, page_index):
        if page_index > 0:
            cur_doc = self.pdf_documents[self.current_doc_index]
            cur_doc.move_page(page_index, page_index - 1)
            new_hidden = set()
            for p in self.hidden_pages:
                if p == page_index:
                    new_hidden.add(page_index - 1)
                elif p == page_index - 1:
                    new_hidden.add(page_index)
                else:
                    new_hidden.add(p)
            self.hidden_pages = new_hidden
            self.page_cache.clear()
            self.total_pages = sum(doc.page_count for doc in self.pdf_documents)
            self.show_thumbnail_gallery()

    def move_page_down(self, page_index):
        cur_doc = self.pdf_documents[self.current_doc_index]
        if page_index < cur_doc.page_count - 1:
            cur_doc.move_page(page_index, page_index + 1)
            new_hidden = set()
            for p in self.hidden_pages:
                if p == page_index:
                    new_hidden.add(page_index + 1)
                elif p == page_index + 1:
                    new_hidden.add(page_index)
                else:
                    new_hidden.add(p)
            self.hidden_pages = new_hidden
            self.page_cache.clear()
            self.total_pages = sum(doc.page_count for doc in self.pdf_documents)
            self.show_thumbnail_gallery()

    def select_slide_and_return(self, page):
        self.current_page = page
        self.update_moderator_view()
        self.stacked_widget.setCurrentIndex(self.moderator_index)

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
        lay.addWidget(QLabel("Clave de licencia o prueba gratuita (15 min):"))
        inp = QLineEdit()
        inp.setPlaceholderText("Clave de licencia")
        lay.addWidget(inp)
        btns = QHBoxLayout()
        btn_trial = QPushButton("Prueba")
        btn_trial.clicked.connect(lambda: self._start_presentation_with_trial(dlg))
        btn_act = QPushButton("Activar")
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
        if hashlib.sha256(key.encode()).hexdigest() == self._license_key_hash:
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
        
        # Láser
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
            pix = self.render_page(self.current_page, scale=2)
            if pix:
                geo = self.presenter_window.size()
                scaled = pix.scaled(geo.width(), geo.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.presenter_label.setPixmap(scaled)

    def end_presentation(self):
        if self.presenter_window:
            try:
                self.presenter_window.releaseKeyboard()
            except:
                pass
            self.presenter_window.close()
            self.presenter_window = None
            self.laser_label = None
        if hasattr(self, 'document_selection_widget'):
            self.stacked_widget.setCurrentIndex(self.document_selection_index)
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
            cur = self.render_page(self.current_page, scale=1)
            if cur:
                self.update_ndi_frame(cur)
        except Exception as e:
            QMessageBox.critical(self, "Error NDI", str(e))
            self.ndi_enabled = False
            self.ndi_sender = None

    def update_ndi_frame(self, pixmap=None):
        if not self.ndi_enabled or not self.ndi_sender:
            return
        if pixmap is None:
            pixmap = self.render_page(self.current_page, scale=1)
        if pixmap is None:
            return
        qimg = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
        w, h = qimg.width(), qimg.height()
        ptr = qimg.bits()
        ptr.setsize(qimg.byteCount())
        arr = np.array(ptr).reshape((h, w, 4))
        vf = ndi.VideoFrameV2()
        vf.data = arr
        vf.xres, vf.yres = w, h
        vf.FourCC = ndi.FOURCC_VIDEO_TYPE_RGBA
        ndi.send_send_video_v2(self.ndi_sender, vf)

    def stop_ndi_sender(self):
        if self.ndi_sender is not None:
            try:
                ndi.send_destroy(self.ndi_sender)
            except:
                pass
            self.ndi_sender = None
        self.ndi_enabled = False

    def closeEvent(self, event):
        self.end_presentation()
        self.stop_ndi_sender()
        for doc in self.pdf_documents:
            doc.close()
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
