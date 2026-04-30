import sys

from PyQt5 import QtWidgets, QtGui

class SystemTrayIcon(QtWidgets.QSystemTrayIcon):
    def __init__(self, icon, parent=None):
        QtWidgets.QSystemTrayIcon.__init__(self, icon, parent)
        menu = QtWidgets.QMenu(parent)
        exit_action = menu.addAction("Exit")
        exit_action.triggered.connect(QtWidgets.qApp.quit)
        self.setContextMenu(menu)

def main(image):
    app = QtWidgets.QApplication([])
    w = QtWidgets.QWidget()
    tray_icon = SystemTrayIcon(QtGui.QIcon(image), w)
    tray_icon.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main('./assets/sync.png')
