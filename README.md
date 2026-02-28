# ProxyRequests

`ProxyRequests` is a lightweight Python helper that fetches public proxies, validates them, and uses them to send HTTP `GET` requests through rotating proxy IPs.

## Features

- Scrapes proxies from `https://free-proxy-list.net`
- Validates proxies against `https://api64.ipify.org?format=json`
- Maintains a background proxy pool in a daemon thread
- Rotates browser impersonation for requests via `curl-cffi`
- Retries with a different proxy when a proxy connection fails

## Requirements

- Python 3.10+
- Packages in `requirements.txt`:
  - `curl-cffi`
  - `lxml`
  - `pandas`

## Install

```bash
pip install -r requirements.txt
```

## Usage

```python
from proxy_requests import ProxyRequests, ProxyGetError, ProxyInitializationError

try:
    client = ProxyRequests(max_proxy_pool_size=50)
    response = client.get("https://httpbin.org/ip", timeout=10)
    print(response.status_code)
    print(response.text)
except ProxyInitializationError as e:
    print(f"Initialization failed: {e}")
except ProxyGetError as e:
    print(f"Request failed: {e}")
```

## API

### `ProxyRequests(max_proxy_pool_size: int)`

Creates a proxy client and starts a background refresher thread to refill candidate proxies.

### `get(url: str, params: dict | None = None, **kwargs)`

Sends a `GET` request through a proxy from the pool.

- Reuses successful proxies by returning them to the queue.
- Removes failed proxies when connection/proxy errors occur.
- Raises `ProxyGetError` if no proxy is available within timeout or if a request fails unexpectedly.

### Exceptions

- `ProxyInitializationError`: local public IP could not be resolved during initialization.
- `ProxyClosedError`: proxy pool has been closed.
- `ProxyGetError`: no proxy available in time or request failure while proxying.

## Notes

- Only `GET` is implemented.
- Proxies are sourced from a public list and may be unstable.
- The refresher runs continuously while the instance is alive.
