"""Shared recorder and editor Qt styles."""
STYLE = """
QWidget { background:#111822; color:#e8edf5; font-family:"Noto Sans CJK SC","Ubuntu",sans-serif; font-size:14px; }
QFrame#card { background:#192331; border:1px solid #2c3a4b; border-radius:14px; }
QFrame#card QLabel, QFrame#card QCheckBox, QWidget#inlineRow { background:transparent; }
QLabel#title { font-size:28px; font-weight:700; }
QLabel#subtitle, QLabel#muted { color:#97a7bb; }
QLabel#section { font-size:16px; font-weight:600; }
QLabel#badge { color:#8ed9c1; background:#173730; border:1px solid #2b5349; border-radius:9px; padding:7px 12px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background:#0f1722; border:1px solid #34455a; border-radius:7px; padding:8px 10px; min-height:20px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color:#8aa8ce; }
QComboBox QAbstractItemView { background:#1e2b3c; selection-background-color:#3c536f; }
QComboBox::drop-down { border:0; width:25px; }
QComboBox::down-arrow { image:url(__CHEVRON__); width:12px; height:8px; }
QPushButton { background:#273749; border:1px solid #40536b; border-radius:8px; padding:9px 15px; }
QPushButton:hover { background:#344961; }
QPushButton:disabled { color:#68788c; background:#202c3a; border-color:#2d3b4c; }
QPushButton#record { background:#f1665c; color:#fff; border:0; font-weight:700; font-size:16px; padding:13px 26px; }
QPushButton#record:hover { background:#ff7b71; }
QPushButton#record:disabled { background:#6d4544; color:#d4c0be; }
QPushButton#stop { color:#ffb1aa; border-color:#774841; font-weight:600; }
QCheckBox { spacing:8px; }
QCheckBox::indicator { width:18px; height:18px; border:1px solid #526981; border-radius:4px; background:#101924; }
QCheckBox::indicator:checked { background:#7bbda8; border:3px solid #17352d; }
QLabel#timer { font-size:26px; font-family:"DejaVu Sans Mono",monospace; font-weight:600; }
QTextEdit { background:#0c121a; border:1px solid #2b3b4d; border-radius:8px; font-size:12px; font-family:monospace; }
QScrollArea { border:0; }
QToolTip { background:#293d54; color:#fff; border:1px solid #526981; padding:5px; }
"""

EXTRA_STYLE='''
QPushButton#export { background:#7ac7ae; color:#10241c; border:0; padding:12px 20px; font-weight:700; }
QPushButton#export:hover { background:#94dfc7; }
QPushButton#export:disabled { background:#324d45; color:#819e92; }
QListWidget { background:#101924; border:1px solid #314155; border-radius:6px; padding:4px; }
QListWidget::item:selected { background:#344d65; }
QProgressBar { background:#101924; border:1px solid #314155; border-radius:6px; text-align:center; height:18px; }
QProgressBar::chunk { background:#65bda0; border-radius:5px; }
QSplitter::handle { background:#34465b; width:5px; }
'''
