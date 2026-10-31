from pathlib import Path
import os
import sys
os.environ.setdefault('MAIBOT_HOST_VERSION', '1.3.12')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maiidentity.shared.core import Clock


class FakeClock(Clock):
    value = 1000.0
    def now(self): return self.value
    def monotonic(self): return self.value
