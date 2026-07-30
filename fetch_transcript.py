#!/usr/bin/env python3
"""Compatibility wrapper — delegates to src/fetch_transcript.py."""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.fetch_transcript import main

if __name__ == "__main__":
    main()