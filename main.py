from fastapi import FastAPI, HTTPException, status, Request, APIRouter, Response
import uvicorn
import httpx
import uuid
import logging
import time
from urllib.parse import urlparse
import socket
import ipaddress

from starlette.responses import JSONResponse

logging.basicConfig(level=logging.INFO, filename='app.log', format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


ALLOWED_DOMAINS = {"localhost"}
ALLOWED_INTERNALS = {"localhost"}
API_KEYS = {'DEV':'abc123', 'QA':'xyz123'}
API_RATE = {}
MAX_REQUEST_PER_MINUTE = 100
BLOCKED_HEADERS = {"host", "connection", "proxy-connection", "transfer-encoding"}
SAFE_HEADERS = {"content-type","cache_control"}

def check_limit(api_key):
    try:
        minute = int(time.time()/60)
        API_RATE[f"{api_key}_{minute:02d}"] = API_RATE.get(f"{api_key}_{minute:02d}", 0) + 1
        print(API_RATE)
        return API_RATE[f"{api_key}_{minute:02d}"] <= MAX_REQUEST_PER_MINUTE
    except Exception as e:
        logging.error(e.args)

def is_private(hostname):
    try:
        ip = socket.gethostbyname(hostname)
        ip_object = ipaddress.ip_address(ip)
        return ip_object.is_private or ip_object.is_loopback or ip_object.is_link_local
    except Exception as e:
        logging.error(e.args)

app = FastAPI(title="Custom Forward Proxy",
              description="Custom Forward Proxy",
              version="1.0.0")

router = APIRouter()


@router.api_route(
    "/proxy",
    methods=["GET", "POST", "OPTIONS", "HEAD", "PUT", "DELETE", "PATCH"],
)
async def handle_all_requests(request: Request):
    start = time.perf_counter()

    # 1. Validate the target URL
    target_url = request.query_params.get("url")

    if not target_url:
        raise HTTPException(
            status_code=400,
            detail="Missing target URL",
        )

    parsed_url = urlparse(target_url)

    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid target URL",
        )

    hostname = parsed_url.hostname.lower().rstrip(".")

    # 2. Allow only explicitly permitted hosts
    if hostname not in ALLOWED_DOMAINS:
        raise HTTPException(
            status_code=403,
            detail="Target domain is not allowed",
        )

    # 3. Authenticate the caller
    api_key = request.headers.get("x-api-key")

    if api_key not in API_KEYS.values():
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
        )

    # 4. Apply rate limit
    if not check_limit(api_key):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
        )

    # 5. Filter incoming headers
    blocked_headers = BLOCKED_HEADERS | {
        "x-api-key",
        "content-length",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "upgrade",
    }

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in blocked_headers
    }

    # 6. Read the request body
    body = await request.body()

    logging.info(
        "Proxy request | method=%s | target=%s",
        request.method,
        target_url,
    )

    try:
        # 7. Forward the request asynchronously
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=False,
        ) as client:
            response = await client.request(
                method=request.method,
                url=target_url,
                content=body,
                headers=headers,
            )

        # 8. Filter downstream response headers
        safe_headers = {
            "content-type",
            "cache-control",
        }

        filtered_headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() in safe_headers
        }

        elapsed_ms = (time.perf_counter() - start) * 1000
        filtered_headers["x-duration"] = f"{elapsed_ms:.2f} ms"

        logging.info(
            "Proxy response | status=%s | duration_ms=%.2f",
            response.status_code,
            elapsed_ms,
        )

        # 9. Return the downstream response
        return Response(
            status_code=response.status_code,
            content=response.content,
            headers=filtered_headers,
        )

    except httpx.TimeoutException as exc:
        logging.warning(
            "Downstream timeout | target=%s | error=%s",
            target_url,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=504,
            detail="Downstream request timed out",
        ) from exc

    except httpx.RequestError as exc:
        logging.warning(
            "Downstream request failed | target=%s | error=%s",
            target_url,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="Downstream service unavailable",
        ) from exc


app.include_router(router)

if __name__ == '__main__':
    uvicorn.run("main:app", host="0.0.0.0", port=11000, reload=True)