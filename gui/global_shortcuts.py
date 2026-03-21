
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtGui import QKeySequence
from flask import views
from .execute_tool import execute_tool

class GlobalShortcutFilter(QObject):
    def __init__(self, app_window):
        super().__init__()
        self.app_window = app_window

    def eventFilter(self, obj, event):
            if event.type() == QEvent.KeyPress:
                
                # ====================================================================
                # BYPASS SHORTCUTS IF USER IS TYPING IN AN INPUT FIELD
                # ====================================================================
                try:
                    from PySide6.QtWidgets import QApplication, QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox
                    focus_widget = QApplication.focusWidget()
                    if isinstance(focus_widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox)):
                        # If the user is typing, let the widget handle its own key presses!
                        # Only bypass if they are NOT holding Ctrl/Alt/Shift (unless it's just Shift for capitals)
                        if not (event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
                            return False
                        # Even if holding Ctrl, let standard text shortcuts (Ctrl+C, Ctrl+V, Ctrl+Z, Ctrl+Y) pass
                        if event.modifiers() & Qt.ControlModifier and event.key() in (Qt.Key_C, Qt.Key_V, Qt.Key_X, Qt.Key_Z, Qt.Key_Y, Qt.Key_A):
                            return False
                except Exception:
                    pass

                # ====================================================================
                # PRIORITY -2: Shift+ESC - Exit active digitize tool, keep drawings
                # ====================================================================
                if event.key() == Qt.Key_Escape and (event.modifiers() & Qt.ShiftModifier):
                    digitizer = getattr(self.app_window, 'digitizer', None)
                    if digitizer and getattr(digitizer, 'active_tool', None):
                        print("🛑 Shift+ESC - deactivating digitizer tool")
                        try:
                            if hasattr(digitizer, '_deactivate_active_tool_keep_drawings') and \
                               digitizer._deactivate_active_tool_keep_drawings():
                                return True
                        except Exception as e:
                            print(f"⚠️ Shift+ESC digitizer deactivation failed: {e}")

                # ====================================================================
                # PRIORITY -1: Curve Tool Shortcuts (highest priority)
                # ====================================================================
                if hasattr(self.app_window, 'curve_tool'):
                    curve_tool = self.app_window.curve_tool
                    
                    # Shift+E - Edit curve color (when curve tool has selection)
                    if event.key() == Qt.Key_E and (event.modifiers() & Qt.ShiftModifier):
                        if curve_tool.selected_curve_data:
                            print("🎨 Shift+E → Edit Curve Color (curve tool)")
                            try:
                                curve_tool._edit_selected_curve_color()
                            except Exception as e:
                                print(f"⚠️ Curve color edit failed: {e}")
                            return True
                    
                    # Delete - Delete curve (when curve tool has selection)
                    if (event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace):
                        if curve_tool.selected_curve_data and not curve_tool.active:
                            print("🗑️ Delete → Delete Curve (curve tool)")
                            try:
                                curve_tool._delete_selected_curve()
                            except Exception as e:
                                print(f"⚠️ Curve delete failed: {e}")
                            return True
                
                # ====================================================================
                # PRIORITY 0: ESC key - Cancel active modes
                # ====================================================================
                if event.key() == Qt.Key_Escape:
                    # Priority 1: Cross-section mode (top-most tool)
                    # if hasattr(self.app_window, 'cross_action') and self.app_window.cross_action.isChecked():
                    if getattr(self.app_window, 'cross_action', None) is not None and self.app_window.cross_action.isChecked():
                        print("🛑 ESC - deactivating cross-section")
                        
                        # Uncheck the button
                        if getattr(self.app_window, 'cross_action', None) is not None:
                                self.app_window.cross_action.setChecked(False)
                        
                        # ✅ DEACTIVATE MODE BUT KEEP EXISTING SECTIONS
                        try:
                            # Clear ONLY the preview/rubber band (not finalized sections)
                            if hasattr(self.app_window, 'section_controller'):
                                sc = self.app_window.section_controller
                                
                                # Clear only preview actors (rubber band, centerline)
                                renderer = self.app_window.vtk_widget.renderer
                                
                                # Remove 2D preview centerline
                                if hasattr(sc, '_centerline_actor_2d') and sc._centerline_actor_2d:
                                    renderer.RemoveActor2D(sc._centerline_actor_2d)
                                    sc._centerline_actor_2d = None
                                
                                # Remove 2D preview rectangle
                                if hasattr(sc, '_rubber_actor_2d') and sc._rubber_actor_2d:
                                    renderer.RemoveActor2D(sc._rubber_actor_2d)
                                    sc._rubber_actor_2d = None
                                
                                # Remove 3D rubber band (in-progress selection)
                                if hasattr(sc, 'rubber_actor') and sc.rubber_actor:
                                    renderer.RemoveActor(sc.rubber_actor)
                                    sc.rubber_actor = None
                                
                                # Reset interactor state (P1, P2)
                                if hasattr(self.app_window, 'cross_interactor'):
                                    ci = self.app_window.cross_interactor
                                    if hasattr(ci, 'P1'):
                                        ci.P1 = None
                                    if hasattr(ci, 'P2'):
                                        ci.P2 = None
                                    if hasattr(ci, 'slice_state'):
                                        ci.slice_state = 0
                            
                            # Clear interactor reference
                            if hasattr(self.app_window, 'cross_interactor'):
                                self.app_window.cross_interactor = None
                            
                            # Restore default interactor
                            from vtkmodules.vtkInteractionStyle import vtkInteractorStyleImage
                            self.app_window.vtk_widget.interactor.SetInteractorStyle(vtkInteractorStyleImage())
                            
                            # Clear state flags
                            if hasattr(self.app_window, 'cross_section_active'):
                                self.app_window.cross_section_active = False
                            
                            self.app_window.vtk_widget.render()
                            
                            print("✅ Cross-section mode deactivated (existing sections preserved)")
                            
                        except Exception as e:
                            print(f"⚠️ Error deactivating cross-section: {e}")
                        
                        return True
                    
                    # Priority 2: Classification tool
                    if hasattr(self.app_window, 'active_classify_tool') and self.app_window.active_classify_tool:
                        print("🛑 ESC - deactivating classification")
                        self.app_window.deactivate_classification_tool()
                        return True
                    
                    # If neither is active, let ESC pass through
                    return False
                
            
                # ====================================================================
                # PRIORITY 1: Undo/Redo (Ctrl+Z/Y)
                # ====================================================================
                if event.modifiers() & Qt.ControlModifier:

                    # ✅ Curve tool undo/redo (if curve tool is active)
                    if hasattr(self.app_window, 'curve_tool') and \
                       hasattr(self.app_window.curve_tool, 'active') and \
                       self.app_window.curve_tool.active:
                        
                        if event.key() == Qt.Key_Z:
                            print("🎨 Ctrl+Z → Curve Tool Undo Point")
                            try:
                                self.app_window.curve_tool._undo_last_point()
                            except Exception as e:
                                print(f"⚠️ Curve undo failed: {e}")
                            return True
                        
                        elif event.key() == Qt.Key_Y:
                            print("🎨 Ctrl+Y → Curve Tool Redo Point")
                            try:
                                self.app_window.curve_tool._redo_last_point()
                            except Exception as e:
                                print(f"⚠️ Curve redo failed: {e}")
                            return True

                    # ✅ Measurement undo/redo — when measurement tool is active
                    elif hasattr(self.app_window, 'measurement_tool') and \
                         hasattr(self.app_window.measurement_tool, 'active') and \
                         self.app_window.measurement_tool.active:
                        measurement_tool = self.app_window.measurement_tool

                        if event.key() == Qt.Key_Z:
                            print("📏 Ctrl+Z → Measurement Undo")
                            try:
                                measurement_tool.undo()
                            except Exception as e:
                                print(f"⚠️ Measurement undo failed: {e}")
                            return True

                        elif event.key() == Qt.Key_Y:
                            print("📏 Ctrl+Y → Measurement Redo")
                            try:
                                measurement_tool.redo()
                            except Exception as e:
                                print(f"⚠️ Measurement redo failed: {e}")
                            return True
                    
                    # ✅ DIGITIZER undo/redo — if digitizer is enabled, it gets priority
                    elif hasattr(self.app_window, 'digitizer') and \
                         self.app_window.digitizer.enabled and \
                         getattr(self.app_window.digitizer, 'active_tool', None):
                        digitizer = self.app_window.digitizer
                        
                        if event.key() == Qt.Key_Z:
                            print("🎨 Ctrl+Z → Digitizer Undo")
                            try:
                                # Let digitizer handle it - will print "Nothing to undo" if empty
                                digitizer.undo()
                            except Exception as e:
                                print(f"⚠️ Digitizer undo failed: {e}")
                            return True

                        elif event.key() == Qt.Key_Y:
                            print("🎨 Ctrl+Y → Digitizer Redo")
                            try:
                                digitizer.redo()
                            except Exception as e:
                                print(f"⚠️ Digitizer redo failed: {e}")
                            return True
                    
                    # ✅ CLASSIFICATION undo/redo — only if digitizer is NOT enabled
                    else:
                        if event.key() == Qt.Key_Z:
                            print("🟢 Ctrl+Z → Undo Classification")
                            try:
                                self.app_window.undo_classification()
                            except Exception as e:
                                print(f"⚠️ Undo failed: {e}")
                            return True

                        elif event.key() == Qt.Key_Y:
                            print("🟢 Ctrl+Y → Redo Classification")
                            try:
                                self.app_window.redo_classification()
                            except Exception as e:
                                print(f"⚠️ Redo failed: {e}")
                            return True
                    if (event.modifiers() & Qt.ShiftModifier):
                        if event.key() == Qt.Key_D:
                            print("🎛️ Ctrl+Shift+D → Apply Display Settings")
                            try:
                                # Check if point cloud data is loaded
                                if not (hasattr(self.app_window, 'data') and self.app_window.data is not None):
                                    print("   ⚠️ No point cloud data loaded")
                                    if hasattr(self.app_window, 'statusBar'):
                                        self.app_window.statusBar().showMessage(
                                            "⚠️ Please load a point cloud file first (File → Open)",
                                            3000
                                        )
                                    return True
                                
                                # ✅ SAVE: Current view selection
                                saved_slot = None
                                if hasattr(self.app_window, 'display_mode_dialog') and \
                                self.app_window.display_mode_dialog is not None:
                                    saved_slot = self.app_window.display_mode_dialog.current_slot
                                    print(f"   💾 Current view: {saved_slot}")
                                
                                # ✅ If Display Mode dialog exists, apply its settings
                                if hasattr(self.app_window, 'display_mode_dialog') and \
                                self.app_window.display_mode_dialog is not None:
                                    
                                    print("   📋 Applying settings from Display Mode dialog...")
                                    
                                    dialog = self.app_window.display_mode_dialog
                                    
                                    # ✅ FIXED: Apply settings WITHOUT forcing weights
                                    # The dialog already has the correct weights - just apply them
                                    dialog.on_apply()
                                    
                                    # ❌ REMOVED: No longer force weights to 1.0
                                    # Let the dialog's existing weights remain unchanged
                                    
                                    # Restore slot selection
                                    if saved_slot is not None:
                                        dialog.current_slot = saved_slot
                                        dialog.slot_box.setCurrentIndex(saved_slot)
                                    
                                    if hasattr(self.app_window, 'statusBar'):
                                        self.app_window.statusBar().showMessage(
                                            "✅ Display settings applied (Ctrl+Shift+D)",
                                            2500
                                        )
                                    print("   ✅ Settings applied (weights preserved)")
                                
                                # ✅ If no dialog exists, CREATE IT SILENTLY
                                else:
                                    print("   🔧 Creating Display Mode dialog silently...")
                                    
                                    from gui.display_mode import DisplayModeDialog
                                    
                                    self.app_window.display_mode_dialog = DisplayModeDialog(self.app_window)
                                    
                                    print("   ⚡ Auto-applying loaded settings...")
                                    self.app_window.display_mode_dialog.on_apply()
                                    
                                    # ❌ REMOVED: No weight enforcement
                                    # The dialog loaded weights from PTC/settings - use those
                                    
                                    print("   🎨 Force rendering...")
                                    from gui.class_display import update_class_mode
                                    update_class_mode(self.app_window)
                                    
                                    if hasattr(self.app_window, 'statusBar'):
                                        num_classes = self.app_window.display_mode_dialog.table.rowCount()
                                        self.app_window.statusBar().showMessage(
                                            f"✅ Display applied: {num_classes} classes from PTC (Ctrl+Shift+D)",
                                            2500
                                        )
                                    print(f"   ✅ Applied {num_classes} classes from PTC file")
                                
                            except Exception as e:
                                print(f"⚠️ Display shortcut failed: {e}")
                                import traceback
                                traceback.print_exc()
                                if hasattr(self.app_window, 'statusBar'):
                                    self.app_window.statusBar().showMessage(
                                        f"❌ Failed to apply display settings: {e}",
                                        3000
                                    )
                            return True
                        
                        
                # ✅ NEW: Apply Shortcuts shortcut (Ctrl+Shift+S)
                # ====================================================================
                if event.key() == Qt.Key_S:
                    print("⚡ Ctrl+Shift+S → Apply Shortcuts from Settings")
                    try:
                        # ✅ Import and call the static method
                        from gui.shortcut_manager import ShortcutManager
                        ShortcutManager.apply_shortcuts_from_settings(self.app_window)
                        
                    except Exception as e:
                        print(f"⚠️ Apply shortcuts failed: {e}")
                        import traceback
                        traceback.print_exc()
                        if hasattr(self.app_window, 'statusBar'):
                            self.app_window.statusBar().showMessage(
                                f"❌ Failed to apply shortcuts: {e}",
                                3000
                            )
                    return True
                # ====================================================================
                # Unlock views shortcut (Shift+P) - Context-aware (focused view only)
                # ====================================================================
                if (event.modifiers() & Qt.ShiftModifier) and event.key() == Qt.Key_P:
                    print("🔓 Shift+P → Unlock Focused View")
                    try:
                        # Get the currently focused widget
                        from PySide6.QtWidgets import QApplication
                        focused = QApplication.focusWidget()
                        
                        print(f"   🔍 Focused widget: {type(focused).__name__}")
                        
                        # Check if a cross-section view is focused
                        unlocked_view = None
                        if hasattr(self.app_window, 'section_vtks') and self.app_window.section_vtks:
                            for view_idx, vtk_widget in self.app_window.section_vtks.items():
                                try:
                                    if (focused == vtk_widget.interactor or
                                        vtk_widget.interactor.isAncestorOf(focused)):
                                        # Unlock THIS cross-section view only
                                        self._unlock_cross_section_view(view_idx, vtk_widget)
                                        unlocked_view = f"Cross-Section {view_idx + 1}"
                                        break
                                except Exception as e:
                                    print(f"   ⚠️ Error checking view {view_idx}: {e}")
                        
                        # If no cross-section focused, unlock main view
                        if unlocked_view is None:
                            self._unlock_main_view()
                            unlocked_view = "Main View"
                        
                        if hasattr(self.app_window, 'statusBar'):
                            self.app_window.statusBar().showMessage(
                                f"🔓 {unlocked_view} unlocked - 3D rotation enabled",
                                1500
                            )
                    except Exception as e:
                        print(f"⚠️ Unlock failed: {e}")
                    return True
        
                # ====================================================================
                # Fit View shortcut (Shift+F) - ONLY Shift, NO Ctrl
                # ====================================================================
                # if event.key() == Qt.Key_F:
                #             print("🧲 Shift+F → Context-Aware Fit View")
                #             try:
                #                 self._handle_context_fit_view()
                #             except Exception as e:
                #                 print(f"⚠️ Fit view failed: {e}")
                #             return True

                if (event.modifiers() & Qt.ShiftModifier) and event.key() == Qt.Key_F:
                    print("🧲 Shift+F → Context-Aware Fit View")
                    try:
                        self._handle_context_fit_view()
                    except Exception as e:
                        print(f"⚠️ Fit view failed: {e}")
                    return True           
                # =====================================
                # PRIORITY 2: Tool Shortcuts (F1–F12, digits, etc.)
                # ====================================================================
    
                key = event.key()
    
                # Build modifier string
                mod_parts = []
                if event.modifiers() & Qt.ControlModifier:
                    mod_parts.append("ctrl")
                if event.modifiers() & Qt.AltModifier:
                    mod_parts.append("alt")
                if event.modifiers() & Qt.ShiftModifier:
                    mod_parts.append("shift")
                mod = "+".join(mod_parts) if mod_parts else "none"
    
                # Robust key normalization (F-keys + digits + others)
                if Qt.Key_F1 <= key <= Qt.Key_F12:
                    keyname = f"F{key - Qt.Key_F1 + 1}"
                elif Qt.Key_0 <= key <= Qt.Key_9:
                    keyname = chr(ord('0') + (key - Qt.Key_0))
                else:
                    keyname = QKeySequence(key).toString().upper() or event.text().upper()
    
                combo = (mod.lower(), keyname.upper())
    
                print(f"KEY DEBUG → combo={combo}")
                print("ALL SHORTCUTS NOW:", list(getattr(self.app_window, 'shortcuts', {}).keys()))
    
                # Look up in shortcut table
                # Look up in shortcut table
                shortcuts = getattr(self.app_window, 'shortcuts', {})
                shortcut = shortcuts.get(combo)

                tool = None
                if shortcut:
                    tool = shortcut.get("tool")  # ✅ ASSIGN TOOL FIRST

                if tool == "DisplayMode":
                    preset = shortcut.get("preset")
                    print(f"✅ SHORTCUT MATCH: {combo} → DisplayMode")

                    if not preset:
                        print("⚠️ DisplayMode shortcut has no preset")
                        return True

                    try:
                        print(f"\n{'='*60}")
                        print(f"🎨 APPLYING DISPLAYMODE PRESET FROM SHORTCUT")
                        print(f"{'='*60}")
                        
                        # ✅ CRITICAL: Extract target_view FIRST before any other operations
                        views = preset.get("views", {})
                        border_percent = preset.get("border_percent", 0.0)
                        
                        # ✅ Get the TARGET VIEW from the preset (MUST be done first!)
                        target_view = int(list(views.keys())[0]) if views else 0
                        print(f"   🎯 TARGET VIEW FROM SHORTCUT: {target_view}")
                        
                        # ============================================================================
                        # ✅ STEP 0A: RESET class_palette VISIBILITY FROM PRESET
                        # ✅ CRITICAL FIX: ONLY if target is Main View (0)
                        # ============================================================================
                        print(f"   🔄 Checking if class_palette reset needed (target={target_view})...")
                        
                        if target_view == 0:
                            # Main View - reset class_palette visibility
                            print(f"   🔄 Resetting class_palette visibility from preset...")
                            
                            # First, set ALL classes to hidden
                            if hasattr(self.app_window, 'class_palette'):
                                for code in self.app_window.class_palette:
                                    self.app_window.class_palette[code]["show"] = False
                            
                            # Then, apply visibility from the preset's main view
                            view_key = str(target_view) if str(target_view) in views else target_view
                            preset_classes = views.get(view_key, views.get(str(view_key), {}))
                            
                            for code, info in preset_classes.items():
                                code_int = int(code)
                                if code_int in self.app_window.class_palette:
                                    self.app_window.class_palette[code_int]["show"] = info.get("show", False)
                                    self.app_window.class_palette[code_int]["weight"] = info.get("weight", 1.0)
                                    print(f"      Class {code_int}: show={info.get('show', False)}")
                            
                            print(f"   ✅ class_palette reset complete (Main View)")
                        else:
                            # Cross-section or Cut View - DO NOT touch class_palette at all
                            print(f"   ⏭️  Skipped class_palette reset (target is View {target_view}, not Main View)")
                            print(f"   ✅ Main View class_palette remains COMPLETELY UNCHANGED")
                    

                        if target_view == 0:
                            # ✅ Target is Main View - safe to clear shading
                            print(f"   🧹 Clearing Main View shading mode actors...")
                            if hasattr(self.app_window, '_shaded_mesh_actor') and self.app_window._shaded_mesh_actor:
                                try:
                                    self.app_window.vtk_widget.remove_actor('shaded_mesh', render=False)
                                    self.app_window._shaded_mesh_actor = None
                                    print(f"      ✅ Removed Main View shading mesh actor")
                                except Exception as e:
                                    print(f"      ⚠️ Could not remove shading actor: {e}")
 
                            if hasattr(self.app_window, '_shaded_mesh_polydata'):
                                self.app_window._shaded_mesh_polydata = None
 
                            # Clear shading cache for Main View
                            try:
                                from gui.shading_display import clear_shading_cache
                                clear_shading_cache("Main View switching to DisplayMode")
                                print(f"      ✅ Cleared Main View shading cache")
                            except Exception as e:
                                print(f"      ⚠️ Could not clear shading cache: {e}")
 
                            # Set Main View display mode back to classification
                            self.app_window.display_mode = 'class'
                            if hasattr(self.app_window, 'current_display_mode'):
                                self.app_window.current_display_mode = 'class'
                            print(f"      ✅ Set Main View display mode to 'class'")
 
                            # Force immediate classification render for Main View
                            try:
                                from gui.class_display import update_class_mode
                                update_class_mode(self.app_window, force_refresh=True)
                                print(f"      ✅ Forced Main View classification render")
                            except Exception as e:
                                print(f"      ⚠️ Could not force render: {e}")
                        else:
                            # ✅ Target is Cross Section or Cut View - DO NOT TOUCH MAIN VIEW!
                            print(f"   ⏭️  Target is View {target_view}, NOT Main View")
                            print(f"   ✅ Skipping shading actor clear - Main View UNCHANGED")
                            print(f"   ✅ Skipping display_mode reset - Main View UNCHANGED")
                            print(f"   ✅ Main View shading state PRESERVED")
                            print(f"   🎯 Only updating Cross Section View {target_view}")
                        
                        view_names = ["Main View", "View 1", "View 2", "View 3", "View 4", "Cut Section"]
                        
                        print(f"   📋 Border: {border_percent}%")
                        print(f"   📋 Views configured: {list(views.keys())}")
                        
                        # ✅ Initialize display_mode_dialog if needed
                        if not hasattr(self.app_window, 'display_mode_dialog') or self.app_window.display_mode_dialog is None:
                            from gui.display_mode import DisplayModeDialog
                            self.app_window.display_mode_dialog = DisplayModeDialog(self.app_window)
                            print("   🔧 Created DisplayModeDialog")
                        
                        dlg = self.app_window.display_mode_dialog
                        
                        # Initialize structures if needed
                        if not hasattr(dlg, 'view_palettes'):
                            dlg.view_palettes = {}
                        if not hasattr(dlg, 'view_borders'):
                            dlg.view_borders = {}
                        if not hasattr(dlg, 'slot_shows'):
                            dlg.slot_shows = {}
                        
                        # ============================================================================
                        # ✅ STEP 1: UPDATE THE SLOT DROPDOWN TO SHOW THE TARGET VIEW
                        # ============================================================================
                        print(f"\n   🔄 SWITCHING DISPLAY MODE DIALOG TO VIEW {target_view}")
                        
                        # Update current_slot
                        dlg.current_slot = target_view
                        
                        # ✅ Update the slot dropdown widget
                        slot_widget = None
                        for attr_name in ['slot_box', 'slot_combo', 'view_combo', 'view_selector']:
                            if hasattr(dlg, attr_name):
                                slot_widget = getattr(dlg, attr_name)
                                if slot_widget is not None:
                                    slot_widget.blockSignals(True)
                                    slot_widget.setCurrentIndex(target_view)
                                    slot_widget.blockSignals(False)
                                    print(f"   ✅ Updated {attr_name} to index {target_view}")
                                    break
                        
                        if slot_widget is None:
                            print(f"   ⚠️ Could not find slot dropdown widget")
                        
                        # ============================================================================
                        # ✅ STEP 2: PROCESS PRESET DATA INTO DIALOG STATE
                        # ============================================================================
                        for view_idx_str, classes in views.items():
                            view_idx = int(view_idx_str)
                            
                            print(f"   🔍 Processing View {view_idx} with {len(classes)} classes")
                            
                            # Deep copy to view_palettes
                            dlg.view_palettes[view_idx] = {}
                            if view_idx not in dlg.slot_shows:
                                dlg.slot_shows[view_idx] = {}
                            
                            for code, info in classes.items():
                                code_int = int(code)
                                dlg.view_palettes[view_idx][code_int] = {
                                    "show": info.get("show", False),
                                    "description": info.get("description", ""),
                                    "color": tuple(info.get("color", (128, 128, 128))),
                                    "weight": float(info.get("weight", 1.0)),
                                    "draw": info.get("draw", ""),
                                    "lvl": info.get("lvl", "")
                                }
                                dlg.slot_shows[view_idx][code_int] = info.get("show", False)
                            
                            dlg.view_borders[view_idx] = border_percent
                            
                            visible = [c for c, i in dlg.view_palettes[view_idx].items() if i.get("show")]
                            print(f"   ✅ View {view_idx}: {len(visible)} visible classes")

                        # ============================================================================
                        # ✅ STEP 3: SYNC TO APP_WINDOW - ONLY the target view
                        # ============================================================================
                        if not hasattr(self.app_window, 'view_palettes'):
                            self.app_window.view_palettes = {}
                        
                        for view_idx_str, classes in views.items():
                            view_idx = int(view_idx_str)
                            self.app_window.view_palettes[view_idx] = {}
                            
                            for code, info in classes.items():
                                code_int = int(code)
                                preset_weight = info.get("weight", 1.0)
                                
                                self.app_window.view_palettes[view_idx][code_int] = {
                                    "show": info.get("show", False),
                                    "description": info.get("description", ""),
                                    "color": tuple(info.get("color", (128, 128, 128))),
                                    "weight": preset_weight,
                                    "draw": info.get("draw", ""),
                                    "lvl": info.get("lvl", "")
                                }
                                
                                # ✅ CRITICAL FIX: ONLY sync to class_palette if this is Main View (0)
                                if view_idx == 0 and code_int in self.app_window.class_palette:
                                    self.app_window.class_palette[code_int]["show"] = info.get("show", False)
                                    self.app_window.class_palette[code_int]["weight"] = preset_weight

                        # ✅ Log what was synced
                        for view_idx in views.keys():
                            view_idx = int(view_idx)
                            if view_idx == 0:
                                print(f"   ✅ Synced to app.view_palettes[{view_idx}] AND app.class_palette")
                            else:
                                print(f"   ✅ Synced to app.view_palettes[{view_idx}] ONLY (Main View untouched)")

                        # ============================================================================
                        # ✅ STEP 4: REFRESH DIALOG UI FOR TARGET VIEW
                        # ============================================================================
                        if dlg.isVisible():
                            print(f"\n   🔄 REFRESHING DIALOG UI FOR TARGET VIEW {target_view}")
                            
                            dlg.blockSignals(True)
                            try:
                                # Reload checkboxes
                                if hasattr(dlg, '_load_slot_checkboxes'):
                                    dlg._load_slot_checkboxes(target_view)
                                    print(f"   ✅ Checkboxes reloaded")
                                
                                # Reload weights
                                if hasattr(dlg, '_load_slot_weights'):
                                    dlg._load_slot_weights(target_view)
                                    print(f"   ✅ Weights reloaded")
                                
                                # Update border display
                                if hasattr(dlg, 'load_view_border'):
                                    dlg.load_view_border(target_view)
                                
                                if hasattr(dlg, 'border_label'):
                                    dlg.border_label.setText(f"🔳 Border: {border_percent}%")
                                if hasattr(dlg, 'border_value_display'):
                                    dlg.border_value_display.setText(f"{border_percent}%")
                                if hasattr(dlg, 'border_slider'):
                                    dlg.border_slider.blockSignals(True)
                                    dlg.border_slider.setValue(int(border_percent))
                                    dlg.border_slider.blockSignals(False)
                                
                                # Update window title
                                view_name = view_names[target_view] if target_view < len(view_names) else f"View {target_view}"
                                dlg.setWindowTitle(f"Display Mode - {view_name} ✓")
                                print(f"   ✅ Title updated to: {view_name}")
                                
                            finally:
                                dlg.blockSignals(False)
                        
                        # ============================================================================
                        # ✅ STEP 4B: SYNC class_palette - ONLY if target is Main View
                        # ============================================================================
                        print(f"\n   🔄 CHECKING IF MAIN VIEW SYNC NEEDED (target={target_view})")
                        
                        if target_view == 0:
                            # Main View - sync to class_palette
                            if target_view in self.app_window.view_palettes:
                                for code, info in self.app_window.view_palettes[target_view].items():
                                    if code in self.app_window.class_palette:
                                        self.app_window.class_palette[code]["show"] = info.get("show", False)
                                        self.app_window.class_palette[code]["weight"] = info.get("weight", 1.0)
                                print(f"   ✅ class_palette synced from view_palettes[0]")
                        else:
                            # Cross-section or Cut View - DO NOT touch class_palette
                            print(f"   ⏭️  Skipped class_palette sync (View {target_view}, not Main View)")
                            print(f"   ✅ Main View class_palette UNCHANGED")

                        # ============================================================================
                        # ✅ STEP 5: CHECK CURRENT DISPLAY MODE AND ADJUST BORDERS
                        # ============================================================================
                        current_display_mode = getattr(self.app_window, 'display_mode', 'class')
                        print(f"\n   🎨 CURRENT DISPLAY MODE: {current_display_mode}")

                        if current_display_mode in ['depth', 'rgb', 'intensity']:
                            print(f"   🔳 Forcing borders to 0 for {current_display_mode} mode")
                            border_percent = 0
                            self.app_window.point_border_percent = 0
                            self.app_window._main_view_borders_active = False
                            dlg.view_borders[target_view] = 0
                            
                            if dlg.isVisible():
                                if hasattr(dlg, 'border_label'):
                                    dlg.border_label.setText(f"🔳 Border: 0%")
                                if hasattr(dlg, 'border_value_display'):
                                    dlg.border_value_display.setText("0%")
                                if hasattr(dlg, 'border_slider'):
                                    dlg.border_slider.blockSignals(True)
                                    dlg.border_slider.setValue(0)
                                    dlg.border_slider.blockSignals(False)
                        else:
                            print(f"   🔳 Using preset border {border_percent}% for classification mode")
                            if target_view == 0:  # Only set border for Main View
                                self.app_window.point_border_percent = border_percent
                                self.app_window._main_view_borders_active = (border_percent > 0)

                        # ============================================================================
                        # ✅ STEP 6: REFRESH VIEWS
                        # ============================================================================
                        self.app_window._preserve_shortcut_visibility = True

                        # Main View refresh - ONLY if target is Main View (0)
                        if target_view == 0 and 0 in views:
                            dlg.view_borders[0] = border_percent
                            
                            from gui.class_display import update_class_mode
                            self.app_window._preserve_view = True
                            update_class_mode(self.app_window, force_refresh=True)
                            print(f"   ✅ Main view refreshed with border={border_percent}%")

                        # Cross-section views refresh
                        all_section_views = [v for v in views.keys() if 1 <= int(v) <= 5]
                        if all_section_views:
                            print(f"\n   🔄 SYNCING SECTION VIEWS: {all_section_views}")
                            for view_idx_str in all_section_views:
                                view_idx = int(view_idx_str)

                                # Handle Cut Section (View 5) separately
                                if view_idx == 5:
                                    if hasattr(self.app_window, 'cut_vtk') and self.app_window.cut_vtk is not None:
                                        try:
                                            print(f"\n      🔪 REFRESHING CUT SECTION (View 5)")
                                            self._refresh_cut_section(view_idx)
                                            print(f"      ✅ Cut Section refreshed")
                                        except Exception as e:
                                            print(f"      ⚠️ Cut Section refresh failed: {e}")
                                            import traceback
                                            traceback.print_exc()
                                    continue

                                # Cross-Sections (Views 1-4) — use unified actor
                                view_index = view_idx - 1

                                if not (hasattr(self.app_window, 'section_vtks') and view_index in self.app_window.section_vtks):
                                    continue

                                try:
                                    from gui.unified_actor_manager import build_section_unified_actor

                                    # ── palette is already written into dlg.view_palettes[view_idx]
                                    # ── and app.view_palettes[view_idx] by STEP 2/3 above.
                                    # ── build_section_unified_actor() reads _get_slot_palette(app, slot_idx)
                                    # ── where slot_idx = view_idx (== view_index + 1), so it will pick
                                    # ── up the new palette automatically.
                                    # ── It also removes the existing unified actor + any stale class_*
                                    # ── actors internally, so no manual actor cleanup is needed here.

                                    actor = build_section_unified_actor(
                                        self.app_window,
                                        view_index,          # 0-based
                                        border_percent=border_percent,
                                    )

                                    if actor is not None:
                                        slot_idx = view_idx          # slot_idx == view_idx for sections
                                        visible = [
                                            c for c, info in
                                            self.app_window.view_palettes.get(view_idx, {}).items()
                                            if info.get("show", False)
                                        ]
                                        print(f"      👁️ Visible in View {view_idx}: {sorted(visible)}")
                                        print(f"      ✅ Synced View {view_idx}: unified actor rebuilt "
                                              f"({len(visible)} classes visible)")
                                    else:
                                        print(f"      ⚠️ View {view_idx}: no data yet — skipped")

                                except Exception as e:
                                    print(f"      ⚠️ View {view_idx} sync failed: {e}")
                                    import traceback
                                    traceback.print_exc()
                        
                        # Status message
                        total_visible = sum(
                            sum(1 for c in classes.values() if c.get("show"))
                            for classes in views.values()
                        )
                        
                        if hasattr(self.app_window, 'statusBar'):
                            view_names_short = []
                            for v in sorted([int(x) for x in views.keys()]):
                                if v == 0: view_names_short.append("Main")
                                elif v == 5: view_names_short.append("Cut")
                                else: view_names_short.append(f"V{v}")
                            
                            self.app_window.statusBar().showMessage(
                                f"✅ DisplayMode: {view_names_short[0]} active, {total_visible} classes visible",
                                2500
                            )
                        
                        print(f"   ✅ DisplayMode shortcut complete - {view_names[target_view]} now active")
                        print(f"{'='*60}\n")
                        
                    except Exception as e:
                        print(f"⚠️ Failed to apply DisplayMode preset: {e}")
                        import traceback
                        traceback.print_exc()
                    
                    finally:
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(1000, lambda: setattr(self.app_window, '_preserve_shortcut_visibility', False))

                    return True
                    
                if tool == "ShadingMode":
                    preset = shortcut.get("preset")
                    print(f"✅ SHORTCUT MATCH: {combo} → ShadingMode")

                    if not preset:
                        print("⚠️ ShadingMode shortcut has no preset")
                        return True

                    try:
                        print(f"\n{'='*60}")
                        print(f"🌗 APPLYING SHADINGMODE PRESET FROM SHORTCUT")
                        print(f"{'='*60}")

                        # STEP 1: Hide classification point actors
                        if hasattr(self.app_window, 'vtk_widget'):
                            for name in list(self.app_window.vtk_widget.actors.keys()):
                                if str(name).startswith("class_"):
                                    self.app_window.vtk_widget.actors[name].SetVisibility(False)

                        # STEP 2: Set display mode
                        self.app_window.display_mode = "shaded_class"
                        if hasattr(self.app_window, 'current_display_mode'):
                            self.app_window.current_display_mode = "shaded_class"

                        # STEP 3: Reset ALL classes hidden, apply preset visibility
                        classes = preset.get("classes", {})

                        # ✅ Reset ALL to hidden first
                        if hasattr(self.app_window, 'class_palette'):
                            for code in self.app_window.class_palette:
                                self.app_window.class_palette[code]["show"] = False

                        visible_set = set()
                        if classes:
                            for code, info in classes.items():
                                code_int = int(code)
                                if code_int in self.app_window.class_palette:
                                    is_visible = info.get("show", False)
                                    self.app_window.class_palette[code_int]["show"] = is_visible
                                    if is_visible:
                                        visible_set.add(code_int)
                        else:
                            if hasattr(self.app_window, 'class_palette'):
                                for code in self.app_window.class_palette:
                                    self.app_window.class_palette[code]["show"] = True
                                    visible_set.add(int(code))

                        visible_count = len(visible_set)
                        print(f"   ✅ Visible classes: {sorted(visible_set)}")

                        # ✅ Set override BEFORE calling update_shaded_class
                        self.app_window._shading_visibility_override = visible_set

                        # STEP 4: ✅ CRITICAL FIX - Sync to display_mode_dialog AND UPDATE CHECKBOXES
                        if hasattr(self.app_window, 'display_mode_dialog') and \
                        self.app_window.display_mode_dialog is not None:
                            dlg = self.app_window.display_mode_dialog
                            
                            if not hasattr(dlg, 'view_palettes'):
                                dlg.view_palettes = {}
                            if 0 not in dlg.view_palettes:
                                dlg.view_palettes[0] = {}
                            
                            # Sync visibility to dialog palette
                            for code, entry in self.app_window.class_palette.items():
                                dlg.view_palettes[0][int(code)] = {
                                    "show": entry.get("show", False),
                                    "color": entry.get("color", (128, 128, 128)),
                                    "weight": entry.get("weight", 1.0),
                                }
                            
                            # ✅ CRITICAL FIX: Update the actual checkboxes in the table
                            if hasattr(dlg, 'table') and dlg.table is not None:
                                print(f"   🔄 Updating Display Mode dialog checkboxes...")
                                
                                for row in range(dlg.table.rowCount()):
                                    try:
                                        code_item = dlg.table.item(row, 1)
                                        if not code_item:
                                            continue
                                        
                                        code = int(code_item.text())
                                        chk = dlg.table.cellWidget(row, 0)
                                        
                                        if chk:
                                            # Block signals to prevent triggering updates
                                            chk.blockSignals(True)
                                            
                                            # Set checkbox based on visibility
                                            is_visible = (code in visible_set)
                                            chk.setChecked(is_visible)
                                            
                                            # Unblock signals
                                            chk.blockSignals(False)
                                            
                                            print(f"      Class {code}: {'✓' if is_visible else '✗'}")
                                    except Exception as e:
                                        print(f"      ⚠️ Row {row} error: {e}")
                                        continue
                                
                                print(f"   ✅ Updated {dlg.table.rowCount()} checkboxes")
                            
                            # ✅ Also update slot_shows for this view
                            if not hasattr(dlg, 'slot_shows'):
                                dlg.slot_shows = {}
                            if 0 not in dlg.slot_shows:
                                dlg.slot_shows[0] = {}
                            
                            for code in self.app_window.class_palette:
                                dlg.slot_shows[0][int(code)] = (int(code) in visible_set)
                            
                            print(f"   ✅ Synced to display_mode_dialog slot 0")

                        # STEP 5: Clear shading cache
                        try:
                            from gui.shading_display import clear_shading_cache
                            clear_shading_cache("shading shortcut applied")
                        except Exception as e:
                            print(f"   ⚠️ Could not clear shading cache: {e}")

                        # STEP 6: Store params
                        azimuth = preset.get("azimuth", 45.0)
                        angle   = preset.get("angle",   45.0)
                        ambient = preset.get("ambient",  0.2)

                        self.app_window.last_shade_azimuth = azimuth
                        self.app_window.last_shade_angle   = angle
                        self.app_window.shade_ambient      = ambient

                        # STEP 7: Apply shading with override STILL SET
                        from gui.shading_display import update_shaded_class
                        update_shaded_class(
                            self.app_window,
                            azimuth=azimuth,
                            angle=angle,
                            ambient=ambient,
                            force_rebuild=True
                        )

                        # ✅ Clear override AFTER shading is complete
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(100, lambda: setattr(self.app_window, '_shading_visibility_override', None))

                        print(f"   ✅ Shading done: az={azimuth}° angle={angle}° | {visible_count} classes")
                        print(f"{'='*60}\n")

                        if hasattr(self.app_window, 'statusBar'):
                            self.app_window.statusBar().showMessage(
                                f"🌗 ShadingMode: {azimuth}°/{angle}°, {visible_count} classes visible",
                                2500
                            )

                    except Exception as e:
                        self.app_window._shading_visibility_override = None
                        print(f"⚠️ Failed to apply ShadingMode preset: {e}")
                        import traceback
                        traceback.print_exc()

                    return True
                    ####
                
                if tool == "DrawSettings":
                    preset = shortcut.get("preset")
                    print(f"✅ SHORTCUT MATCH: {combo} → DrawSettings")

                    if not preset:
                        print("⚠️ DrawSettings shortcut has no preset")
                        return True

                    try:
                        print(f"\n{'='*60}")
                        print(f"🎨 APPLYING DRAW SETTINGS PRESET FROM SHORTCUT")
                        print(f"{'='*60}")

                        tools = preset.get("tools", {})

                        # Apply to digitizer
                        if hasattr(self.app_window, 'digitizer') and \
                                hasattr(self.app_window.digitizer, 'draw_tool_styles'):
                            for tool_key, style in tools.items():
                                self.app_window.digitizer.draw_tool_styles[tool_key] = dict(style)
                            print(f"   ✅ Applied {len(tools)} tool styles to digitizer")
                        else:
                            print("   ⚠️ Digitizer not available, styles saved to QSettings only")

                        # Persist to QSettings
                        from gui.draw_settings_dialog import save_draw_settings
                        save_draw_settings(tools)
                        print(f"   ✅ Saved to QSettings")

                        # ✅ Activate the digitizer and set the chosen tool
                        active_tool = preset.get("active_tool", "smartline")
                        if hasattr(self.app_window, 'digitizer') and self.app_window.digitizer:
                            digi = self.app_window.digitizer
                            # Enable digitizer if not already enabled
                            if hasattr(digi, 'enable'):
                                digi.enable(True)
                            elif hasattr(digi, 'enabled'):
                                digi.enabled = True

                            # Activate the user's chosen tool
                            if hasattr(digi, 'set_tool'):
                                digi.set_tool(active_tool)
                                print(f"   ✅ Activated digitizer with tool: {active_tool}")
                            elif hasattr(digi, 'active_tool'):
                                digi.active_tool = active_tool
                                print(f"   ✅ Set digitizer active_tool: {active_tool}")
                            else:
                                print(f"   ✅ Digitizer enabled (set_tool not available)")
                        else:
                            print("   ⚠️ Digitizer not found, only styles saved")

                        # Refresh DrawToolSettingsDialog if open
                        if hasattr(self.app_window, 'draw_settings_dialog') and \
                                self.app_window.draw_settings_dialog is not None and \
                                self.app_window.draw_settings_dialog.isVisible():
                            try:
                                self.app_window.draw_settings_dialog._load_styles()
                                print(f"   ✅ Refreshed Draw Settings dialog")
                            except Exception:
                                pass

                        if hasattr(self.app_window, 'statusBar'):
                            self.app_window.statusBar().showMessage(
                                f"🎨 DrawSettings applied + {active_tool} activated ({len(tools)} tools updated)",
                                2500
                            )

                        print(f"   ✅ DrawSettings shortcut complete")
                        print(f"{'='*60}\n")

                    except Exception as e:
                        print(f"⚠️ Failed to apply DrawSettings preset: {e}")
                        import traceback
                        traceback.print_exc()

                    return True

                if not shortcut:
                   return False 
                
                # ✅ Existing shortcuts (classification tools)
                from_cls = shortcut.get("from")
                to_cls = shortcut.get("to")
                
                print(f"✅ SHORTCUT MATCH: {combo} → {tool}, from={from_cls}, to={to_cls}")
                execute_tool(self.app_window, tool, from_cls, to_cls)
                return True            
            return False
             
    def _refresh_cut_section(self, view_idx):
        """
        ✅ Refresh Cut Section (View 5) with current classifications
        """
        import numpy as np
        import pyvista as pv
        
        print(f"\n{'='*60}")
        print(f"🔪 REFRESHING CUT SECTION")
        print(f"{'='*60}")
        
        try:
            vtk_widget = self.app_window.cut_vtk
            
            # Get cut section data
            cut_points = getattr(self.app_window, 'cut_section_points', None)
            cut_mask = getattr(self.app_window, 'cut_section_mask', None)
            
            if cut_points is None or cut_mask is None or len(cut_points) == 0:
                print("   ⚠️ No cut section data")
                return
            
            # Save camera
            try:
                cam_pos = vtk_widget.camera_position
            except:
                cam_pos = None
            
            # Clear existing actors
            actors_to_remove = [name for name in list(vtk_widget.actors.keys()) 
                              if name.startswith('class_')]
            for name in actors_to_remove:
                vtk_widget.remove_actor(name, render=False)
            
            print(f"   🗑️ Cleared {len(actors_to_remove)} existing actors")
            
            # Get View 5 palette
            view_palette = self.app_window.view_palettes.get(5, {})
            visible = [c for c, info in view_palette.items() if info.get("show", False)]
            
            print(f"   👁️ Visible classes in Cut Section: {visible}")
            
            # Get current classifications
            current_classes = self.app_window.data["classification"]
            cut_cls = current_classes[cut_mask]
            
            # Rebuild with current data
            for cls_val in visible:
                cls_mask = (cut_cls == cls_val)
                cls_pts = cut_points[cls_mask]
                
                if len(cls_pts) == 0:
                    continue
                
                entry = view_palette.get(int(cls_val), {})
                color = entry.get("color", (128, 128, 128))
                point_size = 5.0
                
                cls_colors = np.array([color] * len(cls_pts), dtype=np.uint8)
                cls_cloud = pv.PolyData(cls_pts)
                cls_cloud["RGB"] = cls_colors
                
                vtk_widget.add_points(
                    cls_cloud,
                    scalars="RGB",
                    rgb=True,
                    point_size=point_size,
                    render_points_as_spheres=True,
                    reset_camera=False,
                    name=f"class_{cls_val}",
                    render=False
                )
                
                print(f"      ✅ Added class {cls_val}: {len(cls_pts)} points")
            
            # Restore camera
            if cam_pos:
                try:
                    vtk_widget.camera_position = cam_pos
                except:
                    pass
            
            vtk_widget.render()
            print(f"   ✅ Cut Section refreshed with {len(visible)} visible classes")
            print(f"{'='*60}\n")
            
        except Exception as e:
            print(f"⚠️ Cut section refresh failed: {e}")
            import traceback
            traceback.print_exc()
            print(f"{'='*60}\n")
 

    def _handle_context_fit_view(self):
        """
        ✅ Context-aware fit view - fits the ACTIVE window
    
        Priority:
        1. Cross-section view (if focused)
        2. Main view (if focused or no cross-section)
        3. Cut section (future support)
        """
    
        # Get the currently focused widget
        from PySide6.QtWidgets import QApplication
        focused = QApplication.focusWidget()
    
        print(f"   🔍 Focused widget: {type(focused).__name__}")
    
        # ====================================================================
        # PRIORITY 1: Check if a cross-section view is focused
        # ====================================================================
        if hasattr(self.app_window, 'section_vtks') and self.app_window.section_vtks:
            for view_idx, vtk_widget in self.app_window.section_vtks.items():
                try:
                    # Check if THIS cross-section view has focus
                    if (focused == vtk_widget.interactor or
                        vtk_widget.interactor.isAncestorOf(focused)):
                    
                        print(f"   🎯 Fitting Cross-Section View {view_idx + 1}")
                        self._fit_cross_section_view(view_idx, vtk_widget)
                    
                        if hasattr(self.app_window, 'statusBar'):
                            self.app_window.statusBar().showMessage(
                                f"🧲 Cross-Section {view_idx + 1} fitted & locked (Shift+F)",
                                1500
                            )
                        return
                except Exception as e:
                    print(f"   ⚠️ Error checking view {view_idx}: {e}")
    
        # ====================================================================
        # PRIORITY 2: Main view (default) with 2D lock
        # ====================================================================
        print(f"   🎯 Fitting Main View with 2D lock")
        self._fit_main_view_with_2d_lock()
    
        if hasattr(self.app_window, 'statusBar'):
            self.app_window.statusBar().showMessage(
                "🧲 Main View fitted & locked (Shift+F)",
                1500
            )
            
            
    def _fit_cross_section_view(self, view_idx, vtk_widget):
        """
        ✅ Restore cross-section view to ORIGINAL STATE (like "Side" button)
        ✅ Reset camera to original coordinates & 2D projection
        ✅ COMPLETELY DISABLE 3D rotation - LOCKED in 2D (SAFE MODE)
        ✅ PRESERVE classification tools - they stay active after Shift+F
        ✅ DEBOUNCED - Prevents crashes from multiple rapid presses

        Args:
            view_idx: View index (0, 1, 2, 3...)
            vtk_widget: The VTK widget to restore
        """
        import numpy as np
        import time

        # ====================================================================
        # DEBOUNCE CHECK - Prevent multiple rapid calls
        # ====================================================================
        if not hasattr(self, '_fit_cross_section_last_call'):
            self._fit_cross_section_last_call = {}
        
        current_time = time.time()
        last_call_time = self._fit_cross_section_last_call.get(view_idx, 0)
        
        # Ignore calls within 500ms of previous call
        if current_time - last_call_time < 0.5:
            print(f"   ⏭️ Ignoring rapid Shift+F press (debounce)")
            return
        
        # Update last call time
        self._fit_cross_section_last_call[view_idx] = current_time
        
        # ====================================================================
        # EXECUTION LOCK - Prevent concurrent execution
        # ====================================================================
        if not hasattr(self, '_fit_cross_section_executing'):
            self._fit_cross_section_executing = {}
        
        if self._fit_cross_section_executing.get(view_idx, False):
            print(f"   ⏭️ Already executing for view {view_idx}, ignoring...")
            return
        
        # Set execution flag
        self._fit_cross_section_executing[view_idx] = True

        print(f"\n{'='*60}")
        print(f"🔄 RESET CROSS-SECTION VIEW {view_idx + 1} TO ORIGINAL STATE")
        print(f"{'='*60}")

        try:
            # Get section data
            core_points = getattr(self.app_window, f'section_{view_idx}_core_points', None)
            core_mask = getattr(self.app_window, f'section_{view_idx}_core_mask', None)
        
            if core_points is None or len(core_points) == 0:
                print(f"   ⚠️ No data in this view")
                self._fit_cross_section_executing[view_idx] = False
                return

            # ====================================================================
            # Get ORIGINAL section plane info
            # ====================================================================
            section_axis = getattr(self.app_window, f'section_{view_idx}_axis', 'X')
            section_position = getattr(self.app_window, f'section_{view_idx}_position', 0.0)
        
            print(f"   📋 Original plane: {section_axis}-axis at {section_position}")

            # ====================================================================
            # Calculate bounds from ORIGINAL section data
            # ====================================================================
            xmin, xmax = core_points[:, 0].min(), core_points[:, 0].max()
            ymin, ymax = core_points[:, 1].min(), core_points[:, 1].max()
            zmin, zmax = core_points[:, 2].min(), core_points[:, 2].max()

            center_x = (xmin + xmax) / 2.0
            center_y = (ymin + ymax) / 2.0
            center_z = (zmin + zmax) / 2.0

            width = (xmax - xmin) * 1.1
            height = (ymax - ymin) * 1.1
            depth = (zmax - zmin) * 1.1

            print(f"   📏 Section bounds:")
            print(f"      X: {xmin:.2f} → {xmax:.2f}")
            print(f"      Y: {ymin:.2f} → {ymax:.2f}")
            print(f"      Z: {zmin:.2f} → {zmax:.2f}")

            # ====================================================================
            # SAVE CURRENT INTERACTOR STYLE (classification tool) BEFORE changes
            # ====================================================================
            interactor = vtk_widget.interactor
            saved_interactor_style = None
            has_classification_tool = False
            active_tool_name = None
            
            if interactor is not None:
                current_style = interactor.GetInteractorStyle()
                if current_style is not None:
                    # Save the current style
                    saved_interactor_style = current_style
                    style_class_name = current_style.GetClassName()
                    
                    # Check if it's a classification tool
                    if 'PointPicker' in style_class_name or 'AreaSelector' in style_class_name:
                        has_classification_tool = True
                        active_tool_name = style_class_name
                        print(f"   💾 SAVED classification tool: {style_class_name}")

            # ====================================================================
            # Setup camera for ORIGINAL view (like the "Side" button)
            # ====================================================================
            renderer = vtk_widget.renderer
            camera = renderer.GetActiveCamera()

            # Enforce orthographic (2D) projection
            camera.ParallelProjectionOn()
            print(f"   🔒 Orthographic projection ENABLED")

            ## ====================================================================
            # ✅ CHECK: If already in 2D locked mode, just re-fit WITHOUT changing orientation
            # ====================================================================
            if (hasattr(self.app_window, '_cross_section_2d_mode') and 
                view_idx in self.app_window._cross_section_2d_mode and
                self.app_window._cross_section_2d_mode[view_idx].get('is_2d_locked', False)):
                
                print(f"   ℹ️ Already in 2D mode - just re-fitting bounds, keeping orientation")
                
                # Just reset the parallel scale (zoom) without changing orientation
                camera = renderer.GetActiveCamera()
                
                if section_axis == 'X':
                    scale = max(height, depth) / 2.0
                elif section_axis == 'Y':
                    scale = max(width, depth) / 2.0
                elif section_axis == 'Z':
                    scale = max(width, height) / 2.0
                else:
                    scale = max(width, height, depth) / 2.0
                
                camera.SetParallelScale(scale)
                renderer.ResetCameraClippingRange()
                vtk_widget.render()
                
                print(f"   ✅ Re-fitted without changing orientation")
                self._fit_cross_section_executing[view_idx] = False
                return  # ✅ EXIT - don't reset camera orientation

            # ====================================================================
            # Setup camera for ORIGINAL view (only runs on FIRST Shift+F)
            # ====================================================================
            # Reset to ORIGINAL orientation based on section axis
            if section_axis == 'X':
                # X-axis slice: looking along X (from negative Y direction)
                # Shows Y-Z plane
                max_dim = max(height, depth)
                pos = (center_x, center_y - max_dim * 2, center_z)
                focal = (center_x, center_y, center_z)
                view_up = (0, 0, 1)
                scale = max(height, depth) / 2.0
                
                camera.SetPosition(*pos)
                camera.SetFocalPoint(*focal)
                camera.SetViewUp(*view_up)
                camera.SetParallelScale(scale)
                
                print(f"   📐 Reset to X-axis slice view (Y-Z plane)")

            elif section_axis == 'Y':
                # Y-axis slice: looking along Y (from positive X direction)
                # Shows X-Z plane
                max_dim = max(width, depth)
                pos = (center_x + max_dim * 2, center_y, center_z)
                focal = (center_x, center_y, center_z)
                view_up = (0, 0, 1)
                scale = max(width, depth) / 2.0
                
                camera.SetPosition(*pos)
                camera.SetFocalPoint(*focal)
                camera.SetViewUp(*view_up)
                camera.SetParallelScale(scale)
                
                print(f"   📐 Reset to Y-axis slice view (X-Z plane)")

            elif section_axis == 'Z':
                # Z-axis slice: looking along Z (from positive Z direction)
                # Shows X-Y plane
                max_dim = max(width, height)
                pos = (center_x, center_y, center_z + max_dim * 2)
                focal = (center_x, center_y, center_z)
                view_up = (0, 1, 0)
                scale = max(width, height) / 2.0
                
                camera.SetPosition(*pos)
                camera.SetFocalPoint(*focal)
                camera.SetViewUp(*view_up)
                camera.SetParallelScale(scale)
                
                print(f"   📐 Reset to Z-axis slice view (X-Y plane)")

            # Store LOCKED camera parameters
            locked_params = {
                'position': camera.GetPosition(),
                'focal_point': camera.GetFocalPoint(),
                'view_up': camera.GetViewUp(),
                'parallel_scale': camera.GetParallelScale(),
                'view_angle': camera.GetViewAngle()
            }

            # Update clipping range
            renderer.ResetCameraClippingRange()
            # ====================================================================
            # ✅ SAFE 2D LOCK - DISABLE ROTATION WITHOUT CRASHING
            # ====================================================================
            if interactor is not None:
                try:
                    # ================================================================
                    # Remove existing observers safely to prevent conflicts
                    # ================================================================
                    try:
                        renderer.RemoveObservers('StartEvent')
                        renderer.RemoveObservers('EndEvent')
                        renderer.RemoveObservers('ModifiedEvent')
                        camera.RemoveObservers('ModifiedEvent')
                    except Exception as obs_err:
                        print(f"   ℹ️ Note: Could not remove some observers: {obs_err}")
                    
                    # ================================================================
                    # ✅ CRITICAL FIX: Re-entry guard and throttling
                    # ================================================================
                    # Create closure variables
                    _enforcing = [False]
                    _last_enforce = [0.0]
                    
                    def enforce_camera_lock(obj, event):
                        """SAFELY lock camera - prevent rotation without crashing"""
                        
                        # ✅ RE-ENTRY GUARD - Prevent recursive calls
                        if _enforcing[0]:
                            return
                        
                        # ✅ THROTTLE - Max 30fps to prevent event cascade
                        import time
                        current_time = time.time()
                        if current_time - _last_enforce[0] < 0.033:  # 30fps
                            return
                        _last_enforce[0] = current_time
                        
                        _enforcing[0] = True
                        try:
                            cam = renderer.GetActiveCamera()
                            
                            # Force parallel projection
                            cam.ParallelProjectionOn()
                            
                            # Get current values
                            current_pos = np.array(cam.GetPosition())
                            current_focal = np.array(cam.GetFocalPoint())
                            current_up = np.array(cam.GetViewUp())
                            
                            locked_pos = np.array(locked_params['position'])
                            locked_focal = np.array(locked_params['focal_point'])
                            locked_up = np.array(locked_params['view_up'])
                            
                            # Calculate view directions
                            current_dir = current_focal - current_pos
                            locked_dir = locked_focal - locked_pos
                            
                            # Normalize
                            current_dir_norm = current_dir / (np.linalg.norm(current_dir) + 1e-10)
                            locked_dir_norm = locked_dir / (np.linalg.norm(locked_dir) + 1e-10)
                            
                            # Check if direction has changed (rotation)
                            direction_dot = np.dot(current_dir_norm, locked_dir_norm)
                            
                            # Check if view up has changed
                            up_dot = np.dot(current_up, locked_up)
                            
                            # If ANY rotation detected, FORCE restore
                            if direction_dot < 0.9999 or up_dot < 0.9999:
                                # Block rotation by restoring RELATIVE geometry
                                # Keep the OFFSET between focal and position (preserves zoom)
                                # But enforce locked direction
                                
                                current_distance = np.linalg.norm(current_dir)
                                
                                # Calculate how much the focal point has moved (pan delta)
                                focal_delta = current_focal - locked_focal
                                
                                # Apply same delta to position (keep them moving together)
                                new_position = locked_pos + focal_delta - (locked_dir_norm * current_distance) + (locked_dir_norm * np.linalg.norm(locked_dir))
                                new_focal = locked_focal + focal_delta
                                
                                cam.SetPosition(*new_position)
                                cam.SetFocalPoint(*new_focal)
                                cam.SetViewUp(*locked_up)
                                renderer.ResetCameraClippingRange()
                                # ✅ NO RENDER - Let normal render cycle handle it
                                # vtk_widget.render()  # ❌ This causes cascade!
                        
                        finally:
                            _enforcing[0] = False
                    
                    # ✅ Use ONLY ONE observer to minimize event firing
                    camera.AddObserver('ModifiedEvent', enforce_camera_lock)
                    
                    print(f"   🔒 SAFE camera lock installed")
                    print(f"   ✓ Single observer with re-entry guard")
                    print(f"   ✓ Throttled to 30fps")
                    
                    # ================================================================
                    # RESTORE SAVED INTERACTOR STYLE (classification tool)
                    # ================================================================
                    # ✅ FORCE 2D-only interactor style (no rotation allowed)
                    # ✅ Use Image style which allows BOTH horizontal AND vertical panning
                    from vtkmodules.vtkInteractionStyle import vtkInteractorStyleImage
                    style_2d = vtkInteractorStyleImage()
                    interactor.SetInteractorStyle(style_2d)

                    if has_classification_tool:
                        print(f"   ⚠️ Classification tool was: {active_tool_name} (replaced with 2D pan/zoom)")
                        
                    else:
                        # No saved style - apply default 2D-only style
                        # ✅ Use Image style which allows BOTH horizontal AND vertical panning
                        from vtkmodules.vtkInteractionStyle import vtkInteractorStyleImage
                        style_2d = vtkInteractorStyleImage()
                        interactor.SetInteractorStyle(style_2d)
                    
                    # Store state
                    if not hasattr(self.app_window, '_cross_section_2d_mode'):
                        self.app_window._cross_section_2d_mode = {}
                    
                    self.app_window._cross_section_2d_mode[view_idx] = {
                        'axis': section_axis,
                        'position': section_position,
                        'locked_params': locked_params,
                        'is_2d_locked': True,
                        'renderer': renderer,
                        'camera': camera,
                        'has_classification_tool': has_classification_tool,
                        'saved_interactor_style': saved_interactor_style,
                        'classification_tool_name': active_tool_name
                    }
                
                    print(f"   🔒 2D MODE SAFELY LOCKED")
                    print(f"   ✓ Rotation: DISABLED")
                    print(f"   ✓ Pan/Zoom: ENABLED with locked orientation")
                    if has_classification_tool:
                        print(f"   ✓ Classification tool: STILL ACTIVE")
                
                except Exception as e:
                    print(f"   ⚠️ Could not set 2D lock: {e}")
                    import traceback
                    traceback.print_exc()

            # Final render
            vtk_widget.render()

            print(f"   ✅ View reset to original state ({section_axis}-axis)")
            print(f"   🔒 3D rotation DISABLED (SAFE MODE)")
            print(f"{'='*60}\n")

        except Exception as e:
            print(f"⚠️ Reset cross-section view failed: {e}")
            import traceback
            traceback.print_exc()
            print(f"{'='*60}\n")
        
        finally:
            # ✅ ALWAYS clear execution flag
            self._fit_cross_section_executing[view_idx] = False    
        
    def _fit_main_view_with_2d_lock(self):
        """
        ✅ Fit main view and lock to 2D mode
        ✅ IDEMPOTENT - Safe to press Shift+F multiple times without 3D flash
        ✅ Uses app_window.fit_view() which includes Point Cloud + DXF + SNT bounds
        """
        import numpy as np

        already_locked = getattr(self.app_window, '_main_view_2d_locked', False)

        print(f"\n{'='*60}")
        print(f"🧲 FITTING MAIN VIEW (with SNT/DXF support)")
        print(f"   Already 2D locked: {already_locked}")
        print(f"{'='*60}")

        vtk_widget = self.app_window.vtk_widget
        renderer = vtk_widget.renderer
        camera = renderer.GetActiveCamera()
        interactor = vtk_widget.interactor

        # ====================================================================
        # STEP 1: ALWAYS remove old camera observers FIRST
        #         Prevents old closures from fighting new camera state
        # ====================================================================
        # try:
        #     camera.RemoveObservers('ModifiedEvent')
        #     renderer.RemoveObservers('StartEvent')
        #     renderer.RemoveObservers('EndEvent')
        #     renderer.RemoveObservers('ModifiedEvent')
        # except Exception:
        #     pass
        # print(f"   🧹 Cleared old camera observers")

        measurement_active = (
            hasattr(self.app_window, 'measurement_tool') and
            getattr(self.app_window.measurement_tool, 'active', False)
        )

        if measurement_active:
            # ✅ Measurement active — fit view then re-capture lock params and reinstall observer
            # ⚠️ Must NOT early-return before observer reinstall — old stale observer fights the new camera state
            print(f"   🔒 Measurement active — fitting then refreshing camera lock")

            # Remove stale observers first so fit_view() isn't fought
            try:
                camera.RemoveObservers('ModifiedEvent')
                renderer.RemoveObservers('StartEvent')
                renderer.RemoveObservers('EndEvent')
                renderer.RemoveObservers('ModifiedEvent')
            except Exception:
                pass
            print(f"   🧹 Cleared old camera observers")

            # Save measurement interactor style so fit_view() can't clobber it
            saved_meas_style = None
            try:
                saved_meas_style = interactor.GetInteractorStyle()
            except Exception:
                pass

            # Run fit_view
            if hasattr(self.app_window, 'fit_view'):
                print(f"   📐 Calling fit_view (Point Cloud + DXF + SNT)...")
                self.app_window.fit_view()
                print(f"   ✅ fit_view complete")

            # Restore measurement interactor style
            if saved_meas_style is not None:
                try:
                    interactor.SetInteractorStyle(saved_meas_style)
                    print(f"   ✅ Measurement interactor style restored")
                except Exception as e:
                    print(f"   ⚠️ Could not restore interactor: {e}")

            # Re-capture camera state AFTER fit (new lock target)
            camera.ParallelProjectionOn()
            locked_params = {
                'position': camera.GetPosition(),
                'focal_point': camera.GetFocalPoint(),
                'view_up': camera.GetViewUp(),
                'parallel_scale': camera.GetParallelScale(),
                'view_angle': camera.GetViewAngle()
            }
            self.app_window._main_view_locked_params = locked_params
            print(f"   📸 Captured new lock target after fit")

            # Reinstall fresh camera lock observer with new params
            _enforcing_m = [False]
            _last_enforce_m = [0.0]

            def enforce_camera_lock_measurement(obj, event):
                if _enforcing_m[0]:
                    return
                import time
                current_time = time.time()
                if current_time - _last_enforce_m[0] < 0.033:
                    return
                _last_enforce_m[0] = current_time
                _enforcing_m[0] = True
                try:
                    cam = renderer.GetActiveCamera()
                    cam.ParallelProjectionOn()
                    current_pos = np.array(cam.GetPosition())
                    current_focal = np.array(cam.GetFocalPoint())
                    current_up = np.array(cam.GetViewUp())
                    locked_pos = np.array(locked_params['position'])
                    locked_focal = np.array(locked_params['focal_point'])
                    locked_up = np.array(locked_params['view_up'])
                    current_dir = current_focal - current_pos
                    locked_dir = locked_focal - locked_pos
                    current_dir_norm = current_dir / (np.linalg.norm(current_dir) + 1e-10)
                    locked_dir_norm = locked_dir / (np.linalg.norm(locked_dir) + 1e-10)
                    direction_dot = np.dot(current_dir_norm, locked_dir_norm)
                    up_dot = np.dot(current_up, locked_up)
                    if direction_dot < 0.9999 or up_dot < 0.9999:
                        current_distance = np.linalg.norm(current_dir)
                        new_position = current_focal - (locked_dir_norm * current_distance)
                        cam.SetPosition(*new_position)
                        cam.SetViewUp(*locked_up)
                finally:
                    _enforcing_m[0] = False

            camera.AddObserver('ModifiedEvent', enforce_camera_lock_measurement)
            print(f"   🔒 Fresh camera lock observer installed (measurement)")

            self.app_window._main_view_2d_locked = True
            renderer.ResetCameraClippingRange()
            vtk_widget.render()
            print(f"   🔒 Main view 2D lock REFRESHED")
            print(f"   ✓ Rotation: DISABLED")
            print(f"   ✓ Pan/Zoom: ENABLED with locked orientation")
            print(f"{'='*60}\n")
            return  # ✅ Early exit — interactor style already restored above
        try:
            camera.RemoveObservers('ModifiedEvent')
            renderer.RemoveObservers('StartEvent')
            renderer.RemoveObservers('EndEvent')
            renderer.RemoveObservers('ModifiedEvent')
        except Exception:
            pass
        print(f"   🧹 Cleared old camera observers")
        # ====================================================================
        # STEP 2: Set top view ONLY on FIRST call
        #         Skip if already locked → prevents interactor style reset → no 3D flash
        # ====================================================================
        if not already_locked:
            print(f"   🔄 Forcing TOP view (first lock)...")
            from gui.views import set_view
            self.app_window._preserve_view = False
            set_view(self.app_window, "top")
            print(f"   ✅ Switched to TOP view")
        else:
            # Already in 2D mode — just ensure parallel projection stays on
            camera.ParallelProjectionOn()
            print(f"   ℹ️ Already 2D locked — re-fitting bounds only (no view reset)")

        # ====================================================================
        # STEP 3: Fit view (Point Cloud + DXF + SNT)
        #         Camera observers are REMOVED so fit_view won't be fought
        # ====================================================================
        if hasattr(self.app_window, 'fit_view'):
            print(f"   📐 Calling fit_view (Point Cloud + DXF + SNT)...")
            self.app_window.fit_view()
            print(f"   ✅ fit_view complete")
        else:
            print(f"   ⚠️ fit_view not found, using fallback bounds...")
            self._fit_main_view_fallback()

        # ====================================================================
        # STEP 4: Capture camera state AFTER fit (this becomes the new lock target)
        # ====================================================================
        locked_params = {
            'position': camera.GetPosition(),
            'focal_point': camera.GetFocalPoint(),
            'view_up': camera.GetViewUp(),
            'parallel_scale': camera.GetParallelScale(),
            'view_angle': camera.GetViewAngle()
        }
        self.app_window._main_view_locked_params = locked_params
        print(f"   📸 Captured new lock target")

        # ====================================================================
        # STEP 5: Save interactor style ONLY on first call
        # ====================================================================
        saved_interactor_style = None
        has_classification_tool = False
        active_tool_name = None

        if not already_locked and interactor is not None:
            current_style = interactor.GetInteractorStyle()
            if current_style is not None:
                saved_interactor_style = current_style
                style_class_name = current_style.GetClassName()
                if 'PointPicker' in style_class_name or 'AreaSelector' in style_class_name:
                    has_classification_tool = True
                    active_tool_name = style_class_name
                    print(f"   💾 SAVED classification tool: {style_class_name}")

        # ====================================================================
        # STEP 6: Install FRESH camera lock observer (with new locked_params)
        # ====================================================================
        _enforcing = [False]
        _last_enforce = [0.0]

        def enforce_camera_lock_main(obj, event):
            """SAFELY lock main view camera — prevent rotation without crashing"""
            if _enforcing[0]:
                return

            import time
            current_time = time.time()
            if current_time - _last_enforce[0] < 0.033:  # 30fps throttle
                return
            _last_enforce[0] = current_time

            _enforcing[0] = True
            try:
                cam = renderer.GetActiveCamera()
                cam.ParallelProjectionOn()

                current_pos = np.array(cam.GetPosition())
                current_focal = np.array(cam.GetFocalPoint())
                current_up = np.array(cam.GetViewUp())

                locked_pos = np.array(locked_params['position'])
                locked_focal = np.array(locked_params['focal_point'])
                locked_up = np.array(locked_params['view_up'])

                current_dir = current_focal - current_pos
                locked_dir = locked_focal - locked_pos

                current_dir_norm = current_dir / (np.linalg.norm(current_dir) + 1e-10)
                locked_dir_norm = locked_dir / (np.linalg.norm(locked_dir) + 1e-10)

                direction_dot = np.dot(current_dir_norm, locked_dir_norm)
                up_dot = np.dot(current_up, locked_up)

                if direction_dot < 0.9999 or up_dot < 0.9999:
                    current_distance = np.linalg.norm(current_dir)
                    new_position = current_focal - (locked_dir_norm * current_distance)
                    cam.SetPosition(*new_position)
                    cam.SetViewUp(*locked_up)
            finally:
                _enforcing[0] = False

        camera.AddObserver('ModifiedEvent', enforce_camera_lock_main)
        print(f"   🔒 Fresh camera lock observer installed")

        # ====================================================================
        # STEP 7: Disable digitize manager picker (only on first call)
        # ====================================================================
        if not already_locked:
            if hasattr(self.app_window, 'digitize_manager'):
                try:
                    if not hasattr(self.app_window, '_digitize_picker_was_enabled'):
                        self.app_window._digitize_picker_was_enabled = True
                    if hasattr(self.app_window.digitize_manager, 'picker_enabled'):
                        self.app_window._digitize_picker_was_enabled = \
                            self.app_window.digitize_manager.picker_enabled
                        self.app_window.digitize_manager.picker_enabled = False
                    if hasattr(self.app_window.digitize_manager, 'disconnect_picker'):
                        self.app_window.digitize_manager.disconnect_picker()
                    print(f"   🔇 DigitizeManager picker DISABLED")
                except Exception as e:
                    print(f"   ⚠️ Could not disable digitize picker: {e}")

        # ====================================================================
        # STEP 8: Set interactor style (only on first call)
        #         On repeat calls the style is ALREADY correct — don't touch it
        # ====================================================================
        if not already_locked:
            if has_classification_tool and saved_interactor_style is not None:
                interactor.SetInteractorStyle(saved_interactor_style)
                print(f"   ✅ Classification tool PRESERVED: {active_tool_name}")
            else:
                from vtkmodules.vtkInteractionStyle import vtkInteractorStyleImage
                style_2d = vtkInteractorStyleImage()
                style_2d.SetInteractionModeToImageSlicing()
                interactor.SetInteractorStyle(style_2d)
                print(f"   🔒 2D pan/zoom enabled, rotation locked")

        # ====================================================================
        # STEP 9: Mark as locked
        # ====================================================================
        self.app_window._main_view_2d_locked = True

        # Final render
        renderer.ResetCameraClippingRange()
        vtk_widget.render()

        print(f"   🔒 Main view 2D lock {'REFRESHED' if already_locked else 'ENABLED'}")
        print(f"   ✓ Rotation: DISABLED")
        print(f"   ✓ Pan/Zoom: ENABLED with locked orientation")
        print(f"{'='*60}\n")

    def _fit_main_view_fallback(self):
        """
        Fallback bounds calculation when fit_view() is not available.
        Handles point cloud + DWG bounds.
        """
        import numpy as np

        def _get_point_cloud_bounds():
            pts = getattr(self.app_window, 'points', None)
            if pts is not None and len(pts) > 0:
                return [pts[:,0].min(), pts[:,0].max(),
                        pts[:,1].min(), pts[:,1].max(),
                        pts[:,2].min(), pts[:,2].max()]
            data = getattr(self.app_window, 'data', None)
            if data is not None:
                xyz = data.get('xyz') if hasattr(data, 'get') else getattr(data, 'xyz', None)
                if xyz is not None and len(xyz) > 0:
                    arr = np.asarray(xyz)
                    return [float(arr[:,0].min()), float(arr[:,0].max()),
                            float(arr[:,1].min()), float(arr[:,1].max()),
                            float(arr[:,2].min()), float(arr[:,2].max())]
            return None

        def _get_dwg_bounds():
            try:
                dwg_actors = getattr(self.app_window, 'dwg_actors', [])
                if not dwg_actors:
                    return None
                all_actors = [a for entry in dwg_actors for a in entry.get('actors', [])]
                if not all_actors:
                    return None
                xmin = ymin = zmin = 1e18
                xmax = ymax = zmax = -1e18
                for actor in all_actors:
                    if not actor.GetVisibility():
                        continue
                    b = actor.GetBounds()
                    if b[0] > b[1]:
                        continue
                    xmin = min(xmin, b[0]); xmax = max(xmax, b[1])
                    ymin = min(ymin, b[2]); ymax = max(ymax, b[3])
                    zmin = min(zmin, b[4]); zmax = max(zmax, b[5])
                if xmin > xmax:
                    return None
                return [xmin, xmax, ymin, ymax, zmin, zmax]
            except Exception:
                return None

        renderer = self.app_window.vtk_widget.renderer
        pc_bounds = _get_point_cloud_bounds()
        dwg_bounds = _get_dwg_bounds()

        if pc_bounds is not None:
            renderer.ResetCamera(pc_bounds)
            print(f"   ✅ Fitted to point cloud bounds")
        elif dwg_bounds is not None:
            renderer.ResetCamera(dwg_bounds)
            print(f"   ✅ Fitted to DWG bounds")
        elif hasattr(self.app_window, 'view_ribbon') and self.app_window.view_ribbon:
            self.app_window.view_ribbon._fit_view()
            print(f"   ✅ Fitted via view_ribbon")
        else:
            print(f"   ⚠️ No data to fit")
        
    def _unlock_cross_section_view(self, view_idx, vtk_widget):
        """Unlock a SINGLE cross-section view"""
        from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
        
        try:
            renderer = vtk_widget.renderer
            camera = renderer.GetActiveCamera()
            
            # Remove observers
            camera.RemoveObservers('ModifiedEvent')
            renderer.RemoveObservers('StartEvent')
            renderer.RemoveObservers('EndEvent')
            
            # Restore 3D trackball camera
            vtk_widget.interactor.SetInteractorStyle(vtkInteractorStyleTrackballCamera())
            camera.ParallelProjectionOff()
            vtk_widget.render()
            
            # Clear state
            if hasattr(self.app_window, '_cross_section_2d_mode'):
                if view_idx in self.app_window._cross_section_2d_mode:
                    del self.app_window._cross_section_2d_mode[view_idx]
            
            print(f"   ✅ Cross-section view {view_idx + 1} unlocked")
        except Exception as e:
            print(f"   ⚠️ Error unlocking view {view_idx}: {e}")

    def _unlock_main_view(self):
        """Unlock ONLY the main view"""
        from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
        
        try:
            vtk_widget = self.app_window.vtk_widget
            renderer = vtk_widget.renderer
            camera = renderer.GetActiveCamera()
            
            # Remove observers
            camera.RemoveObservers('ModifiedEvent')
            renderer.RemoveObservers('StartEvent')
            renderer.RemoveObservers('EndEvent')
            
            # Restore 3D trackball camera
            vtk_widget.interactor.SetInteractorStyle(vtkInteractorStyleTrackballCamera())
            camera.ParallelProjectionOff()
            vtk_widget.render()
            
            self.app_window._main_view_2d_locked = False
            
            # Re-enable digitize manager picker
            if hasattr(self.app_window, 'digitize_manager'):
                try:
                    if hasattr(self.app_window, '_digitize_picker_was_enabled'):
                        if self.app_window._digitize_picker_was_enabled:
                            if hasattr(self.app_window.digitize_manager, 'picker_enabled'):
                                self.app_window.digitize_manager.picker_enabled = True
                            
                            if hasattr(self.app_window.digitize_manager, 'connect_picker'):
                                self.app_window.digitize_manager.connect_picker()
                            
                            print(f"   🔊 DigitizeManager picker RE-ENABLED")
                except Exception as e:
                    print(f"   ⚠️ Could not re-enable digitize picker: {e}")
            
            print(f"   ✅ Main view unlocked")
        except Exception as e:
            print(f"   ⚠️ Error unlocking main view: {e}")