#!/usr/bin/env python3
"""
Main entry point for RefChecker Web UI

This script starts the FastAPI backend server for the RefChecker Web UI.

Usage:
    python run_webui.py [--host HOST] [--port PORT]
    
Alternatively, if installed via pip:
    refchecker-webui [--host HOST] [--port PORT]
    
The frontend (if installed separately) should be started with:
    cd web-ui && npm run dev
"""

import sys
import os
import argparse

# Add the src directory to Python path so refchecker package can be found
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_SOURCE_ROOT = os.path.join(_PROJECT_ROOT, 'src')
if _SOURCE_ROOT in sys.path:
    sys.path.remove(_SOURCE_ROOT)
sys.path.insert(0, _SOURCE_ROOT)

# Load the shared core before Uvicorn imports backend.main.  This guarantees a
# source checkout cannot silently reuse a stale site-packages copy that was
# imported by launcher instrumentation or another startup hook.
from refchecker.utils import text_utils as _shared_text_utils

_SHARED_CORE_PATH = os.path.realpath(_shared_text_utils.__file__)
_EXPECTED_CORE_ROOT = os.path.realpath(os.path.join(_SOURCE_ROOT, 'refchecker'))
if os.path.commonpath((_SHARED_CORE_PATH, _EXPECTED_CORE_ROOT)) != _EXPECTED_CORE_ROOT:
    raise RuntimeError(
        "WebUI loaded refchecker from an unexpected location: "
        f"{_SHARED_CORE_PATH} (expected {_EXPECTED_CORE_ROOT})"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Start the RefChecker Web UI backend server"
    )
    parser.add_argument(
        "--host", 
        default="0.0.0.0", 
        help="Host to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=int(os.environ.get("PORT", "8000")), 
        help="Port to listen on (default: PORT env var or 8000)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development"
    )
    
    args = parser.parse_args()
    
    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn is not installed.")
        print("Install it with: pip install 'academic-refchecker[webui]'")
        sys.exit(1)
    
    print(f"Starting RefChecker Web UI backend on http://{args.host}:{args.port}")
    print(f"Shared RefChecker core: {_SHARED_CORE_PATH}")
    print("Make sure to start the frontend separately (cd web-ui && npm run dev)")
    print()
    
    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload
    )


if __name__ == "__main__":
    main()
