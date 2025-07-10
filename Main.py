import sys
import fitz
import os
import json
import uuid
import hashlib
from datetime import datetime, timedelta

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QFileDialog,
    QVBoxLayout, QHBoxLayout, QProgressBar, QComboBox, QSizePolicy, QStackedWidget,
    QScrollArea, QMessageBox, QFrame, QGridLayout, QProgressDialog, QLineEdit, QDialog
)
from PyQt5.QtCore import Qt, QSize, QTime, QTimer, QMimeData, QDateTime, QDate
from PyQt5.QtGui import QGuiApplication, QPixmap, QImage, QIcon, QFont, QDrag


class DocumentItem(QFrame):
    """
    A custom widget to represent a single PDF document in the selection view.
    It displays a thumbnail and the document name, and supports drag-and-drop.
    """
    def __init__(self, doc_index, doc_name, thumbnail_pixmap, parent=None):
        super().__init__(parent)
        self.doc_index = doc_index
        self.doc_name = doc_name
        self.thumbnail_pixmap = thumbnail_pixmap
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setLineWidth(2)
        self.setCursor(Qt.OpenHandCursor) # Indicate draggable

        self.setMinimumSize(180, 150)
        self.setMaximumWidth(200) # Limit width for better layout in gallery
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setFixedSize(160, 120) # Fixed size for consistent thumbnails
        if self.thumbnail_pixmap:
            scaled_pixmap = self.thumbnail_pixmap.scaled(
                self.thumbnail_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.thumbnail_label.setPixmap(scaled_pixmap)
        else:
            self.thumbnail_label.setText("No Preview")
            self.thumbnail_label.setStyleSheet("color: #888; border: 1px dashed #ccc;") # Added dashed border for no preview

        self.name_label = QLabel(self.doc_name)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True) # Allow long names to wrap
        self.name_label.setFont(QFont("Helvetica Neue", 10))

        layout.addWidget(self.thumbnail_label)
        layout.addWidget(self.name_label)
        self.setLayout(layout)

        self.start_drag_pos = None

    def mousePressEvent(self, event):
        """
        Handles mouse press events. If it's a left click, store the position
        to potentially start a drag.
        """
        if event.button() == Qt.LeftButton:
            self.start_drag_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """
        Handles mouse move events. If a drag has started and the mouse moves
        beyond a certain threshold, initiate a drag operation.
        """
        if event.buttons() == Qt.LeftButton and self.start_drag_pos:
            if (event.pos() - self.start_drag_pos).manhattanLength() > QApplication.startDragDistance():
                self.start_drag()
        super().mouseMoveEvent(event)

    def start_drag(self):
        """
        Initiates a drag operation for this document item.
        """
        drag = QDrag(self)
        mime_data = QMimeData()
        # Store the original index of this document item as text data
        mime_data.setText(str(self.doc_index))
        drag.setMimeData(mime_data)
        # Set a pixmap for the drag cursor (e.g., a smaller version of the thumbnail)
        if self.thumbnail_pixmap:
            drag.setPixmap(self.thumbnail_pixmap.scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        drag.setHotSpot(self.rect().topLeft()) # Set drag hotspot

        # Start the drag. This will block until the drag operation is finished.
        drag.exec_(Qt.MoveAction)
        self.start_drag_pos = None # Reset drag position


class PDFPresenter(QMainWindow):
    _license_key = "216573AE419CC" # Updated license key
    _trial_duration_secs = 15 * 60 # 15 minutes in seconds
    _license_state_file = "pdf_presenter_license.json" # File to store license state

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Presenter - Inicio")
        self.setWindowIcon(QIcon("icono.ico"))
        self.setStyleSheet(self.get_mac_style())
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        self.pdf_documents = []  
        self.current_doc_index = 0 
        self.current_page = 0    
        self.total_pages = 0     
        self.presenter_window = None 
        self.available_screens = QGuiApplication.screens() 
        self.selected_screen_index = 1 if len(self.available_screens) > 1 else 0
        self.presentation_time = QTime(0, 0, 0) 
        self.timer = QTimer(self) 
        self.timer.timeout.connect(self.update_timer)

        # License variables
        self._trial_active = False
        self._trial_expiration_datetime = QDateTime() # Stores the QDateTime when trial expires
        self._trial_timer = QTimer(self)
        self._trial_timer.timeout.connect(self.check_trial_status)
        self._full_license_activated = False 
        self._machine_id = self._generate_machine_id() # Generate machine ID once

        self.page_cache = {}

        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        # Initialize labels and other widgets here to prevent AttributeError if update_moderator_view is called early
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

        self.init_initial_ui()
        self.selector_index = 0  
        self.document_selection_index = 1 
        self.moderator_index = 2 
        self.gallery_index = 3   
        self.setAcceptDrops(True) 

        self.load_license_state() # Load license state on startup

    def _generate_machine_id(self):
        """Generates a unique ID for the machine (e.g., using MAC address)."""
        # uuid.getnode() returns the MAC address as an integer
        return hex(uuid.getnode())

    def _generate_license_hash(self, machine_id, status, expiry_str=""):
        """Generates a simple hash for license integrity checking."""
        data = f"{machine_id}-{status}-{expiry_str}-{self._license_key}"
        return hashlib.sha256(data.encode('utf-8')).hexdigest()

    def save_license_state(self):
        """Saves the current license state to a JSON file."""
        license_data = {
            "machine_id": self._machine_id,
            "status": "activated" if self._full_license_activated else ("trial" if self._trial_active else "inactive"),
            "trial_expiration": self._trial_expiration_datetime.toString(Qt.ISODate) if self._trial_active else "",
            "last_saved": QDateTime.currentDateTime().toString(Qt.ISODate)
        }
        # Add hash for integrity check
        license_data["hash"] = self._generate_license_hash(
            license_data["machine_id"], 
            license_data["status"], 
            license_data["trial_expiration"]
        )

        try:
            with open(self._license_state_file, 'w') as f:
                json.dump(license_data, f, indent=4)
            # print(f"License state saved to {self._license_state_file}")
        except Exception as e:
            print(f"Error saving license state: {e}")

    def load_license_state(self):
        """Loads the license state from a JSON file."""
        if not os.path.exists(self._license_state_file):
            self._full_license_activated = False
            self._trial_active = False
            self.update_moderator_view() # Ensure label is updated even without file
            return

        try:
            with open(self._license_state_file, 'r') as f:
                license_data = json.load(f)

            # Verify integrity hash
            expected_hash = self._generate_license_hash(
                license_data.get("machine_id", ""), 
                license_data.get("status", ""), 
                license_data.get("trial_expiration", "")
            )
            if license_data.get("hash") != expected_hash:
                QMessageBox.warning(self, "Error de Licencia", "Archivo de licencia corrompido o manipulado.")
                self._full_license_activated = False
                self._trial_active = False
                self.save_license_state() # Overwrite with inactive state
                return

            # Verify machine ID
            if license_data.get("machine_id") != self._machine_id:
                QMessageBox.warning(self, "Error de Licencia", "Archivo de licencia no válido para esta PC.")
                self._full_license_activated = False
                self._trial_active = False
                self.save_license_state() # Overwrite with inactive state
                return

            status = license_data.get("status")
            if status == "activated":
                self._full_license_activated = True
                self._trial_active = False
                self._trial_timer.stop()
            elif status == "trial":
                expiration_str = license_data.get("trial_expiration")
                if expiration_str:
                    self._trial_expiration_datetime = QDateTime.fromString(expiration_str, Qt.ISODate)
                    if QDateTime.currentDateTime() < self._trial_expiration_datetime:
                        self._trial_active = True
                        self._full_license_activated = False
                        self._trial_timer.start(1000) # Resume trial timer
                    else:
                        QMessageBox.information(self, "Fin de la Prueba", "Su período de prueba ha expirado.")
                        self._trial_active = False
                        self._full_license_activated = False
                else: # Corrupted trial state
                    self._trial_active = False
                    self._full_license_activated = False
            else: # "inactive" or unknown status
                self._full_license_activated = False
                self._trial_active = False
            
            # print(f"License state loaded: Full active: {self._full_license_activated}, Trial active: {self._trial_active}")

        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Error de Licencia", f"Error al leer el archivo de licencia: {e}")
            self._full_license_activated = False
            self._trial_active = False
            self.save_license_state() # Overwrite with inactive state
        except Exception as e:
            QMessageBox.critical(self, "Error de Licencia", f"Error inesperado al cargar licencia: {e}")
            self._full_license_activated = False
            self._trial_active = False
            self.save_license_state() # Overwrite with inactive state
        finally:
            self.update_moderator_view() # Update license label on startup


    def get_mac_style(self):
        """
        Returns a CSS-like string for styling the application to resemble macOS Big Sur.
        """
        return """
            QMainWindow {
                background-color: #f2f2f5; /* Light gray background */
                color: #333; /* Dark text color */
                font-family: 'Helvetica Neue', sans-serif; /* Modern sans-serif font */
            }
            QPushButton {
                background-color: #e0e0e5; /* Light gray button background */
                border-radius: 8px; /* Rounded corners */
                padding: 8px 16px; /* Padding inside buttons */
                font-size: 14px; /* Font size for buttons */
                border: none; /* No border */
                margin: 4px; /* Margin around buttons */
            }
            QPushButton:hover {
                background-color: #d0d0d5; /* Slightly darker on hover */
            }
            QPushButton:pressed {
                background-color: #c0c0c5; /* Even darker when pressed */
            }
            QComboBox {
                padding: 6px; /* Padding inside combobox */
                border-radius: 6px; /* Rounded corners */
                background-color: #f9f9fb; /* Very light background */
                border: 1px solid #ccc; /* Light gray border */
                font-size: 14px; /* Font size for combobox */
            }
            QProgressBar {
                height: 12px; /* Height of the progress bar */
                border-radius: 6px; /* Rounded corners */
                text-align: center; /* Center align text (if any) */
                background-color: #e0e0e5; /* Light gray background */
                border: 1px solid #ccc; /* Light gray border */
            }
            QProgressBar::chunk {
                background-color: #7676ff; /* Blue progress chunk */
                border-radius: 5px; /* Rounded corners for the chunk */
            }
            QLabel {
                color: #333; /* Dark text color for labels */
            }
            DocumentItem {
                background-color: #ffffff;
                border: 1px solid #ddd;
                border-radius: 10px;
                margin: 5px;
                padding: 10px;
            }
            DocumentItem:hover {
                background-color: #f0f0f5;
                border: 1px solid #bbb;
            }
        """

    def dragEnterEvent(self, event):
        """
        Handles drag enter events to accept PDF files.
        """
        mime_data = event.mimeData()
        if mime_data.hasUrls() and all(url.toLocalFile().lower().endswith('.pdf') for url in mime_data.urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        """
        Handles drop events to load dropped PDF files.
        """
        urls = event.mimeData().urls()
        pdf_paths = [url.toLocalFile() for url in urls if url.toLocalFile().lower().endswith('.pdf')]
        if pdf_paths:
            # When dropping files onto the main window, always append them
            self.load_multiple_pdfs(file_paths=pdf_paths, append=True)
            event.acceptProposedAction()
        else:
            event.ignore()


    def init_initial_ui(self):
        """
        Sets up the initial UI screen where users can load PDFs.
        """
        initial_widget = QWidget()
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)

        label = QLabel("Arrastra o haz clic para cargar uno o más PDFs")
        label.setStyleSheet("font-size: 16px; color: #555;")

        load_button = QPushButton("Cargar Presentación(es)")
        # This button replaces existing PDFs
        load_button.clicked.connect(lambda: self.load_multiple_pdfs(append=False))

        layout.addWidget(label, alignment=Qt.AlignCenter)
        layout.addWidget(load_button, alignment=Qt.AlignCenter)
        initial_widget.setLayout(layout)
        self.stacked_widget.addWidget(initial_widget)

    def load_multiple_pdfs(self, file_paths=None, append=False):
        """
        Loads one or more PDF files. If file_paths is None, opens a file dialog.
        The 'append' parameter controls whether documents are added or replace existing ones.
        """
        if not file_paths:
            file_paths, _ = QFileDialog.getOpenFileNames(
                self, "Seleccionar PDF(s)", "", "PDF files (*.pdf)"
            )
        
        if file_paths:
            try:
                new_documents = [fitz.open(path) for path in file_paths]

                if append:
                    self.pdf_documents.extend(new_documents)
                else:
                    # Close previously opened documents to free resources if replacing
                    for doc in self.pdf_documents:
                        doc.close()
                    self.pdf_documents = new_documents
                    self.current_doc_index = 0
                    self.current_page = 0    
                    self.page_cache = {} 

                self.total_pages = sum(doc.page_count for doc in self.pdf_documents)
                
                # If loading new documents and not already licensed, ensure trial is inactive.
                # This ensures trial doesn't start unless explicitly prompted.
                if not self._full_license_activated:
                    self._trial_active = False 
                    self._trial_timer.stop() 
                    self.save_license_state()

                self.setup_document_selection_view()
                self.stacked_widget.setCurrentIndex(self.document_selection_index)
                self.update_moderator_view() # Update license label

                # Ensure doc_combo is updated if moderator view is already active
                if hasattr(self, 'doc_combo') and self.doc_combo.count() > 0:
                    self.doc_combo.clear()
                    self.doc_combo.addItems([os.path.basename(doc.name) for doc in self.pdf_documents])
                    self.doc_combo.setCurrentIndex(self.current_doc_index)


            except Exception as e:
                QMessageBox.critical(self, "Error al cargar PDFs", f"No se pudieron cargar los PDFs: {e}")
                print(f"Error al cargar PDFs: {e}")

    def setup_document_selection_view(self):
        """
        Sets up the UI for the document selection view, allowing reordering and selection.
        """
        if hasattr(self, 'document_selection_widget'):
            self.stacked_widget.removeWidget(self.document_selection_widget)
            self.document_selection_widget.deleteLater()

        self.document_selection_widget = QWidget()
        main_layout = QVBoxLayout(self.document_selection_widget)
        main_layout.setAlignment(Qt.AlignCenter)

        title_label = QLabel("Selecciona y Reordena Documentos")
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; margin-bottom: 20px;")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        self.doc_scroll_area = QScrollArea()
        self.doc_scroll_area.setWidgetResizable(True)
        self.doc_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff) 
        self.doc_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.doc_list_widget = QWidget()
        self.doc_list_layout = QGridLayout(self.doc_list_widget)
        self.doc_list_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft) 
        self.doc_list_widget.setLayout(self.doc_list_layout)
        self.doc_scroll_area.setWidget(self.doc_list_widget)

        main_layout.addWidget(self.doc_scroll_area)

        bottom_buttons_layout = QHBoxLayout()
        bottom_buttons_layout.addStretch()
        self.add_more_docs_btn = QPushButton("Añadir más PDFs")
        # This button appends new PDFs
        self.add_more_docs_btn.clicked.connect(lambda: self.load_multiple_pdfs(append=True))
        bottom_buttons_layout.addWidget(self.add_more_docs_btn)
        bottom_buttons_layout.addStretch()
        main_layout.addLayout(bottom_buttons_layout)

        self.stacked_widget.addWidget(self.document_selection_widget)
        self.update_document_selection_view()

        self.doc_list_widget.setAcceptDrops(True)
        self.doc_list_widget.dragEnterEvent = self.document_list_dragEnterEvent
        self.doc_list_widget.dragMoveEvent = self.document_list_dragMoveEvent
        self.doc_list_widget.dropEvent = self.document_list_dropEvent

    def update_document_selection_view(self):
        """
        Populates the document selection view with DocumentItem widgets in a grid.
        Refreshes the view after reordering or loading new documents.
        """
        for i in reversed(range(self.doc_list_layout.count())):
            widget_to_remove = self.doc_list_layout.itemAt(i).widget()
            if widget_to_remove:
                widget_to_remove.setParent(None)
                widget_to_remove.deleteLater()

        num_columns = 3 

        if len(self.pdf_documents) > 5:
            progress_dialog = QProgressDialog("Cargando miniaturas...", "Cancelar", 0, len(self.pdf_documents), self)
            progress_dialog.setWindowTitle("Cargando")
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.setMinimumDuration(0)
            progress_dialog.setValue(0)
            QApplication.processEvents() 

        for i, doc in enumerate(self.pdf_documents):
            if len(self.pdf_documents) > 5:
                progress_dialog.setValue(i)
                QApplication.processEvents() 

            first_page_pixmap = self.render_page_for_selection(i, 0, scale=0.5) 

            doc_name = os.path.basename(doc.name)

            doc_item = DocumentItem(i, doc_name, first_page_pixmap)
            # Use a lambda to pass the index correctly when the item is clicked
            doc_item.mousePressEvent = lambda event, idx=i: self.select_document_from_list(event, idx)

            row = i // num_columns
            col = i % num_columns
            self.doc_list_layout.addWidget(doc_item, row, col)

        if len(self.pdf_documents) > 5:
            progress_dialog.setValue(len(self.pdf_documents)) 
            progress_dialog.close()

    def render_page_for_selection(self, doc_index, page_in_doc_index, scale=0.5):
        """
        Renders a specific page from a specific document for the selection view.
        """
        cache_key = (doc_index, page_in_doc_index, scale)
        if cache_key in self.page_cache:
            return self.page_cache[cache_key]

        try:
            doc = self.pdf_documents[doc_index]
            page = doc[page_in_doc_index]
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            img = QImage.fromData(pix.tobytes("png"))
            qpixmap = QPixmap.fromImage(img)
            self.page_cache[cache_key] = qpixmap
            return qpixmap
        except Exception as e:
            print(f"Error al renderizar miniatura para selección: {e}")
            return None

    def select_document_from_list(self, event, selected_doc_index):
        """
        Handles selection of a document from the document selection list.
        Switches to moderator view for the selected document.
        """
        if event.button() == Qt.LeftButton:
            self.current_doc_index = selected_doc_index
            start_page_global_index = sum(doc.page_count for doc in self.pdf_documents[:selected_doc_index])
            self.current_page = start_page_global_index

            # Ensure moderator view is set up BEFORE trying to switch to it
            self.setup_moderator_view()
            self.update_moderator_view()
            self.stacked_widget.setCurrentIndex(self.moderator_index)


    def document_list_dragEnterEvent(self, event):
        """
        Allows drag events to enter the document list widget.
        Accepts both text (for internal reordering) and URLs (for dropping new files).
        """
        mime_data = event.mimeData()
        if mime_data.hasText() or (mime_data.hasUrls() and all(url.toLocalFile().lower().endswith('.pdf') for url in mime_data.urls())):
            event.acceptProposedAction()
        else:
            event.ignore()

    def document_list_dragMoveEvent(self, event):
        """
        Handles drag move events within the document list.
        """
        if event.mimeData().hasText() or (event.mimeData().hasUrls() and all(url.toLocalFile().lower().endswith('.pdf') for url in event.mimeData().urls())):
            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def document_list_dropEvent(self, event):
        """
        Handles drop events to reorder the documents or add new ones.
        Differentiates between internal drags (reordering) and external file drops (adding new PDFs).
        """
        mime_data = event.mimeData()

        if mime_data.hasUrls(): # Dropping new PDF files from outside
            pdf_paths = [url.toLocalFile() for url in mime_data.urls() if url.toLocalFile().lower().endswith('.pdf')]
            if pdf_paths:
                self.load_multiple_pdfs(file_paths=pdf_paths, append=True)
                event.acceptProposedAction()
                return

        elif mime_data.hasText(): # Internal drag-and-drop for reordering DocumentItems
            try:
                source_original_index = int(mime_data.text())
            except ValueError:
                event.ignore()
                return

            current_selected_doc_obj = None
            if 0 <= self.current_doc_index < len(self.pdf_documents):
                current_selected_doc_obj = self.pdf_documents[self.current_doc_index]

            target_layout_index = -1
            for i in range(self.doc_list_layout.count()):
                item = self.doc_list_layout.itemAt(i)
                if item and item.widget() and item.widget().geometry().contains(event.pos()):
                    target_layout_index = i
                    break

            if target_layout_index == -1:
                target_layout_index = self.doc_list_layout.count()

            source_current_layout_index = -1
            for i in range(self.doc_list_layout.count()):
                item_widget = self.doc_list_layout.itemAt(i).widget()
                if isinstance(item_widget, DocumentItem) and item_widget.doc_index == source_original_index:
                    source_current_layout_index = i
                    break

            if source_current_layout_index == -1 or source_current_layout_index == target_layout_index:
                event.ignore()
                return

            # Adjust target index if dragging from left to right within the same row/column logic
            if source_current_layout_index < target_layout_index:
                target_layout_index -= 1

            moved_doc = self.pdf_documents.pop(source_original_index)
            self.pdf_documents.insert(target_layout_index, moved_doc)

            # Update the doc_combo if it exists
            if hasattr(self, 'doc_combo') and self.doc_combo.count() > 0:
                self.doc_combo.clear()
                self.doc_combo.addItems([os.path.basename(doc.name) for doc in self.pdf_documents])


            if current_selected_doc_obj:
                try:
                    self.current_doc_index = self.pdf_documents.index(current_selected_doc_obj)
                except ValueError:
                    self.current_doc_index = 0 

            self.update_document_selection_view()

            # If the moderator view is active, update the combo box selection
            if self.stacked_widget.indexOf(self.moderator_widget) != -1:
                self.doc_combo.setCurrentIndex(self.current_doc_index)


            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def setup_moderator_view(self):
        """
        Sets up the UI for the moderator view, including previews, controls, and timer.
        """
        # Ensure moderator_widget is removed and deleted if it already exists
        if hasattr(self, 'moderator_widget') and self.stacked_widget.indexOf(self.moderator_widget) != -1:
            self.stacked_widget.removeWidget(self.moderator_widget)
            self.moderator_widget.deleteLater()

        self.moderator_layout = QVBoxLayout()

        top_bar = QHBoxLayout()
        self.btn_end = QPushButton("Finalizar Presentación")
        self.btn_end.clicked.connect(self.end_presentation)

        # Use pre-initialized combo box
        self.doc_combo.clear() # Clear existing items if any
        self.doc_combo.addItems([os.path.basename(doc.name) for doc in self.pdf_documents])
        self.doc_combo.currentIndexChanged.connect(self.change_document)
        self.doc_combo.setCurrentIndex(self.current_doc_index)

        # Use pre-initialized screen combo
        self.update_screen_selector() 

        top_bar.addWidget(self.btn_end)
        top_bar.addStretch() 
        top_bar.addWidget(self.time_label)
        top_bar.addWidget(self.trial_label) 
        top_bar.addWidget(self.doc_combo)
        top_bar.addWidget(self.screen_combo)

        preview_container = QHBoxLayout()
        # Use pre-initialized preview labels
        self.current_preview.setAlignment(Qt.AlignCenter)
        self.current_preview.setStyleSheet("background-color: black; border: 1px solid #aaa;")
        self.current_preview.setMinimumSize(600, 400) 
        self.current_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.next_preview.setAlignment(Qt.AlignCenter)
        self.next_preview.setStyleSheet("background-color: black; border: 1px solid #aaa;")
        self.next_preview.setFixedSize(200, 150) 

        preview_container.addWidget(self.current_preview, stretch=3) 
        preview_container.addWidget(self.next_preview, stretch=1) 

        # Use pre-initialized slide info and progress bar
        self.slide_info.setAlignment(Qt.AlignCenter)

        self.progress.setValue(0)

        bottom_bar = QHBoxLayout()
        self.btn_prev = QPushButton("Anterior")
        self.btn_prev.clicked.connect(self.prev_page)

        self.btn_gallery = QPushButton("Mostrar Diapositivas")
        self.btn_gallery.clicked.connect(self.show_thumbnail_gallery)

        self.btn_present = QPushButton("Iniciar Presentación")
        self.btn_present.clicked.connect(self.start_presentation)

        self.btn_next = QPushButton("Siguiente")
        self.btn_next.clicked.connect(self.next_page)

        bottom_bar.addWidget(self.btn_prev)
        bottom_bar.addWidget(self.btn_gallery)
        bottom_bar.addStretch()
        bottom_bar.addWidget(self.btn_present)
        bottom_bar.addStretch()
        bottom_bar.addWidget(self.btn_next)

        self.moderator_layout.addLayout(top_bar)
        self.moderator_layout.addLayout(preview_container)
        self.moderator_layout.addWidget(self.slide_info)
        self.moderator_layout.addWidget(self.progress)
        self.moderator_layout.addLayout(bottom_bar)

        self.moderator_widget = QWidget()
        self.moderator_widget.setLayout(self.moderator_layout)
        self.stacked_widget.addWidget(self.moderator_widget)

        self.timer.start(1000) 

    def change_document(self, index):
        """
        Changes the currently displayed PDF document in the moderator view.
        """
        if 0 <= index < len(self.pdf_documents):
            self.current_doc_index = index
            start_page_global_index = sum(doc.page_count for doc in self.pdf_documents[:self.current_doc_index])
            self.current_page = start_page_global_index
            self.update_moderator_view()

    def update_moderator_view(self):
        """
        Updates the current and next slide previews, slide info, and progress bar.
        Also updates the full-screen presentation if it's active.
        """
        # Always update trial_label and time_label as they are initialized in __init__
        if self._full_license_activated:
            self.trial_label.setText("Licencia: Completa")
            self.trial_label.setStyleSheet("font-size: 14px; color: #008000; font-weight: bold;")
        elif self._trial_active:
            remaining_seconds = max(0, QDateTime.currentDateTime().secsTo(self._trial_expiration_datetime))
            minutes = remaining_seconds // 60
            seconds = remaining_seconds % 60
            self.trial_label.setText(f"Licencia de prueba: {minutes:02d}:{seconds:02d}")
            self.trial_label.setStyleSheet("font-size: 14px; color: #cc0000; font-weight: bold;")
        else:
            self.trial_label.setText("Licencia: Inactiva")
            self.trial_label.setStyleSheet("font-size: 14px; color: #cc0000; font-weight: bold;")

        # Only update other elements if the moderator view has been fully set up
        if not hasattr(self, 'moderator_widget') or self.stacked_widget.indexOf(self.moderator_widget) == -1:
            return # Moderator widget not ready, exit early

        if not self.pdf_documents:
            self.current_preview.clear()
            self.next_preview.clear()
            self.slide_info.setText("0 de 0")
            self.progress.setValue(0)
            self.update_button_states()
            return

        current_doc = self.pdf_documents[self.current_doc_index]
        pages_before_current_doc = sum(doc.page_count for doc in self.pdf_documents[:self.current_doc_index])
        current_page_in_doc = self.current_page - pages_before_current_doc
        current_doc_page_count = current_doc.page_count

        current_pixmap = self.render_page(self.current_page)
        if current_pixmap:
            self.current_preview.setPixmap(current_pixmap.scaled(
                self.current_preview.width(), self.current_preview.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

        next_pixmap = self.render_page(self.current_page + 1)
        if next_pixmap:
            self.next_preview.setPixmap(next_pixmap.scaled(
                self.next_preview.size(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
        else:
            self.next_preview.clear() 

        self.slide_info.setText(f"{current_page_in_doc + 1} de {current_doc_page_count}")
        self.progress.setRange(0, current_doc_page_count)
        self.progress.setValue(current_page_in_doc + 1)

        self.update_button_states() 
        if self.presenter_window and self.presenter_window.isVisible():
            self.update_presentation()


    def render_page(self, page_number, scale=2):
        """
        Renders a specific page from the loaded PDF documents into a QPixmap.
        """
        if page_number >= self.total_pages or page_number < 0:
            return None

        doc_idx = 0
        remaining = page_number
        for i, doc in enumerate(self.pdf_documents):
            if remaining < doc.page_count:
                doc_idx = i
                break
            remaining -= doc.page_count

        page_in_doc_index = remaining

        cache_key = (doc_idx, page_in_doc_index, scale)

        if cache_key in self.page_cache:
            return self.page_cache[cache_key]

        try:
            page = self.pdf_documents[doc_idx][page_in_doc_index]
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            img = QImage.fromData(pix.tobytes("png")) 
            qpixmap = QPixmap.fromImage(img) 
            self.page_cache[cache_key] = qpixmap 
            return qpixmap
        except Exception as e:
            QMessageBox.warning(self, "Error de Renderizado", f"No se pudo renderizar la página {page_number + 1}: {e}")
            print(f"Error al renderizar página {page_number + 1}: {e}")
            return None

    def keyPressEvent(self, event):
        """
        Handles keyboard shortcuts for presentation control.
        """
        if event.key() == Qt.Key_F5:
            self.start_presentation()
        elif event.key() == Qt.Key_Escape and self.presenter_window:
            self.end_presentation()
        elif event.key() in (Qt.Key_PageDown, Qt.Key_Right, Qt.Key_Down, Qt.Key_Space):
            self.next_page()
        elif event.key() in (Qt.Key_PageUp, Qt.Key_Left, Qt.Key_Up):
            self.prev_page()
        else:
            super().keyPressEvent(event) 

    def prev_page(self):
        """
        Navigates to the previous page.
        """
        pages_before_current_doc = sum(doc.page_count for doc in self.pdf_documents[:self.current_doc_index])
        if self.current_page > pages_before_current_doc:
            self.current_page -= 1
            self.update_moderator_view()

    def next_page(self):
        """
        Navigates to the next page.
        """
        pages_before_current_doc = sum(doc.page_count for doc in self.pdf_documents[:self.current_doc_index])
        current_doc_page_count = self.pdf_documents[self.current_doc_index].page_count
        if self.current_page < pages_before_current_doc + current_doc_page_count - 1:
            self.current_page += 1
            self.update_moderator_view()

    def update_button_states(self):
        """
        Enables or disables the 'Previous' and 'Next' buttons based on current page
        within the current document.
        """
        # Ensure buttons exist before trying to enable/disable them
        if not hasattr(self, 'btn_prev') or not hasattr(self, 'btn_next'):
            return

        if not self.pdf_documents:
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            return

        pages_before_current_doc = sum(doc.page_count for doc in self.pdf_documents[:self.current_doc_index])
        current_doc_page_count = self.pdf_documents[self.current_doc_index].page_count

        self.btn_prev.setEnabled(self.current_page > pages_before_current_doc)
        self.btn_next.setEnabled(self.current_page < pages_before_current_doc + current_doc_page_count - 1)


    def show_thumbnail_gallery(self):
        """
        Displays a scrollable gallery of PDF page thumbnails for the current document.
        """
        if not self.pdf_documents:
            QMessageBox.warning(self, "No hay PDFs", "Por favor, carga un PDF para ver la galería de diapositivas.")
            return

        current_doc = self.pdf_documents[self.current_doc_index]
        pages_before_current_doc = sum(doc.page_count for doc in self.pdf_documents[:self.current_doc_index])
        
        scroll_area = QScrollArea()
        scroll_content = QWidget()
        scroll_layout = QGridLayout(scroll_content)
        scroll_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        for i in reversed(range(scroll_layout.count())):
            widget_to_remove = scroll_layout.itemAt(i).widget()
            if widget_to_remove:
                widget_to_remove.setParent(None)
                widget_to_remove.deleteLater()

        num_columns = 4 

        for page_num_in_doc in range(current_doc.page_count):
            global_page_num = pages_before_current_doc + page_num_in_doc

            container = QVBoxLayout()
            thumbnail = QLabel()
            thumbnail.setFixedSize(120, 90) 

            pixmap = self.render_page(global_page_num, scale=1)
            if pixmap:
                scaled = pixmap.scaled(thumbnail.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                thumbnail.setPixmap(scaled)
            else:
                thumbnail.setText("No Preview")
                thumbnail.setStyleSheet("color: #888; border: 1px dashed #ccc;")

            label = QLabel(f"{page_num_in_doc + 1}") 
            label.setAlignment(Qt.AlignCenter)

            container.addWidget(thumbnail)
            container.addWidget(label)

            widget = QWidget()
            widget.setLayout(container)
            widget.mousePressEvent = lambda e, pn=global_page_num: self.select_slide_and_return(pn)
            
            row = page_num_in_doc // num_columns
            col = page_num_in_doc % num_columns
            scroll_layout.addWidget(widget, row, col)

        scroll_area.setWidget(scroll_content)
        scroll_area.setWidgetResizable(True)

        # Add buttons below the gallery
        bottom_buttons_layout = QHBoxLayout()
        bottom_buttons_layout.addStretch()

        export_button = QPushButton("Exportar Diapositivas")
        export_button.clicked.connect(self.export_slides_to_folder)
        bottom_buttons_layout.addWidget(export_button)

        back_button = QPushButton("Volver")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(self.moderator_index))
        bottom_buttons_layout.addWidget(back_button)

        bottom_buttons_layout.addStretch()


        layout = QVBoxLayout()
        layout.addWidget(scroll_area)
        layout.addLayout(bottom_buttons_layout) # Add the new button layout here

        gallery_widget = QWidget()
        gallery_widget.setLayout(layout)
        if self.stacked_widget.indexOf(gallery_widget) == -1:
            self.stacked_widget.addWidget(gallery_widget)
        else:
            self.stacked_widget.removeWidget(self.stacked_widget.widget(self.gallery_index))
            self.stacked_widget.addWidget(gallery_widget)
            self.stacked_widget.insertWidget(self.gallery_index, gallery_widget) 

        self.stacked_widget.setCurrentIndex(self.gallery_index)

    def export_slides_to_folder(self):
        """
        Exports all slides of the current PDF document to a selected folder.
        Each slide is saved as a PNG image with the presentation name and slide number.
        """
        if not self.pdf_documents:
            QMessageBox.warning(self, "No hay PDFs", "Por favor, carga un PDF para exportar sus diapositivas.")
            return

        current_doc = self.pdf_documents[self.current_doc_index]
        pdf_base_name = os.path.splitext(os.path.basename(current_doc.name))[0]

        output_dir = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta para Exportar Diapositivas", "")

        if output_dir:
            export_folder_path = os.path.join(output_dir, f"{pdf_base_name}_Diapositivas")
            
            try:
                os.makedirs(export_folder_path, exist_ok=True)

                progress_dialog = QProgressDialog(f"Exportando diapositivas de '{pdf_base_name}'...", "Cancelar", 0, current_doc.page_count, self)
                progress_dialog.setWindowTitle("Exportando")
                progress_dialog.setWindowModality(Qt.WindowModal)
                progress_dialog.setMinimumDuration(0)
                progress_dialog.setValue(0)
                QApplication.processEvents() # Ensure dialog is shown

                for page_in_doc_index in range(current_doc.page_count):
                    if progress_dialog.wasCanceled():
                        QMessageBox.information(self, "Exportación Cancelada", "La exportación de diapositivas ha sido cancelada.")
                        break

                    page = current_doc[page_in_doc_index]
                    # Render with a higher scale for better export quality (e.g., 2x or 3x original size)
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) 
                    
                    filename = f"{pdf_base_name}_{page_in_doc_index + 1:03d}.png"
                    output_file_path = os.path.join(export_folder_path, filename)
                    pix.save(output_file_path)

                    progress_dialog.setValue(page_in_doc_index + 1)
                    QApplication.processEvents()

                progress_dialog.close()
                if not progress_dialog.wasCanceled():
                    QMessageBox.information(self, "Exportación Completa", 
                                            f"Las diapositivas han sido exportadas exitosamente a:\n{export_folder_path}")

            except Exception as e:
                QMessageBox.critical(self, "Error de Exportación", f"Ocurrió un error al exportar las diapositivas: {e}")
                print(f"Error al exportar diapositivas: {e}")

    def select_slide_and_return(self, page_number):
        """
        Sets the current page to the selected thumbnail's page and returns to moderator view.
        """
        self.current_page = page_number
        self.update_moderator_view()
        self.stacked_widget.setCurrentIndex(self.moderator_index)

    def start_presentation(self):
        """
        Initiates the full-screen presentation on the selected screen.
        Checks for license validity.
        """
        if not self.pdf_documents:
            QMessageBox.warning(self, "No hay PDFs", "Por favor, carga al menos un PDF antes de iniciar la presentación.")
            return
        
        if self._full_license_activated:
            self.create_presentation_window()
            return

        if self._trial_active: # If trial is already active and valid
            self.create_presentation_window()
            return
        
        # If no license is active, prompt for activation/trial
        license_dialog = QDialog(self)
        license_dialog.setWindowTitle("Iniciar Presentación")
        dialog_layout = QVBoxLayout()

        message_label = QLabel("Introduce la clave de licencia o inicia la prueba gratuita (15 minutos).")
        message_label.setAlignment(Qt.AlignCenter)
        dialog_layout.addWidget(message_label)

        license_input = QLineEdit()
        license_input.setPlaceholderText("Clave de licencia")
        dialog_layout.addWidget(license_input)

        button_layout = QHBoxLayout()
        start_trial_button = QPushButton("Iniciar Prueba")
        start_trial_button.clicked.connect(lambda: self._start_presentation_with_trial(license_dialog))
        button_layout.addWidget(start_trial_button)

        activate_license_button = QPushButton("Activar Licencia")
        activate_license_button.clicked.connect(lambda: self._start_presentation_with_key(license_input.text(), license_dialog))
        button_layout.addWidget(activate_license_button)

        cancel_button = QPushButton("Cancelar")
        cancel_button.clicked.connect(license_dialog.reject)
        button_layout.addWidget(cancel_button)

        dialog_layout.addLayout(button_layout)
        license_dialog.setLayout(dialog_layout)

        license_dialog.exec_() # Show as modal dialog

    def _start_presentation_with_trial(self, dialog):
        """Helper method to start presentation after starting trial."""
        self.start_trial()
        if self._trial_active: # Check if trial was successfully started (not expired immediately)
            dialog.accept()
            self.create_presentation_window()
        else:
            dialog.reject()

    def _start_presentation_with_key(self, key, dialog):
        """Helper method to start presentation after checking key."""
        if key == self._license_key:
            QMessageBox.information(self, "Licencia Activada", "La licencia ha sido activada correctamente.")
            self._full_license_activated = True 
            self._trial_active = False 
            self._trial_timer.stop()
            self.save_license_state() # Save full license state
            self.update_moderator_view() # Update label to show full license
            dialog.accept()
            self.create_presentation_window()
        else:
            QMessageBox.warning(self, "Clave Inválida", "La clave de licencia introducida es incorrecta.")
            dialog.reject()


    def start_trial(self):
        """Starts the 15-minute trial period."""
        if not self._trial_active and not self._full_license_activated: 
            self._trial_active = True
            # Calculate expiration datetime
            self._trial_expiration_datetime = QDateTime.currentDateTime().addSecs(self._trial_duration_secs)
            self._trial_timer.start(1000) 
            self.save_license_state() # Save trial state
            QMessageBox.information(self, "Modo de Prueba", f"La presentación se ejecutará en modo de prueba por {self._trial_duration_secs // 60} minutos.")
            self.update_moderator_view() 


    def stop_trial(self):
        """Stops the trial timer and deactivates trial mode."""
        self._trial_timer.stop()
        self._trial_active = False
        self._trial_expiration_datetime = QDateTime() # Reset expiration
        self.save_license_state() # Save inactive state
        self.update_moderator_view() 

    def check_trial_status(self):
        """Checks if the trial period has expired."""
        if self._trial_active:
            if QDateTime.currentDateTime() >= self._trial_expiration_datetime:
                self.stop_trial()
                self.end_presentation()
                QMessageBox.warning(self, "Fin de la Prueba", "El tiempo de prueba ha finalizado. La presentación se ha detenido.")
            self.update_moderator_view() # Update countdown label

    def create_presentation_window(self):
        """
        Creates and displays the full-screen presentation window.
        """
        self.selected_screen_index = self.screen_combo.currentData()

        if self.presenter_window:
            self.presenter_window.close()
            self.presenter_window = None

        self.presenter_window = QWidget()
        self.presenter_window.setWindowTitle("Presentación")
        self.presenter_window.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.presenter_window.setStyleSheet("background-color: black;")

        screen = self.available_screens[self.selected_screen_index]
        geo = screen.geometry()
        self.presenter_window.setGeometry(geo)
        self.presenter_window.showFullScreen() 

        self.presenter_label = QLabel(self.presenter_window)
        self.presenter_label.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout()
        layout.addWidget(self.presenter_label)
        layout.setContentsMargins(0, 0, 0, 0) 
        layout.setSpacing(0) 
        self.presenter_window.setLayout(layout)

        self.presenter_window.setFocusPolicy(Qt.StrongFocus)
        self.presenter_window.installEventFilter(self) 

        self.update_presentation() 

    def update_presentation(self):
        """
        Updates the image displayed in the full-screen presentation window.
        """
        pixmap = self.render_page(self.current_page, scale=3)
        if pixmap and self.presenter_window:
            screen = self.presenter_window.screen().geometry()
            scaled = pixmap.scaled(screen.width(), screen.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.presenter_label.setPixmap(scaled)

    def end_presentation(self):
        """
        Closes the full-screen presentation window and returns to the document selection view.
        """
        if self.presenter_window:
            self.presenter_window.close()
            self.presenter_window = None 
        # Attempt to switch to document selection view if it exists, otherwise to initial view
        if hasattr(self, 'document_selection_widget') and self.stacked_widget.indexOf(self.document_selection_widget) != -1:
            self.stacked_widget.setCurrentIndex(self.document_selection_index)
        else:
            self.stacked_widget.setCurrentIndex(self.selector_index) # Go back to initial UI

        self.presentation_time = QTime(0,0,0) 
        self.time_label.setText("00:00:00") 
        if not self._full_license_activated: 
            self.stop_trial() 
        self.update_moderator_view() # Ensure license label is updated when returning to moderator

    def update_timer(self):
        """
        Updates the presentation timer every second if the presentation is active.
        """
        if self.presenter_window and self.presenter_window.isVisible():
            self.presentation_time = self.presentation_time.addSecs(1)
            self.time_label.setText(self.presentation_time.toString("hh:mm:ss"))

    def closeEvent(self, event):
        """
        Handles the main window close event, ensuring the presentation window is also closed.
        """
        self.end_presentation() 
        for doc in self.pdf_documents:
            doc.close()
        event.accept() 

    def eventFilter(self, obj, event):
        """
        Filters events for the presentation window to handle key presses for navigation.
        """
        if event.type() == event.KeyPress and self.presenter_window:
            if event.key() == Qt.Key_Escape:
                self.end_presentation()
            elif event.key() in (Qt.Key_Right, Qt.Key_Down, Qt.Key_PageDown, Qt.Key_Space):
                self.next_page()
            elif event.key() in (Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp):
                self.prev_page()
            return True 
        return super().eventFilter(obj, event) 

    def update_screen_selector(self):
        """
        Populates the screen selection combo box with available screens.
        """
        self.screen_combo.clear()
        for i, screen in enumerate(self.available_screens):
            self.screen_combo.addItem(f"Pantalla {i+1} - {screen.name()}", i)
        if len(self.available_screens) > 1:
            self.screen_combo.setCurrentIndex(1)
        else:
            self.screen_combo.setCurrentIndex(0)


if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion") 
        window = PDFPresenter()
        window.resize(800, 600) 
        window.show() 
        sys.exit(app.exec_()) 
    except Exception as e:
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setText("Error al iniciar la aplicación")
        msg_box.setInformativeText(f"Ha ocurrido un error inesperado al iniciar la aplicación:\n\n{e}")
        msg_box.setWindowTitle("Error de Inicio")
        msg_box.exec_()
        sys.exit(1)
