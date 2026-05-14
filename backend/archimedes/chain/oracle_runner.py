"""Oracle runner — periodic loop that fetches prices and pushes them on-chain.

Run as a standalone process:
    python -m archimedes.chain.oracle_runner

Env:
    ORACLE_INTERVAL_SECONDS  — how often to push prices (default: 60)
    ARC_OWNER_PRIVATE_KEY    — required for on-chain pushes
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from archimedes.chain.oracle_updater import OracleUpdater

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

INTERVAL = int(os.getenv("ORACLE_INTERVAL_SECONDS", "60"))


async def run() -> None:
    updater = OracleUpdater()
    logger.info(f"Oracle runner started — updating every {INTERVAL}s")

    while True:
        try:
            prices = await updater.fetch_prices()
            if prices:
                tx = await updater.push_prices_on_chain(prices)
                if tx:
                    logger.info(f"Price push complete — first tx: {tx}")
                else:
                    logger.info("Prices fetched (no on-chain push — owner key not configured)")
            else:
                logger.warning("No prices fetched this cycle")
        except Exception:
            logger.exception("Oracle cycle failed — will retry next interval")

        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
