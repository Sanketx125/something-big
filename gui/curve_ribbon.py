"""
Curve Ribbon for NakshaAI
Provides curve drawing tools with MicroStation-style point-by-point workflow
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PySide6.QtCore import Signal


class CurveRibbon(QWidget):
    """Ribbon for Curve drawing tools"""
    
    curve_tool_selected = Signal(str)
    clear_curves = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.build_ribbon()
        
    def build_ribbon(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # 🎯 Curve Tools Section
        from gui.menu_sidebar_system import RibbonSection
        
        tools = RibbonSection("🎯 Curve Tools", self)
        
        # ✅ THE BUTTON YOU NEED: "Curve Point"
        tools.add_button(
            "Curve\nPoint", 
            "🔮", 
            lambda: self.curve_tool_selected.emit("curve_point"),
            toggleable=True  # Can stay active
        )
        
        layout.addWidget(tools)
        
        # 🗑️ Actions Section
        actions = RibbonSection("🗑️ Actions", self)
        actions.add_button(
            "Clear", 
            "🗑️", 
            self.clear_curves.emit,
            toggleable=False
        )
        layout.addWidget(actions)
        
        layout.addStretch()