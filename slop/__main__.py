import os
import sys

try:
    from .cli import main
except ImportError as e:  # a broken checkout: say what to run, not a traceback
    tk = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.stderr.write(f"slop: cannot start ({e}). Check: bash {tk}/bin/setup.sh --check, then repair: bash "
                     f"{tk}/bin/setup.sh\n")
    sys.exit(2)

sys.exit(main())
