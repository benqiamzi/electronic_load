from __future__ import annotations

from PySide6.QtWidgets import QWidget


VOLTAGE = "#1266b5"
CURRENT = "#13805d"
POWER = "#a65b13"
LEFT_TEMPERATURE = "#b54059"
RIGHT_TEMPERATURE = "#7358ac"
PLOT_BACKGROUND = "#f8fafc"
PLOT_TEXT = "#475970"
PLOT_AXIS = "#8192a8"
PLACEHOLDER = "—"


def set_tone(widget: QWidget, tone: str) -> None:
    if widget.property("tone") != tone:
        widget.setProperty("tone", tone)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


STYLESHEET = f"""
QWidget#dashboard, QDialog {{
    background: #eaf0f6;
}}
QMainWindow, QDialog {{
    color: #182940;
    font-size: 13px;
}}
QLabel {{
    color: #182940;
}}
QLabel[role="caption"], QLabel[role="muted"] {{
    color: #53667e;
}}
QLabel[role="heading"] {{
    font-size: 15px;
    font-weight: 600;
}}
QLabel[role="readout"] {{
    font-size: 32px;
    font-weight: 600;
}}
QLabel[role="unit"] {{
    font-size: 15px;
    font-weight: 600;
}}
QLabel[role="summary"] {{
    font-weight: 600;
}}
QLabel[metric="voltage"] {{ color: {VOLTAGE}; }}
QLabel[metric="current"] {{ color: {CURRENT}; }}
QLabel[metric="power"] {{ color: {POWER}; }}
QLabel[metric="leftTemperature"] {{ color: {LEFT_TEMPERATURE}; }}
QLabel[metric="rightTemperature"] {{ color: {RIGHT_TEMPERATURE}; }}
QLabel[tone="muted"] {{ color: #53667e; }}
QLabel[tone="success"] {{ color: #107252; }}
QLabel[tone="warning"] {{ color: #8e4b14; }}
QLabel[tone="error"], QToolButton[tone="error"] {{ color: #a32937; }}
QTextEdit[role="menuText"] {{
    background: #ffffff;
    color: #182940;
    padding: 0;
}}
QTextEdit[role="menuText"][tone="error"] {{ color: #a32937; }}

QFrame[role="panel"], QGroupBox {{
    background: #ffffff;
    border: 1px solid #d4deea;
    border-radius: 8px;
}}
QGroupBox {{
    margin-top: 12px;
    padding-top: 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 5px;
}}
QFrame[role="metric"], QLabel[role="dacReadout"] {{
    background: #f3f7fb;
    border: 1px solid #e0e8f1;
    border-radius: 6px;
}}
QLabel[role="dacReadout"] {{
    padding: 10px;
    font-size: 19px;
    font-weight: 600;
}}
QToolBar#mainToolbar {{
    background: #ffffff;
    border: none;
    border-bottom: 1px solid #d4deea;
    padding: 7px 16px;
    spacing: 6px;
}}
QToolBar::separator {{
    background: #d4deea;
    width: 1px;
    margin: 3px 4px;
}}
QToolButton, QPushButton {{
    background: #ffffff;
    color: #243950;
    border: 1px solid #cbd7e5;
    border-radius: 5px;
    padding: 4px 9px;
    min-height: 19px;
}}
QToolButton {{
    background: transparent;
    border-color: transparent;
    padding-right: 17px;
    font-weight: 600;
}}
QToolButton::menu-indicator {{
    subcontrol-position: right center;
    right: 5px;
}}
QPushButton:hover, QToolButton:hover, QToolButton:open {{
    background: #eaf2fa;
    border-color: #adc2d9;
}}
QPushButton:pressed, QToolButton:pressed {{
    background: #dce9f7;
}}
QPushButton[variant="primary"] {{
    background: #225a91;
    border-color: #225a91;
    color: #ffffff;
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: #194c80; }}
QPushButton[variant="primary"]:pressed {{ background: #153c65; }}
QPushButton[variant="load"][tone="success"] {{
    background: #147451;
    border-color: #147451;
    color: #ffffff;
    font-weight: 600;
}}
QPushButton[variant="load"][tone="success"]:hover {{ background: #0e6244; }}
QPushButton[variant="load"][tone="success"]:pressed {{ background: #0c5239; }}
QPushButton[variant="danger"] {{
    background: #ad2e3b;
    border-color: #ad2e3b;
    color: #ffffff;
    font-weight: 600;
}}
QPushButton[variant="danger"]:hover {{ background: #932633; }}
QPushButton[variant="danger"]:pressed {{ background: #7a1f2b; }}
QPushButton[variant="warning"] {{
    background: #fff3e3;
    border-color: #e9c49d;
    color: #804719;
}}
QPushButton[variant="warning"]:hover {{ background: #fce7cc; }}
QPushButton[variant="warning"]:pressed {{ background: #f6dbb7; }}
QComboBox, QDoubleSpinBox {{
    background: #f8fafc;
    color: #182940;
    border: 1px solid #cbd7e5;
    border-radius: 5px;
    min-height: 20px;
    padding: 3px 6px;
}}
QComboBox QAbstractItemView {{
    background: #ffffff;
    color: #182940;
    selection-background-color: #dceafa;
    selection-color: #182940;
}}
QPushButton:disabled, QPushButton[variant]:disabled,
QPushButton[variant="load"][tone]:disabled, QToolButton:disabled,
QComboBox:disabled, QDoubleSpinBox:disabled {{
    background: #edf1f6;
    border-color: #dce4ee;
    color: #5f7086;
}}
QPushButton:focus, QToolButton:focus, QComboBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid #3975b0;
}}
QMenu {{
    background: #ffffff;
    color: #182940;
    border: 1px solid #cbd7e5;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 28px 6px 24px;
}}
QMenu::item:selected {{
    background: #e6eff9;
    color: #182940;
}}
QMenu::item:disabled {{ color: #64748a; }}
QMenu::separator {{
    height: 1px;
    background: #e0e7f0;
    margin: 4px 8px;
}}
QSplitter::handle {{
    background: #d6e2ef;
    border-radius: 3px;
    margin: 2px 0;
}}
QSplitter::handle:hover {{ background: #a4bad1; }}
QTabWidget::pane {{
    background: #ffffff;
    border: 1px solid #d4deea;
    border-radius: 6px;
}}
QTabBar::tab {{
    background: #eaf0f6;
    color: #53667e;
    border: 1px solid #d4deea;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    margin-right: 4px;
    padding: 5px 16px;
    min-height: 16px;
}}
QTabBar::tab:selected {{
    background: #ffffff;
    color: #225a91;
    font-weight: 600;
}}
QTabBar::tab:!selected:hover {{ background: #dfeaf5; }}
QPlainTextEdit#communicationLog {{
    background: #f8fafc;
    color: #283c54;
    border: 1px solid #e0e8f1;
    border-radius: 5px;
    selection-background-color: #dceafa;
    selection-color: #182940;
    font-size: 12px;
}}
"""
