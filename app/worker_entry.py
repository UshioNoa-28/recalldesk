"""后台 worker 进程的统一入口：装配 DI 容器、处理退出信号、跑 service.run。

四个 worker（document/eval × publisher/consumer）的进程样板完全一样，
只差「从容器里解析哪个 service、根 logger 叫什么」。
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Protocol, TypeVar

from app.container import create_container


class Stoppable(Protocol):
    async def run(self, stop_event: asyncio.Event) -> None: ...


T = TypeVar("T", bound=Stoppable)


def run_worker(service_type: type[T], *, logger_name: str) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    logger = logging.getLogger(logger_name)

    async def main() -> None:
        container = create_container()
        service = await container.get(service_type)
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def handle_signal() -> None:
            logger.info("收到退出信号，通知 %s 停止", service_type.__name__)
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, handle_signal)
            except NotImplementedError:
                pass

        try:
            await service.run(stop_event)
        finally:
            await container.close()

    asyncio.run(main())


__all__ = ["run_worker"]
