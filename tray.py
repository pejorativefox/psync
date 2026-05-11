import sys
from PySide6 import QtWidgets, QtGui

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MainWindow")
        self.setCentralWidget(QtWidgets.QLabel("MainWindow"))

    def closeEvent(self, event):
        event.ignore()
        self.hide()

class SystemTrayIcon(QtWidgets.QSystemTrayIcon):
    def __init__(self, icon, parent=None):
        QtWidgets.QSystemTrayIcon.__init__(self, icon, parent)
        menu = QtWidgets.QMenu(parent)
        show_action = menu.addAction("Show Window")
        show_action.triggered.connect(parent.show)
        exit_action = menu.addAction("Exit")
        exit_action.triggered.connect(QtWidgets.QApplication.instance().quit)
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
