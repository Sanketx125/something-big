
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import QSettings
import os
from .shading_display import clear_shading_cache

def _save_display_settings_before_clear(app):
    """
    Save current display mode settings to QSettings before clearing.
    ✅ FIXED: Saves PTC, palettes, checkboxes, color mode, and display mode.
    """
    try:
        settings = QSettings("NakshaAI", "LidarApp")
        
        # Identify the active dialog instance
        dialog = None
        if hasattr(app, 'display_mode_dialog') and app.display_mode_dialog:
            dialog = app.display_mode_dialog
        elif hasattr(app, 'display_dialog') and app.display_dialog:
            dialog = app.display_dialog
            
        # ====================================================================
        # ✅ Save Global Last Used PTC (Independent of any file)
        # ====================================================================
        if dialog and hasattr(dialog, 'current_ptc_path') and dialog.current_ptc_path:
            settings.setValue("global_last_ptc_path", dialog.current_ptc_path)
            print(f"🌍 Saved GLOBAL PTC: {os.path.basename(dialog.current_ptc_path)}")

        # ====================================================================
        # ✅ NEW: Save GLOBAL display settings (independent of specific files)
        # These will be applied to ANY new file loaded
        # ====================================================================
        if dialog:
            # Save ALL view palettes globally
            if hasattr(dialog, 'view_palettes') and dialog.view_palettes:
                global_palette_data = {}
                for view_idx, palette in dialog.view_palettes.items():
                    global_palette_data[str(view_idx)] = {
                        str(code): {
                            'show': info.get('show', True),
                            'description': info.get('description', ''),
                            'color': list(info.get('color', (128, 128, 128))),
                            'weight': info.get('weight', 1.0)
                        }
                        for code, info in palette.items()
                    }
                settings.setValue("global_view_palettes", global_palette_data)
                print(f"  ✅ Saved {len(global_palette_data)} GLOBAL view palettes")
            
            # Save ALL checkbox states globally
            if hasattr(dialog, 'slot_shows') and dialog.slot_shows:
                global_checkbox_data = {}
                for slot_idx, show_dict in dialog.slot_shows.items():
                    global_checkbox_data[str(slot_idx)] = {
                        str(code): checked
                        for code, checked in show_dict.items()
                    }
                settings.setValue("global_slot_shows", global_checkbox_data)
                print(f"  ✅ Saved GLOBAL checkbox states for {len(global_checkbox_data)} views")
            
            # Save color mode globally
            if hasattr(dialog, 'color_mode'):
                color_mode_idx = dialog.color_mode.currentIndex()
                settings.setValue("global_color_mode", color_mode_idx)
                print(f"  ✅ Saved GLOBAL color mode: {color_mode_idx}")
            
            # Save border values globally
            if hasattr(dialog, 'view_borders') and dialog.view_borders:
                settings.setValue("global_view_borders", dialog.view_borders)
                print(f"  ✅ Saved GLOBAL border values: {dialog.view_borders}")

        # Save display mode globally
        if hasattr(app, 'display_mode') and app.display_mode:
            settings.setValue("global_display_mode", app.display_mode)
            print(f"  ✅ Saved GLOBAL display mode: {app.display_mode}")

        # ====================================================================
        # File-Specific Settings (Only if a file is loaded)
        # ====================================================================
        if not hasattr(app, 'loaded_file') or not app.loaded_file:
            settings.sync()
            print("✅ GLOBAL display settings saved\n")
            return
        
        file_key = os.path.abspath(app.loaded_file)
        print(f"💾 Saving display settings for: {os.path.basename(file_key)}")
        
        # 1️⃣ Save current PTC path for THIS specific file
        if dialog and hasattr(dialog, 'current_ptc_path') and dialog.current_ptc_path:
            settings.setValue(f"file_ptc/{file_key}", dialog.current_ptc_path)
            print(f"  ✅ PTC: {os.path.basename(dialog.current_ptc_path)}")
        
        # 2️⃣ Save view palettes (colors, weights, descriptions for all views)
        if hasattr(app, 'view_palettes') and app.view_palettes:
            palette_data = {}
            for view_idx, palette in app.view_palettes.items():
                palette_data[str(view_idx)] = {
                    str(code): {
                        'show': info.get('show', True),
                        'description': info.get('description', ''),
                        'color': list(info.get('color', (128, 128, 128))),  # Convert tuple to list for JSON
                        'weight': info.get('weight', 1.0)
                    }
                    for code, info in palette.items()
                }
            settings.setValue(f"file_palettes/{file_key}", palette_data)
            print(f"  ✅ Saved {len(palette_data)} view palettes")
        
        # 3️⃣ Save checkbox states (slot_shows)
        if dialog and hasattr(dialog, 'slot_shows') and dialog.slot_shows:
            checkbox_data = {}
            for slot_idx, show_dict in dialog.slot_shows.items():
                checkbox_data[str(slot_idx)] = {
                    str(code): checked
                    for code, checked in show_dict.items()
                }
            settings.setValue(f"file_slot_shows/{file_key}", checkbox_data)
            print(f"  ✅ Saved checkbox states for {len(checkbox_data)} views")
        
        # 4️⃣ Save display mode (rgb, class, intensity, etc.)
        if hasattr(app, 'display_mode') and app.display_mode:
            settings.setValue(f"file_display_mode/{file_key}", app.display_mode)
            print(f"  ✅ Display mode: {app.display_mode}")
        
        # 5️⃣ Save color mode index from dialog
        if dialog and hasattr(dialog, 'color_mode'):
            color_mode_idx = dialog.color_mode.currentIndex()
            settings.setValue(f"file_color_mode/{file_key}", color_mode_idx)
            print(f"  ✅ Color mode index: {color_mode_idx}")
        
        settings.sync()
        print(f"✅ Display settings saved for: {os.path.basename(file_key)}\n")
        
    except Exception as e:
        print(f"⚠️ Failed to save display settings: {e}")
        import traceback
        traceback.print_exc()


def clear_project(app):
    """
    Clear all loaded files and reset state, with confirmation.
    ✅ EXECUTION ORDER: Close cut view → Clear main view → Clear cross-section views
    ✅ Display settings preserved, Display Mode dialog kept intact
    """
    # ✅ FIX: Explicitly clear the shading cache to prevent stale data between projects
    clear_shading_cache(reason="project_clear")

    # ============================================================================
    # ✅ CHECK IF PROJECT HAS UNSAVED DATA
    # ============================================================================
    should_save = False
    
    if hasattr(app, 'data') and app.data is not None:
        # Create custom message box with Save/Don't Save/Cancel options
        msg_box = QMessageBox(app)
        msg_box.setIcon(QMessageBox.Question)
        msg_box.setWindowTitle("Clear Project")
        msg_box.setText("Do you want to save the current project before clearing?")
        msg_box.setInformativeText("Your display settings will be preserved and restored when you reload the file.")
        
        # Add custom buttons
        save_button = msg_box.addButton("Save", QMessageBox.AcceptRole)
        dont_save_button = msg_box.addButton("Don't Save", QMessageBox.DestructiveRole)
        cancel_button = msg_box.addButton("Cancel", QMessageBox.RejectRole)
        
        msg_box.setDefaultButton(save_button)
        msg_box.setEscapeButton(cancel_button)
        
        # Show dialog and get response
        msg_box.exec()
        clicked_button = msg_box.clickedButton()
        
        if clicked_button == cancel_button:
            print("❌ Clear project cancelled by user")
            return
        elif clicked_button == save_button:
            should_save = True
            print("✅ User chose to save before clearing")
        else:  # don't_save_button
            should_save = False
            print("⚠️ User chose NOT to save before clearing")
    else:
        # No data loaded, just confirm clear
        reply = QMessageBox.question(
            app,
            "Clear Project",
            "Are you sure you want to clear the project?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

    try:
        print("\n" + "="*60)
        if should_save:
            print("🧹 CLEARING PROJECT (SAVING PROJECT & DISPLAY SETTINGS)")
        else:
            print("🧹 CLEARING PROJECT (NOT SAVING - DISPLAY SETTINGS WILL BE PRESERVED)")
        print("="*60)

        # ============================================================================
        # ✅ SAVE THE PROJECT IF USER CHOSE TO SAVE
        # ============================================================================
        if should_save and hasattr(app, 'data') and app.data is not None:
            save_path = None
            
            # Determine save path
            if hasattr(app, 'last_save_path') and app.last_save_path:
                save_path = app.last_save_path
            elif hasattr(app, 'loaded_file') and app.loaded_file:
                save_path = app.loaded_file
            
            if save_path:
                try:
                    print(f"\n💾 Saving project to: {os.path.basename(save_path)}")
                    
                    # Import from same gui folder (lazy import to avoid circular dependency)
                    from .save_pointcloud import save_pointcloud_quick
                    
                    # Save without showing dialog
                    save_pointcloud_quick(app, save_path)
                    
                    print(f"✅ Project saved successfully before clearing")
                    
                    if hasattr(app, "statusBar"):
                        app.statusBar().showMessage(f"✅ Saved: {os.path.basename(save_path)}", 3000)
                    
                except Exception as save_error:
                    print(f"⚠️ Error saving: {save_error}")
                    if hasattr(app, "statusBar"):
                        app.statusBar().showMessage(f"⚠️ Save failed: {save_error}", 5000)
            else:
                print("⚠️ No save path available - skipping save")

        # ============================================================================
        # ✅ SAVE DISPLAY SETTINGS BEFORE CLEARING
        # ============================================================================
        _save_display_settings_before_clear(app)

        # ============================================================================
        # STEP 1: Close Cut Section FIRST (let it complete naturally)
        # ============================================================================
        if hasattr(app, "cut_section_controller") and app.cut_section_controller:
            ctrl = app.cut_section_controller
            try:
                print(f"\n🔒 Closing cut section dock...")
                
                # Close dock - let closeEvent run naturally
                if ctrl.cut_dock is not None:
                    try:
                        ctrl.cut_dock.close()
                        ctrl.cut_dock = None
                        print("  ✅ Cut dock closed")
                    except Exception as e:
                        print(f"  ⚠️ Dock close: {e}")
                        ctrl.cut_dock = None
                
                # Clear VTK
                if ctrl.cut_vtk is not None:
                    try:
                        renderer = ctrl.cut_vtk.renderer
                        renderer.RemoveAllViewProps()
                        ctrl.cut_vtk.close()
                        ctrl.cut_vtk = None
                        print("  ✅ Cut VTK cleared")
                    except Exception as e:
                        print(f"  ⚠️ VTK clear: {e}")
                        ctrl.cut_vtk = None
                
                # Reset state
                ctrl.is_cut_view_active = False
                ctrl._state = 0
                ctrl.cut_points = None
                
                print("✅ Cut section closed")
                
            except Exception as e:
                print(f"⚠️ Cut section close failed: {e}")

        # ============================================================================
        # STEP 2: Clear Main View
        # ============================================================================
        if hasattr(app, "vtk_widget") and app.vtk_widget:
            try:
                renderer = app.vtk_widget.renderer
                
                # Store DXF actors if they exist (to preserve them)
                dxf_actors_backup = []
                if hasattr(app, 'dxf_actors') and app.dxf_actors:
                    for dxf_data in app.dxf_actors:
                        if 'actors' in dxf_data:
                            dxf_actors_backup.extend(dxf_data['actors'])
                    print(f"\n✅ Backing up {len(dxf_actors_backup)} DXF actors")
                
                # Store digitizer/drawing actors if they exist
                drawing_actors_backup = []
                if hasattr(app, 'digitizer') and app.digitizer:
                    if hasattr(app.digitizer, 'actors') and app.digitizer.actors:
                        drawing_actors_backup = list(app.digitizer.actors)
                        print(f"✅ Backing up {len(drawing_actors_backup)} drawing actors")
                
                # Remove ALL actors from renderer
                renderer.RemoveAllViewProps()
                print("✅ Removed all point cloud actors from main view")
                
                # Re-add ONLY DXF actors
                for actor in dxf_actors_backup:
                    renderer.AddActor(actor)
                
                # Re-add drawing actors
                for actor in drawing_actors_backup:
                    renderer.AddActor(actor)
                
                if dxf_actors_backup or drawing_actors_backup:
                    print(f"✅ Restored {len(dxf_actors_backup)} DXF + {len(drawing_actors_backup)} drawing actors")
                
                # Render to show cleared view
                app.vtk_widget.render()
                print(f"✅ Main viewer cleared (preserved: {len(dxf_actors_backup) + len(drawing_actors_backup)} actors)")
                    
            except Exception as e:
                print(f"⚠️ VTK clear failed: {e}")
                import traceback
                traceback.print_exc()

        # ============================================================================
        # STEP 3: Clear Cross-Section Views (AFTER cut is closed)
        # ============================================================================
        if hasattr(app, 'section_vtks') and app.section_vtks:
            print(f"\n🔄 Clearing point cloud data from {len(app.section_vtks)} cross-section views...")
            
            for view_idx, vtk_widget in app.section_vtks.items():
                try:
                    if vtk_widget and hasattr(vtk_widget, 'renderer'):
                        vtk_widget.renderer.RemoveAllViewProps()
                        vtk_widget.render()
                    print(f"  ✅ Cleared cross-section view {view_idx}")
                except Exception as e:
                    print(f"  ⚠️ Failed to clear view {view_idx}: {e}")
            
            print(f"✅ All cross-section views cleared (docks remain open)")

        # ============================================================================
        # STEP 4: Clear Section Controller
        # ============================================================================
        if hasattr(app, "section_controller") and app.section_controller:
            try:
                ctrl = app.section_controller
                
                # Clear sections data
                if hasattr(ctrl, 'sections'):
                    ctrl.sections.clear()
                
                # Clear stored cross-section data
                for view_idx in range(4):
                    section_view = getattr(ctrl, f"section_view_{view_idx}", None)
                    if section_view and hasattr(section_view, 'vtk_widget'):
                        try:
                            if hasattr(section_view.vtk_widget, 'renderer'):
                                section_view.vtk_widget.renderer.RemoveAllViewProps()
                                section_view.vtk_widget.render()
                        except Exception as e:
                            print(f"  ⚠️ Failed to clear section_view_{view_idx}: {e}")
                
                # Reset state flags
                if hasattr(ctrl, 'active_view'):
                    ctrl.active_view = 0
                if hasattr(ctrl, 'section_line'):
                    ctrl.section_line = None
                
                print("✅ Section controller cleared")
            except Exception as e:
                print(f"⚠️ Section controller clear failed: {e}")

        # ============================================================================
        # Clear Layers
        # ============================================================================
        app.layers = []
        if hasattr(app, "layers_dock") and app.layers_dock:
            try:
                app.layers_dock.clear_layers()
                print("✅ Layers cleared")
            except Exception as e:
                print(f"⚠️ Layers clear failed: {e}")

        # ============================================================================
        # Clear Digitizer Drawings
        # ============================================================================
        if hasattr(app, "digitizer") and app.digitizer:
            try:
                app.digitizer.clear_drawings()
                print("✅ Drawings cleared")
            except Exception as e:
                print(f"⚠️ Drawings clear failed: {e}")

        # Clear Internal State - BUT PRESERVE DISPLAY SETTINGS
        try:
            from .memory_manager import ObserverRegistry, release_data_arrays

            release_data_arrays(app)
            ObserverRegistry.release_all()

            mem_guard = getattr(app, "_mem_guard", None)
            if mem_guard is not None:
                mem_guard.force_gc()
        except Exception as e:
            print(f"⚠️ Memory manager cleanup skipped: {e}")

        app.data = None
        app.project_crs_epsg = None
        app.project_crs_wkt = None
        app.last_save_path = None
        app.loaded_file = None
        
        # ✅ PRESERVE display palettes and settings
        # app.class_palette stays intact - it's the main view configuration
        # app.view_palettes stays intact - these are all view configurations
        # They will be applied to the next file when loaded
        
        print("✅ Internal state cleared (display palettes preserved)")

        # ============================================================================
        # Clear Stored Section Data
        # ============================================================================
        for i in range(4):
            for attr in [f"section_{i}_core_points", f"section_{i}_buffer_points",
                        f"section_{i}_core_mask", f"section_{i}_buffer_mask"]:
                if hasattr(app, attr):
                    try:
                        delattr(app, attr)
                    except Exception:
                        pass
        print("✅ Stored section data cleared")

        # ============================================================================
        # Clear Undo/Redo Stacks
        # ============================================================================
        if hasattr(app, "undo_stack"):
            app.undo_stack.clear()
        if hasattr(app, "redo_stack"):
            app.redo_stack.clear()
        print("✅ Undo/redo history cleared")

        # ============================================================================
        # ✅ KEEP Display Mode Dialog COMPLETELY INTACT
        # Do NOT touch it - keep PTC loaded, keep table, keep all settings
        # ============================================================================
        if hasattr(app, "display_dialog") and app.display_dialog:
            try:
                print("✅ Display Mode dialog kept intact (PTC and table preserved)")
            except Exception as e:
                print(f"⚠️ Display Mode check failed: {e}")

        if hasattr(app, "display_mode_dialog") and app.display_mode_dialog:
            try:
                print("✅ Display Mode dialog kept intact (PTC and table preserved)")
            except Exception as e:
                print(f"⚠️ Display Mode check failed: {e}")

        # ============================================================================
        # Close Class Picker
        # ============================================================================
        if hasattr(app, "class_picker") and app.class_picker:
            try:
                app.class_picker.close()
                app.class_picker.deleteLater()
                app.class_picker = None
                print("✅ Class Picker closed")
            except Exception as e:
                print(f"⚠️ Class Picker close failed: {e}")

        # ============================================================================
        # Close Shading Control Panel
        # ============================================================================
        if hasattr(app, "shading_dock") and app.shading_dock:
            try:
                if hasattr(app, "removeDockWidget") and hasattr(app.shading_dock, "setWidget"):
                    app.removeDockWidget(app.shading_dock)
                else:
                    app.shading_dock.close()
                app.shading_dock.deleteLater()
                app.shading_dock = None
                if hasattr(app, "shading_panel"):
                    app.shading_panel = None
                print("✅ Shading dock closed")
            except Exception as e:
                print(f"⚠️ Shading dock close failed: {e}")

        # ============================================================================
        # Clear Point Statistics Widget
        # ============================================================================
        if hasattr(app, "point_count_widget") and app.point_count_widget:
            try:
                if hasattr(app.point_count_widget, 'clear_statistics'):
                    app.point_count_widget.clear_statistics()
                else:
                    if hasattr(app.point_count_widget, 'total_label'):
                        app.point_count_widget.total_label.setText("Total: 0")
                    if hasattr(app.point_count_widget, 'visible_label'):
                        app.point_count_widget.visible_label.setText("Visible: 0")
                    if hasattr(app.point_count_widget, 'class_tree'):
                        app.point_count_widget.class_tree.clear()
                print("✅ Point statistics cleared")
            except Exception as e:
                print(f"⚠️ Statistics clear failed: {e}")

        # ============================================================================
        # Reset Other States
        # ============================================================================
        app.active_classify_tool = None
        if hasattr(app, "skip_main_view_refresh"):
            app.skip_main_view_refresh = False
        
        # ✅ Keep display_mode as is (don't reset to "rgb")
        # User's preferred mode stays until next file loads
        
        if hasattr(app, "spatial_index"):
            app.spatial_index = None

        # ============================================================================
        # Update UI
        # ============================================================================
        app._update_window_title(None, None)
        
        if hasattr(app, "statusBar"):
            if should_save:
                app.statusBar().showMessage("🧹 Project saved and cleared - Display settings preserved", 5000)
            else:
                app.statusBar().showMessage("🧹 Project cleared - Display settings preserved", 5000)

        print("="*60)
        if should_save:
            print("✅ PROJECT SAVED AND CLEARED (DISPLAY SETTINGS PRESERVED)")
        else:
            print("✅ PROJECT CLEARED (DISPLAY SETTINGS PRESERVED)")
        print("="*60 + "\n")

    except Exception as e:
        error_msg = f"Failed to clear project: {e}"
        print(f"❌ {error_msg}")
        import traceback
        traceback.print_exc()
        
        if hasattr(app, "statusBar"):
            app.statusBar().showMessage(f"⚠️ {error_msg}", 5000)
        
        QMessageBox.critical(
            app,
            "Clear Project Error",
            f"An error occurred while clearing the project:\n\n{e}\n\n"
            "Some components may not have been cleared properly."
        )
