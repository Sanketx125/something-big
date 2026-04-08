

import numpy as np
import vtk


class CrossSectionInteractor(vtk.vtkInteractorStyleTrackballCamera):
    """Persistent interactor for directional cross-section selection."""

    def __init__(self, app, iren):
        super().__init__()
        self.app = app
        self.iren = iren

        # ✅ NEW: Store original interactor style for restoration
        self._original_style = iren.GetInteractorStyle()
        
        # ✅ NEW: Store observer IDs for cleanup
        self._observer_ids = []

        # state machine
        self.slice_state = 0
        self.P1 = None
        self.P2 = None

        # ✅ FIXED: Store observer IDs
        self._observer_ids.append(
            self.AddObserver("LeftButtonPressEvent", self.on_left_press)
        )
        self._observer_ids.append(
            self.AddObserver("MouseMoveEvent", self.on_mouse_move)
        )
        self._observer_ids.append(
            self.AddObserver("LeftButtonReleaseEvent", self.on_left_release)
        )

        # keep camera navigation
        self._observer_ids.append(
            self.AddObserver("MiddleButtonPressEvent", lambda o, e: self.OnMiddleButtonDown())
        )
        self._observer_ids.append(
            self.AddObserver("MiddleButtonReleaseEvent", lambda o, e: self.OnMiddleButtonUp())
        )
        self._observer_ids.append(
            self.AddObserver("RightButtonPressEvent", lambda o, e: self.OnRightButtonDown())
        )
        self._observer_ids.append(
            self.AddObserver("RightButtonReleaseEvent", lambda o, e: self.OnRightButtonUp())
        )

    # ✅ NEW: Add cleanup method
    def cleanup(self):
        """Remove all observers and restore original interactor style."""
        try:
            # Remove all observers
            for obs_id in self._observer_ids:
                try:
                    self.RemoveObserver(obs_id)
                except Exception:
                    pass
            self._observer_ids.clear()
            
            # Restore original interactor style
            if self._original_style is not None and self.iren is not None:
                try:
                    self.iren.SetInteractorStyle(self._original_style)
                    print("✅ CrossSectionInteractor: Original style restored")
                except Exception as e:
                    print(f"⚠️ Failed to restore original style: {e}")
            
            # Clear state
            self.P1 = None
            self.P2 = None
            self.slice_state = 0
            
        except Exception as e:
            print(f"⚠️ CrossSectionInteractor cleanup error: {e}")

    # ---------------- PICKER ----------------

    def on_left_press(self, obj, ev):
        x, y = self.iren.GetEventPosition()
        pt = self._display_to_world(x, y)

        if self.slice_state == 0:
            self.app.section_controller.clear()
            self.P1 = pt
            self.slice_state = 1

        elif self.slice_state == 1:
            self.P2 = pt
            self.slice_state = 2



    def _display_to_world(self, x, y):
        """
        Cursor-accurate DISPLAY → WORLD conversion.
        No snapping. No picking. Zoom safe.
        """
        ren = self.app.vtk_widget.renderer

        coord = vtk.vtkCoordinate()
        coord.SetCoordinateSystemToDisplay()
        coord.SetValue(float(x), float(y), 0.0)

        world = coord.GetComputedWorldValue(ren)
        return np.array(world, dtype=np.float64)



    def on_mouse_move(self, obj, ev):
        x, y = self.iren.GetEventPosition()
        curr = self._display_to_world(x, y)

        # 🔒 LOCK Z — THIS REMOVES ALL MAGNETIC EFFECTS
        if self.P1 is not None:
            curr[2] = self.P1[2]

        if self.slice_state == 1 and self.P1 is not None:
            self.app.section_controller.draw_centerline(self.P1, curr)

        elif self.slice_state == 2:
            if self.P1 is None or self.P2 is None:
                return

            v = self.P2[:2] - self.P1[:2]
            if np.linalg.norm(v) < 1e-9:
                return

            dir = v / np.linalg.norm(v)
            perp = np.array([-dir[1], dir[0]])
            half_width = abs(np.dot(curr[:2] - self.P2[:2], perp))

            self.app.section_controller.draw_rubber_rectangle(
                self.P1, self.P2, half_width
            )

        self.OnMouseMove()




    def on_left_release(self, obj, evt):
        if self.slice_state == 2 and self.P1 is not None and self.P2 is not None:
            # finalize rectangle + compute section
            self.app.section_controller.finalize_section(self.P1, self.P2)

            # ✅ notify app that section in this view changed
            try:
                view_idx = getattr(self.app.section_controller, "active_view", None)
                if view_idx is None:
                    view_idx = 0
                if hasattr(self.app, "_on_section_updated"):
                    self.app._on_section_updated(view_idx)
            except Exception as e:
                print(f"⚠️ Sync hook failed after finalize_section: {e}")

            # reset so user can start next cross-section
            self.P1 = None
            self.P2 = None
            self.slice_state = 0

    # def on_key_press(self, obj, ev):
    #     key = self.iren.GetKeySym()
    #     if key.lower() == "escape":
    #         from vtk import vtkInteractorStyleTrackballCamera
    #         self.app.vtk_widget.interactor.SetInteractorStyle(vtkInteractorStyleTrackballCamera())
    #         self.app.section_controller.clear()
    #         self.P1 = None
    #         self.P2 = None
    #         self.slice_state = 0
    #         if self.app.cross_action.isChecked():
    #             self.app.cross_action.setChecked(False)
    
    # def on_key_press(self, obj, ev):
    #     key = self.iren.GetKeySym()
    #     if key.lower() == "escape":
    #         # ❌ DELETE THESE LINES (or comment them out):
    #         # from vtk import vtkInteractorStyleTrackballCamera
    #         # self.app.vtk_widget.interactor.SetInteractorStyle(vtkInteractorStyleTrackballCamera())
    #         # self.app.section_controller.clear()
    #         # self.P1 = None
    #         # self.P2 = None
    #         # self.slice_state = 0
    #         # if self.app.cross_action.isChecked():
    #         #     self.app.cross_action.setChecked(False)
    #         pass  # ✅ ADD THIS - do nothing, let main app handle ESC
