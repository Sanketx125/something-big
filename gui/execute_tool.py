TOOL_MAP = {
    "AboveLine": "above_line",
    "BelowLine": "below_line",
    "Rectangle": "rectangle",
    "Circle": "circle",
    "Freehand": "freehand",
    "Brush": "brush",
    "Point": "point",
    "CrossSectionRect": "cross_section",
    "CutSectionRect": "cut_section",
    "CutFromCross": "CutFromCross",  
    "CutFromCut": "CutFromCut",  
    "TopView": "top_view",
    "MeasureLine": "measure_line",
    "MeasurePath": "measure_path",
    "ClearMeasurements": "clear_measurements",
    "DisplayMode": "display_mode",
    "ShadingMode": "shading_mode",
}


def _deactivate_curve_tool_safely(app_window, reason="switching tools"):
    """
    Safely deactivate curve tool in all modes.
    Called when switching to any other tool context.
    """
    if not hasattr(app_window, 'curve_tool') or app_window.curve_tool is None:
        return
    
    ct = app_window.curve_tool
    
    # Check if curve tool has any active mode
    is_active = ct.active
    is_select_mode = getattr(ct, '_select_mode', False)
    
    if not is_active and not is_select_mode:
        return
    
    print(f"   🎨 Deactivating curve tool ({reason})")
    
    # Cancel active drawing if in progress
    if is_active:
        ct._cancel_curve()
    
    # Exit select mode if active
    if is_select_mode:
        ct.deactivate_select_mode()


def _deactivate_measurement_tool_safely(app_window, reason="switching tools"):
    """
    Safely deactivate measurement tool.
    Called when switching to classification or section tools.
    """
    if not hasattr(app_window, 'measurement_tool') or app_window.measurement_tool is None:
        return
    
    mt = app_window.measurement_tool
    
    if not getattr(mt, 'active', False) and not getattr(mt, 'is_measuring', False):
        return
    
    print(f"   📏 Deactivating measurement tool ({reason})")
    
    if hasattr(mt, 'deactivate'):
        try:
            mt.deactivate()
        except Exception as e:
            print(f"      ⚠️ Measurement deactivate failed: {e}")
    
    # Force flags even if deactivate() didn't clear them
    mt.active = False
    mt.is_measuring = False
    if hasattr(mt, 'is_drawing'):
        mt.is_drawing = False


def execute_tool(app_window, tool, from_cls=None, to_cls=None, preset=None):
    """
    Execute a classification or cross-section tool.
    ✅ FIXED: Uses open_next_cross_section_view() for direct activation (no dialog)
    ✅ FIXED: Preserves classification parameters across view changes
    ✅ FIXED: Returns focus to correct view for immediate use
    ✅ NEW: Handles DisplayMode and ShadingMode presets
    ✅ FIXED: Properly deactivates curve/measurement tools when switching contexts
    """
    
    print(f"🔧 execute_tool called: tool={tool}, from_cls={from_cls}, to_cls={to_cls}, preset={preset is not None}")
    
    tool_name = TOOL_MAP.get(tool, tool.lower())
    
    # ✅ NEW: If switching AWAY from cross-section while it was active, deactivate it properly
    if tool_name != "cross_section" and getattr(app_window, "cross_section_active", False):
        print(f"🛑 Deactivating cross-section (switching to {tool_name} via shortcut)")
        if hasattr(app_window, "_cancel_cross_section_tool_only"):
            app_window._cancel_cross_section_tool_only()

    # Handle empty list case
    if from_cls is not None and isinstance(from_cls, list) and len(from_cls) == 0:
        from_cls = None

    # ========================================================================
    # ✅ NEW: DISPLAY MODE PRESET (Non-classification)
    # ========================================================================
    if tool_name == "display_mode":
        print("🎨 Applying DisplayMode preset from shortcut")
        
        # ✅ Deactivate curve tool when switching to display mode
        _deactivate_curve_tool_safely(app_window, "switching to DisplayMode")
        
        if preset is None:
            print("   ⚠️ No preset provided for DisplayMode")
            return
        
        try:
            # ✅ ADD THIS: Clear shading actors when switching to DisplayMode
            print(f"   🧹 Clearing shading mode actors...")
            if hasattr(app_window, '_shaded_mesh_actor') and app_window._shaded_mesh_actor:
                app_window.vtk_widget.remove_actor('shaded_mesh', render=False)
                app_window._shaded_mesh_actor = None
                print(f"      ✅ Removed shading mesh actor")
            
            if hasattr(app_window, '_shaded_mesh_polydata'):
                app_window._shaded_mesh_polydata = None
            
            # Clear shading cache
            from gui.shading_display import clear_shading_cache
            clear_shading_cache("switching to DisplayMode")
            
            # ✅ Extract multi-view preset data
            views = preset.get("views", {})
            border_percent = preset.get("border_percent", 0)
            
            if not views:
                print("   ⚠️ No views configured in preset")
                return
            
            print(f"\n{'='*60}")
            print(f"🎨 APPLYING DISPLAYMODE PRESET")
            print(f"{'='*60}")
            
            # ✅ CRITICAL: Initialize app_window.view_palettes with CORRECT WEIGHTS
            if not hasattr(app_window, 'view_palettes'):
                app_window.view_palettes = {}
            
            # Set default weights based on view type
            for view_idx in range(6):  # 0=Main, 1-4=Cross-sections, 5=Cut
                if view_idx == 0:
                    default_weight = 1.0  # Main View
                else:
                    default_weight = 0.5  # All others
                
                app_window.view_palettes[view_idx] = {}
            
            # ✅ Now apply preset values, overriding defaults only where preset has data
            for view_idx_str, classes in views.items():
                view_idx = int(view_idx_str)
                
                print(f"\n   Processing View {view_idx}:")
                
                # Get default weight for this view type
                default_weight = 1.0 if view_idx == 0 else 0.5
                
                # Copy all class info from preset
                for code_str, info in classes.items():
                    code_int = int(code_str)
                    
                    # ✅ Use weight from preset if available, otherwise use default
                    preset_weight = info.get("weight", default_weight)
                    
                    app_window.view_palettes[view_idx][code_int] = {
                        "show": info.get("show", False),
                        "description": info.get("description", ""),
                        "color": info.get("color", (128, 128, 128)),
                        "weight": preset_weight,
                        "draw": info.get("draw", ""),
                        "lvl": info.get("lvl", "")
                    }
                
                # Print summary
                visible = sum(1 for c in app_window.view_palettes[view_idx].values() if c.get("show"))
                weights = set(c.get("weight") for c in app_window.view_palettes[view_idx].values())
                view_name = "Main" if view_idx == 0 else f"View {view_idx}"
                print(f"      ✅ {view_name}: {len(app_window.view_palettes[view_idx])} classes")
                print(f"      📊 Visible: {visible}")
                print(f"      ⚖️ Weights: {weights}")
            
            # ✅ Also update class_palette from view 0
            if 0 in views:
                app_window.class_palette = {}
                for code_str, info in views[0].items():
                    code_int = int(code_str)
                    app_window.class_palette[code_int] = {
                        "show": info.get("show", False),
                        "description": info.get("description", ""),
                        "color": info.get("color", (128, 128, 128)),
                        "weight": info.get("weight", 1.0),
                        "draw": info.get("draw", ""),
                        "lvl": info.get("lvl", "")
                    }
            
            # Trigger refresh
            from gui.class_display import update_class_mode
            app_window._preserve_view = True
            update_class_mode(app_window, force_refresh=True)
            
            if hasattr(app_window, "statusBar"):
                app_window.statusBar().showMessage(
                    f"✅ DisplayMode: Main=1.0, Views 1-5=0.5",
                    2000
                )
            
            print(f"{'='*60}")
            print(f"✅ Weights set: Main=1.0, Views 1-5=0.5")
            print(f"{'='*60}\n")
            
        except Exception as e:
            print(f"⚠️ Failed: {e}")
            import traceback
            traceback.print_exc()
        
        return

    # ========================================================================
    # ✅ NEW: SHADING MODE PRESET (Non-classification)
    # ========================================================================
    if tool_name == "shading_mode":
        print("🌗 Applying ShadingMode preset from shortcut")
        
        # ✅ Deactivate curve tool when switching to shading mode
        _deactivate_curve_tool_safely(app_window, "switching to ShadingMode")
        
        if preset is None:
            print("   ⚠️ No preset provided for ShadingMode")
            return
        
        try:
            # Extract shading parameters
            azimuth = preset.get("azimuth", 45.0)
            angle = preset.get("angle", 45.0)
            ambient = preset.get("ambient", 0.1)
            quality = preset.get("quality", 100.0)
            speed = preset.get("speed", 1)
            classes = preset.get("classes", {})
            
            print(f"   🌗 Shading: az={azimuth}°, angle={angle}°, ambient={ambient}")
            print(f"   📋 Classes: {len(classes)} configured")
            
            # Apply shading parameters to panel
            if hasattr(app_window, 'shading_panel'):
                panel = app_window.shading_panel
                
                if hasattr(panel, 'az_spin'):
                    panel.az_spin.setValue(azimuth)
                if hasattr(panel, 'el_spin'):
                    panel.el_spin.setValue(angle)
                if hasattr(panel, 'quality_spin'):
                    panel.quality_spin.setValue(quality)
                if hasattr(panel, 'speed_spin'):
                    panel.speed_spin.setValue(speed)
                
                print("   ✅ Shading parameters set in panel")
            
            # Apply ambient
            app_window.shade_ambient = ambient
            
            # ✅ CRITICAL: Only update visibility for classes in the preset
            if classes and hasattr(app_window, 'class_palette'):
                for code, info in classes.items():
                    code_int = int(code)
                    if code_int in app_window.class_palette:
                        app_window.class_palette[code_int]["show"] = info.get("show", False)
                
                print(f"   ✅ Updated visibility for {len(classes)} classes")
            
            # Trigger shading mode
            if hasattr(app_window, 'on_display_changed'):
                app_window.on_display_changed("shading", force_refresh=True)
                print("   ✅ Triggered shading mode")
            elif hasattr(app_window, 'set_display_mode'):
                app_window.set_display_mode("shading")
                print("   ✅ Set shading mode")
            
            # Clear any active classification tool
            app_window.active_classify_tool = None
            
            # Return focus
            _return_focus_to_main_view(app_window)
            
            visible_count = sum(1 for c in classes.values() if c.get("show")) if classes else 0
            
            if hasattr(app_window, "statusBar"):
                app_window.statusBar().showMessage(
                    f"🌗 Shading preset applied: {azimuth}°/{angle}°, {visible_count} classes visible",
                    2000
                )
            
            print(f"   ✅ ShadingMode preset applied successfully")
            
        except Exception as e:
            print(f"⚠️ ShadingMode preset application failed: {e}")
            import traceback
            traceback.print_exc()
        
        return

    # ========================================================================
    # VIEW NAVIGATION TOOLS (Non-classification)
    # ========================================================================

    if tool_name in ("measure_line", "measure_path"):
        print(f"📏 Activating measurement shortcut: {tool_name}")

        # ✅ Deactivate curve tool when switching to measurement
        _deactivate_curve_tool_safely(app_window, "switching to measurement")

        try:
            if hasattr(app_window, "_sync_tools_for_ribbon_tab"):
                app_window._sync_tools_for_ribbon_tab("measure")
            elif hasattr(app_window, "_enter_measure_tab_mode"):
                app_window._enter_measure_tab_mode()

            if hasattr(app_window, "activate_measurement_tool"):
                app_window.activate_measurement_tool(tool_name)
                _return_focus_to_main_view(app_window)
                print(f"   ✅ Measurement tool activated: {tool_name}")
            else:
                print("   ⚠️ Measurement activation handler not available")
        except Exception as e:
            print(f"⚠️ Measurement shortcut failed: {e}")
            import traceback
            traceback.print_exc()
        return

    if tool_name == "clear_measurements":
        print("🗑️ Clearing measurements from shortcut")

        try:
            if hasattr(app_window, "clear_all_measurements"):
                app_window.clear_all_measurements()
            elif hasattr(app_window, "measurement_tool") and app_window.measurement_tool:
                app_window.measurement_tool.clear_all_measurements()
            else:
                print("   ⚠️ No measurement tool available to clear")
                return

            _return_focus_to_main_view(app_window)
            print("   ✅ Measurements cleared")
        except Exception as e:
            print(f"⚠️ Clear measurements shortcut failed: {e}")
            import traceback
            traceback.print_exc()
        return

    if tool_name == "top_view":
        print("🔝 Activating Top View")
        
        # ✅ Deactivate curve tool when switching to top view
        _deactivate_curve_tool_safely(app_window, "switching to TopView")
        
        try:
            from vtkmodules.vtkInteractionStyle import vtkInteractorStyleImage
            
            cam = app_window.vtk_widget.renderer.GetActiveCamera()
            cam.ParallelProjectionOn()
            cam.SetViewUp(0, 1, 0)
            cam.SetPosition(0, 0, 1)
            cam.SetFocalPoint(0, 0, 0)
            
            app_window.vtk_widget.renderer.ResetCamera()
            app_window.vtk_widget.render()
            print("   ✅ Camera configured (top view + orthographic + reset)")
            
            interactor = app_window.vtk_widget.interactor
            style = vtkInteractorStyleImage()
            interactor.SetInteractorStyle(style)
            print("   🔒 Interactor LOCKED to 2D (pan/zoom only, no rotation)")
            
            app_window.current_view = "top"
            app_window.active_classify_tool = None
            
            _return_focus_to_main_view(app_window)
            
            if hasattr(app_window, "statusBar"):
                app_window.statusBar().showMessage("🔝 Top View LOCKED (Space Bar)", 2000)
            
            print("   ✅ Top View switched successfully (LOCKED)")
        except Exception as e:
            print(f"⚠️ Top View activation failed: {e}")
            import traceback
            traceback.print_exc()
        return
    
    # ✅ DISPLAY MODE SHORTCUTS (Non-classification)
    # ========================================================================
    if tool in ("Depth", "RGB", "Intensity", "Elevation", "Class"):
        
        print(f"🎨 Switching to {tool} display mode")
        
        # ✅ Deactivate curve tool when switching display modes
        _deactivate_curve_tool_safely(app_window, f"switching to {tool} mode")
        
        # Clear shading actors
        if hasattr(app_window, '_shaded_mesh_actor') and app_window._shaded_mesh_actor:
            app_window.vtk_widget.remove_actor('shaded_mesh', render=False)
            app_window._shaded_mesh_actor = None
        
        if hasattr(app_window, '_shaded_mesh_polydata'):
            app_window._shaded_mesh_polydata = None
        
        from gui.shading_display import clear_shading_cache
        clear_shading_cache(f"switching to {tool} mode")
        
        mode_map = {
            "Depth": "depth",
            "RGB": "rgb",
            "Intensity": "intensity",
            "Elevation": "elevation",
            "Class": "class"
        }
        
        mode = mode_map[tool]
        
        if mode in ['depth', 'rgb', 'intensity', 'elevation']:
            print(f"   🔳 Clearing borders for {mode} mode")
            
            app_window.point_border_percent = 0
            app_window._main_view_borders_active = False
            
            if hasattr(app_window, 'display_mode_dialog') and app_window.display_mode_dialog:
                dlg = app_window.display_mode_dialog
                dlg.view_borders[0] = 0
                
                if dlg.isVisible():
                    if hasattr(dlg, 'border_slider'):
                        dlg.border_slider.blockSignals(True)
                        dlg.border_slider.setValue(0)
                        dlg.border_slider.blockSignals(False)
                    if hasattr(dlg, 'border_value_display'):
                        dlg.border_value_display.setText("0%")
                    if hasattr(dlg, 'border_label'):
                        dlg.border_label.setText("🔳 Border: 0%")
            
            print(f"   ✅ Borders set to 0%")
        
        elif mode == 'class':
            if hasattr(app_window, 'shading_class_visibility'):
                print(f"   🗑️ Clearing shading_class_visibility")
                app_window.shading_class_visibility = {}

            if hasattr(app_window, 'display_mode_dialog') and app_window.display_mode_dialog:
                dlg = app_window.display_mode_dialog
                saved_border = dlg.view_borders.get(0, 0)

                if saved_border > 0:
                    app_window.point_border_percent = saved_border
                    app_window._main_view_borders_active = True
                    print(f"   ✅ Restored borders to {saved_border}%")

            palette = getattr(app_window, 'class_palette', {})
            if palette and not any(v.get('show', True) for v in palette.values()):
                for code in palette:
                    palette[code]['show'] = True
                print(f"   ⚠️ All classes were hidden — reset to visible")

        try:
            if hasattr(app_window, 'on_display_changed'):
                app_window.on_display_changed(mode)
                print(f"   ✅ Called on_display_changed({mode})")
            elif hasattr(app_window, 'set_display_mode'):
                app_window.set_display_mode(mode)
                print(f"   ✅ Called set_display_mode({mode})")
            elif hasattr(app_window, 'change_display_mode'):
                app_window.change_display_mode(mode)
                print(f"   ✅ Called change_display_mode({mode})")
            else:
                if hasattr(app_window, 'view_ribbon'):
                    app_window.view_ribbon.display_changed.emit(mode)
                    print(f"   ✅ Emitted display_changed signal: {mode}")
                else:
                    print(f"   ⚠️ No display mode handler found!")
                    return
            
            app_window.active_classify_tool = None
            _return_focus_to_main_view(app_window)
            
            icon_map = {"depth": "🧱", "rgb": "🌈", "intensity": "💡", "elevation": "📊", "class": "🏷️"}
            icon = icon_map.get(mode, "🎨")
            
            if hasattr(app_window, "statusBar"):
                app_window.statusBar().showMessage(f"{icon} {tool} mode activated", 1500)
            
            print(f"   ✅ {tool} display mode activated")
            
        except Exception as e:
            print(f"⚠️ Failed to switch to {tool} mode: {e}")
            import traceback
            traceback.print_exc()
        
        return

    # ========================================================================
    # CROSS-SECTION TOOL (Non-classification)
    # ========================================================================
    if tool_name == "cross_section":
        print("🔧 Activating Cross Section tool - SHOWING POPUP DIALOG")
        
        # ✅ Deactivate curve tool when switching to cross-section
        _deactivate_curve_tool_safely(app_window, "switching to cross-section")
        
        # ✅ Deactivate measurement tool
        _deactivate_measurement_tool_safely(app_window, "switching to cross-section")
        
        # Clear any active classification session
        class_picker = getattr(app_window, "class_picker", None)
        classification_active = bool(
            getattr(app_window, "active_classify_tool", None)
            or (class_picker and class_picker.isVisible())
            or getattr(app_window, "classify_interactor", None)
            or getattr(app_window, "classify_interactors", None)
            or getattr(app_window, "cut_classify_interactor", None)
        )

        if classification_active and hasattr(app_window, "deactivate_classification_tool"):
            has_cross_action = (
                hasattr(app_window, 'cross_action') 
                and app_window.cross_action is not None
            )
            app_window.deactivate_classification_tool(
                preserve_cross_section=has_cross_action
            )
            app_window.active_classify_tool = None
        
        # ✅ Deactivate cut section pending state
        if hasattr(app_window, "cut_section_controller") and app_window.cut_section_controller:
            if hasattr(app_window.cut_section_controller, "_force_deactivate_pending_state"):
                print("   🛑 Deactivating pending cut tool state...")
                app_window.cut_section_controller._force_deactivate_pending_state()

        # ✅ CRITICAL: Use enable_cross_section_mode() to show popup dialog FIRST
        if hasattr(app_window, "enable_cross_section_mode"):
            app_window.enable_cross_section_mode()
            print("   ✅ Used enable_cross_section_mode() - SHOWS POPUP DIALOG!")
        elif hasattr(app_window, "open_next_cross_section_view"):
            app_window.open_next_cross_section_view()
            print("   ⚠️ Fell back to open_next_cross_section_view() - auto-select view")
        
        _return_focus_to_main_view(app_window)
        
        if hasattr(app_window, "statusBar"):
            app_window.statusBar().showMessage(
                "✅ Select view from popup - Draw line on main view", 3000
            )
        return

    # ========================================================================
    # CUT SECTION TOOL (Non-classification)
    # ========================================================================
    if tool_name == "cut_section":
        print("🔧 Activating Cut Section tool")
        
        # ✅ Deactivate curve tool when switching to cut-section
        _deactivate_curve_tool_safely(app_window, "switching to cut-section")
        
        # ✅ Deactivate measurement tool
        _deactivate_measurement_tool_safely(app_window, "switching to cut-section")
        
        try:
            app_window.active_classify_tool = None
            app_window.cut_section_controller.activate()
            _return_focus_to_main_view(app_window)
            
            if hasattr(app_window, "statusBar"):
                app_window.statusBar().showMessage(
                    "✅ Cut Section ready - Click center, drag, then finalize", 3000
                )
        except Exception as e:
            print(f"⚠️ Cut Section activation failed: {e}")
        return
    
    # ========================================================================
    # CutFromCross/CutFromCut
    # ========================================================================
    if tool_name == "CutFromCross":
        # ✅ Deactivate curve tool
        _deactivate_curve_tool_safely(app_window, "switching to CutFromCross")
        
        if hasattr(app_window, "cut_section_controller"):
            app_window.cut_section_controller.activate_from_cross_shortcut()
        return

    if tool_name == "CutFromCut":
        # ✅ Deactivate curve tool
        _deactivate_curve_tool_safely(app_window, "switching to CutFromCut")
        
        if hasattr(app_window, "cut_section_controller"):
            app_window.cut_section_controller.activate_from_cut_shortcut()
        return

    # ========================================================================
    # CLASSIFICATION TOOLS
    # ========================================================================

    # ── Guard: block classify tools when non-class display mode is active ──
    _CLASSIFY_RESTRICTED_MODES = {"depth", "rgb", "intensity", "elevation"}
    _current_display_mode = getattr(app_window, "display_mode", "class")

    if _current_display_mode in _CLASSIFY_RESTRICTED_MODES:
        _mode_label = {
            "depth": "Depth", "rgb": "RGB",
            "intensity": "Intensity", "elevation": "Elevation",
        }.get(_current_display_mode, _current_display_mode.capitalize())

        print(f"🚫 Classification tool blocked — current display mode is '{_current_display_mode}'")

        try:
            from PySide6.QtWidgets import (
                QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QApplication
            )
            from PySide6.QtCore import Qt

            try:
                from gui.theme_manager import get_dialog_stylesheet, ThemeColors
                sheet   = get_dialog_stylesheet()
                accent  = ThemeColors.get("accent", "#f59e0b")
                txt_pri = ThemeColors.get("text_primary", "#f1f5f9")
                txt_sec = ThemeColors.get("text_secondary", "#94a3b8")
            except Exception:
                sheet = ""
                accent, txt_pri, txt_sec = "#f59e0b", "#f1f5f9", "#94a3b8"

            parent_widget = getattr(app_window, "vtk_widget", app_window)
            dlg = QDialog(app_window, Qt.Dialog | Qt.FramelessWindowHint)
            dlg.setWindowModality(Qt.ApplicationModal)
            dlg.setStyleSheet(sheet + f"""
                QDialog {{
                    border: 2px solid {accent};
                    border-radius: 12px;
                }}
            """)
            dlg.setFixedWidth(380)

            outer = QVBoxLayout(dlg)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)

            header = QLabel(f"  ⚠️  Classification Unavailable")
            header.setFixedHeight(42)
            header.setStyleSheet(f"""
                QLabel {{
                    background-color: {accent};
                    color: #0f172a;
                    font-weight: bold;
                    font-size: 13px;
                    border-top-left-radius: 10px;
                    border-top-right-radius: 10px;
                    padding-left: 8px;
                }}
            """)
            outer.addWidget(header)

            body = QVBoxLayout()
            body.setContentsMargins(20, 16, 20, 20)
            body.setSpacing(10)

            icon_lbl = QLabel("🚫")
            icon_lbl.setAlignment(Qt.AlignCenter)
            icon_lbl.setStyleSheet("font-size: 36px; background: transparent;")
            body.addWidget(icon_lbl)

            msg = QLabel(
                f"<b>Classification tools are disabled</b><br>"
                f"while <b>{_mode_label}</b> view is active.<br><br>"
                f"Please switch to <b>Class</b> or <b>Shading</b> view<br>"
                f"from the <i>View → Display</i> ribbon to use<br>"
                f"classification tools."
            )
            msg.setAlignment(Qt.AlignCenter)
            msg.setWordWrap(True)
            msg.setStyleSheet(f"""
                QLabel {{
                    color: {txt_pri};
                    font-size: 12px;
                    background: transparent;
                }}
            """)
            body.addWidget(msg)

            hint = QLabel("💡 Tip: Use  View › Class  or  View › Shading")
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet(f"""
                QLabel {{
                    color: {txt_sec};
                    font-size: 10px;
                    background: transparent;
                    padding: 4px 8px;
                    border: 1px solid {accent};
                    border-radius: 6px;
                }}
            """)
            body.addWidget(hint)

            btn_row = QHBoxLayout()
            btn_row.addStretch()
            ok_btn = QPushButton("  Got it  ")
            ok_btn.setFixedHeight(34)
            ok_btn.setCursor(Qt.PointingHandCursor)
            ok_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {accent};
                    color: #0f172a;
                    font-weight: bold;
                    font-size: 12px;
                    border-radius: 7px;
                    padding: 4px 20px;
                    border: none;
                }}
                QPushButton:hover {{ background-color: #fbbf24; }}
                QPushButton:pressed {{ background-color: #d97706; }}
            """)
            ok_btn.clicked.connect(dlg.accept)
            btn_row.addWidget(ok_btn)
            btn_row.addStretch()
            body.addLayout(btn_row)
            outer.addLayout(body)
            dlg.exec()

        except Exception as _popup_err:
            print(f"⚠️ Could not show classify restriction popup: {_popup_err}")

        return  # ← do NOT activate the tool

    # ── All clear — proceed with classification tool activation ──────────────
    print(f"🎯 Activating classification tool: {tool_name}")
    
    # ✅ CRITICAL: Deactivate curve tool when switching to classification
    _deactivate_curve_tool_safely(app_window, "switching to classification")
    
    # ✅ CRITICAL: Deactivate measurement tool when switching to classification
    _deactivate_measurement_tool_safely(app_window, "switching to classification")
    
    # ✅ Determine classification target (main/cross/cut)
    classification_target = _determine_classification_target(app_window)
    
    print(f"   📍 Classification target: {classification_target}")

    # Set classification parameters
    app_window.from_classes = from_cls
    app_window.to_class = to_cls
    app_window.active_classify_tool = tool_name
    
    # ✅ CRITICAL: Set the classification target
    if hasattr(app_window, "active_classify_target"):
        app_window.active_classify_target = classification_target
    
    # ✅ Use set_classify_tool if available (better integration)
    if hasattr(app_window, "set_classify_tool"):
        app_window.set_classify_tool(tool_name)
    
    # Build display message
    if isinstance(from_cls, list) and len(from_cls) > 0:
        from_display = ", ".join(str(c) for c in from_cls)
    else:
        from_display = "Any"
    
    to_display = str(to_cls) if to_cls is not None else "Any"
    
    print(f"✅ Tool armed: {tool_name} [{from_display} → {to_display}]")
    print(f"   Target view: {classification_target}")

    # ✅ CRITICAL: Update ClassPicker BUT keep focus on main view
    if hasattr(app_window, "class_picker") and app_window.class_picker:
        app_window.class_picker.sync_with_app()
        
        if not app_window.class_picker.isVisible():
            app_window.class_picker.show()

    # ✅ CRITICAL: Return focus to appropriate view
    if classification_target == "cross":
        _return_focus_to_cross_section(app_window)
    elif classification_target == "cut":
        _return_focus_to_cut_section(app_window)
    else:
        _return_focus_to_main_view(app_window)
    
    # Status bar feedback
    if hasattr(app_window, "statusBar"):
        target_name = {
            "main": "Main View",
            "cross": "Cross-Section",
            "cut": "Cut Section"
        }.get(classification_target, "View")
        
        msg = f"✅ {tool_name.title()} ready in {target_name} [{from_display} → {to_display}]"
        app_window.statusBar().showMessage(msg, 3000)


def _determine_classification_target(app_window):
    """
    ✅ Determine which view should receive classification actions.
    Priority: Cut Section > Cross Section > Main View
    
    Returns:
        "cut", "cross", or "main"
    """
    
    # Check if cut section is active and locked
    if hasattr(app_window, 'cut_section_controller') and app_window.cut_section_controller:
        ctrl = app_window.cut_section_controller
        if getattr(ctrl, 'is_locked', False) and getattr(ctrl, 'is_cut_view_active', False):
            print("   🔒 Cut section is locked and active")
            return "cut"
    
    # Check if cross-section view is active
    if hasattr(app_window, 'section_controller') and app_window.section_controller:
        active_view = getattr(app_window.section_controller, 'active_view', None)
        
        if active_view is not None:
            if hasattr(app_window, 'section_vtks') and active_view in app_window.section_vtks:
                vtk_widget = app_window.section_vtks[active_view]
                
                if vtk_widget and hasattr(vtk_widget, 'isVisible') and vtk_widget.isVisible():
                    print(f"   📊 Cross-section view {active_view} is active")
                    return "cross"
    
    # Default to main view
    print("   🏠 Using main view")
    return "main"


def _return_focus_to_main_view(app_window):
    """
    ✅ CRITICAL: Return keyboard focus to main VTK viewer
    This allows next shortcut key to work immediately without clicking
    """
    try:
        if hasattr(app_window, 'vtk_widget') and app_window.vtk_widget:
            app_window.vtk_widget.setFocus()
            print("   🎯 Focus returned to main VTK widget")
            return
        
        if hasattr(app_window, 'setFocus'):
            app_window.setFocus()
            print("   🎯 Focus returned to main window")
            return
        
        print("   ⚠️ Could not return focus (no vtk_widget found)")
        
    except Exception as e:
        print(f"   ⚠️ Focus return failed: {e}")


def _return_focus_to_cross_section(app_window):
    """
    ✅ Return keyboard focus to active cross-section view
    """
    try:
        if not hasattr(app_window, 'section_controller') or not app_window.section_controller:
            print("   ⚠️ No section_controller found")
            _return_focus_to_main_view(app_window)
            return
        
        active_view = getattr(app_window.section_controller, 'active_view', None)
        
        if active_view is None:
            print("   ⚠️ No active cross-section view")
            _return_focus_to_main_view(app_window)
            return
        
        if hasattr(app_window, 'section_vtks') and active_view in app_window.section_vtks:
            vtk_widget = app_window.section_vtks[active_view]
            
            if vtk_widget and hasattr(vtk_widget, 'setFocus'):
                vtk_widget.setFocus()
                print(f"   🎯 Focus returned to cross-section view {active_view}")
                return
        
        print("   ⚠️ Could not find cross-section VTK widget")
        _return_focus_to_main_view(app_window)
        
    except Exception as e:
        print(f"   ⚠️ Cross-section focus return failed: {e}")
        _return_focus_to_main_view(app_window)


def _return_focus_to_cut_section(app_window):
    """
    ✅ Return keyboard focus to cut section view
    """
    try:
        if not hasattr(app_window, 'cut_section_controller') or not app_window.cut_section_controller:
            print("   ⚠️ No cut_section_controller found")
            _return_focus_to_main_view(app_window)
            return
        
        ctrl = app_window.cut_section_controller
        
        if hasattr(ctrl, 'cut_vtk') and ctrl.cut_vtk:
            if hasattr(ctrl.cut_vtk, 'setFocus'):
                ctrl.cut_vtk.setFocus()
                print("   🎯 Focus returned to cut section view")
                return
        
        print("   ⚠️ Could not find cut section VTK widget")
        _return_focus_to_main_view(app_window)
        
    except Exception as e:
        print(f"   ⚠️ Cut section focus return failed: {e}")
        _return_focus_to_main_view(app_window)