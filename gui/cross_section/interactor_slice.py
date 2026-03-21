

import numpy as np
import vtk


class CrossSectionInteractor(vtk.vtkInteractorStyleTrackballCamera):
    """Persistent interactor for directional cross-section selection."""

    def __init__(self, app, iren):
        super().__init__()
        self.app = app
        self.iren = iren

        # state machine
        # 0 = waiting for first click
        # 1 = dragging preview line (P1 → cursor)
        # 2 = width adjustment after P2 fixed
        self.slice_state = 0
        self.P1 = None
        self.P2 = None

        self.AddObserver("LeftButtonPressEvent", self.on_left_press)
        self.AddObserver("MouseMoveEvent", self.on_mouse_move)
        self.AddObserver("LeftButtonReleaseEvent", self.on_left_release)

        # keep camera navigation
        self.AddObserver("MiddleButtonPressEvent", lambda o, e: self.OnMiddleButtonDown())
        self.AddObserver("MiddleButtonReleaseEvent", lambda o, e: self.OnMiddleButtonUp())
        self.AddObserver("RightButtonPressEvent", lambda o, e: self.OnRightButtonDown())
        self.AddObserver("RightButtonReleaseEvent", lambda o, e: self.OnRightButtonUp())
        # self.AddObserver("KeyPressEvent", self.on_key_press)

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
