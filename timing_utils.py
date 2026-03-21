"""
Simple timing utility for performance measurement.
"""
import time


class SectionTimer:
    """Simple timer for cross-section operations."""
    
    _instance = None
    
    def __init__(self):
        self.timers = {}
        self.history = []
    
    @classmethod
    def get(cls):
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = SectionTimer()
        return cls._instance
    
    def start(self, name="cross_section"):
        """Start timing."""
        self.timers[name] = time.perf_counter()
    
    def stop(self, name="cross_section", points=None):
        """Stop timing and print result."""
        if name not in self.timers:
            print(f"⚠️ Timer '{name}' was not started")
            return 0
        
        elapsed = time.perf_counter() - self.timers[name]
        
        # Store in history
        self.history.append({
            "name": name,
            "time_sec": elapsed,
            "points": points
        })
        
        # Print result
        print(f"\n{'='*60}")
        print(f"⏱️ {name.upper().replace('_', ' ')}")
        print(f"   Time: {elapsed:.3f} seconds ({elapsed*1000:.1f} ms)")
        if points:
            print(f"   Points: {points:,}")
            rate = points / elapsed if elapsed > 0 else 0
            print(f"   Rate: {rate:,.0f} points/second")
        print(f"{'='*60}\n")
        
        del self.timers[name]
        return elapsed
    
    def print_history(self):
        """Print all recorded times."""
        if not self.history:
            print("No timing history recorded.")
            return
        
        print(f"\n{'='*60}")
        print("📊 TIMING HISTORY")
        print(f"{'='*60}")
        
        for i, record in enumerate(self.history, 1):
            print(f"{i}. {record['name']}: {record['time_sec']:.3f}s", end="")
            if record['points']:
                print(f" ({record['points']:,} points)")
            else:
                print()
        
        # Calculate average
        times = [r['time_sec'] for r in self.history]
        print(f"\n   Average: {sum(times)/len(times):.3f}s")
        print(f"   Min: {min(times):.3f}s")
        print(f"   Max: {max(times):.3f}s")
        print(f"{'='*60}\n")
    
    def clear_history(self):
        """Clear timing history."""
        self.history = []
        print("✅ Timing history cleared")


# Global instance for easy access
timer = SectionTimer.get()


class Timer:
    """
    Compatibility wrapper so existing code can call:
        with Timer("name"):
            ...
    """
    def __init__(self, name="operation"):
        self.name = name

    def __enter__(self):
        SectionTimer.get().start(self.name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        SectionTimer.get().stop(self.name)
