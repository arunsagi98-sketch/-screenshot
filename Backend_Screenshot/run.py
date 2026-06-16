import asyncio
import os
import sys
import uvicorn

if __name__ == "__main__":
    # Proactor is required on older Python for Playwright subprocesses on Windows.
    # From Python 3.14 onward, overriding the asyncio policy is deprecated; use the default.
    if sys.platform == "win32" and sys.version_info < (3, 14):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

    # Render (and most PaaS) injects PORT env var and requires host 0.0.0.0.
    # Falls back to 127.0.0.1:8001 for local dev when PORT is not set.
    _host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    _port = int(os.environ.get("PORT", 8001))

    uvicorn.run(
        "main:app",
        host=_host,
        port=_port,
        reload=False,
    )
