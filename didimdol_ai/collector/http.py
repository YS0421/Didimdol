"""예의 바른 HTTP 수집: robots.txt 준수, 호스트별 요청 간격, 크기 제한, 일반 User-Agent."""

from __future__ import annotations

import time
import urllib.robotparser
from typing import Optional
from urllib.parse import urlsplit

import requests

USER_AGENT = "Mozilla/5.0 (compatible; job-board-reader/0.1)"
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


class RobotsDisallowed(Exception):
    pass


class Fetcher:
    def __init__(self, min_interval: float = 2.0, timeout: float = 30.0, retries: int = 2):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self.robots_notes: dict[str, str] = {}  # 호스트별 robots.txt 상태 (실행 요약용)

    # ------------------------------------------------------------ robots
    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                self._throttle(parts.netloc)
                r = self.session.get(origin + "/robots.txt", timeout=self.timeout)
                if r.status_code in (401, 403):
                    rp.disallow_all = True
                    self.robots_notes[origin] = f"HTTP {r.status_code} → 전체 금지로 처리"
                elif r.status_code >= 400 or "text/html" in r.headers.get("Content-Type", ""):
                    # RFC 9309: robots.txt를 받을 수 없으면(4xx) 제한 없음으로 본다
                    rp.allow_all = True
                    self.robots_notes[origin] = f"robots.txt 없음/차단(HTTP {r.status_code}) → 표준대로 허용"
                else:
                    rp.parse(r.text.splitlines())
                    self.robots_notes[origin] = "robots.txt 적용"
            except requests.RequestException as e:
                rp.disallow_all = True
                self.robots_notes[origin] = f"robots.txt 요청 실패({e.__class__.__name__}) → 이번 실행은 금지로 처리"
            self._robots[origin] = rp
        return self._robots[origin]

    def allowed(self, url: str) -> bool:
        return self._robots_for(url).can_fetch(USER_AGENT, url)

    # ------------------------------------------------------------ 요청
    def _throttle(self, host: str) -> None:
        wait = self.min_interval - (time.monotonic() - self._last.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()

    def _get(self, url: str, stream: bool = False) -> requests.Response:
        if not self.allowed(url):
            raise RobotsDisallowed(url)
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            self._throttle(urlsplit(url).netloc)
            try:
                r = self.session.get(url, timeout=self.timeout, stream=stream)
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                last_exc = e
                time.sleep(1.5 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    def get_text(self, url: str) -> str:
        r = self._get(url)
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding
        return r.text

    def download(self, url: str, dest_path: str) -> str:
        """파일을 받아 저장하고, 서버가 알려준 파일명(Content-Disposition)을 돌려준다."""
        with self._get(url, stream=True) as r:
            size = 0
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(64 * 1024):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise ValueError("too_large")
                    f.write(chunk)
            return r.headers.get("Content-Disposition", "")
