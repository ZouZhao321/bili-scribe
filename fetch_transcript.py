#!/usr/bin/env python3
"""Compatibility wrapper — delegates to cli/main.py.

This file exists at the project root so that existing scripts and
workflows referencing `python3 fetch_transcript.py` continue to work
after the project was reorganized into core/cli/shell/web directories.
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.core.main import main

if __name__ == "__main__":
    main()