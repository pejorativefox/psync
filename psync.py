#!/usr/bin/env python3

import argparse
import logging
import sys

from server import run_server
from sync import sync
from database import close_db
from watch import watch
from config import Config

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Psync: A simple file synchronization tool.")
    parser.add_argument("--sync", action="store_true", help="Perform a one-time synchronization")
    parser.add_argument("--watch", action="store_true", help="Watch the directories for changes")
    parser.add_argument("--server", action="store_true", help="Start the FastAPI server")
    args = parser.parse_args()
    
    config = Config()

    if args.server:
        logger.info("Starting API server...")
        run_server()
        sys.exit(0)

    if config.is_new and (args.sync or args.watch):
        logger.error(f"Configuration file not found. A default has been created at: {config.settings_path}")
        logger.error("Please edit this file to set your 'base_path' before running the client (sync, watch, or gui).")
        sys.exit(1)

    if args.watch:
        logger.info("Starting watch process...")
        watch(config)
    elif args.sync:
        logger.info("Starting One time sync...")
        sync(config)
    else: # Default to GUI if no other arguments are provided, or if --gui is explicitly used
        logger.info("Starting GUI...")
        from gui import main as run_gui
        run_gui(config)