"""
Optimization Configuration - Feature Flags

Controls which optimizations are active. 
Set ENABLE_OPTIMIZED_REFRESH = False to use original code.
"""

# ═══════════════════════════════════════════════════════════════════════
# MASTER SWITCH - Set to False to disable ALL optimizations
# ═══════════════════════════════════════════════════════════════════════
ENABLE_OPTIMIZED_REFRESH = True

# ═══════════════════════════════════════════════════════════════════════
# INDIVIDUAL FEATURE FLAGS
# ═══════════════════════════════════════════════════════════════════════

# Skip weight sync if weights haven't changed
ENABLE_DELTA_WEIGHT_SYNC = True

# Only refresh views that contain changed points
ENABLE_DIRTY_VIEW_TRACKING = True

# Update actors in-place instead of recreating
ENABLE_INPLACE_ACTOR_UPDATE = True

# Single render pass instead of multiple
ENABLE_BATCHED_RENDERING = True

# Use stable actor names (no weight suffix)
ENABLE_STABLE_ACTOR_NAMES = True

# ═══════════════════════════════════════════════════════════════════════
# DEBUGGING
# ═══════════════════════════════════════════════════════════════════════

# Print timing information
ENABLE_PERFORMANCE_LOGGING = True

# Print detailed state changes
ENABLE_DEBUG_LOGGING = False


def is_optimization_enabled() -> bool:
    """Check if optimization is enabled."""
    return ENABLE_OPTIMIZED_REFRESH


def get_active_optimizations() -> dict:
    """Get dictionary of active optimizations."""
    return {
        'delta_weight_sync': ENABLE_DELTA_WEIGHT_SYNC,
        'dirty_view_tracking': ENABLE_DIRTY_VIEW_TRACKING,
        'inplace_actor_update': ENABLE_INPLACE_ACTOR_UPDATE,
        'batched_rendering': ENABLE_BATCHED_RENDERING,
        'stable_actor_names': ENABLE_STABLE_ACTOR_NAMES,
    }