import sys
import os
import signal
import logging
import subprocess
from datetime import datetime

from PySide6 import QtWidgets, QtGui, QtCore

from database import init_db
from watch import watch, stop_watching
from sync import sync as run_psync
from client import ServerClient

def xdg_open(target):
    if sys.platform.startswith("win"):
        os.startfile(target) # pyright: ignore[reportAttributeAccessIssue]
    elif sys.platform == "darwin":
        subprocess.run(["open", target], check=False)
    else:
        subprocess.run(["xdg-open", target], check=False)

def get_asset_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    # PyInstaller extracts assets to a temporary folder stored in sys._MEIPASS
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

class ConfigWizard(QtWidgets.QDialog):
    """Dialog to configure initial Psync settings."""
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Psync Configuration Wizard")
        self.setMinimumWidth(450)
        
        layout = QtWidgets.QFormLayout(self)
        
        self.path_edit = QtWidgets.QLineEdit(config.base_path)
        self.browse_btn = QtWidgets.QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.on_browse)
        
        path_layout = QtWidgets.QHBoxLayout()
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.browse_btn)
        layout.addRow("Local Sync Folder:", path_layout)
        
        self.host_edit = QtWidgets.QLineEdit(config.server_hostname)
        layout.addRow("Server Hostname:", self.host_edit)
        
        self.port_edit = QtWidgets.QLineEdit(str(config.server_port))
        self.port_edit.setValidator(QtGui.QIntValidator(1, 65535))
        layout.addRow("Server Port:", self.port_edit)

        self.interval_edit = QtWidgets.QLineEdit(str(config.remote_sync_interval))
        self.interval_edit.setValidator(QtGui.QIntValidator(5, 86400))
        layout.addRow("Sync Interval (sec):", self.interval_edit)

        self.ignore_edit = QtWidgets.QPlainTextEdit("\n".join(config.ignore_patterns))
        self.ignore_edit.setMaximumHeight(80)
        layout.addRow("Ignore Patterns (line-separated):", self.ignore_edit)

        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save | 
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.on_save)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)

    def on_browse(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Sync Directory", self.path_edit.text())
        if directory:
            self.path_edit.setText(directory)

    def on_save(self):
        path = self.path_edit.text().strip()
        if not path or not os.path.isdir(path):
            QtWidgets.QMessageBox.warning(self, "Invalid Path", "Please select a valid local directory.")
            return

        ignore_patterns = [p.strip() for p in self.ignore_edit.toPlainText().splitlines() if p.strip()]
        self.config.save_settings(
            path, 
            self.host_edit.text().strip(), 
            self.port_edit.text().strip(),
            self.interval_edit.text().strip(),
            ignore_patterns
        )
        self.accept()

class SyncWorkerThread(QtCore.QThread):
    """Background thread to run the full synchronization logic."""
    finished = QtCore.Signal()
    error = QtCore.Signal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        try:
            run_psync(self.config)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

class FileRefreshThread(QtCore.QThread):
    """Background thread to handle the network request for file listing."""
    finished = QtCore.Signal(list)
    error = QtCore.Signal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        try:
            client = ServerClient(self.config)
            self.finished.emit(client.get_server_files())
        except Exception as e:
            self.error.emit(str(e))

class WatchThread(QtCore.QThread):
    """Background thread to run the file system observer (watch)."""
    def __init__(self, config):
        super().__init__()
        self.config = config

    def stop(self):
        stop_watching()
        self.wait()

    def run(self):
        # This will perform an initial sync and then enter the watchdog loop
        watch(self.config)

class QtLogHandler(logging.Handler, QtCore.QObject):
    """Custom logging handler that emits a Qt signal for every log record."""
    log_signal = QtCore.Signal(str)

    def __init__(self):
        logging.Handler.__init__(self)
        QtCore.QObject.__init__(self)

    def emit(self, record):
        self.log_signal.emit(self.format(record))

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle("Psync - Tracked Files")

        # Set window height to 80% of the available screen height
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.resize(600, int(screen.height() * 0.8))
        
        # Set up menu bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        settings_action = file_menu.addAction("&Settings...")
        settings_action.triggered.connect(self.open_config_wizard)
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(QtWidgets.QApplication.instance().quit) # pyright: ignore[reportOptionalMemberAccess]

        # Set up the central layout
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)

        # Fuzzy finder search box and clear button
        search_layout = QtWidgets.QHBoxLayout()
        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText("Fuzzy find files...")
        self.search_box.textChanged.connect(self.filter_file_list)

        self.show_deleted_cb = QtWidgets.QCheckBox("Show Deleted")
        self.show_deleted_cb.setChecked(False)
        self.show_deleted_cb.stateChanged.connect(self.filter_file_list)

        self.clear_button = QtWidgets.QPushButton("Clear")
        self.clear_button.clicked.connect(self.search_box.clear)

        self.sync_button = QtWidgets.QPushButton("Sync")
        self.sync_button.clicked.connect(self.start_sync)

        search_layout.addWidget(self.search_box)
        search_layout.addWidget(self.show_deleted_cb)
        search_layout.addWidget(self.clear_button)
        layout.addLayout(search_layout)

        # File list widget
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.show_revisions)
        layout.addWidget(self.list_widget)

        # Activity Log Viewer
        layout.addWidget(QtWidgets.QLabel("Activity Log:"))
        self.log_viewer = QtWidgets.QPlainTextEdit()
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setMaximumHeight(100)
        layout.addWidget(self.log_viewer)

        # Revisions button at the bottom
        self.revisions_button = QtWidgets.QPushButton("Revisions")
        self.revisions_button.clicked.connect(self.on_revisions_clicked)
        
        bottom_buttons = QtWidgets.QHBoxLayout()
        bottom_buttons.addWidget(self.sync_button)
        bottom_buttons.addWidget(self.revisions_button)
        layout.addLayout(bottom_buttons)

        # Initialize the status bar
        self.statusBar().showMessage("Ready")
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate mode
        self.progress_bar.setMaximumWidth(150)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        self.statusBar().addPermanentWidget(self.progress_bar)

        # Initialize the server client
        self.client = ServerClient(self.config)

        # Set up the background refresh thread
        self.refresh_thread = FileRefreshThread(self.config)
        self.refresh_thread.finished.connect(self.on_refresh_finished)
        self.refresh_thread.error.connect(self.on_refresh_error)

        # Set up the background sync thread
        self.sync_worker = SyncWorkerThread(self.config)
        self.sync_worker.finished.connect(self.on_sync_finished)
        self.sync_worker.error.connect(self.on_sync_error)

        self.setCentralWidget(container)
        
        # Delay check to allow UI to render
        QtCore.QTimer.singleShot(0, self.initial_setup_check)

    def initial_setup_check(self):
        """Checks if the configuration is valid; shows wizard if not."""
        if self.check_config():
            self.refresh_file_list()

    def check_config(self):
        """
        Validates the current configuration. 
        Returns True if valid, or shows Wizard. Returns False if user cancels.
        """
        if self.config.is_new or not os.path.isdir(self.config.base_path):
            wizard = ConfigWizard(self.config, self)
            if wizard.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                # Successfully configured, notify app to start watching
                q_app = QtWidgets.QApplication.instance()
                if hasattr(q_app, 'start_watching'):
                    q_app.start_watching() # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
                return True
            else:
                # User aborted setup
                QtWidgets.QApplication.instance().quit() # pyright: ignore[reportOptionalMemberAccess]
                return False
        return True

    def open_config_wizard(self):
        """Opens the configuration wizard manually."""
        wizard = ConfigWizard(self.config, self)
        if wizard.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            # Re-initialize the client with new config details
            self.client = ServerClient(self.config)
            # Notify app to start/update watching
            q_app = QtWidgets.QApplication.instance()
            if hasattr(q_app, 'start_watching'):
                q_app.start_watching() # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]
            self.refresh_file_list()

    def start_sync(self):
        """Starts the full synchronization process."""
        if self.sync_worker.isRunning() or self.refresh_thread.isRunning():
            return

        self.statusBar().showMessage("Synchronizing...")
        self.progress_bar.show()
        self.sync_button.setEnabled(False)
        self.sync_worker.start()

    def on_sync_finished(self):
        """Called when manual sync completes; triggers file list refresh."""
        self.refresh_file_list()

    def on_sync_error(self, error_message):
        self.statusBar().showMessage(f"Sync Error: {error_message}")
        self.progress_bar.hide()
        self.sync_button.setEnabled(True)

    def refresh_file_list(self):
        """Starts the background thread to query the server."""
        if self.refresh_thread.isRunning():
            return

        self.statusBar().showMessage("Refreshing file list...")
        self.progress_bar.show()
        self.sync_button.setEnabled(False)
        self.refresh_thread.start()

    def on_refresh_finished(self, files_data):
        """Updates the UI once the background thread finishes successfully."""
        self.list_widget.clear()
        for entry in files_data:
            display_name = entry.get("f", "Unknown")
            if entry.get("d"):
                display_name += " (Deleted)"
            item = QtWidgets.QListWidgetItem(display_name)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, entry.get("f"))
            item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, entry.get("d", False))
            self.list_widget.addItem(item)

        # Re-apply filter if text was already present during refresh
        self.filter_file_list(self.search_box.text())

        # Update the status bar with the current time
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.statusBar().showMessage(f"Last updated: {now}")
        self.progress_bar.hide()
        self.sync_button.setEnabled(True)

    def on_refresh_error(self, error_message):
        """Handles errors reported by the background thread."""
        self.list_widget.clear()
        self.list_widget.addItem(f"Error connecting to server: {error_message}")
        self.progress_bar.hide()
        self.sync_button.setEnabled(True)

    def filter_file_list(self, _=None):
        """Filters the file list based on search text and deleted status."""
        search_term = self.search_box.text().lower()
        show_deleted = self.show_deleted_cb.isChecked()

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            is_deleted = bool(item.data(QtCore.Qt.ItemDataRole.UserRole + 1))

            matches_search = search_term in item.text().lower()
            visible_status = show_deleted or not is_deleted

            item.setHidden(not (matches_search and visible_status))

    @QtCore.Slot(str)
    def append_log(self, message):
        """Appends a log message to the log viewer."""
        self.log_viewer.appendPlainText(message)

    def on_revisions_clicked(self):
        """Handler for the Revisions button."""
        item = self.list_widget.currentItem()
        if item:
            self.show_revisions(item)
        else:
            QtWidgets.QMessageBox.information(self, "Selection Required", "Please select a file from the list first.")

    def show_revisions(self, item):
        """Fetches and displays the revision history for a double-clicked file."""
        rel_path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        
        try:
            revisions = self.client.get_revisions(rel_path)

            # Create a popup dialog
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle(f"Revision History: {rel_path}")
            dialog.resize(500, 350)
            
            layout = QtWidgets.QVBoxLayout(dialog)
            
            # Use QTreeWidget for a structured view with sortable and adjustable columns
            tree = QtWidgets.QTreeWidget()
            tree.setColumnCount(3)
            tree.setHeaderLabels(["Hash", "Timestamp", "Size"])
            tree.setSortingEnabled(True)
            
            for rev in revisions:
                # Clean up timestamp for display (e.g., 2023-10-27 10:30:00)
                ts = rev.get("created_at", "").replace("T", " ")[:19]
                size_kb = rev.get("size", 0) / 1024
                
                tree_item = QtWidgets.QTreeWidgetItem([
                    rev.get('full_hash', 'N/A'),
                    ts,
                    f"{size_kb:.2f} KB"
                ])
                tree_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, rev.get('full_hash'))
                tree.addTopLevelItem(tree_item)
            
            # Auto-adjust columns to content initially
            for i in range(3):
                tree.resizeColumnToContents(i)
                
            layout.addWidget(tree)

            # Add download button
            download_btn = QtWidgets.QPushButton("Download Selected Revision")
            layout.addWidget(download_btn)

            def handle_download():
                selected = tree.currentItem()
                if not selected:
                    QtWidgets.QMessageBox.warning(dialog, "Selection Required", "Please select a revision to download.")
                    return
                
                full_hash = selected.data(0, QtCore.Qt.ItemDataRole.UserRole)
                default_name = os.path.basename(rel_path)
                
                save_path, _ = QtWidgets.QFileDialog.getSaveFileName(dialog, "Save Revision As", default_name)
                if not save_path:
                    return

                try:
                    self.client.download_file(full_hash, save_path)
                    msg_box = QtWidgets.QMessageBox(dialog)
                    msg_box.setWindowTitle("Success")
                    msg_box.setText(f"Revision saved to:\n{save_path}")
                    msg_box.setIcon(QtWidgets.QMessageBox.Icon.Information)
                    open_btn = msg_box.addButton("Open", QtWidgets.QMessageBox.ButtonRole.ActionRole)
                    msg_box.addButton(QtWidgets.QMessageBox.StandardButton.Ok)
                    msg_box.exec()
                    if msg_box.clickedButton() == open_btn:
                        xdg_open(save_path)
                except Exception as ex:
                    QtWidgets.QMessageBox.critical(dialog, "Download Error", f"Failed to download revision:\n{ex}")

            download_btn.clicked.connect(handle_download)
            dialog.exec()

        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Server Error", f"Could not fetch revisions for {rel_path}:\n{e}")

    def closeEvent(self, event):
        event.ignore()
        self.hide()
    
    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.Type.ActivationChange and self.isActiveWindow():
            # Window gained focus, refresh the file list
            self.refresh_file_list()

class SystemTrayIcon(QtWidgets.QSystemTrayIcon):
    def __init__(self, icon, parent=None):
        QtWidgets.QSystemTrayIcon.__init__(self, icon, parent)
        menu = QtWidgets.QMenu(parent)
        exit_action = menu.addAction("E&xit")
        exit_action.triggered.connect(QtWidgets.QApplication.instance().quit) # pyright: ignore[reportOptionalMemberAccess]
        self.setContextMenu(menu)

class PsyncApp(QtWidgets.QApplication):
    def __init__(self, args, icon_path, config):
        super().__init__(args)
        self.config = config
        self.setQuitOnLastWindowClosed(False)
        
        # Set the application icon
        self.setWindowIcon(QtGui.QIcon(icon_path))
        
        self.window = MainWindow(config)

        # Configure global logging to pipe into the UI
        self.log_handler = QtLogHandler()
        self.log_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', '%H:%M:%S'))
        self.log_handler.log_signal.connect(self.window.append_log)
        logging.getLogger().addHandler(self.log_handler)

        self.tray_icon = SystemTrayIcon(QtGui.QIcon(icon_path))

        # Start the background file watcher
        self.watch_thread = None
        self._last_started_path = None
        if not config.is_new and os.path.isdir(config.base_path):
            self.start_watching()

        self.aboutToQuit.connect(self.on_quit)

        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def start_watching(self):
        new_path = self.config.base_path
        
        if self.watch_thread and self._last_started_path != new_path:
            logging.info(f"Restarting watch thread: path changed from {self._last_started_path} to {new_path}")
            self.watch_thread.stop()
            self.watch_thread = None

        if not self.watch_thread and os.path.isdir(new_path):
            self._last_started_path = new_path
            self.watch_thread = WatchThread(self.config)
            self.watch_thread.start()

    def on_quit(self):
        if self.watch_thread:
            self.watch_thread.stop()

    def on_tray_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
            if self.window.isVisible():
                self.window.hide()
            else:
                self.window.show()
                self.window.activateWindow()

def main(config, image=None):
    if image is None:
        image = get_asset_path('assets/idle.png')
    # Allow the application to be terminated with Ctrl+C in the terminal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    init_db()
    app = PsyncApp(sys.argv, image, config)
    sys.exit(app.exec())

if __name__ == '__main__':
    from config import Config
    main(Config())
