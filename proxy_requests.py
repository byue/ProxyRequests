from __future__ import annotations

import random
import time
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Empty, Queue
from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError
from curl_cffi.requests.exceptions import ProxyError as CurlProxyError
from curl_cffi import requests as curl_requests
from threading import Event, Thread
from typing import Any, Dict, List, Optional, Set
from lxml.html import fromstring
from urllib.parse import urlparse

BROWSER = 'chrome136'
IP_CHECK_URL = 'https://api64.ipify.org?format=json'
PROXY_LIST_URL = 'https://free-proxy-list.net'
PROXY_VALIDATE_TIMEOUT = 1
PROXY_REFRESH_SLEEP_SECONDS = 2
PROXY_VALIDATE_WORKERS = 32
BROWSERS = [
    "chrome99",
    "chrome100",
    "chrome101",
    "chrome104",
    "chrome107",
    "chrome110",
    "chrome116",
    "chrome119",
    "chrome120",
    "chrome123",
    "chrome124",
    "chrome131",
    "chrome136",
    "chrome142",
    "chrome99_android",
    "chrome131_android",
    "edge99",
    "edge101",
    "safari15_3",
    "safari15_5",
]

def get_random_browser() -> str:
    return random.choice(BROWSERS)

class ProxyInitializationError(Exception):
    pass

class ProxyClosedError(Exception):
    pass

class ProxyGetError(Exception):
    pass

class ProxyRequests:
    def __init__(self, max_proxy_pool_size: int):
        self.stop_proxy_refresher = Event()
        self.proxies = Queue(maxsize=max_proxy_pool_size)
        self.local_public_ip = self._get_local_public_ip()
        if not self.local_public_ip:
            raise ProxyInitializationError(
                "Unable to resolve local public IP from IP_CHECK_URL"
            )
        self.failed_urls: Set[str] = set()
        self.proxy_refresher = Thread(target=self._refresh_proxies, daemon=True)
        self.proxy_refresher.start()

    def __del__(self):
        self.stop_proxy_refresher.set()

    def __len__(self):
        return self.proxies.qsize()

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        timeout = kwargs.get("timeout") or 10
        while True:
            if self.stop_proxy_refresher.is_set():
                raise ProxyClosedError("Proxy pool is closed")
            try:
                proxy_url = self.proxies.get(block=True, timeout=timeout)
            except Empty as exc:
                raise ProxyGetError(
                    f"No proxy available in pool within {timeout} seconds"
                ) from exc
            kwargs["proxy"] = proxy_url
            kwargs["impersonate"] = get_random_browser()
            try:
                response = curl_requests.get(url, params=params, **kwargs)
                try:
                    self.proxies.put_nowait(proxy_url)
                except Exception:
                    pass
                return response
            except CurlConnectionError:
                self.failed_urls.add(proxy_url)
                continue
            except CurlProxyError:
                self.failed_urls.add(proxy_url)
                continue
            except Exception as exc:
                self.failed_urls.add(proxy_url)
                raise ProxyGetError("Request failed while using proxy") from exc

    def _is_well_formed_proxy_url(self, proxy_url: str) -> bool:
        parsed = urlparse(proxy_url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if not parsed.hostname:
            return False
        if parsed.port is None or not (1 <= parsed.port <= 65535):
            return False
        try:
            ipaddress.ip_address(parsed.hostname)
            return True
        except ValueError:
            return False

    def _scrape_proxy_urls(self) -> List[str]:
        response = curl_requests.get(PROXY_LIST_URL, timeout=15)
        response.raise_for_status()
        parser = fromstring(response.text)
        proxy_urls: Set[str] = set()
        for row in parser.xpath("//tbody/tr"):
            host = row.xpath(".//td[1]/text()")
            port = row.xpath(".//td[2]/text()")
            if host and port:
                proxy_url = f"http://{host[0].strip()}:{port[0].strip()}"
                if self._is_well_formed_proxy_url(proxy_url):
                    proxy_urls.add(proxy_url)
        return list(proxy_urls)

    def _extract_ip_from_payload(self, payload: Dict[str, Any]) -> Optional[str]:
        ip_value = payload.get("ip")
        if not isinstance(ip_value, str):
            return None
        ip_value = ip_value.strip()
        try:
            ipaddress.ip_address(ip_value)
            return ip_value
        except ValueError:
            return None

    def _get_local_public_ip(self) -> Optional[str]:
        try:
            response = curl_requests.get(
                IP_CHECK_URL,
                timeout=PROXY_VALIDATE_TIMEOUT,
                impersonate=BROWSER,
            )
            if not response.ok:
                return None
            return self._extract_ip_from_payload(response.json())
        except Exception:
            return None

    def _proxy_works(self, proxy_url: str) -> bool:
        try:
            if not self.local_public_ip:
                return False
            response = curl_requests.get(
                IP_CHECK_URL,
                proxy=proxy_url,
                timeout=PROXY_VALIDATE_TIMEOUT,
                impersonate=BROWSER,
            )
            if not response.ok:
                return False
            proxy_ip = self._extract_ip_from_payload(response.json())
            if not proxy_ip:
                return False
            return proxy_ip != self.local_public_ip
        except Exception:
            return False

    def _refresh_proxies(self) -> None:
        while not self.stop_proxy_refresher.is_set():
            try:
                all_proxy_urls = self._scrape_proxy_urls()
                candidates = [u for u in all_proxy_urls if u not in self.failed_urls]
                if not candidates:
                    time.sleep(PROXY_REFRESH_SLEEP_SECONDS)
                    continue
                max_workers = min(PROXY_VALIDATE_WORKERS, len(candidates))
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_proxy = {
                        executor.submit(self._proxy_works, proxy_url): proxy_url
                        for proxy_url in candidates
                    }
                    for future in as_completed(future_to_proxy):
                        proxy_url = future_to_proxy[future]
                        try:
                            ok = future.result()
                        except Exception:
                            ok = False
                        if ok:
                            self.proxies.put(proxy_url, block=True)
                        else:
                            self.failed_urls.add(proxy_url)
            except Exception:
                time.sleep(PROXY_REFRESH_SLEEP_SECONDS)
