import numpy as np


class FitViewController:
    """
    Robust Fit View controller.
    Prevents black screen by fixing camera Z and clipping.
    """

    def __init__(self, app):
        self.app = app

    def fit_main_view(self):
        vtk_widget = getattr(self.app, "vtk_widget", None)
        if not vtk_widget:
            return

        renderer = vtk_widget.renderer
        cam = renderer.GetActiveCamera()

        data = getattr(self.app, "data", None)
        if not isinstance(data, dict) or "xyz" not in data:
            renderer.ResetCamera()
            vtk_widget.render()
            return

        xyz = data["xyz"]
        if xyz is None or len(xyz) == 0:
            return

        self._fit_xyz(renderer, cam, xyz)
        vtk_widget.render()
        print("✅ Fit View applied safely")

    # --------------------------------------------------
    def _fit_xyz(self, renderer, cam, xyz):
        xmin, ymin, zmin = xyz.min(axis=0)
        xmax, ymax, zmax = xyz.max(axis=0)

        cx = 0.5 * (xmin + xmax)
        cy = 0.5 * (ymin + ymax)
        cz = 0.5 * (zmin + zmax)

        # -----------------------------
        # 2D Plan View safe setup
        # -----------------------------
        cam.ParallelProjectionOn()

        # Place camera ABOVE the data, not at Z=1
        z_offset = max(zmax - zmin, 1.0) * 2.0
        cam.SetFocalPoint(cx, cy, cz)
        cam.SetPosition(cx, cy, cz + z_offset)
        cam.SetViewUp(0, 1, 0)

        # Correct parallel scale
        span_xy = max(xmax - xmin, ymax - ymin)
        cam.SetParallelScale(span_xy * 0.55)

        # CRITICAL: fix clipping
        renderer.ResetCameraClippingRange(xmin, xmax, ymin, ymax, zmin, zmax)
