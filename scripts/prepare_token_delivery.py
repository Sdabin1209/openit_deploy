#!/usr/bin/env python3
"""Validate the token transfer request and bind its consuming image identity."""
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from openit_deploy.wiring.token_delivery import main
if __name__ == '__main__':
    sys.exit(main())
