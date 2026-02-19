"""
A2A Server Entry Point
======================
Usage:
    python -m a2a_server.run [--config PATH] [--host HOST] [--port PORT]

If no config file is specified, loads from /a0/usr/organizations/a2a_config.json.
"""

import argparse
import logging
import sys

from aiohttp import web

from .config import load_config
from .server import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("a2a_server")


def main():
    parser = argparse.ArgumentParser(description="A2A Compatibility Layer for Organization Kernel")
    parser.add_argument("--config", type=str, default=None, help="Path to a2a_config.json")
    parser.add_argument("--host", type=str, default=None, help="Bind host (overrides config)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (overrides config)")
    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # CLI overrides
    host = args.host or config.get("host", "0.0.0.0")
    port = args.port or config.get("port", 8200)
    config["host"] = host
    config["port"] = port

    logger.info(f"Starting A2A server on {host}:{port}")
    logger.info(f"Org directory: {config.get('org_dir')}")
    logger.info(f"Agent-Zero: {config.get('agent_connection', {}).get('base_url')}")

    app = create_app(config)

    try:
        web.run_app(app, host=host, port=port, print=lambda msg: logger.info(msg))
    except KeyboardInterrupt:
        logger.info("Shutting down A2A server")
        sys.exit(0)


if __name__ == "__main__":
    main()
