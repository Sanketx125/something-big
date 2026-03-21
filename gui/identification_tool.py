
"""
Identification Tool for NakshaAI
Allows clicking on points to identify their class and properties
✅ FIXED: Highlights identified class in Point Statistics widget
"""

from PySide6.QtCore import QObject, Signal
import numpy as np


class IdentificationTool(QObject):
    """Tool for identifying point properties on click"""
    
    point_identified = Signal(int, str, tuple)  # class_code, class_name, (x, y, z)
    
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.active = False
        self.picker = None
        self._click_observer = None
        self._section_observers = {}
        print("✅ IdentificationTool initialized")
    
    def activate(self):
        """Activate identification mode for main view and all open section views"""
        if self.active:
            print("⚠️ Identification tool already active")
            return
        
        self.active = True
        print("🔍 Identification tool ACTIVATED")
        
        # Activate for main view
        if hasattr(self.app, 'vtk_widget'):
            try:
                vtk_interactor = self.app.vtk_widget.interactor
                
                if self.picker is None:
                    import vtk
                    self.picker = vtk.vtkPointPicker()
                    self.picker.SetTolerance(0.005)
                
                # ✅ FIX: Use LOWER priority so Cross Section interactor runs first
                # Cross Section uses default priority (0.0), we use -1.0 to run AFTER it
                self._click_observer = vtk_interactor.AddObserver(
                    "LeftButtonPressEvent",
                    self._on_left_click,
                    -1.0  # Lower priority = runs after other tools
                )
                
                print(f"   ✅ Main view observer attached with LOW priority (ID: {self._click_observer})")
                
            except Exception as e:
                print(f"   ⚠️ Failed to attach main observer: {e}")
        
        # Activate for all open cross-section views
        if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
            for view_index, vtk_widget in self.app.section_vtks.items():
                self.activate_for_section(vtk_widget, view_index)

    def deactivate(self):
        """Deactivate identification mode for all views"""
        if not self.active:
            return
        
        self.active = False
        print("🔍 Identification tool DEACTIVATED")
        
        # Deactivate main view
        if self._click_observer is not None and hasattr(self.app, 'vtk_widget'):
            try:
                vtk_interactor = self.app.vtk_widget.interactor
                vtk_interactor.RemoveObserver(self._click_observer)
                print(f"   ✅ Main view observer removed")
            except Exception as e:
                print(f"   ⚠️ Failed to remove main observer: {e}")
            
            self._click_observer = None
        
        # Deactivate all section views
        self.deactivate_all_sections()
        
        # ✅ NEW: Clear highlight when deactivating
        self.clear_highlight()
    
    def _on_left_click(self, obj, event):
        """
        Handle left click to identify point.
        ✅ FIX: Check if Cross Section tool is active and skip if it is
        """
        if not self.active:
            return
        
        # ✅ CRITICAL FIX: Don't interfere with Cross Section tool
        if hasattr(self.app, 'cross_interactor') and self.app.cross_interactor:
            # Check if Cross Section is currently active (drawing rectangle)
            if hasattr(self.app, 'cross_action') and self.app.cross_action:
                if self.app.cross_action.isChecked():
                    print("🚫 Cross Section active - skipping identification")
                    return
        
        try:
            # Get click position
            vtk_interactor = self.app.vtk_widget.interactor
            click_pos = vtk_interactor.GetEventPosition()
            
            print(f"🔍 Click at screen position: {click_pos}")
            
            # Get renderer
            renderer = self.app.vtk_widget.renderer
            
            # Use cell picker instead of point picker
            import vtk
            picker = vtk.vtkCellPicker()
            picker.SetTolerance(0.01)  # Increased tolerance for better picking
            
            # Pick at the click location
            success = picker.Pick(click_pos[0], click_pos[1], 0, renderer)
            
            if success:
                # Get the picked 3D position
                picked_pos = picker.GetPickPosition()
                
                print(f"   ✅ Picked 3D position: {picked_pos}")
                
                # Find the closest point in the actual point cloud data
                if hasattr(self.app, 'data') and self.app.data is not None:
                    xyz = self.app.data.get('xyz')
                    classification = self.app.data.get('classification')
                    
                    if xyz is not None and classification is not None:
                        # Find closest point to picked position
                        picked_array = np.array(picked_pos)
                        distances = np.linalg.norm(xyz - picked_array, axis=1)
                        closest_idx = np.argmin(distances)
                        closest_dist = distances[closest_idx]
                        
                        print(f"   📍 Closest point index: {closest_idx} (distance: {closest_dist:.3f})")
                        
                        # Only accept if reasonably close (within 1 unit)
                        if closest_dist < 1.0:
                            class_code = int(classification[closest_idx])
                            class_name = self.get_class_name(class_code)
                            actual_pos = tuple(xyz[closest_idx])
                            
                            print(f"   🏷️ Class: {class_code} ({class_name})")
                            
                            # ✅ NEW: Highlight in Point Statistics widget
                            self.highlight_class(class_code)
                            
                            # Update ribbon display
                            self._update_ribbon_info(class_code, class_name, actual_pos)
                            
                            # Emit signal
                            self.point_identified.emit(class_code, class_name, actual_pos)
                        else:
                            print(f"   ⚠️ Closest point too far away ({closest_dist:.3f} units)")
                    else:
                        print("   ⚠️ No xyz or classification data")
                else:
                    print("   ⚠️ No point cloud data loaded")
            else:
                print("   ⚠️ Pick failed - no geometry at click location")
                    
        except Exception as e:
            print(f"   ❌ Error in click handler: {e}")
            import traceback
            traceback.print_exc()
    
    def _update_ribbon_info(self, class_code, class_name, xyz):
        """Update the identification ribbon with point info"""
        try:
            if hasattr(self.app, 'ribbon_manager'):
                identify_ribbon = self.app.ribbon_manager.ribbons.get('identify')
                if identify_ribbon:
                    # ✅ FIX: Get BOTH color AND level
                    class_color = self.get_class_color(class_code)
                    class_lvl = self.get_class_lvl(class_code)  # ← ADD THIS
                    
                    # ✅ FIX: Pass level to update_info
                    identify_ribbon.update_info(
                        class_code, 
                        class_name, 
                        xyz, 
                        color=class_color,
                        lvl=class_lvl  # ← ADD THIS
                    )
        except Exception as e:
            print(f"   ⚠️ Failed to update ribbon: {e}")
    
    def highlight_class(self, class_code):
        """
        ✅ NEW: Highlight a class in the Point Statistics widget.
        
        Args:
            class_code: The classification code to highlight
        """
        if not hasattr(self.app, 'point_count_widget') or not self.app.point_count_widget:
            print("   ⚠️ Point Statistics widget not available")
            return
        
        try:
            # Get the widget's stats container
            stats_container = self.app.point_count_widget.stats_container
            layout = self.app.point_count_widget.stats_layout
            
            # Iterate through all stat widgets to find and highlight the matching class
            for i in range(layout.count()):
                widget = layout.itemAt(i).widget()
                if widget and hasattr(widget, 'property'):
                    # Check if this widget represents our class
                    stored_code = widget.property('class_code')
                    if stored_code == class_code:
                        # Apply highlight style
                        self._apply_highlight_style(widget, class_code)
                        
                        # Scroll to make it visible
                        if hasattr(self.app.point_count_widget, 'parent') and \
                           hasattr(self.app.point_count_widget.parent(), 'ensureWidgetVisible'):
                            self.app.point_count_widget.parent().ensureWidgetVisible(widget)
                        
                        print(f"   ✅ Highlighted class {class_code} in Point Statistics")
                        return
            
            print(f"   ⚠️ Class {class_code} not found in Point Statistics widget")
            
        except Exception as e:
            print(f"   ⚠️ Failed to highlight class: {e}")
            import traceback
            traceback.print_exc()
    
    def _apply_highlight_style(self, widget, class_code):
        """Apply a highlight animation/style to a widget."""
        try:
            from PySide6.QtCore import QPropertyAnimation, QEasingCurve
            from PySide6.QtGui import QColor
            
            # Get the original style
            original_style = widget.styleSheet()
            
            # Create a pulsing highlight effect
            def pulse_highlight():
                # Bright highlight
                highlight_style = original_style.replace(
                    'background-color: rgba(',
                    'background-color: rgba(255, 255, 100, 0.4); /* background-color: rgba('
                )
                widget.setStyleSheet(highlight_style)
                
                # After 500ms, fade back
                from PySide6.QtCore import QTimer
                QTimer.singleShot(500, lambda: widget.setStyleSheet(original_style))
            
            # Trigger pulse
            pulse_highlight()
            
        except Exception as e:
            print(f"   ⚠️ Failed to apply highlight animation: {e}")
    
    def clear_highlight(self):
        """Clear all highlights from the Point Statistics widget."""
        if not hasattr(self.app, 'point_count_widget') or not self.app.point_count_widget:
            return
        
        try:
            # Simply refresh the widget to restore original styles
            self.app.point_count_widget.update_statistics()
        except Exception as e:
            print(f"   ⚠️ Failed to clear highlight: {e}")
    
    def get_class_color(self, class_code):
        """
        Get the RGB color for a classification code from the app's class palette.
        Returns tuple (r, g, b) or None if not found.
        """
        # Try to get from app's class palette first
        if hasattr(self.app, 'class_palette') and self.app.class_palette:
            class_info = self.app.class_palette.get(class_code)
            if class_info and 'color' in class_info:
                return class_info['color']
        
        # Try Display Mode dialog palette as backup
        if hasattr(self.app, 'display_mode_dialog') and self.app.display_mode_dialog:
            dialog = self.app.display_mode_dialog
            if hasattr(dialog, 'view_palettes'):
                for view_palette in dialog.view_palettes.values():
                    if class_code in view_palette:
                        color = view_palette[class_code].get('color')
                        if color:
                            return color
        
        # Try Display Mode table directly
        if hasattr(self.app, 'display_dialog') and self.app.display_dialog:
            dialog = self.app.display_dialog
            if hasattr(dialog, 'table'):
                table = dialog.table
                for row in range(table.rowCount()):
                    try:
                        code = int(table.item(row, 1).text())
                        if code == class_code:
                            color_item = table.item(row, 5)
                            if color_item:
                                color = color_item.background().color().getRgb()[:3]
                                return color
                    except:
                        continue
        
        # Fallback to default gray
        return (160, 160, 160)
    
    def get_class_name(self, class_code):
        """
        Get the name for a classification code from the app's class palette.
        Falls back to default names if palette not available.
        """
        if hasattr(self.app, 'display_mode_dialog') and self.app.display_mode_dialog:
            table = self.app.display_mode_dialog.table
            for row in range(table.rowCount()):
                try:
                    code = int(table.item(row, 1).text())
                    if code == class_code:
                        desc = table.item(row, 2).text()  # Description column
                        return desc
                except:
                    continue
        # Try to get from app's class palette first
        if hasattr(self.app, 'class_palette') and self.app.class_palette:
            class_info = self.app.class_palette.get(class_code)
            if class_info and 'description' in class_info:
                return class_info['description']
        
        # Try Display Mode dialog palette as backup
        if hasattr(self.app, 'display_mode_dialog') and self.app.display_mode_dialog:
            dialog = self.app.display_mode_dialog
            if hasattr(dialog, 'view_palettes'):
                for view_palette in dialog.view_palettes.values():
                    if class_code in view_palette:
                        return view_palette[class_code].get('description', f"Class {class_code}")
        
        # Fallback to standard LAS classification names
        default_names = {
            0: "Never Classified",
            1: "Unclassified",
            2: "Ground",
            3: "Low Vegetation",
            4: "Medium Vegetation",
            5: "High Vegetation",
            6: "Building",
            7: "Low Point (Noise)",
            8: "Reserved",
            9: "Water",
            10: "Rail",
            11: "Road Surface",
            12: "Reserved",
            13: "Wire - Guard",
            14: "Wire - Conductor",
            15: "Transmission Tower",
            16: "Wire - Connector",
            17: "Bridge Deck",
            18: "High Noise"
        }
        
        return default_names.get(class_code, f"Class {class_code}")
    
    def activate_for_section(self, section_vtk_widget, view_index):
        """
        Activate identification for a specific cross-section view.
        
        Args:
            section_vtk_widget: The QtInteractor widget for the section view
            view_index: Index of the section view (0-3)
        """
        if not hasattr(self, '_section_observers'):
            self._section_observers = {}
        
        # Don't re-attach if already active for this view
        if view_index in self._section_observers:
            print(f"⚠️ Identification already active for section view {view_index + 1}")
            return
        
        print(f"🔍 Activating identification for Cross Section View {view_index + 1}")
        
        try:
            vtk_interactor = section_vtk_widget.interactor
            
            # Add observer for left click (lower priority for section views too)
            observer_id = vtk_interactor.AddObserver(
                "LeftButtonPressEvent",
                lambda obj, event: self._on_section_click(obj, event, section_vtk_widget, view_index),
                -1.0  # Lower priority
            )
            
            self._section_observers[view_index] = {
                'observer_id': observer_id,
                'vtk_widget': section_vtk_widget
            }
            
            print(f"   ✅ Section click observer attached (ID: {observer_id})")
            
        except Exception as e:
            print(f"   ⚠️ Failed to attach section observer: {e}")

    def deactivate_for_section(self, view_index):
        """Deactivate identification for a specific cross-section view."""
        if not hasattr(self, '_section_observers'):
            return
        
        if view_index not in self._section_observers:
            return
        
        try:
            info = self._section_observers[view_index]
            vtk_interactor = info['vtk_widget'].interactor
            vtk_interactor.RemoveObserver(info['observer_id'])
            
            del self._section_observers[view_index]
            print(f"   ✅ Section observer removed for view {view_index + 1}")
            
        except Exception as e:
            print(f"   ⚠️ Failed to remove section observer: {e}")

    def deactivate_all_sections(self):
        """Deactivate identification for all cross-section views."""
        if not hasattr(self, '_section_observers'):
            return
        
        for view_index in list(self._section_observers.keys()):
            self.deactivate_for_section(view_index)

    def _on_section_click(self, obj, event, section_vtk_widget, view_index):
        """Handle left click in cross-section view to identify point"""
        if not self.active:
            return
        
        try:
            # Get click position
            vtk_interactor = section_vtk_widget.interactor
            click_pos = vtk_interactor.GetEventPosition()
            
            print(f"🔍 Section View {view_index + 1} - Click at: {click_pos}")
            
            # Get renderer
            renderer = section_vtk_widget.renderer
            
            # Use cell picker
            import vtk
            picker = vtk.vtkCellPicker()
            picker.SetTolerance(0.01)
            
            # Pick at the click location
            success = picker.Pick(click_pos[0], click_pos[1], 0, renderer)
            
            if success:
                # Get the picked 3D position
                picked_pos = picker.GetPickPosition()
                
                print(f"   ✅ Picked 3D position: {picked_pos}")
                
                # Get section data for this view
                section_xyz = self._get_section_xyz(view_index)
                
                if section_xyz is not None and len(section_xyz) > 0:
                    # Find closest point in section data
                    picked_array = np.array(picked_pos)
                    distances = np.linalg.norm(section_xyz - picked_array, axis=1)
                    closest_idx = np.argmin(distances)
                    closest_dist = distances[closest_idx]
                    
                    print(f"   📍 Closest point index in section: {closest_idx} (distance: {closest_dist:.3f})")
                    
                    # Only accept if reasonably close
                    if closest_dist < 2.0:  # Larger tolerance for section views
                        # Get the original point index in main dataset
                        original_idx = self._get_original_index(view_index, closest_idx)
                        
                        if original_idx is not None:
                            classification = self.app.data.get('classification')
                            
                            if classification is not None:
                                class_code = int(classification[original_idx])
                                class_name = self.get_class_name(class_code)
                                actual_pos = tuple(section_xyz[closest_idx])
                                
                                print(f"   🏷️ Class: {class_code} ({class_name})")
                                
                                # ✅ NEW: Highlight in Point Statistics widget
                                self.highlight_class(class_code)
                                
                                # Update ribbon display
                                self._update_ribbon_info(class_code, class_name, actual_pos)
                                
                                # Emit signal
                                self.point_identified.emit(class_code, class_name, actual_pos)
                            else:
                                print("   ⚠️ No classification data")
                        else:
                            print("   ⚠️ Could not find original point index")
                    else:
                        print(f"   ⚠️ Closest point too far away ({closest_dist:.3f} units)")
                else:
                    print("   ⚠️ No section data available")
            else:
                print("   ⚠️ Pick failed - no geometry at click location")
                    
        except Exception as e:
            print(f"   ❌ Error in section click handler: {e}")
            import traceback
            traceback.print_exc()

    def _get_section_xyz(self, view_index):
        """Get XYZ coordinates for a section view."""
        try:
            # Try to get from stored section data
            core_pts = getattr(self.app, f'section_{view_index}_core_points', None)
            buf_pts = getattr(self.app, f'section_{view_index}_buffer_points', None)
            
            if core_pts is not None:
                if buf_pts is not None:
                    return np.vstack([core_pts, buf_pts])
                return core_pts
            
            return None
            
        except Exception as e:
            print(f"   ⚠️ Error getting section XYZ: {e}")
            return None

    def _get_original_index(self, view_index, section_local_idx):
        """
        Convert local section index to original dataset index.
        
        Args:
            view_index: Section view index (0-3)
            section_local_idx: Index within the section point array
        
        Returns:
            Original index in app.data, or None if not found
        """
        try:
            # Get masks for this section
            core_mask = getattr(self.app, f'section_{view_index}_core_mask', None)
            buffer_mask = getattr(self.app, f'section_{view_index}_buffer_mask', None)
            
            if core_mask is None:
                return None
            
            # Get core and buffer point counts
            core_pts = getattr(self.app, f'section_{view_index}_core_points', None)
            buf_pts = getattr(self.app, f'section_{view_index}_buffer_points', None)
            
            num_core = len(core_pts) if core_pts is not None else 0
            
            # Check if index is in core or buffer
            if section_local_idx < num_core:
                # It's in core - find the Nth true value in core_mask
                core_indices = np.where(core_mask)[0]
                if section_local_idx < len(core_indices):
                    return core_indices[section_local_idx]
            else:
                # It's in buffer
                if buffer_mask is not None:
                    buffer_local_idx = section_local_idx - num_core
                    # Find indices that are in buffer but not in core
                    buffer_only = buffer_mask & ~core_mask
                    buffer_indices = np.where(buffer_only)[0]
                    if buffer_local_idx < len(buffer_indices):
                        return buffer_indices[buffer_local_idx]
            
            return None
            
        except Exception as e:
            print(f"   ⚠️ Error mapping section index: {e}")
            return None
        
    def get_class_lvl(self, class_code):
        """
        Get the Level (Lvl) for a classification code from Display Mode table.
        Returns string or empty string if not found.
        """
        # Read from Display Mode dialog table (Column 4 = Lvl)
        if hasattr(self.app, 'display_mode_dialog') and self.app.display_mode_dialog:
            table = self.app.display_mode_dialog.table
            for row in range(table.rowCount()):
                try:
                    code = int(table.item(row, 1).text())
                    if code == class_code:
                        lvl_item = table.item(row, 4)  # Column 4 = Lvl
                        return lvl_item.text() if lvl_item else ""
                except:
                    continue
        
        # Fallback
        return ""