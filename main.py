from fastapi import FastAPI, HTTPException, status, Request, APIRouter, Response
import uvicorn
import httpx
import uuid
import logging
import time

from starlette.responses import JSONResponse

logging.basicConfig(level=logging.INFO, filename='app.log', format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

app = FastAPI(title="Custom Forward Proxy",
              description="Custom Forward Proxy",
              version="1.0.0")

router = APIRouter()

@router.api_route("/proxy", methods=["GET", "POST", "OPTIONS", "HEAD", "PUT", "DELETE", "PATCH"])
async def handle_all_requests(request: Request):
    try:
        start = time.perf_counter()
        target_url = request.query_params.get("url")
        headers = dict(request.headers)
        headers.update({"x-request-id": str(uuid.uuid4())})
        method = request.method

        body = await request.body()

        logging.info(f"target url :{target_url} | headers: {headers} | method: {method} | body:{body}")

        with httpx.Client() as client:
            response = client.request(method=method, url=target_url, content=body, headers=headers, timeout=10)

        received_headers = dict(response.headers)


        time_elapsed = time.perf_counter() - start
        received_headers.update({'x-duration': f"{time_elapsed*1000:.2f} ms"})

        logging.info(f"response :{response.content} | headers: {received_headers}")

        return Response(status_code=response.status_code, content=response.content, headers=received_headers)


    except Exception as e:
        logging.error(e.args)
        raise e


app.include_router(router)

if __name__ == '__main__':
    uvicorn.run("main:app", host="0.0.0.0", port=11000, reload=True)