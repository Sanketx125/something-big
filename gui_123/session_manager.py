import gc
import time

class SessionManager:
    def __init__(self):
        self._last_cleanup = 0.0

    def maintenance(self):
        now = time.time()
        if now - self._last_cleanup > 120:   # ← changed from 60 to 120
            self._last_cleanup = now
            print("🧹 Session maintenance: GC running")  # optional
            gc.collect()

SESSION = SessionManager()

