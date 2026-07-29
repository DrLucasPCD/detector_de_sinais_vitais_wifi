from __future__ import annotations

import asyncio
import hmac
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect, WebSocketState

from . import __version__
from .config import Settings
from .processing import SensorEngine
from .simulator import run_simulator
from .udp import create_udp_receiver

settings = Settings.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = SensorEngine(
        calibration_frames=settings.calibration_frames,
        stale_after_seconds=settings.stale_after_seconds,
    )
    app.state.engine = engine
    app.state.started_at = time.monotonic()
    udp_transport = await create_udp_receiver(
        engine=engine,
        host=settings.udp_host,
        port=settings.udp_port,
        allowed_senders=settings.allowed_senders,
        simulator_active=settings.simulator,
    )
    simulator_task: asyncio.Task[None] | None = None
    if settings.simulator:
        simulator_task = asyncio.create_task(
            run_simulator(
                host="127.0.0.1",
                port=settings.udp_port,
                scenario=settings.simulator_scenario,
                seed=settings.simulator_seed,
            ),
            name="rf-sense-simulator",
        )
    try:
        yield
    finally:
        udp_transport.close()
        if simulator_task:
            simulator_task.cancel()
            await asyncio.gather(simulator_task, return_exceptions=True)


app = FastAPI(
    title="RF Sense",
    version=__version__,
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)

if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )


def get_engine(request: Request) -> SensorEngine:
    return request.app.state.engine


def require_token(authorization: str | None = Header(default=None)) -> None:
    if settings.api_token is None:
        return
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        token, settings.api_token
    ):
        raise HTTPException(status_code=401, detail="token inválido")


class CalibrationRequest(BaseModel):
    frames: int = Field(default=600, ge=100, le=100_000)


@app.get("/health")
async def health(request: Request) -> dict[str, object]:
    engine: SensorEngine = request.app.state.engine
    return {
        "status": "ok",
        "source": "simulator" if settings.simulator else "esp32",
        "version": __version__,
        "uptime_s": round(time.monotonic() - request.app.state.started_at, 1),
        "nodes": len(engine.nodes),
    }


@app.get("/api/v1/sensing/latest", dependencies=[Depends(require_token)])
async def sensing_latest(
    engine: SensorEngine = Depends(get_engine),
) -> dict[str, object]:
    return engine.latest()


@app.get("/api/v1/nodes", dependencies=[Depends(require_token)])
async def nodes(engine: SensorEngine = Depends(get_engine)) -> dict[str, object]:
    return {"nodes": engine.node_inventory()}


@app.get("/api/v1/vital-signs", dependencies=[Depends(require_token)])
async def vital_signs(
    engine: SensorEngine = Depends(get_engine),
) -> dict[str, object]:
    latest = engine.latest()
    return {
        "source": latest["source"],
        "vital_signs": latest["vital_signs"],
        "disclaimer": (
            "Estimativas experimentais; confidence é um SQI heurístico, "
            "não probabilidade clínica. Não usar para fins médicos."
        ),
    }


@app.get("/api/v1/config", dependencies=[Depends(require_token)])
async def config() -> dict[str, object]:
    return settings.public_dict()


@app.post("/api/v1/calibration/start", dependencies=[Depends(require_token)])
async def calibration_start(
    body: CalibrationRequest,
    engine: SensorEngine = Depends(get_engine),
) -> dict[str, object]:
    affected = engine.restart_calibration(body.frames)
    return {
        "status": "started",
        "target_frames": body.frames,
        "affected_nodes": affected,
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics(engine: SensorEngine = Depends(get_engine)) -> str:
    lines = [
        "# HELP rf_sense_frames_total Quadros CSI por resultado.",
        "# TYPE rf_sense_frames_total counter",
    ]
    for key, value in sorted(engine.counters.items()):
        lines.append(f'rf_sense_frames_total{{result="{key}"}} {value}')
    for node in engine.node_inventory():
        node_id = node["node_id"]
        lines.append(f'rf_sense_node_fps{{node_id="{node_id}"}} {node["fps"]}')
        lines.append(
            f'rf_sense_node_packet_loss_ratio{{node_id="{node_id}"}} '
            f'{node["packet_loss"]}'
        )
    return "\n".join(lines) + "\n"


@app.websocket("/ws/sensing")
async def sensing_socket(websocket: WebSocket) -> None:
    if settings.api_token is not None:
        supplied = websocket.query_params.get("token", "")
        if not hmac.compare_digest(supplied, settings.api_token):
            await websocket.close(code=4401)
            return
    await websocket.accept()
    engine: SensorEngine = websocket.app.state.engine
    last_version = -1
    try:
        while True:
            if engine.version != last_version:
                last_version = engine.version
                await websocket.send_json(engine.latest())
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        return
    except Exception:
        if websocket.application_state == WebSocketState.CONNECTED:
            await websocket.close(code=1011)


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="dashboard")
