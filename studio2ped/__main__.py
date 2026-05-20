"""Allow running as `python -m studio2ped`."""
import sys
from .cli import main
sys.exit(main())
