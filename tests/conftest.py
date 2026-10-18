"""Shared test setup."""
import os

# the update reminder never reaches the network from the tests (tests/test_update.py turns it on for its own origin)
os.environ.setdefault("SLOP_UPDATE_CHECK", "0")
# the home-GPU link is parked in the shipped bot (SLOP_GPU_LINK unset); its tests keep running with it switched on.
# (SLOP_GPU itself is the analysis mode - auto, off or require - and stays unset here.)
os.environ.setdefault("SLOP_GPU_LINK", "1")
# model ids resolve to the newest of their family from OpenRouter's live list; the tests pin them (test_latest_models.py
# turns resolution on with a fixture list)
os.environ.setdefault("SLOP_PIN_MODELS", "1")
# the relay supervisor's OpenRouter key watch stays off the network (tests/test_setup_036.py drives it directly)
os.environ.setdefault("SLOP_KEY_WATCH", "0")
