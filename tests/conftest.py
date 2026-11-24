"""Réglages communs aux tests : une boîte jetable, sans son ni lecteur NFC.

Ces variables doivent être posées AVANT le premier import de app/ (les
chemins sont fixés à l'import de app/config.py)."""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

BASE = Path(tempfile.mkdtemp(prefix="contar-test-"))
os.environ["CONTAR_BASE_DIR"] = str(BASE)
os.environ["CONTAR_VLC_AOUT"] = "dummy"
os.environ["CONTAR_NFC"] = "simu"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
atexit.register(shutil.rmtree, BASE, True)
