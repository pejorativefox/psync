from PySide6 import QtWidgets, QtGui

class SystemTrayIcon(QtWidgets.QSystemTrayIcon):
    def __init__(self, icon, parent=None):
        QtWidgets.QSystemTrayIcon.__init__(self, icon, parent)
        menu = QtWidgets.QMenu(parent)
        exit_action = menu.addAction("Exit")
        exit_action.triggered.connect(QtWidgets.QApplication.instance().quit)
        self.setContextMenu(menu)

def main(image):
    app = QtWidgets.QApplication([])
    tray_icon = SystemTrayIcon(QtGui.QIcon(image))
    tray_icon.show()
    app.exec_()

if __name__ == '__main__':
    main('assets/idle.png')
