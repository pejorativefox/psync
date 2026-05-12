import sys
import requests
from PySide6 import QtWidgets, QtGui
from config import SETTINGS

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Psync - Tracked Files")
        self.resize(600, 400)
        
        # Set up menu bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(QtWidgets.QApplication.instance().quit) # pyright: ignore[reportOptionalMemberAccess]

        # Set up the central layout
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)

        # Fuzzy finder search box
        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText("Fuzzy find files...")
        self.search_box.textChanged.connect(self.filter_file_list)
        layout.addWidget(self.search_box)

        # File list widget
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.show_revisions)
        layout.addWidget(self.list_widget)

        # Revisions button at the bottom
        self.revisions_button = QtWidgets.QPushButton("Revisions")
        self.revisions_button.clicked.connect(self.on_revisions_clicked)
        layout.addWidget(self.revisions_button)

        self.setCentralWidget(container)
        
        self.refresh_file_list()

    def refresh_file_list(self):
        """Queries the server for the canonical list of files and populates the view."""
        server_host = SETTINGS.get("core", {}).get("server_hostname", "127.0.0.1")
        server_port = SETTINGS.get("core", {}).get("server_port", 8000)
        url = f"http://{server_host}:{server_port}/files"

        try:
            # Fetch the JSON dump of all tracked files from the server
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            files_data = response.json()

            self.list_widget.clear()
            for entry in files_data:
                display_name = entry.get("f", "Unknown")
                if entry.get("d"):
                    display_name += " (Deleted)"
                self.list_widget.addItem(display_name)

            # Re-apply filter if text was already present during refresh
            self.filter_file_list(self.search_box.text())
        except Exception as e:
            self.list_widget.clear()
            self.list_widget.addItem(f"Error connecting to server: {e}")

    def filter_file_list(self, text):
        """Filters the file list based on search text (case-insensitive)."""
        search_term = text.lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            # Narrow down the list by hiding items that don't match the substring
            item.setHidden(search_term not in item.text().lower())

    def on_revisions_clicked(self):
        """Handler for the Revisions button."""
        item = self.list_widget.currentItem()
        if item:
            self.show_revisions(item)
        else:
            QtWidgets.QMessageBox.information(self, "Selection Required", "Please select a file from the list first.")

    def show_revisions(self, item):
        """Fetches and displays the revision history for a double-clicked file."""
        # Extract the relative path by stripping the status suffix
        rel_path = item.text().split(" (")[0]
        
        server_host = SETTINGS.get("core", {}).get("server_hostname", "127.0.0.1")
        server_port = SETTINGS.get("core", {}).get("server_port", 8000)
        url = f"http://{server_host}:{server_port}/revisions/{rel_path}"

        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            revisions = response.json()

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
                    rev.get('short_hash', 'N/A'),
                    ts,
                    f"{size_kb:.2f} KB"
                ])
                tree.addTopLevelItem(tree_item)
            
            # Auto-adjust columns to content initially
            for i in range(3):
                tree.resizeColumnToContents(i)
                
            layout.addWidget(tree)
            dialog.exec()

        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Server Error", f"Could not fetch revisions for {rel_path}:\n{e}")

    def closeEvent(self, event):
        event.ignore()
        self.hide()

class SystemTrayIcon(QtWidgets.QSystemTrayIcon):
    def __init__(self, icon, parent=None):
        QtWidgets.QSystemTrayIcon.__init__(self, icon, parent)
        menu = QtWidgets.QMenu(parent)
        exit_action = menu.addAction("Exit")
        exit_action.triggered.connect(QtWidgets.QApplication.instance().quit) # pyright: ignore[reportOptionalMemberAccess]
        self.setContextMenu(menu)

class PsyncApp(QtWidgets.QApplication):
    def __init__(self, args, icon_path):
        super().__init__(args)
        self.setQuitOnLastWindowClosed(False)
        
        self.window = MainWindow()
        self.tray_icon = SystemTrayIcon(QtGui.QIcon(icon_path))
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
            if self.window.isVisible():
                self.window.hide()
            else:
                self.window.show()
                self.window.activateWindow()

def main(image):
    app = PsyncApp(sys.argv, image)
    sys.exit(app.exec())

if __name__ == '__main__':
    main('assets/idle.png')
