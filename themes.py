"""主题样式表"""

DARK_THEME = """
* { font-family: 'Segoe UI', 'Microsoft YaHei UI', sans-serif; }
QMainWindow, QWidget { background-color: #0f0f0f; color: #e0e0e0; }
QFrame#header { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #1a1a2e, stop:1 #16213e); border-bottom: 2px solid #0f3460; }
QLabel#headerTitle { font-size: 20px; font-weight: bold; color: #e94560; }
QLabel#headerSub { font-size: 11px; color: #5c6370; }
QFrame#sidebar { background-color: #141414; border-right: 1px solid #2a2a2a; }
QPushButton#navBtn { background: transparent; color: #8b949e; border: none; border-radius: 8px; padding: 12px 16px; text-align: left; font-size: 13px; font-weight: 600; }
QPushButton#navBtn:hover { background-color: #1e1e1e; color: #e0e0e0; }
QPushButton#navBtn:checked { background-color: #1a1a2e; color: #e94560; border-left: 3px solid #e94560; }
QLineEdit { background-color: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 10px 14px; color: #e0e0e0; font-size: 14px; }
QLineEdit:focus { border-color: #e94560; }
QComboBox { background-color: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 8px 12px; color: #e0e0e0; min-width: 140px; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox QAbstractItemView { background-color: #1a1a1a; border: 1px solid #2a2a2a; selection-background-color: #1a1a2e; }
QSpinBox { background-color: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 6px; padding: 6px; color: #e0e0e0; }
QPushButton#primaryBtn { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #e94560, stop:1 #c73659); color: white; border: none; border-radius: 8px; padding: 10px 24px; font-weight: bold; font-size: 13px; }
QPushButton#primaryBtn:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #f05672, stop:1 #d4476a); }
QPushButton#primaryBtn:disabled { background-color: #2a2a2a; color: #555; }
QPushButton#secondaryBtn { background-color: #1a1a1a; color: #c0c0c0; border: 1px solid #2a2a2a; border-radius: 8px; padding: 10px 20px; font-weight: 600; }
QPushButton#secondaryBtn:hover { background-color: #222; border-color: #444; }
QPushButton#dangerBtn { background-color: #b91c1c; color: white; border: none; border-radius: 8px; padding: 10px 20px; font-weight: bold; }
QPushButton#dangerBtn:hover { background-color: #dc2626; }
QPushButton#smallBtn { background-color: #1a1a2e; color: #e94560; border: 1px solid #e94560; border-radius: 6px; padding: 6px 14px; font-size: 12px; font-weight: 600; }
QPushButton#smallBtn:hover { background-color: #e94560; color: white; }
QPushButton#filterBtn { background-color: #1a1a1a; color: #8b949e; border: 1px solid #2a2a2a; border-radius: 6px; padding: 6px 16px; font-size: 12px; }
QPushButton#filterBtn:checked { background-color: #e94560; color: white; border-color: #e94560; }
QTableWidget { background-color: #141414; border: 1px solid #2a2a2a; border-radius: 8px; gridline-color: #1e1e1e; selection-background-color: #1a1a2e; alternate-background-color: #181818; }
QTableWidget::item { padding: 8px; border-bottom: 1px solid #1e1e1e; }
QTableWidget::item:selected { background-color: #1a1a2e; color: #e0e0e0; }
QHeaderView::section { background-color: #1a1a1a; color: #6b7280; border: none; border-bottom: 2px solid #2a2a2a; padding: 10px 12px; font-weight: bold; font-size: 11px; }
QProgressBar { border: none; border-radius: 8px; background-color: #1a1a1a; text-align: center; color: #e0e0e0; font-weight: bold; height: 26px; }
QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #e94560, stop:1 #c73659); border-radius: 8px; }
QScrollBar:vertical { background: #0f0f0f; width: 8px; border-radius: 4px; }
QScrollBar::handle:vertical { background: #2a2a2a; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #0f0f0f; height: 8px; }
QScrollBar::handle:horizontal { background: #2a2a2a; border-radius: 4px; }
QTextEdit { background-color: #141414; border: 1px solid #2a2a2a; border-radius: 8px; padding: 10px; color: #6b7280; font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px; }
QGroupBox { border: 1px solid #2a2a2a; border-radius: 10px; margin-top: 14px; padding-top: 18px; font-weight: bold; color: #6b7280; }
QGroupBox::title { subcontrol-origin: margin; left: 16px; padding: 0 8px; }
QCheckBox { color: #c0c0c0; spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px; border: 2px solid #2a2a2a; background: #1a1a1a; }
QCheckBox::indicator:checked { background-color: #e94560; border-color: #e94560; }
QLabel#sectionLabel { font-size: 16px; font-weight: bold; color: #e0e0e0; }
QLabel#statsLabel { font-size: 12px; color: #6b7280; }
QLabel#accentLabel { font-size: 13px; color: #e94560; font-weight: 600; }
QLabel#rawTag { background-color: #7c3aed; color: white; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: bold; }
QLabel#transTag { background-color: #059669; color: white; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: bold; }
QStatusBar { background-color: #0a0a0a; color: #6b7280; border-top: 1px solid #1e1e1e; font-size: 12px; padding: 4px 12px; }
QMenu { background-color: #1a1a1a; border: 1px solid #2a2a2a; color: #e0e0e0; padding: 4px; }
QMenu::item:selected { background-color: #1a1a2e; }
"""

LIGHT_THEME = """
* { font-family: 'Segoe UI', 'Microsoft YaHei UI', sans-serif; }
QMainWindow, QWidget { background-color: #f8f9fa; color: #1a1a1a; }
QFrame#header { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #e8eaf6, stop:1 #c5cae9); border-bottom: 2px solid #7986cb; }
QLabel#headerTitle { font-size: 20px; font-weight: bold; color: #e94560; }
QLabel#headerSub { font-size: 11px; color: #78909c; }
QFrame#sidebar { background-color: #ffffff; border-right: 1px solid #e0e0e0; }
QPushButton#navBtn { background: transparent; color: #616161; border: none; border-radius: 8px; padding: 12px 16px; text-align: left; font-size: 13px; font-weight: 600; }
QPushButton#navBtn:hover { background-color: #f0f0f0; color: #1a1a1a; }
QPushButton#navBtn:checked { background-color: #e8eaf6; color: #e94560; border-left: 3px solid #e94560; }
QLineEdit { background-color: #ffffff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 10px 14px; color: #1a1a1a; font-size: 14px; }
QLineEdit:focus { border-color: #e94560; }
QComboBox { background-color: #ffffff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 8px 12px; color: #1a1a1a; min-width: 140px; }
QComboBox QAbstractItemView { background-color: #ffffff; border: 1px solid #e0e0e0; selection-background-color: #e8eaf6; }
QSpinBox { background-color: #ffffff; border: 1px solid #e0e0e0; border-radius: 6px; padding: 6px; color: #1a1a1a; }
QPushButton#primaryBtn { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #e94560, stop:1 #c73659); color: white; border: none; border-radius: 8px; padding: 10px 24px; font-weight: bold; }
QPushButton#primaryBtn:disabled { background-color: #e0e0e0; color: #999; }
QPushButton#secondaryBtn { background-color: #ffffff; color: #424242; border: 1px solid #e0e0e0; border-radius: 8px; padding: 10px 20px; font-weight: 600; }
QPushButton#dangerBtn { background-color: #ef5350; color: white; border: none; border-radius: 8px; padding: 10px 20px; font-weight: bold; }
QPushButton#smallBtn { background-color: #fce4ec; color: #e94560; border: 1px solid #e94560; border-radius: 6px; padding: 6px 14px; font-size: 12px; }
QPushButton#smallBtn:hover { background-color: #e94560; color: white; }
QPushButton#filterBtn { background-color: #fff; color: #616161; border: 1px solid #e0e0e0; border-radius: 6px; padding: 6px 16px; font-size: 12px; }
QPushButton#filterBtn:checked { background-color: #e94560; color: white; border-color: #e94560; }
QTableWidget { background-color: #ffffff; border: 1px solid #e0e0e0; border-radius: 8px; gridline-color: #f0f0f0; selection-background-color: #e8eaf6; alternate-background-color: #fafafa; }
QTableWidget::item { padding: 8px; border-bottom: 1px solid #f0f0f0; }
QHeaderView::section { background-color: #f5f5f5; color: #757575; border: none; border-bottom: 2px solid #e0e0e0; padding: 10px 12px; font-weight: bold; }
QProgressBar { border: none; border-radius: 8px; background-color: #e0e0e0; text-align: center; color: #1a1a1a; font-weight: bold; height: 26px; }
QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #e94560, stop:1 #c73659); border-radius: 8px; }
QScrollBar:vertical { background: #f8f9fa; width: 8px; }
QScrollBar::handle:vertical { background: #bdbdbd; border-radius: 4px; min-height: 30px; }
QTextEdit { background-color: #ffffff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 10px; color: #616161; font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px; }
QGroupBox { border: 1px solid #e0e0e0; border-radius: 10px; margin-top: 14px; padding-top: 18px; font-weight: bold; color: #757575; }
QCheckBox { color: #424242; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px; border: 2px solid #bdbdbd; background: #fff; }
QCheckBox::indicator:checked { background-color: #e94560; border-color: #e94560; }
QLabel#sectionLabel { font-size: 16px; font-weight: bold; color: #1a1a1a; }
QLabel#statsLabel { font-size: 12px; color: #757575; }
QLabel#accentLabel { font-size: 13px; color: #e94560; font-weight: 600; }
QLabel#rawTag { background-color: #7c3aed; color: white; border-radius: 4px; padding: 2px 8px; font-size: 11px; }
QLabel#transTag { background-color: #059669; color: white; border-radius: 4px; padding: 2px 8px; font-size: 11px; }
QStatusBar { background-color: #f5f5f5; color: #757575; border-top: 1px solid #e0e0e0; }
QMenu { background-color: #fff; border: 1px solid #e0e0e0; color: #1a1a1a; }
QMenu::item:selected { background-color: #e8eaf6; }
"""
