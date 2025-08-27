"""
DatCure - Data Curation Application
===================================

This module implements a PyQt5 based application for browsing and
curating image datasets.  Users can load a directory containing images
and optional caption files (``.txt`` files with comma separated
tags).  Images are displayed in a grid with controls for changing the
number of columns, selecting multiple images, and adding or removing
tags.  A detachable focus window shows a larger view of the
currently selected image along with its tags and basic metadata.  The
application supports copying or moving a selection of images (and
their caption files) to a new directory.  Tags can be filtered in
either an inclusive or exclusive fashion, and tags in the focus
window can be sorted by frequency.

This file is intended to be self‑contained; no external modules beyond
the Python standard library and PyQt5 are required.  All UI
construction and logic live in the ``DatCureApp`` class defined
herein.
"""

import os
import sys
import shutil
from collections import defaultdict

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QFileDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QScrollArea,
    QLineEdit,
    QSplitter,
    QAction,
    QMenu,
    QCheckBox,
    QMessageBox,
    QDockWidget,
)
from PyQt5.QtGui import QPixmap, QPalette, QColor, QFont
from PyQt5.QtCore import Qt, QThreadPool, QRunnable, pyqtSlot, QObject, pyqtSignal


# -----------------------------------------------------------------------------
# Worker infrastructure
#
# Loading images from disk can be a slow operation when traversing a large
# directory.  To keep the user interface responsive the work of walking
# directories and reading caption files is offloaded to a separate thread
# managed by a ``QThreadPool``.  The ``Worker`` class encapsulates a callable
# along with its arguments and provides signals for communicating results or
# errors back to the main thread.

class WorkerSignals(QObject):
    """Signals available from a running worker thread."""

    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)


class Worker(QRunnable):
    """Wrap a callable to be executed in a worker thread."""

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        """Execute the callable and emit the appropriate signals."""
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception:
            self.signals.error.emit(sys.exc_info())
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


# -----------------------------------------------------------------------------
# Main application window


class DatCureApp(QMainWindow):
    """Top level window for the DatCure application."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DatCure - Data Curation App")
        self.setGeometry(100, 100, 1200, 800)

        # Worker thread pool
        self.threadpool = QThreadPool()

        # Apply a dark theme throughout the application
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(45, 45, 45))
        palette.setColor(QPalette.WindowText, QColor(220, 220, 220))
        palette.setColor(QPalette.Base, QColor(55, 55, 55))
        palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
        palette.setColor(QPalette.ToolTipBase, QColor(200, 200, 200))
        palette.setColor(QPalette.ToolTipText, QColor(0, 0, 0))
        palette.setColor(QPalette.Text, QColor(0, 0, 0))
        palette.setColor(QPalette.Button, QColor(30, 30, 30))
        palette.setColor(QPalette.ButtonText, QColor(0, 0, 0))
        palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
        palette.setColor(QPalette.Highlight, QColor(100, 100, 100))
        palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        self.setPalette(palette)

        # Data structures
        self.image_dir = ""
        self.images = []  # list of image file paths
        self.captions = {}  # mapping from image path to list of tags
        self.tag_frequency = defaultdict(int)  # global tag frequency across all images
        self.selected_images = set()  # currently selected images
        self.all_tags = set()  # set of all unique tags
        self.filtered_images = []  # images matching current filter
        self.filter_active = False  # whether a filter is currently applied
        self.filter_mode = "Inclusive"
        self.images_per_row = 5

        # Build UI components
        self.create_menu()
        self.create_tag_and_folder_area()
        self.create_gallery_controls()
        self.create_data_analytics_placeholder()

        # Main splitter divides the tag/folder sidebar from the gallery
        self.main_splitter = QSplitter(Qt.Horizontal)

        # Sidebar containing folder tree and tag list
        self.tag_folder_widget = QWidget()
        self.tag_folder_widget.setLayout(self.tag_folder_layout)
        self.main_splitter.addWidget(self.tag_folder_widget)

        # Gallery area
        self.gallery_widget = QWidget()
        self.gallery_layout = QVBoxLayout()
        self.gallery_widget.setLayout(self.gallery_layout)
        self.main_splitter.addWidget(self.gallery_widget)

        # Gallery controls sit above the scrolling area
        self.gallery_layout.addLayout(self.gallery_controls_layout)

        # Scroll area for displaying image thumbnails
        self.scroll_area = QScrollArea()
        self.scroll_area_widget = QWidget()
        self.scroll_area_layout = QVBoxLayout()
        self.scroll_area_widget.setLayout(self.scroll_area_layout)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_area_widget)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.gallery_layout.addWidget(self.scroll_area)

        # Assemble central widget with splitter
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.addWidget(self.main_splitter)
        self.setCentralWidget(central_widget)

        # Focus window dock showing a larger view of the current image
        self.create_focus_window()
        self.focus_dock = QDockWidget("Focus Window", self)
        self.focus_dock.setWidget(self.focus_widget)
        self.focus_dock.setAllowedAreas(
            Qt.LeftDockWidgetArea
            | Qt.RightDockWidgetArea
            | Qt.TopDockWidgetArea
            | Qt.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self.focus_dock)
        self.focus_dock.setFloating(True)

        # Set initial sizes for the splitter
        self.main_splitter.setSizes([300, 900])

    # ------------------------------------------------------------------
    # Menu construction
    def create_menu(self):
        """Create the top menu bar and its actions."""
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        open_dir_action = QAction("Open Directory", self)
        open_dir_action.triggered.connect(self.open_directory)
        file_menu.addAction(open_dir_action)

        data_analytics_action = QAction("Data Analytics", self)
        data_analytics_action.triggered.connect(self.open_data_analytics)
        file_menu.addAction(data_analytics_action)

        # Export submenu
        export_menu = QMenu("Export", self)
        export_copy_action = QAction("Copy Selection", self)
        export_copy_action.triggered.connect(self.copy_selection)
        export_move_action = QAction("Move Selection", self)
        export_move_action.triggered.connect(self.move_selection)
        export_menu.addAction(export_copy_action)
        export_menu.addAction(export_move_action)
        file_menu.addMenu(export_menu)

    # ------------------------------------------------------------------
    # Gallery controls
    def create_gallery_controls(self):
        """Construct widgets for controlling the gallery view."""
        self.gallery_controls_layout = QHBoxLayout()

        # Images per row control
        images_per_row_layout = QHBoxLayout()
        decrease_images_btn = QPushButton("<")
        decrease_images_btn.clicked.connect(lambda: self.change_images_per_row(-1))
        increase_images_btn = QPushButton(">")
        increase_images_btn.clicked.connect(lambda: self.change_images_per_row(1))
        self.images_per_row_label = QLabel(str(self.images_per_row))
        self.images_per_row_label.setStyleSheet(
            "background-color: black; color: #00BFFF; font-weight: bold; padding: 5px;"
        )
        self.images_per_row_label.setFont(QFont("Arial", 12))
        images_per_row_layout.addWidget(decrease_images_btn)
        images_per_row_layout.addWidget(self.images_per_row_label)
        images_per_row_layout.addWidget(increase_images_btn)
        self.gallery_controls_layout.addWidget(QLabel("Images Per Row:"))
        self.gallery_controls_layout.addLayout(images_per_row_layout)

        # Selected images counter
        self.selected_counter = QLabel("Selected Images: ")
        self.selected_counter.setStyleSheet("color: white;")
        self.selected_counter.setFont(QFont("Arial", 12))
        self.selected_count_label = QLabel("0")
        self.selected_count_label.setStyleSheet(
            "background-color: black; color: #00BFFF; font-weight: bold; padding: 5px;"
        )
        self.selected_count_label.setFont(QFont("Arial", 12))
        self.gallery_controls_layout.addWidget(self.selected_counter)
        self.gallery_controls_layout.addWidget(self.selected_count_label)

        # Batch selection buttons
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.select_all_images)
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self.deselect_all_images)
        invert_selection_btn = QPushButton("Invert Selection")
        invert_selection_btn.clicked.connect(self.invert_selection)
        self.gallery_controls_layout.addWidget(select_all_btn)
        self.gallery_controls_layout.addWidget(deselect_all_btn)
        self.gallery_controls_layout.addWidget(invert_selection_btn)

        # Tag operations: add and remove tags
        tag_op_layout = QHBoxLayout()
        self.add_tag_input = QLineEdit()
        self.add_tag_input.setPlaceholderText("Add Tag to Selected")
        add_tag_btn = QPushButton("Add Tag")
        add_tag_btn.clicked.connect(self.add_tag_to_selected)
        tag_op_layout.addWidget(self.add_tag_input)
        tag_op_layout.addWidget(add_tag_btn)
        self.remove_tag_input = QLineEdit()
        self.remove_tag_input.setPlaceholderText("Remove Tag from Selected")
        remove_tag_btn = QPushButton("Remove Tag")
        remove_tag_btn.clicked.connect(self.remove_tag_from_selected)
        tag_op_layout.addWidget(self.remove_tag_input)
        tag_op_layout.addWidget(remove_tag_btn)
        self.gallery_controls_layout.addLayout(tag_op_layout)

        # Apply consistent styling
        for widget in [
            decrease_images_btn,
            increase_images_btn,
            select_all_btn,
            deselect_all_btn,
            invert_selection_btn,
            add_tag_btn,
            remove_tag_btn,
        ]:
            widget.setStyleSheet("background-color: #1e1e1e; color: #00BFFF;")
        for widget in [self.add_tag_input, self.remove_tag_input]:
            widget.setStyleSheet("background-color: #b0b0b0; color: black;")

    # ------------------------------------------------------------------
    # Tag and folder area
    def create_tag_and_folder_area(self):
        """Build the sidebar containing the folder tree and tag list."""
        self.tag_folder_layout = QVBoxLayout()

        # Folder tree controls
        folder_tree_layout = QVBoxLayout()
        self.folder_tree_toggle = QPushButton("Show Folder Tree")
        self.folder_tree_toggle.setCheckable(True)
        self.folder_tree_toggle.toggled.connect(self.toggle_folder_tree)
        folder_tree_layout.addWidget(self.folder_tree_toggle)

        self.include_subdirs_checkbox = QCheckBox("Include Subdirectories")
        self.include_subdirs_checkbox.setChecked(True)
        folder_tree_layout.addWidget(self.include_subdirs_checkbox)

        open_selected_folder_btn = QPushButton("Open Selected Folder")
        open_selected_folder_btn.clicked.connect(self.open_selected_folder)
        folder_tree_layout.addWidget(open_selected_folder_btn)

        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderLabel("Folders")
        self.folder_tree.hide()
        folder_tree_layout.addWidget(self.folder_tree)

        self.tag_folder_layout.addLayout(folder_tree_layout)

        # Tag list and filtering controls
        tag_list_layout = QVBoxLayout()
        self.tag_list = QListWidget()
        self.tag_list.setSelectionMode(QListWidget.MultiSelection)
        self.tag_list.itemSelectionChanged.connect(self.update_tag_filter)
        tag_list_layout.addWidget(self.tag_list)

        self.filter_mode_toggle = QPushButton("Filter Mode: Inclusive")
        self.filter_mode_toggle.setCheckable(True)
        self.filter_mode_toggle.toggled.connect(self.toggle_filter_mode)
        tag_list_layout.addWidget(self.filter_mode_toggle)

        filter_layout = QHBoxLayout()
        filter_tags_btn = QPushButton("Filter Tags")
        filter_tags_btn.clicked.connect(self.filter_images)
        ignore_tags_btn = QPushButton("Ignore Tags")
        ignore_tags_btn.clicked.connect(self.ignore_tags)
        clear_filter_btn = QPushButton("Clear Filter")
        clear_filter_btn.clicked.connect(self.clear_filter)
        filter_layout.addWidget(filter_tags_btn)
        filter_layout.addWidget(ignore_tags_btn)
        filter_layout.addWidget(clear_filter_btn)
        tag_list_layout.addLayout(filter_layout)

        self.tag_folder_layout.addLayout(tag_list_layout)

        # Apply styling to sidebar buttons
        self.folder_tree_toggle.setStyleSheet(
            "background-color: #1e1e1e; color: #00BFFF;"
        )
        open_selected_folder_btn.setStyleSheet(
            "background-color: #1e1e1e; color: #00BFFF;"
        )
        self.filter_mode_toggle.setStyleSheet(
            "background-color: #1e1e1e; color: #00BFFF;"
        )
        filter_tags_btn.setStyleSheet("background-color: #1e1e1e; color: #00BFFF;")
        ignore_tags_btn.setStyleSheet("background-color: #1e1e1e; color: #00BFFF;")
        clear_filter_btn.setStyleSheet("background-color: #1e1e1e; color: #00BFFF;")

    # ------------------------------------------------------------------
    # Focus window
    def create_focus_window(self):
        """Create the detachable focus window showing a large preview and tags."""
        self.focus_widget = QWidget()
        self.focus_widget.setMinimumSize(400, 600)

        # Apply dark theme to focus window
        focus_palette = QPalette()
        focus_palette.setColor(QPalette.Window, QColor(45, 45, 45))
        focus_palette.setColor(QPalette.WindowText, QColor(220, 220, 220))
        focus_palette.setColor(QPalette.Base, QColor(55, 55, 55))
        focus_palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
        focus_palette.setColor(QPalette.Text, QColor(220, 220, 220))
        focus_palette.setColor(QPalette.Button, QColor(30, 30, 30))
        focus_palette.setColor(QPalette.ButtonText, QColor(220, 220, 220))
        self.focus_widget.setPalette(focus_palette)
        self.focus_widget.setStyleSheet(
            "background-color: #2d2d2d; color: #dcdcdc;"
        )

        focus_layout = QVBoxLayout()
        focus_layout.setContentsMargins(5, 5, 5, 5)
        focus_layout.setSpacing(5)

        # Scroll area to allow the image to be zoomed and panned
        self.focus_image_scroll = QScrollArea()
        self.focus_image_scroll.setWidgetResizable(True)
        self.focus_image_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.focus_image_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.focus_image_scroll.setAlignment(Qt.AlignCenter)
        self.focus_image_scroll.setStyleSheet(
            "QScrollArea { border: none; background-color: #2d2d2d; }"
        )

        # Container for the image label
        self.focus_image_container = QWidget()
        self.focus_image_container.setStyleSheet(
            "background-color: #2d2d2d;"
        )
        container_layout = QVBoxLayout()
        container_layout.setContentsMargins(0, 0, 0, 0)
        self.focus_image_label = QLabel("No Image Selected")
        self.focus_image_label.setAlignment(Qt.AlignCenter)
        self.focus_image_label.setStyleSheet(
            "color: #dcdcdc; background-color: #2d2d2d;"
        )
        self.focus_image_label.setScaledContents(False)
        self.focus_image_label.setMouseTracking(True)
        container_layout.addWidget(self.focus_image_label)
        self.focus_image_container.setLayout(container_layout)
        self.focus_image_scroll.setWidget(self.focus_image_container)
        focus_layout.addWidget(self.focus_image_scroll, stretch=1)

        # Bottom panel for image info and tag list
        bottom_widget = QWidget()
        bottom_widget.setMaximumHeight(200)
        bottom_widget.setStyleSheet(
            "background-color: #373737; border-top: 1px solid #555;"
        )
        bottom_layout = QVBoxLayout()
        bottom_layout.setContentsMargins(8, 8, 8, 8)
        bottom_layout.setSpacing(4)

        # Information line showing resolution and zoom
        self.focus_info_label = QLabel()
        self.focus_info_label.setStyleSheet(
            "color: #00BFFF; font-size: 11px; font-weight: bold;"
        )
        self.focus_info_label.setMaximumHeight(20)
        bottom_layout.addWidget(self.focus_info_label)

        # Tag sorting buttons
        tag_sort_layout = QHBoxLayout()
        tag_sort_layout.setSpacing(4)
        sort_high_btn = QPushButton("Freq ↓")
        sort_high_btn.clicked.connect(self.sort_tags_high)
        sort_low_btn = QPushButton("Freq ↑")
        sort_low_btn.clicked.connect(self.sort_tags_low)
        button_style = (
            "QPushButton { background-color: #1e1e1e; color: #00BFFF; border: 1px solid #555;"
            " padding: 4px 8px; font-size: 10px; max-height: 24px; }"
            "QPushButton:hover { background-color: #2a2a2a; }"
        )
        sort_high_btn.setStyleSheet(button_style)
        sort_low_btn.setStyleSheet(button_style)
        tag_sort_layout.addWidget(sort_high_btn)
        tag_sort_layout.addWidget(sort_low_btn)
        tag_sort_layout.addStretch()
        bottom_layout.addLayout(tag_sort_layout)

        # List of tags for the focused image
        self.focus_tag_list = QListWidget()
        self.focus_tag_list.setSelectionMode(QListWidget.MultiSelection)
        self.focus_tag_list.setMaximumHeight(120)
        self.focus_tag_list.setStyleSheet(
            """
            QListWidget {
                color: white;
                background-color: #2d2d2d;
                border: 1px solid #555;
                font-size: 11px;
            }
            QListWidget::item {
                padding: 2px;
                border-bottom: 1px solid #444;
            }
            QListWidget::item:selected {
                background-color: #00BFFF;
                color: black;
            }
            """
        )
        bottom_layout.addWidget(self.focus_tag_list)
        bottom_widget.setLayout(bottom_layout)
        focus_layout.addWidget(bottom_widget, stretch=0)

        self.focus_widget.setLayout(focus_layout)

        # Track zoom state and current pixmap
        self.focus_zoom_factor = 1.0
        self.focus_pixmap = None
        self.focus_image_path = None

        # Install event filters to intercept mouse wheel events for zooming
        self.focus_image_label.installEventFilter(self)
        self.focus_image_scroll.installEventFilter(self)

    # ------------------------------------------------------------------
    # Event filter for mouse wheel zooming
    def eventFilter(self, obj, event):
        if (
            (obj == self.focus_image_label or obj == self.focus_image_scroll)
            and event.type() == event.Wheel
        ):
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in_focus_image()
            else:
                self.zoom_out_focus_image()
            return True
        return super().eventFilter(obj, event)

    def zoom_in_focus_image(self):
        self.update_focus_zoom(1.2)

    def zoom_out_focus_image(self):
        self.update_focus_zoom(0.8)

    def update_focus_zoom(self, scale_factor):
        """Scale the focused image by the provided factor and update UI."""
        if self.focus_pixmap and not self.focus_pixmap.isNull():
            self.focus_zoom_factor *= scale_factor
            self.focus_zoom_factor = max(0.1, min(self.focus_zoom_factor, 10.0))
            original_size = self.focus_pixmap.size()
            new_size = original_size * self.focus_zoom_factor
            scaled_pixmap = self.focus_pixmap.scaled(
                new_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.focus_image_label.setPixmap(scaled_pixmap)
            self.focus_image_label.resize(scaled_pixmap.size())
            self.update_focus_info()

    def update_focus_info(self):
        """Refresh the text showing resolution and zoom percentage."""
        if self.focus_pixmap and not self.focus_pixmap.isNull():
            zoom_percentage = self.focus_zoom_factor * 100.0
            info_text = (
                f"Resolution: {self.focus_pixmap.width()}×{self.focus_pixmap.height()} | "
                f"Zoom: {zoom_percentage:.1f}%"
            )
            self.focus_info_label.setText(info_text)
        else:
            self.focus_info_label.setText("No image loaded")

    # ------------------------------------------------------------------
    # Slot to update the focus window with a new image
    def update_focus_window(self, image_path):
        """Load the specified image into the focus window and update tags."""
        self.focus_image_path = image_path
        self.focus_pixmap = QPixmap(image_path)
        if not self.focus_pixmap.isNull():
            # Reset zoom factor when loading a new image
            self.focus_zoom_factor = 1.0
            # Determine available space in the scroll area
            scroll_size = self.focus_image_scroll.size()
            available_width = scroll_size.width() - 20
            available_height = scroll_size.height() - 20
            scaled_pixmap = self.focus_pixmap.scaled(
                available_width,
                available_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.focus_image_label.setPixmap(scaled_pixmap)
            self.focus_image_label.resize(scaled_pixmap.size())
            if self.focus_pixmap.width() > 0 and self.focus_pixmap.height() > 0:
                self.focus_zoom_factor = min(
                    available_width / self.focus_pixmap.width(),
                    available_height / self.focus_pixmap.height(),
                )
        else:
            self.focus_image_label.setText("Failed to load image")
            self.focus_image_label.clear()
        self.update_focus_info()
        # Populate the tags list for this image
        self.focus_tag_list.clear()
        if image_path in self.captions:
            for tag in self.captions[image_path]:
                freq = self.tag_frequency.get(tag, 0)
                item = QListWidgetItem(f"{tag} ({freq})")
                self.focus_tag_list.addItem(item)

    # ------------------------------------------------------------------
    # Tag sorting for focus window
    def sort_tags_high(self):
        """Sort tags in descending order of frequency, then alphabetically."""
        if self.focus_image_path and self.focus_image_path in self.captions:
            tags = self.captions[self.focus_image_path]
            sorted_tags = sorted(tags, key=lambda t: (-self.tag_frequency.get(t, 0), t))
            self.captions[self.focus_image_path] = sorted_tags
            self.save_caption_file(self.focus_image_path)
            self.update_focus_window(self.focus_image_path)

    def sort_tags_low(self):
        """Sort tags in ascending order of frequency, then alphabetically."""
        if self.focus_image_path and self.focus_image_path in self.captions:
            tags = self.captions[self.focus_image_path]
            sorted_tags = sorted(tags, key=lambda t: (self.tag_frequency.get(t, 0), t))
            self.captions[self.focus_image_path] = sorted_tags
            self.save_caption_file(self.focus_image_path)
            self.update_focus_window(self.focus_image_path)

    # ------------------------------------------------------------------
    # Folder tree management
    def toggle_folder_tree(self, checked):
        """Show or hide the folder tree and populate it when shown."""
        if checked:
            self.folder_tree.show()
            self.folder_tree_toggle.setText("Hide Folder Tree")
            self.populate_folder_tree()
        else:
            self.folder_tree.hide()
            self.folder_tree_toggle.setText("Show Folder Tree")

    def populate_folder_tree(self):
        """Populate the tree with the contents of the currently loaded directory."""
        self.folder_tree.clear()
        if not self.image_dir:
            return
        root_item = QTreeWidgetItem(self.folder_tree)
        root_item.setText(0, os.path.basename(self.image_dir))
        root_item.setData(0, Qt.UserRole, self.image_dir)
        if self.include_subdirs_checkbox.isChecked():
            self.add_folder_items(root_item, self.image_dir)
        self.folder_tree.expandAll()

    def add_folder_items(self, parent_item, parent_path):
        """Recursively add subdirectories to the folder tree."""
        try:
            for item in sorted(os.listdir(parent_path)):
                item_path = os.path.join(parent_path, item)
                if os.path.isdir(item_path):
                    folder_item = QTreeWidgetItem(parent_item)
                    folder_item.setText(0, item)
                    folder_item.setData(0, Qt.UserRole, item_path)
                    self.add_folder_items(folder_item, item_path)
        except PermissionError:
            pass

    def open_selected_folder(self):
        """Load images from the folder currently selected in the tree."""
        current_item = self.folder_tree.currentItem()
        if current_item:
            folder_path = current_item.data(0, Qt.UserRole)
            if folder_path:
                self.image_dir = folder_path
                self.load_images(folder_path)

    # ------------------------------------------------------------------
    # Tag filtering controls
    def update_tag_filter(self):
        """Placeholder slot for tag selection changes (unused)."""
        # We intentionally leave this method empty; filtering is executed when
        # the user clicks one of the filter buttons.  However, connecting
        # ``itemSelectionChanged`` allows us to update state in the future
        # without re‑creating the signal connection.
        pass

    def toggle_filter_mode(self, checked):
        """Toggle between inclusive and exclusive filter modes."""
        if checked:
            self.filter_mode = "Exclusive"
            self.filter_mode_toggle.setText("Filter Mode: Exclusive")
        else:
            self.filter_mode = "Inclusive"
            self.filter_mode_toggle.setText("Filter Mode: Inclusive")

    def filter_images(self):
        """Filter the displayed images based on the selected tags."""
        selected_items = self.tag_list.selectedItems()
        if not selected_items:
            return
        selected_tags = []
        for item in selected_items:
            tag_text = item.text()
            tag = tag_text.rsplit(" (", 1)[0]
            selected_tags.append(tag)
        self.filtered_images = []
        for image_path in self.images:
            image_tags = self.captions.get(image_path, [])
            if self.filter_mode == "Inclusive":
                # Any of the selected tags
                if any(tag in image_tags for tag in selected_tags):
                    self.filtered_images.append(image_path)
            else:
                # All of the selected tags must be present
                if all(tag in image_tags for tag in selected_tags):
                    self.filtered_images.append(image_path)
        self.filter_active = True
        self.populate_gallery(self.filtered_images)

    def ignore_tags(self):
        """Filter out images that contain any of the selected tags."""
        selected_items = self.tag_list.selectedItems()
        if not selected_items:
            return
        selected_tags = []
        for item in selected_items:
            tag_text = item.text()
            tag = tag_text.rsplit(" (", 1)[0]
            selected_tags.append(tag)
        self.filtered_images = []
        for image_path in self.images:
            image_tags = self.captions.get(image_path, [])
            if not any(tag in image_tags for tag in selected_tags):
                self.filtered_images.append(image_path)
        self.filter_active = True
        self.populate_gallery(self.filtered_images)

    def clear_filter(self):
        """Clear any active filter and show all images."""
        self.filter_active = False
        self.filtered_images = []
        self.populate_gallery(self.images)

    # ------------------------------------------------------------------
    # File operations: copy and move selections
    def copy_selection(self):
        """Copy the selected images and captions to a new directory."""
        if not self.selected_images:
            QMessageBox.information(self, "Copy Selection", "No images selected.")
            return
        dest_dir = QFileDialog.getExistingDirectory(
            self, "Select Destination Directory for Copy"
        )
        if not dest_dir:
            return
        for image_path in self.selected_images:
            base_name = os.path.basename(image_path)
            dest_image_path = os.path.join(dest_dir, base_name)
            # Avoid overwriting existing files by appending a counter if necessary
            if os.path.exists(dest_image_path):
                root, ext = os.path.splitext(base_name)
                i = 1
                new_name = f"{root}_{i}{ext}"
                while os.path.exists(os.path.join(dest_dir, new_name)):
                    i += 1
                    new_name = f"{root}_{i}{ext}"
                dest_image_path = os.path.join(dest_dir, new_name)
            try:
                shutil.copy2(image_path, dest_image_path)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Copy Error",
                    f"Failed to copy {image_path} to {dest_dir}: {e}",
                )
                continue
            # Copy caption file if present
            caption_src = os.path.splitext(image_path)[0] + ".txt"
            if os.path.exists(caption_src):
                dest_base_root = os.path.splitext(os.path.basename(dest_image_path))[0]
                dest_caption_path = os.path.join(dest_dir, dest_base_root + ".txt")
                try:
                    shutil.copy2(caption_src, dest_caption_path)
                except Exception as e:
                    QMessageBox.warning(
                        self,
                        "Copy Error",
                        f"Failed to copy {caption_src} to {dest_dir}: {e}",
                    )
        QMessageBox.information(
            self,
            "Copy Complete",
            "Selected images and captions have been copied successfully.",
        )

    def move_selection(self):
        """Move the selected images and captions to a new directory."""
        if not self.selected_images:
            QMessageBox.information(self, "Move Selection", "No images selected.")
            return
        dest_dir = QFileDialog.getExistingDirectory(
            self, "Select Destination Directory for Move"
        )
        if not dest_dir:
            return
        images_to_remove = []
        for image_path in list(self.selected_images):
            base_name = os.path.basename(image_path)
            dest_image_path = os.path.join(dest_dir, base_name)
            if os.path.exists(dest_image_path):
                root, ext = os.path.splitext(base_name)
                i = 1
                new_name = f"{root}_{i}{ext}"
                while os.path.exists(os.path.join(dest_dir, new_name)):
                    i += 1
                    new_name = f"{root}_{i}{ext}"
                dest_image_path = os.path.join(dest_dir, new_name)
            try:
                shutil.move(image_path, dest_image_path)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Move Error",
                    f"Failed to move {image_path} to {dest_dir}: {e}",
                )
                continue
            # Move caption file if present
            caption_src = os.path.splitext(image_path)[0] + ".txt"
            if os.path.exists(caption_src):
                dest_base_root = os.path.splitext(os.path.basename(dest_image_path))[0]
                dest_caption_path = os.path.join(dest_dir, dest_base_root + ".txt")
                try:
                    shutil.move(caption_src, dest_caption_path)
                except Exception as e:
                    QMessageBox.warning(
                        self,
                        "Move Error",
                        f"Failed to move {caption_src} to {dest_dir}: {e}",
                    )
            images_to_remove.append(image_path)
        # Remove moved images from internal state
        for image_path in images_to_remove:
            if image_path in self.images:
                self.images.remove(image_path)
            # Remove tags associated with this image
            if image_path in self.captions:
                tags = self.captions.pop(image_path)
                for tag in tags:
                    if self.tag_frequency[tag] > 0:
                        self.tag_frequency[tag] -= 1
                        if self.tag_frequency[tag] == 0:
                            del self.tag_frequency[tag]
        # Recompute all_tags based on remaining images
        self.all_tags = set(self.tag_frequency.keys())
        # Clear selection and refresh UI
        self.selected_images.clear()
        self.update_selected_counter()
        self.update_tag_list()
        # Reset filter state and repopulate gallery
        self.filter_active = False
        self.filtered_images = []
        self.populate_gallery(self.images)
        QMessageBox.information(
            self,
            "Move Complete",
            "Selected images and captions have been moved successfully.",
        )

    # ------------------------------------------------------------------
    # Directory loading
    def open_directory(self):
        """Prompt the user for a directory and load images from it."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory")
        if dir_path:
            self.image_dir = dir_path
            self.load_images(dir_path)

    def load_images(self, dir_path):
        """Reset state and start a worker to load images from disk."""
        self.images = []
        self.captions = {}
        self.selected_images.clear()
        self.all_tags.clear()
        self.tag_frequency.clear()
        self.update_selected_counter()
        # Start background thread
        worker = Worker(self.load_images_thread, dir_path)
        worker.signals.result.connect(self.populate_gallery)
        self.threadpool.start(worker)

    def load_images_thread(self, dir_path):
        """Worker function to walk the directory and collect image and caption data."""
        image_extensions = (".png", ".jpg", ".jpeg", ".bmp", ".gif")
        loaded_images = []
        for root, dirs, files in os.walk(dir_path):
            for file in files:
                if file.lower().endswith(image_extensions):
                    image_path = os.path.join(root, file)
                    loaded_images.append(image_path)
                    caption_path = os.path.splitext(image_path)[0] + ".txt"
                    if os.path.exists(caption_path):
                        with open(caption_path, "r", encoding="utf-8", errors="ignore") as f:
                            tags = [tag.strip() for tag in f.read().split(",") if tag.strip()]
                        self.captions[image_path] = tags
                        for tag in tags:
                            self.all_tags.add(tag)
                            self.tag_frequency[tag] += 1
                    else:
                        self.captions[image_path] = []
        self.images = loaded_images
        return loaded_images

    # ------------------------------------------------------------------
    # Gallery management
    def clear_layout(self, layout):
        """Recursively remove all widgets and layouts from the given layout."""
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            else:
                child_layout = item.layout()
                if child_layout is not None:
                    self.clear_layout(child_layout)
        # Spacers are ignored

    def populate_gallery(self, images):
        """Populate the gallery scroll area with thumbnails for the given images."""
        # Clear existing thumbnails
        self.clear_layout(self.scroll_area_layout)
        # Update tag list based on all tags
        self.update_tag_list()
        if not images:
            return
        # Determine width available for each thumbnail
        scroll_area_width = self.scroll_area.viewport().width()
        if self.scroll_area.verticalScrollBar().isVisible():
            scroll_area_width -= self.scroll_area.verticalScrollBar().width()
        image_width = (
            int(scroll_area_width / self.images_per_row)
            if self.images_per_row > 0
            else scroll_area_width
        )
        row_layout = QHBoxLayout()
        for idx, image_path in enumerate(images):
            pixmap = QPixmap(image_path).scaled(
                image_width,
                image_width,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            image_label = QLabel()
            image_label.setPixmap(pixmap)
            image_label.setAlignment(Qt.AlignCenter)
            # Set border based on selection state
            if image_path in self.selected_images:
                image_label.setStyleSheet("border: 2px solid #00BFFF;")
            else:
                image_label.setStyleSheet("border: 2px solid transparent;")
            # Capture image_path and label in a lambda for the click handler
            image_label.mousePressEvent = (
                lambda event, path=image_path, label=image_label: self.image_clicked(
                    event, path, label
                )
            )
            row_layout.addWidget(image_label)
            if (idx + 1) % self.images_per_row == 0:
                self.scroll_area_layout.addLayout(row_layout)
                row_layout = QHBoxLayout()
        if row_layout.count() > 0:
            self.scroll_area_layout.addLayout(row_layout)

    def update_gallery(self):
        """Repopulate the gallery based on current filter state."""
        if self.filter_active:
            self.populate_gallery(self.filtered_images)
        else:
            self.populate_gallery(self.images)

    def change_images_per_row(self, delta):
        """Increase or decrease the number of thumbnails per row."""
        new_value = self.images_per_row + delta
        if new_value >= 1:
            self.images_per_row = new_value
            self.images_per_row_label.setText(str(self.images_per_row))
            self.update_gallery()

    def image_clicked(self, event, image_path, image_label):
        """Handle selection/deselection of an image thumbnail."""
        if image_path in self.selected_images:
            self.selected_images.remove(image_path)
            image_label.setStyleSheet("border: 2px solid transparent;")
        else:
            self.selected_images.add(image_path)
            image_label.setStyleSheet("border: 2px solid #00BFFF;")
        self.update_selected_counter()
        self.update_focus_window(image_path)

    def update_selected_counter(self):
        """Update the selected image count displayed in the toolbar."""
        self.selected_count_label.setText(str(len(self.selected_images)))

    def select_all_images(self):
        """Select all images currently displayed."""
        if self.filter_active:
            self.selected_images = set(self.filtered_images)
        else:
            self.selected_images = set(self.images)
        self.update_gallery_selection_styles()
        self.update_selected_counter()

    def deselect_all_images(self):
        """Deselect all currently selected images."""
        self.selected_images.clear()
        self.update_gallery_selection_styles()
        self.update_selected_counter()

    def invert_selection(self):
        """Invert the current selection (select unselected, deselect selected)."""
        if self.filter_active:
            current_set = set(self.filtered_images)
        else:
            current_set = set(self.images)
        self.selected_images = current_set.symmetric_difference(self.selected_images)
        self.update_gallery_selection_styles()
        self.update_selected_counter()

    def update_gallery_selection_styles(self):
        """Refresh the thumbnail borders to reflect selection state."""
        # Simple approach: repopulate the gallery based on filter state
        self.update_gallery()

    # ------------------------------------------------------------------
    # Tag editing
    def add_tag_to_selected(self):
        """Add a new tag to each selected image."""
        new_tag = self.add_tag_input.text().strip()
        if new_tag and self.selected_images:
            for image_path in self.selected_images:
                if new_tag not in self.captions.get(image_path, []):
                    self.captions.setdefault(image_path, []).append(new_tag)
                    self.tag_frequency[new_tag] += 1
                    self.all_tags.add(new_tag)
                    # Persist changes to disk
                    self.save_caption_file(image_path)
            self.add_tag_input.clear()
            # Update UI
            self.update_focus_window(next(iter(self.selected_images)))
            self.update_tag_list()

    def remove_tag_from_selected(self):
        """Remove a tag from each selected image."""
        tag_to_remove = self.remove_tag_input.text().strip()
        if tag_to_remove and self.selected_images:
            for image_path in self.selected_images:
                if tag_to_remove in self.captions.get(image_path, []):
                    self.captions[image_path].remove(tag_to_remove)
                    if self.tag_frequency[tag_to_remove] > 0:
                        self.tag_frequency[tag_to_remove] -= 1
                        if self.tag_frequency[tag_to_remove] == 0:
                            del self.tag_frequency[tag_to_remove]
                            self.all_tags.discard(tag_to_remove)
                    # Persist change
                    self.save_caption_file(image_path)
            self.remove_tag_input.clear()
            # Refresh UI
            self.update_focus_window(next(iter(self.selected_images)))
            self.update_tag_list()

    def update_tag_list(self):
        """Rebuild the global tag list widget."""
        self.tag_list.clear()
        for tag in sorted(self.all_tags):
            item = QListWidgetItem(f"{tag} ({self.tag_frequency[tag]})")
            self.tag_list.addItem(item)

    # ------------------------------------------------------------------
    # Keyboard navigation in focus window
    def keyPressEvent(self, event):
        """Intercept left/right arrow keys to navigate images."""
        if event.key() == Qt.Key_Left:
            self.navigate_focus_image(-1)
        elif event.key() == Qt.Key_Right:
            self.navigate_focus_image(1)
        else:
            super().keyPressEvent(event)

    def navigate_focus_image(self, direction):
        """Advance or regress the focus image within the current selection."""
        nav_list = (
            sorted(list(self.selected_images)) if self.selected_images else self.images
        )
        if not nav_list:
            return
        try:
            current_index = nav_list.index(self.focus_image_path)
            next_index = (current_index + direction) % len(nav_list)
        except (ValueError, TypeError):
            next_index = 0 if direction >= 0 else -1
        self.update_focus_window(nav_list[next_index])

    # ------------------------------------------------------------------
    # Caption file persistence
    def save_caption_file(self, image_path):
        """Write the tags for an image back to its companion caption file."""
        tags = self.captions.get(image_path, [])
        caption_path = os.path.splitext(image_path)[0] + ".txt"
        try:
            with open(caption_path, "w", encoding="utf-8") as f:
                f.write(", ".join(tags))
        except Exception as e:
            # Persisting errors are non‑fatal; print to stderr for debugging
            print(f"Failed to save caption file {caption_path}: {e}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Data analytics placeholder
    def create_data_analytics_placeholder(self):
        """Create a minimal analytics window to avoid crashes when invoked."""
        self.data_analytics_window = QWidget()
        self.data_analytics_window.setWindowTitle("Data Analytics")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Data Analytics placeholder"))
        self.data_analytics_window.setLayout(layout)

    def open_data_analytics(self):
        """Display the data analytics placeholder window."""
        self.data_analytics_window.show()


# -----------------------------------------------------------------------------
# Entry point
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DatCureApp()
    window.show()
    sys.exit(app.exec_())
