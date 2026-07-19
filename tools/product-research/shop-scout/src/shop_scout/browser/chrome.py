from __future__ import annotations

import asyncio
import platform
import shutil
from pathlib import Path

import httpx

from shop_scout.config import Settings
from shop_scout.exceptions import ShopScoutError


class ChromeProcessManager:
    def __init__(self, settings: Settings) -> None:
        if settings.chrome_remote_debugging_host != "127.0.0.1":
            raise ValueError("CDP must bind only to 127.0.0.1")
        self.settings = settings
        self.process: asyncio.subprocess.Process | None = None

    def discover(self) -> Path | None:
        if self.settings.chrome_executable:
            path = self.settings.chrome_executable.expanduser()
            return path if path.is_file() else None
        names = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]
        for name in names:
            found = shutil.which(name)
            if found:
                return Path(found)
        candidates: list[Path] = []
        system = platform.system()
        if system == "Darwin":
            candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
        elif system == "Windows":
            candidates = [
                Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
                Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
            ]
        return next((path for path in candidates if path.is_file()), None)

    async def is_cdp_ready(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=1) as client:
                response = await client.get(f"{self.settings.cdp_url}/json/version")
                return response.is_success
        except httpx.HTTPError:
            return False

    async def start(self, initial_url: str | None = None) -> None:
        if await self.is_cdp_ready():
            return
        executable = self.discover()
        if executable is None:
            raise ShopScoutError("Chrome/Chromium not found; set CHROME_EXECUTABLE")
        profile = self.settings.chrome_user_data_dir.resolve()
        profile.mkdir(parents=True, exist_ok=True)
        args = [
            str(executable),
            f"--remote-debugging-address={self.settings.chrome_remote_debugging_host}",
            f"--remote-debugging-port={self.settings.chrome_remote_debugging_port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if self.settings.chrome_headless:
            args.append("--headless=new")
        if initial_url:
            args.append(initial_url)
        self.process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        deadline = asyncio.get_running_loop().time() + self.settings.chrome_start_timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            if await self.is_cdp_ready():
                return
            if self.process.returncode is not None:
                break
            await asyncio.sleep(0.25)
        await self.stop()
        raise ShopScoutError("Chrome started but its loopback CDP endpoint did not become ready")

    async def stop(self) -> None:
        if self.process is None or self.process.returncode is not None:
            return
        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=5)
        except TimeoutError:
            self.process.kill()
            await self.process.wait()
