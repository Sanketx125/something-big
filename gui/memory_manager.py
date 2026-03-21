"""
Memory utilities for periodic cleanup and memory pressure handling.
"""

from __future__ import annotations

import gc
import os

from PySide6.QtCore import QObject, QTimer

try:
    import psutil
except Exception:  # pragma: no cover - optional at runtime
    psutil = None


MAX_UNDO_STEPS = 20
GC_INTERVAL_MS = 15_000
RAM_CHECK_MS = 15_000
RAM_WARN_PERCENT = 80


class ObserverRegistry:
    """Central store for VTK interactor observer IDs."""

    _registry: dict = {}

    @classmethod
    def track(cls, interactor, observer_id: int, tag: str = "") -> None:
        if interactor is None or observer_id is None:
            return
        key = id(interactor)
        if key not in cls._registry:
            cls._registry[key] = {"interactor": interactor, "ids": [], "tags": []}
        cls._registry[key]["ids"].append(observer_id)
        cls._registry[key]["tags"].append(tag)

    @classmethod
    def release(cls, interactor) -> None:
        if interactor is None:
            return
        key = id(interactor)
        entry = cls._registry.pop(key, None)
        if entry is None:
            return
        removed = 0
        for observer_id in entry["ids"]:
            try:
                interactor.RemoveObserver(observer_id)
                removed += 1
            except Exception:
                pass
        if removed:
            print(f"[MEM] ObserverRegistry removed {removed} observer(s)")

    @classmethod
    def release_all(cls) -> None:
        for _, entry in list(cls._registry.items()):
            interactor = entry.get("interactor")
            if interactor is None:
                continue
            for observer_id in entry.get("ids", []):
                try:
                    interactor.RemoveObserver(observer_id)
                except Exception:
                    pass
        cls._registry.clear()

    @classmethod
    def count(cls) -> int:
        return sum(len(entry["ids"]) for entry in cls._registry.values())

def _free_undo_entry(entry: dict) -> None:
    if not isinstance(entry, dict):
        return
    for key in ("mask", "old_classes", "new_classes", "oldclasses", "newclasses",
                "old", "new", "classification"):
        arr = entry.pop(key, None)
        if arr is not None:
            del arr

def trim_undo_stack(app, max_steps: int = MAX_UNDO_STEPS) -> None:
    """Trim undo/redo stacks and free arrays from dropped entries."""
    undo = getattr(app, "undo_stack", None)
    if not isinstance(undo, list):
        return

    redo = getattr(app, "redo_stack", None)
    if isinstance(redo, list):
        while len(redo) > max_steps:
            _free_undo_entry(redo.pop(0))

    while len(undo) > max_steps:
        _free_undo_entry(undo.pop(0))

def release_data_arrays(app) -> None:
    """Release project arrays and memory-heavy structures."""
    data = getattr(app, "data", None)
    if isinstance(data, dict):
        for key in list(data.keys()):
            value = data.pop(key, None)
            if value is not None:
                del value
        del data
    app.data = None

    if hasattr(app, "spatial_index") and app.spatial_index is not None:
        try:
            del app.spatial_index.tree
            del app.spatial_index.xyz
        except Exception:
            pass
        app.spatial_index = None

    for attr in ("current_gpu_indices", "current_visibility_mask"):
        if hasattr(app, attr):
            setattr(app, attr, None)

    for stack_name in ("undo_stack", "redo_stack"):
        stack = getattr(app, stack_name, None)
        if isinstance(stack, list):
            for entry in stack:
                _free_undo_entry(entry)
            stack.clear()

    print("[MEM] Data arrays explicitly released")


def cleanup_stale_actors(app) -> int:
    """Remove orphaned class actors from section views."""
    cleaned = 0
    section_vtks = getattr(app, "section_vtks", None)
    if not isinstance(section_vtks, dict):
        return cleaned

    for view_idx, vtk_widget in section_vtks.items():
        if vtk_widget is None or not hasattr(vtk_widget, "actors"):
            continue

        core_mask = getattr(app, f"section_{view_idx}_core_mask", None)
        if core_mask is not None:
            continue

        try:
            actor_names = list(vtk_widget.actors.keys())
        except Exception:
            continue

        for name in actor_names:
            if not str(name).startswith("class_"):
                continue
            try:
                vtk_widget.remove_actor(name, render=False)
                cleaned += 1
            except Exception:
                pass

    if cleaned:
        print(f"[MEM] Cleaned {cleaned} stale actor(s) from section views")
    return cleaned


def count_all_actors(app) -> int:
    total = 0

    main = getattr(app, "vtk_widget", None)
    if main is not None and hasattr(main, "actors"):
        total += len(main.actors)

    section_vtks = getattr(app, "section_vtks", None)
    if isinstance(section_vtks, dict):
        for view in section_vtks.values():
            if view is not None and hasattr(view, "actors"):
                total += len(view.actors)

    cut_ctrl = getattr(app, "cut_section_controller", None)
    if cut_ctrl is not None:
        cut_vtk = getattr(cut_ctrl, "cut_vtk", None)
        if cut_vtk is not None and hasattr(cut_vtk, "actors"):
            total += len(cut_vtk.actors)

    return total


class MemoryLeakGuard(QObject):
    """
    Periodic memory maintenance:
    - gc.collect() every 15s
    - RAM check every 15s (warn if above threshold)
    - Undo stack trim
    - Stale actor cleanup
    """

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self._gc_timer = QTimer(self)
        self._ram_timer = QTimer(self)
        self._process = psutil.Process(os.getpid()) if psutil is not None else None
        self._gc_timer.timeout.connect(self._run_gc)
        self._ram_timer.timeout.connect(self._check_ram)
        self._last_gc_freed = 0

    def start(self) -> None:
        self._gc_timer.start(GC_INTERVAL_MS)
        if psutil is not None:
            self._ram_timer.start(RAM_CHECK_MS)
        print(
            f"[MEM] MemoryLeakGuard started (GC every {GC_INTERVAL_MS // 1000}s, "
            f"max undo={MAX_UNDO_STEPS})"
        )

    def stop(self) -> None:
        self._gc_timer.stop()
        self._ram_timer.stop()

    def force_gc(self) -> None:
        self._run_gc(verbose=True)

    def _run_gc(self, verbose: bool = False) -> None:
        try:
            ram_pct = self._get_ram_pct()
            if ram_pct > 70:
                trim_undo_stack(self.app, 10)
            else:
                trim_undo_stack(self.app, MAX_UNDO_STEPS)

            cleanup_stale_actors(self.app)

            freed = gc.collect(generation=2)
            self._last_gc_freed = freed

            if verbose or freed > 0:
                ram_mb = 0
                if self._process is not None:
                    ram_mb = self._process.memory_info().rss // 1024**2
                actors = count_all_actors(self.app)
                observers = ObserverRegistry.count()
                undo_depth = len(getattr(self.app, "undo_stack", []))
                print(
                    f"[MEM] GC: freed {freed} objects | RAM: {ram_mb} MB | "
                    f"Actors: {actors} | Undo: {undo_depth} | Observers: {observers}"
                )
        except Exception as exc:
            print(f"[MEM] MemoryLeakGuard GC error: {exc}")

    def _get_ram_pct(self) -> float:
        if psutil is None or self._process is None:
            return 0.0
        try:
            proc_mb = self._process.memory_info().rss // 1024**2
            total_mb = psutil.virtual_memory().total // 1024**2
            return (proc_mb / total_mb) * 100
        except Exception:
            return 0.0

    def _check_ram(self) -> None:
        if psutil is None or self._process is None:
            return
        try:
            pct = self._get_ram_pct()
            if pct < RAM_WARN_PERCENT:
                return
            proc_mb = self._process.memory_info().rss // 1024**2
            total_mb = psutil.virtual_memory().total // 1024**2
            print(f"[MEM] HIGH RAM: {proc_mb} MB / {total_mb} MB ({pct:.1f}%)")
            if hasattr(self.app, "statusBar"):
                self.app.statusBar().showMessage(
                    f"High memory: {proc_mb} MB - consider clearing project", 8000
                )
        except Exception:
            pass

    def get_stats(self) -> dict:
        try:
            if self._process is not None and psutil is not None:
                proc_mb = self._process.memory_info().rss // 1024**2
                total_mb = psutil.virtual_memory().total // 1024**2
                ram_pct = round((proc_mb / total_mb) * 100, 1)
            else:
                proc_mb = 0
                total_mb = 0
                ram_pct = 0.0

            return {
                "ram_mb": proc_mb,
                "ram_total_mb": total_mb,
                "ram_pct": ram_pct,
                "undo_depth": len(getattr(self.app, "undo_stack", [])),
                "redo_depth": len(getattr(self.app, "redo_stack", [])),
                "live_observers": ObserverRegistry.count(),
                "total_actors": count_all_actors(self.app),
                "last_gc_freed": self._last_gc_freed,
            }
        except Exception:
            return {}
