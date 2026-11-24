"""
État du stockage (espace disque), pour éviter de saturer la carte SD
sans s'en rendre compte — affiché dans Réglages.
"""

import shutil

from app.config import BASE_DIR

WARNING_THRESHOLD_PERCENT = 85


def get_storage_status() -> dict:
    try:
        total, used, free = shutil.disk_usage(BASE_DIR)
    except Exception:
        return {"available": False}

    percent_used = round(used / total * 100, 1) if total else 0.0
    return {
        "available": True,
        "total_gb": round(total / 1_000_000_000, 1),
        "used_gb": round(used / 1_000_000_000, 1),
        "free_gb": round(free / 1_000_000_000, 1),
        "percent_used": percent_used,
        "warning": percent_used >= WARNING_THRESHOLD_PERCENT,
    }
