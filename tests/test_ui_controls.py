import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtGui, QtWidgets

from tv_scan_studio.ui_controls import DecisionChoice, DisclosureButton, SwitchToggle


def test_switch_keeps_checkbox_state_and_keyboard_access():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    toggle = SwitchToggle("Gün içi sınır")
    toggle.show()
    toggle.setFocus()
    application.processEvents()
    assert toggle.sizeHint().height() >= 32
    assert not toggle.grab().isNull()
    QtWidgets.QApplication.sendEvent(toggle, QtGui.QKeyEvent(
        QtCore.QEvent.KeyPress, QtCore.Qt.Key_Space, QtCore.Qt.NoModifier))
    QtWidgets.QApplication.sendEvent(toggle, QtGui.QKeyEvent(
        QtCore.QEvent.KeyRelease, QtCore.Qt.Key_Space, QtCore.Qt.NoModifier))
    assert toggle.isChecked()
    toggle.close()


def test_disclosure_keeps_button_signal_and_paints_both_states():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    button = DisclosureButton("Test koşulları")
    changes = []
    button.toggled.connect(changes.append)
    button.show()
    application.processEvents()
    assert not button.grab().isNull()
    button.click()
    assert changes == [True]
    assert not button.grab().isNull()
    button.close()


def test_scan_decision_keeps_combobox_choices_and_paints_each_state():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    choice = DecisionChoice()
    choice.addItems(["Sabit bırak", "Tara", "Hariç tut"])
    choice.show()
    application.processEvents()
    for label in ("Sabit bırak", "Tara", "Hariç tut"):
        choice.setCurrentText(label)
        assert choice.currentText() == label
        assert not choice.grab().isNull()
    choice.close()
