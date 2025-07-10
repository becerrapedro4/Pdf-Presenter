import sys
import fitz
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QFileDialog,
    QVBoxLayout, QHBoxLayout, QProgressBar, QComboBox, QSizePolicy, QStackedWidget,
    QScrollArea, QMessageBox, QFrame, QGridLayout, QProgressDialog
)
from PyQt5.QtCore import Qt, QSize, QTime, QTimer, QMimeData
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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Presenter - Inicio")
        # Ensure 'icono.ico' exists in the same directory as the script, or provide a full path.
        # If the icon file is missing or corrupted, it might cause issues.
        self.setWindowIcon(QIcon("icono.ico"))
        self.setStyleSheet(self.get_mac_style())
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        # Variables to manage PDF documents and presentation state
        self.pdf_documents = []  # Stores multiple PDF documents opened with fitz
        self.current_doc_index = 0 # Index of the currently active PDF document
        self.current_page = 0    # Current page number across all loaded PDFs (global index)
        self.total_pages = 0     # Total pages across all loaded PDFs (global count)
        self.presenter_window = None # Reference to the full-screen presentation window
        self.available_screens = QGuiApplication.screens() # List of available display screens
        # Selects the second screen if available, otherwise the first
        self.selected_screen_index = 1 if len(self.available_screens) > 1 else 0
        self.presentation_time = QTime(0, 0, 0) # Tracks presentation duration
        self.timer = QTimer(self) # Timer for updating presentation time
        self.timer.timeout.connect(self.update_timer)

        # Cache para almacenar las páginas renderizadas (QPixmap)
        # La clave será una tupla (índice_documento, índice_página_dentro_del_documento, escala)
        self.page_cache = {}

        # UI setup: Uses a QStackedWidget to manage different views (initial, moderator, gallery, document selector)
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        # Initialize the initial UI (PDF selection screen)
        self.init_initial_ui()
        # Define indices for different views in the stacked widget
        self.selector_index = 0  # Initial PDF loading screen
        self.document_selection_index = 1 # New: Document selection and reordering view
        self.moderator_index = 2 # Moderator control panel
        self.gallery_index = 3   # Thumbnail gallery view
        self.setAcceptDrops(True) # Enable drag-and-drop for PDF files on the main window

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
            self.load_multiple_pdfs(pdf_paths)

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
        load_button.clicked.connect(lambda: self.load_multiple_pdfs())

        layout.addWidget(label, alignment=Qt.AlignCenter)
        layout.addWidget(load_button, alignment=Qt.AlignCenter)
        initial_widget.setLayout(layout)
        self.stacked_widget.addWidget(initial_widget)

    def load_multiple_pdfs(self, file_paths=None):
        """
        Loads one or more PDF files. If file_paths is None, opens a file dialog.
        """
        if not file_paths:
            file_paths, _ = QFileDialog.getOpenFileNames(
                self, "Seleccionar PDF(s)", "", "PDF files (*.pdf)"
            )
        if file_paths:
            try:
                # Close previously opened documents to free resources
                for doc in self.pdf_documents:
                    doc.close()
                self.pdf_documents = [fitz.open(path) for path in file_paths]
                self.current_doc_index = 0
                # Calculate total pages across all documents (global count)
                self.total_pages = sum(doc.page_count for doc in self.pdf_documents)
                self.current_page = 0 # Reset to the first page (global index)
                self.page_cache = {} # Clear cache when new PDFs are loaded

                # Setup the new document selection view
                self.setup_document_selection_view()
                self.stacked_widget.setCurrentIndex(self.document_selection_index)

            except Exception as e:
                QMessageBox.critical(self, "Error al cargar PDFs", f"No se pudieron cargar los PDFs: {e}")
                print(f"Error al cargar PDFs: {e}")

    def setup_document_selection_view(self):
        """
        Sets up the UI for the document selection view, allowing reordering and selection.
        """
        # Remove existing document selection widget if it exists
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

        # Scroll area for document items
        self.doc_scroll_area = QScrollArea()
        self.doc_scroll_area.setWidgetResizable(True)
        self.doc_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff) # No horizontal scroll
        self.doc_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.doc_list_widget = QWidget()
        # Change to QGridLayout for a grid view
        self.doc_list_layout = QGridLayout(self.doc_list_widget)
        self.doc_list_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft) # Align items to top and left
        self.doc_list_widget.setLayout(self.doc_list_layout)
        self.doc_scroll_area.setWidget(self.doc_list_widget)

        main_layout.addWidget(self.doc_scroll_area)

        # Buttons at the bottom
        bottom_buttons_layout = QHBoxLayout()
        bottom_buttons_layout.addStretch()
        self.add_more_docs_btn = QPushButton("Añadir más PDFs")
        self.add_more_docs_btn.clicked.connect(lambda: self.load_multiple_pdfs())
        bottom_buttons_layout.addWidget(self.add_more_docs_btn)
        bottom_buttons_layout.addStretch()
        main_layout.addLayout(bottom_buttons_layout)

        self.stacked_widget.addWidget(self.document_selection_widget)
        self.update_document_selection_view()

        # Enable drop events for the document list layout
        self.doc_list_widget.setAcceptDrops(True)
        self.doc_list_widget.dragEnterEvent = self.document_list_dragEnterEvent
        self.doc_list_widget.dragMoveEvent = self.document_list_dragMoveEvent
        self.doc_list_widget.dropEvent = self.document_list_dropEvent

    def update_document_selection_view(self):
        """
        Populates the document selection view with DocumentItem widgets in a grid.
        Refreshes the view after reordering or loading new documents.
        """
        # Clear existing items from the layout
        for i in reversed(range(self.doc_list_layout.count())):
            widget_to_remove = self.doc_list_layout.itemAt(i).widget()
            if widget_to_remove:
                widget_to_remove.setParent(None)
                widget_to_remove.deleteLater()

        num_columns = 3 # Define number of columns for the grid

        # Show a loading dialog for large number of documents
        if len(self.pdf_documents) > 5: # Threshold for showing loading dialog
            progress_dialog = QProgressDialog("Cargando miniaturas...", "Cancelar", 0, len(self.pdf_documents), self)
            progress_dialog.setWindowTitle("Cargando")
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.setMinimumDuration(0)
            progress_dialog.setValue(0)
            QApplication.processEvents() # Process events to show the dialog immediately

        # Re-populate the layout with DocumentItem widgets in the current order
        for i, doc in enumerate(self.pdf_documents):
            if len(self.pdf_documents) > 5:
                progress_dialog.setValue(i)
                QApplication.processEvents() # Update dialog

            # Get the first page thumbnail for the document
            first_page_pixmap = self.render_page_for_selection(i, 0, scale=0.5) # Render at a small scale

            # Get filename from document path
            doc_name = doc.name.split('/')[-1].split('\\')[-1] # Handles both / and \ paths

            doc_item = DocumentItem(i, doc_name, first_page_pixmap)
            # Connect mousePressEvent to select the document and switch to moderator view
            doc_item.mousePressEvent = lambda event, idx=i: self.select_document_from_list(event, idx)

            row = i // num_columns
            col = i % num_columns
            self.doc_list_layout.addWidget(doc_item, row, col)

        if len(self.pdf_documents) > 5:
            progress_dialog.setValue(len(self.pdf_documents)) # Complete the progress
            progress_dialog.close()


    def render_page_for_selection(self, doc_index, page_in_doc_index, scale=0.5):
        """
        Renders a specific page from a specific document for the selection view.
        This version does not check self.current_doc_index, as it's for global document previews.
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
        # Only process left mouse button clicks
        if event.button() == Qt.LeftButton:
            self.current_doc_index = selected_doc_index
            # Calculate the global page index for the first page of the selected document
            # This is important for `render_page` which still uses global page numbers
            start_page_global_index = sum(doc.page_count for doc in self.pdf_documents[:selected_doc_index])
            self.current_page = start_page_global_index

            # Setup moderator view if not already set up or needs refresh
            if not hasattr(self, 'moderator_widget') or self.stacked_widget.indexOf(self.moderator_widget) == -1:
                self.setup_moderator_view()
            else:
                # Update the doc_combo in moderator view to reflect the selection
                self.doc_combo.setCurrentIndex(self.current_doc_index)

            self.update_moderator_view()
            self.stacked_widget.setCurrentIndex(self.moderator_index)

    def document_list_dragEnterEvent(self, event):
        """
        Allows drag events to enter the document list widget.
        """
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def document_list_dragMoveEvent(self, event):
        """
        Handles drag move events within the document list.
        """
        if event.mimeData().hasText():
            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def document_list_dropEvent(self, event):
        """
        Handles drop events to reorder the documents.
        """
        if event.mimeData().hasText():
            source_original_index = int(event.mimeData().text())

            # Store the currently selected document object (if any) to preserve selection after reorder
            current_selected_doc_obj = None
            if 0 <= self.current_doc_index < len(self.pdf_documents):
                current_selected_doc_obj = self.pdf_documents[self.current_doc_index]

            # Determine the target index in the layout
            target_layout_index = -1
            # Iterate through the grid layout to find the dropped-on item's index
            for i in range(self.doc_list_layout.count()):
                item = self.doc_list_layout.itemAt(i)
                if item and item.widget() and item.widget().geometry().contains(event.pos()):
                    target_layout_index = i
                    break

            # If dropped in empty space, append to the end
            if target_layout_index == -1:
                target_layout_index = self.doc_list_layout.count()

            # Get the current linear index of the dragged item in the layout
            # This requires iterating through the layout to find the item with source_original_index
            source_current_layout_index = -1
            for i in range(self.doc_list_layout.count()):
                item_widget = self.doc_list_layout.itemAt(i).widget()
                if isinstance(item_widget, DocumentItem) and item_widget.doc_index == source_original_index:
                    source_current_layout_index = i
                    break

            if source_current_layout_index == -1 or source_current_layout_index == target_layout_index:
                event.ignore()
                return

            # Adjust target_layout_index if dragging an item backwards
            # This adjustment is for the `insert` operation after `pop`
            if source_current_layout_index < target_layout_index:
                target_layout_index -= 1

            # Reorder the self.pdf_documents list
            moved_doc = self.pdf_documents.pop(source_original_index)
            self.pdf_documents.insert(target_layout_index, moved_doc)

            # Reorder the doc_combo items
            if hasattr(self, 'doc_combo') and self.doc_combo.count() > 0:
                moved_doc_name = self.doc_combo.itemText(source_original_index)
                self.doc_combo.removeItem(source_original_index)
                self.doc_combo.insertItem(target_layout_index, moved_doc_name)

            # Update current_doc_index based on the object reference
            if current_selected_doc_obj:
                try:
                    self.current_doc_index = self.pdf_documents.index(current_selected_doc_obj)
                except ValueError:
                    # Should not happen if the object was in the list, but for robustness
                    self.current_doc_index = 0 # Default to first document if not found

            # Rebuild the document selection view to reflect the new order and update doc_index in DocumentItem
            self.update_document_selection_view()

            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def setup_moderator_view(self):
        """
        Sets up the UI for the moderator view, including previews, controls, and timer.
        """
        # Remove existing moderator widget if it exists to prevent duplicates on reload
        if hasattr(self, 'moderator_widget'):
            self.stacked_widget.removeWidget(self.moderator_widget)
            self.moderator_widget.deleteLater()

        self.moderator_layout = QVBoxLayout()

        # Top bar: End Presentation button, Timer, Document Selector, Screen Selector
        top_bar = QHBoxLayout()
        self.btn_end = QPushButton("Finalizar Presentación")
        # Change: End presentation now goes back to document selection
        self.btn_end.clicked.connect(self.end_presentation)

        self.time_label = QLabel("00:00:00")
        self.time_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.time_label.setAlignment(Qt.AlignCenter)

        self.doc_combo = QComboBox()
        # Populate document combo box with filenames
        self.doc_combo.addItems([doc.name.split('/')[-1].split('\\')[-1] for doc in self.pdf_documents])
        self.doc_combo.currentIndexChanged.connect(self.change_document)
        # Set the current index to the selected document
        self.doc_combo.setCurrentIndex(self.current_doc_index)


        self.screen_combo = QComboBox()
        self.update_screen_selector() # Populate screen combo box

        top_bar.addWidget(self.btn_end)
        top_bar.addStretch() # Pushes elements to the sides
        top_bar.addWidget(self.time_label)
        top_bar.addWidget(self.doc_combo)
        top_bar.addWidget(self.screen_combo)

        # Preview area: Current slide and next slide previews
        preview_container = QHBoxLayout()
        self.current_preview = QLabel()
        self.current_preview.setAlignment(Qt.AlignCenter)
        self.current_preview.setStyleSheet("background-color: black; border: 1px solid #aaa;")
        self.current_preview.setMinimumSize(600, 400) # Minimum size for current slide
        self.current_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.next_preview = QLabel()
        self.next_preview.setAlignment(Qt.AlignCenter)
        self.next_preview.setStyleSheet("background-color: black; border: 1px solid #aaa;")
        self.next_preview.setFixedSize(200, 150) # Fixed size for next slide thumbnail

        preview_container.addWidget(self.current_preview, stretch=3) # Current preview takes more space
        preview_container.addWidget(self.next_preview, stretch=1) # Next preview takes less space

        # Slide information and progress bar
        self.slide_info = QLabel("1 de 9") # Placeholder text, will be updated
        self.slide_info.setAlignment(Qt.AlignCenter)

        self.progress = QProgressBar()
        # Progress bar range will be set dynamically based on current document
        self.progress.setValue(0)

        # Bottom bar: Navigation buttons and Start Presentation button
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

        # Add all components to the main moderator layout
        self.moderator_layout.addLayout(top_bar)
        self.moderator_layout.addLayout(preview_container)
        self.moderator_layout.addWidget(self.slide_info)
        self.moderator_layout.addWidget(self.progress)
        self.moderator_layout.addLayout(bottom_bar)

        self.moderator_widget = QWidget()
        self.moderator_widget.setLayout(self.moderator_layout)
        self.stacked_widget.addWidget(self.moderator_widget)

        self.timer.start(1000) # Start the timer for presentation time

    def change_document(self, index):
        """
        Changes the currently displayed PDF document in the moderator view.
        This is called when the QComboBox in the moderator view is changed.
        """
        # Ensure the index is valid for the current list of documents
        if 0 <= index < len(self.pdf_documents):
            self.current_doc_index = index
            # Calculate the global page index for the first page of the selected document
            start_page_global_index = sum(doc.page_count for doc in self.pdf_documents[:self.current_doc_index])
            self.current_page = start_page_global_index
            self.update_moderator_view()

    def update_moderator_view(self):
        """
        Updates the current and next slide previews, slide info, and progress bar.
        Also updates the full-screen presentation if it's active.
        """
        if not self.pdf_documents:
            return

        # Calculate local page information for the current document
        current_doc = self.pdf_documents[self.current_doc_index]
        pages_before_current_doc = sum(doc.page_count for doc in self.pdf_documents[:self.current_doc_index])
        current_page_in_doc = self.current_page - pages_before_current_doc
        current_doc_page_count = current_doc.page_count

        # Render current page preview
        current_pixmap = self.render_page(self.current_page)
        if current_pixmap:
            self.current_preview.setPixmap(current_pixmap.scaled(
                self.current_preview.width(), self.current_preview.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

        # Render next page preview (if available)
        next_pixmap = self.render_page(self.current_page + 1)
        if next_pixmap:
            self.next_preview.setPixmap(next_pixmap.scaled(
                self.next_preview.size(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
        else:
            self.next_preview.clear() # Clear if no next page

        # Update slide information and progress bar (now local to the current document)
        self.slide_info.setText(f"{current_page_in_doc + 1} de {current_doc_page_count}")
        self.progress.setRange(0, current_doc_page_count)
        self.progress.setValue(current_page_in_doc + 1)

        self.update_button_states() # Enable/disable navigation buttons
        # Update the full-screen presentation if it's open
        if self.presenter_window and self.presenter_window.isVisible():
            self.update_presentation()

    def render_page(self, page_number, scale=2):
        """
        Renders a specific page from the loaded PDF documents into a QPixmap.
        Handles multi-document page indexing.
        Uses a cache to store and retrieve rendered pages for performance.
        """
        # If page_number is out of bounds for all documents, return None
        if page_number >= self.total_pages or page_number < 0:
            return None

        doc_idx = 0
        remaining = page_number
        # Determine which PDF document the page_number belongs to
        for i, doc in enumerate(self.pdf_documents):
            if remaining < doc.page_count:
                doc_idx = i
                break
            remaining -= doc.page_count

        # Calculate the actual page index within the specific document
        page_in_doc_index = remaining

        # Create a unique key for the cache including the scale
        cache_key = (doc_idx, page_in_doc_index, scale)

        # Check if the page is already in the cache
        if cache_key in self.page_cache:
            return self.page_cache[cache_key]

        try:
            # Open the page and render it as a pixmap
            page = self.pdf_documents[doc_idx][page_in_doc_index]
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            img = QImage.fromData(pix.tobytes("png")) # Convert to QImage
            qpixmap = QPixmap.fromImage(img) # Convert to QPixmap
            self.page_cache[cache_key] = qpixmap # Store in cache
            return qpixmap
        except Exception as e:
            # Catch rendering errors and provide feedback
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
            super().keyPressEvent(event) # Call base class method for unhandled keys

    def prev_page(self):
        """
        Navigates to the previous page.
        """
        # Ensure we don't go below the first page of the current document
        pages_before_current_doc = sum(doc.page_count for doc in self.pdf_documents[:self.current_doc_index])
        if self.current_page > pages_before_current_doc:
            self.current_page -= 1
            self.update_moderator_view()

    def next_page(self):
        """
        Navigates to the next page.
        """
        # Ensure we don't go beyond the last page of the current document
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
        # Use QGridLayout for the gallery thumbnails
        scroll_layout = QGridLayout(scroll_content)
        scroll_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        # Clear existing widgets from the layout if re-entering the gallery
        for i in reversed(range(scroll_layout.count())):
            widget_to_remove = scroll_layout.itemAt(i).widget()
            if widget_to_remove:
                widget_to_remove.setParent(None)
                widget_to_remove.deleteLater()

        num_columns = 4 # Number of columns for the gallery grid

        # Iterate only through pages of the current document
        for page_num_in_doc in range(current_doc.page_count):
            global_page_num = pages_before_current_doc + page_num_in_doc

            container = QVBoxLayout()
            thumbnail = QLabel()
            thumbnail.setFixedSize(120, 90) # Fixed size for thumbnails

            # Render thumbnail at lower scale (scale=1)
            pixmap = self.render_page(global_page_num, scale=1)
            if pixmap:
                scaled = pixmap.scaled(thumbnail.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                thumbnail.setPixmap(scaled)
            else:
                thumbnail.setText("No Preview")
                thumbnail.setStyleSheet("color: #888; border: 1px dashed #ccc;")

            label = QLabel(f"{page_num_in_doc + 1}") # Display local page number
            label.setAlignment(Qt.AlignCenter)

            container.addWidget(thumbnail)
            container.addWidget(label)

            widget = QWidget()
            widget.setLayout(container)
            # Make the thumbnail clickable to jump to that page
            widget.mousePressEvent = lambda e, pn=global_page_num: self.select_slide_and_return(pn)
            
            row = page_num_in_doc // num_columns
            col = page_num_in_doc % num_columns
            scroll_layout.addWidget(widget, row, col)

        scroll_area.setWidget(scroll_content)
        scroll_area.setWidgetResizable(True)

        back_button = QPushButton("Volver")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(self.moderator_index))

        layout = QVBoxLayout()
        layout.addWidget(scroll_area)
        layout.addWidget(back_button, alignment=Qt.AlignCenter)

        gallery_widget = QWidget()
        gallery_widget.setLayout(layout)
        # Add the gallery widget to the stacked widget if not already present
        if self.stacked_widget.indexOf(gallery_widget) == -1:
            self.stacked_widget.addWidget(gallery_widget)
        else:
            # If it exists, remove and re-add to ensure layout updates correctly
            self.stacked_widget.removeWidget(self.stacked_widget.widget(self.gallery_index))
            self.stacked_widget.addWidget(gallery_widget)
            self.stacked_widget.insertWidget(self.gallery_index, gallery_widget) # Ensure it's at the correct index

        self.stacked_widget.setCurrentIndex(self.gallery_index)

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
        """
        if not self.pdf_documents:
            QMessageBox.warning(self, "No hay PDFs", "Por favor, carga al menos un PDF antes de iniciar la presentación.")
            return

        # Get the selected screen index from the combo box
        self.selected_screen_index = self.screen_combo.currentData()
        self.create_presentation_window()

    def create_presentation_window(self):
        """
        Creates and displays the full-screen presentation window.
        """
        # Close existing presentation window if any
        if self.presenter_window:
            self.presenter_window.close()
            self.presenter_window = None

        self.presenter_window = QWidget()
        self.presenter_window.setWindowTitle("Presentación")
        # Set window flags for frameless and always-on-top
        self.presenter_window.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.presenter_window.setStyleSheet("background-color: black;")

        # Get the geometry of the selected screen
        screen = self.available_screens[self.selected_screen_index]
        geo = screen.geometry()
        self.presenter_window.setGeometry(geo)
        self.presenter_window.showFullScreen() # Display in full screen

        self.presenter_label = QLabel(self.presenter_window)
        self.presenter_label.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout()
        layout.addWidget(self.presenter_label)
        layout.setContentsMargins(0, 0, 0, 0) # No margins
        layout.setSpacing(0) # No spacing
        self.presenter_window.setLayout(layout)

        # Enable strong focus policy for key events in the presentation window
        self.presenter_window.setFocusPolicy(Qt.StrongFocus)
        self.presenter_window.installEventFilter(self) # Install event filter for key events

        self.update_presentation() # Display the current page

    def update_presentation(self):
        """
        Updates the image displayed in the full-screen presentation window.
        """
        # Render the current page at a higher scale for full-screen display
        pixmap = self.render_page(self.current_page, scale=3)
        if pixmap and self.presenter_window:
            screen = self.presenter_window.screen().geometry()
            # Scale the pixmap to fit the screen while maintaining aspect ratio
            scaled = pixmap.scaled(screen.width(), screen.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.presenter_label.setPixmap(scaled)

    def end_presentation(self):
        """
        Closes the full-screen presentation window and returns to the document selection view.
        """
        if self.presenter_window:
            self.presenter_window.close()
            self.presenter_window = None # Clear the reference
        # Return to document selection view after ending presentation
        self.stacked_widget.setCurrentIndex(self.document_selection_index)
        self.presentation_time = QTime(0,0,0) # Reset timer
        self.time_label.setText("00:00:00") # Reset timer display

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
        self.end_presentation() # Close the presentation window
        # Close all opened PDF documents to release resources
        for doc in self.pdf_documents:
            doc.close()
        event.accept() # Accept the close event

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
            return True # Event handled
        return super().eventFilter(obj, event) # Pass unhandled events to base class

    def update_screen_selector(self):
        """
        Populates the screen selection combo box with available screens.
        """
        self.screen_combo.clear()
        for i, screen in enumerate(self.available_screens):
            self.screen_combo.addItem(f"Pantalla {i+1} - {screen.name()}", i)
        # Set default selection to the second screen if available, otherwise the first
        if len(self.available_screens) > 1:
            self.screen_combo.setCurrentIndex(1)
        else:
            self.screen_combo.setCurrentIndex(0)


if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")  # Apply a modern style to the application
        window = PDFPresenter()
        window.resize(800, 600) # Set initial size of the main window
        window.show() # Display the main window
        sys.exit(app.exec_()) # Start the application event loop
    except Exception as e:
        # Catch any exceptions during application startup and display them
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setText("Error al iniciar la aplicación")
        msg_box.setInformativeText(f"Ha ocurrido un error inesperado al iniciar la aplicación:\n\n{e}")
        msg_box.setWindowTitle("Error de Inicio")
        msg_box.exec_()
        sys.exit(1) # Exit with an error code
