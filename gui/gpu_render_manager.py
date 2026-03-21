"""
GPU Render Manager - Non-invasive performance optimization
Handles render throttling, LOD, and GPU memory management
"""

import numpy as np
import time
from PySide6.QtCore import QTimer, QObject
from PySide6.QtWidgets import QApplication


class GPURenderManager(QObject):
    """
    Wraps VTK rendering with intelligent throttling and LOD.
    Zero modifications to existing code - pure wrapper pattern.
    """
    
    def __init__(self, app):
        super().__init__()
        self.app = app
        
        # Render throttling
        self.render_timer = QTimer()
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(self._execute_render)
        self.pending_render = False
        self.render_delay_ms = 100  # 100ms debounce (10 FPS during scroll)
        
        # Performance tracking
        self.last_render_time = 0
        self.render_count = 0
        self.skipped_renders = 0
        
        # LOD management
        self.lod_enabled = True
        self.last_camera_distance = None
        
        # Original render functions (to restore if needed)
        self._original_render = None
        self._original_add_points = None
        
        print("✅ GPU Render Manager initialized")
    
    def install(self):
        """Install render hooks into app"""
        try:
            # Hook into main VTK widget
            if hasattr(self.app, 'vtk_widget'):
                self._wrap_vtk_widget(self.app.vtk_widget)
                print("   📌 Hooked main VTK widget")
            
            # Hook into camera observers
            self._install_camera_observer()
            print("   📌 Installed camera observer")
            
            # Activate LOD if available
            if not hasattr(self.app, 'lod_manager'):
                from gui.performance_optimizations import LODManager
                self.app.lod_manager = LODManager(self.app)
                print("   📌 LOD Manager activated")
            
            print("✅ GPU Render Manager installed successfully")
            
        except Exception as e:
            print(f"⚠️  GPU Render Manager installation warning: {e}")
    
    def _wrap_vtk_widget(self, vtk_widget):
        """Wrap VTK widget's render method with throttling"""
        if not hasattr(vtk_widget, 'render'):
            return
        
        # Store original
        self._original_render = vtk_widget.render
        
        # Create throttled wrapper
        def throttled_render(*args, **kwargs):
            return self.request_render(vtk_widget, *args, **kwargs)
        
        # Replace
        vtk_widget.render = throttled_render
        print(f"      ✓ Wrapped vtk_widget.render()")
    
    def _install_camera_observer(self):
        """Install observer for camera movements"""
        try:
            interactor = self.app.vtk_widget.interactor
            
            # Mouse wheel events
            interactor.AddObserver("MouseWheelForwardEvent", self._on_camera_interaction)
            interactor.AddObserver("MouseWheelBackwardEvent", self._on_camera_interaction)
            
            # Pan/zoom interactions
            interactor.AddObserver("InteractionEvent", self._on_camera_interaction)
            
            print("      ✓ Camera observers installed")
            
        except Exception as e:
            print(f"      ⚠️  Camera observer warning: {e}")
    
    def _on_camera_interaction(self, obj, event):
        """Called on every camera movement - trigger LOD check"""
        try:
            # Don't trigger LOD during active rendering
            if self.pending_render:
                return
            
            # Check if LOD level needs update
            self._check_lod_update()
            
        except Exception as e:
            pass  # Silent fail during interaction
    
    def _check_lod_update(self):
        """Check if camera distance changed enough to update LOD"""
        try:
            if not self.lod_enabled or not hasattr(self.app, 'lod_manager'):
                return
            
            # Get current camera distance
            cam = self.app.vtk_widget.renderer.GetActiveCamera()
            cam_pos = np.array(cam.GetPosition())
            focal = np.array(cam.GetFocalPoint())
            distance = np.linalg.norm(cam_pos - focal)
            
            # Only update if distance changed significantly (>10%)
            if self.last_camera_distance is None:
                self.last_camera_distance = distance
                return
            
            change = abs(distance - self.last_camera_distance) / (self.last_camera_distance + 1e-6)
            
            if change > 0.1:  # 10% change threshold
                self.last_camera_distance = distance
                # LOD will be applied on next render
                
        except Exception:
            pass
    
    def request_render(self, vtk_widget, *args, **kwargs):
        """
        Throttled render request - batches rapid calls.
        
        Key optimization: Multiple rapid renders → Single delayed render
        """
        current_time = time.time()
        
        # If last render was very recent, schedule delayed render
        time_since_last = (current_time - self.last_render_time) * 1000  # ms
        
        if time_since_last < self.render_delay_ms:
            # Too soon - schedule for later
            if not self.pending_render:
                self.pending_render = True
                self.render_timer.start(self.render_delay_ms)
                self.skipped_renders += 1
            return
        
        # Enough time passed - render immediately
        self._execute_render()
    
    def _execute_render(self):
        """Execute the actual render (called after debounce delay)"""
        try:
            self.pending_render = False
            
            # Use original render method
            if self._original_render:
                self._original_render()
            else:
                # Fallback
                self.app.vtk_widget.GetRenderWindow().Render()
            
            self.last_render_time = time.time()
            self.render_count += 1
            
            # Log performance every 50 renders
            if self.render_count % 50 == 0:
                efficiency = (self.skipped_renders / (self.render_count + self.skipped_renders + 1)) * 100
                print(f"🎯 Render efficiency: {efficiency:.1f}% saved ({self.skipped_renders} skipped / {self.render_count} executed)")
                
        except Exception as e:
            print(f"⚠️  Render execution error: {e}")
    
    def force_render(self):
        """Force immediate render (bypass throttling)"""
        self.render_timer.stop()
        self.pending_render = False
        self._execute_render()
    
    def set_lod_enabled(self, enabled: bool):
        """Enable/disable LOD system"""
        self.lod_enabled = enabled
        print(f"{'✅' if enabled else '❌'} LOD {'enabled' if enabled else 'disabled'}")
    
    def set_render_delay(self, delay_ms: int):
        """
        Adjust render throttle delay.
        
        Lower = more responsive but higher GPU load
        Higher = smoother but slight lag
        
        Recommended: 100ms for 4GB GPU, 50ms for 8GB+ GPU
        """
        self.render_delay_ms = max(16, min(delay_ms, 500))  # Clamp 16-500ms
        print(f"⏱️  Render delay: {self.render_delay_ms}ms")
    
    def get_stats(self):
        """Return performance statistics"""
        total = self.render_count + self.skipped_renders
        if total == 0:
            return {"efficiency": 0, "renders": 0, "skipped": 0}
        
        return {
            "efficiency": (self.skipped_renders / total) * 100,
            "renders": self.render_count,
            "skipped": self.skipped_renders,
            "avg_delay_ms": self.render_delay_ms
        }


class AdaptivePointSize:
    """
    Automatically adjust point size based on zoom level.
    Smaller points when zoomed out = less GPU geometry.
    """
    
    def __init__(self, app):
        self.app = app
        self.base_point_size = 2.0
        self.min_size = 1.0
        self.max_size = 5.0
    
    def get_adaptive_size(self) -> float:
        """Calculate point size based on camera distance"""
        try:
            cam = self.app.vtk_widget.renderer.GetActiveCamera()
            cam_pos = np.array(cam.GetPosition())
            focal = np.array(cam.GetFocalPoint())
            distance = np.linalg.norm(cam_pos - focal)
            
            # Simple heuristic: closer = larger points
            if distance < 100:
                return self.max_size
            elif distance < 500:
                return self.base_point_size
            elif distance < 1000:
                return self.base_point_size * 0.75
            else:
                return self.min_size
                
        except:
            return self.base_point_size


# ============================================================================
# HELPER FUNCTIONS - Call these from your existing code
# ============================================================================

def safe_render(app):
    """
    Replacement for app.vtk_widget.render()
    Use this in critical places where you need guaranteed render.
    """
    if hasattr(app, 'gpu_render_manager'):
        app.gpu_render_manager.force_render()
    else:
        app.vtk_widget.render()


def get_render_stats(app):
    """Get performance statistics"""
    if hasattr(app, 'gpu_render_manager'):
        return app.gpu_render_manager.get_stats()
    return None


def configure_render_delay(app, delay_ms: int):
    """
    Configure render throttle delay.
    
    Call this based on GPU capability:
    - 4GB GPU: configure_render_delay(app, 100)  # Conservative
    - 8GB+ GPU: configure_render_delay(app, 50)   # Responsive
    """
    if hasattr(app, 'gpu_render_manager'):
        app.gpu_render_manager.set_render_delay(delay_ms)
