import sys
from pathlib import Path

# Keep `from fakes.fake_backend import FakeBackend` working when this dir is run alone.
_TESTS = str(Path(__file__).resolve().parents[1])
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
