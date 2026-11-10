"""Стартиране без .exe (с Python от Microsoft Store или python.org) - без черен прозорец."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main import main  # noqa: E402

sys.exit(main())
