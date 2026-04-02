import sys
import os

fpath = 'gui/menu_sidebar_system.py'
with open(fpath, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace block 1
target1 = '''        tools.add_button("Line", "📏", lambda: self._handle_line_click())
        tools.add_button("Polyline", "⬡", lambda: self._handle_polyline_click())'''
repl1 = '''        tools.add_button("Line", "📏", lambda: self._handle_line_click())
        tools.add_button("Ortho", "📐", lambda: self._handle_ortho_click())
        tools.add_button("Polyline", "⬡", lambda: self._handle_polyline_click())'''

if target1 in content:
    content = content.replace(target1, repl1)
    print("Replaced block 1")
else:
    print("Block 1 not found")

# Replace block 2
target2 = '''    # ========================================================================
    # POLYLINE SETTINGS (existing)
    # ========================================================================
    def _handle_polyline_click(self):
        """Handle Polyline button click with Shift detection"""
        modifiers = QApplication.keyboardModifiers()'''
repl2 = '''    # ========================================================================
    # ORTHO SETTINGS
    # ========================================================================
    def _handle_ortho_click(self):
        """Handle Ortho button click with Shift detection"""
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.ShiftModifier:
            self._show_tool_permanent_settings('orthopolygon', 'orthopolygon_permanent_mode', 'Orthopolygon')
        else:
            self.draw_tool_selected.emit("orthopolygon")

    # ========================================================================
    # POLYLINE SETTINGS (existing)
    # ========================================================================
    def _handle_polyline_click(self):
        """Handle Polyline button click with Shift detection"""
        modifiers = QApplication.keyboardModifiers()'''

if target2 in content:
    content = content.replace(target2, repl2)
    print("Replaced block 2")
else:
    print("Block 2 not found")

with open(fpath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
