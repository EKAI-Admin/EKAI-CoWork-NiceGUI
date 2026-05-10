"""Centralised design tokens — import everywhere for visual consistency."""

# ---------- Semantic status colours ----------
# Each entry: (tailwind-text-class, quasar-badge-color, icon-name, label)
STATUS = {
    "completed": {"color": "emerald",  "tw": "text-emerald-600 dark:text-emerald-400", "icon": "check_circle",    "label": "Completed", "badge": "green"},
    "failed":    {"color": "rose",     "tw": "text-rose-600 dark:text-rose-400",       "icon": "error",           "label": "Failed",    "badge": "red"},
    "running":   {"color": "blue",     "tw": "text-blue-600 dark:text-blue-400",       "icon": "sync",            "label": "Running",   "badge": "blue"},
    "pending":   {"color": "amber",    "tw": "text-amber-600 dark:text-amber-400",     "icon": "hourglass_empty", "label": "Pending",   "badge": "orange"},
    "cancelling":{"color": "amber",    "tw": "text-amber-600 dark:text-amber-400",     "icon": "cancel",          "label": "Cancelling","badge": "orange"},
}

# Convenience accessor
def status_tw(s: str) -> str:
    """Return Tailwind text class for a run status."""
    return STATUS.get(s, STATUS["pending"])["tw"]

def status_icon(s: str) -> str:
    return STATUS.get(s, STATUS["pending"])["icon"]

def status_label(s: str) -> str:
    return STATUS.get(s, STATUS["pending"])["label"]

def status_badge_color(s: str) -> str:
    return STATUS.get(s, STATUS["pending"])["badge"]


# CoWorker status (active/inactive/paused)
CW_STATUS_COLORS = {
    "active":   "green",
    "inactive": "red",
    "paused":   "orange",
}


# ---------- Avatar gradients ----------
# CSS gradient strings, cycled by index
AVATAR_GRADIENTS = [
    "linear-gradient(135deg, #3b82f6, #6366f1)",   # blue → indigo
    "linear-gradient(135deg, #14b8a6, #0ea5e9)",   # teal → sky
    "linear-gradient(135deg, #8b5cf6, #ec4899)",   # purple → pink
    "linear-gradient(135deg, #f97316, #ef4444)",   # orange → red
    "linear-gradient(135deg, #ec4899, #8b5cf6)",   # pink → purple
    "linear-gradient(135deg, #06b6d4, #3b82f6)",   # cyan → blue
    "linear-gradient(135deg, #6366f1, #8b5cf6)",   # indigo → purple
    "linear-gradient(135deg, #22c55e, #14b8a6)",   # green → teal
]

def avatar_gradient(index: int) -> str:
    """Return a CSS gradient for the i-th avatar."""
    return AVATAR_GRADIENTS[index % len(AVATAR_GRADIENTS)]


# ---------- Skeleton helpers ----------
def skeleton_classes(extra: str = "") -> str:
    """Standard skeleton shimmer classes."""
    return f"animate-pulse bg-gray-200 dark:bg-gray-700 rounded {extra}"
