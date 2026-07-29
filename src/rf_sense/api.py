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
from .spatial import Environment, MeshObservation, SpatialEngine
from .udp import create_udp_receiver

settings = Settings.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = SensorEngine(
        calibration_frames=settings.calibration_frames,
        stale_after_seconds=settings.stale_after_seconds,
    )
    app.state.engine = engine
    environment = Environment.load(settings.environment_file)
    spatial = SpatialEngine(
        environment,
        track_ttl_seconds=float(settings.stale_after_seconds),
    )
    app.state.spatial = spatial
    app.state.started_at = time.monotonic()
    udp_transport = await create_udp_receiver(
        engine=engine,
        host=settings.udp_host,
        port=settings.udp_port,
        allowed_senders=settings.allowed_senders,
        simulator_active=settings.simulator,
    )
    simulator_task: asyncio.Task[None] | None = None
    integration_task: asyncio.Task[None] | None = None
    integrations: list[object] = []
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
    if settings.homekit_enabled:
        if not settings.homekit_pin:
            raise ValueError(
                "RF_HOMEKIT_PIN é obrigatório quando RF_HOMEKIT_ENABLED=true"
            )
        from .integrations.homekit import HomeKitBridge

        homekit = HomeKitBridge(
            lambda: spatial.snapshot(engine),
            list(environment.raw["rooms"]),
            port=settings.homekit_port,
            pin=settings.homekit_pin,
            persist_file=settings.homekit_persist_file,
        )
        homekit.start()
        integrations.append(homekit)
    if settings.home_assistant_enabled:
        if not settings.mqtt_host:
            raise ValueError(
                "RF_MQTT_HOST é obrigatório quando "
                "RF_HOME_ASSISTANT_ENABLED=true"
            )
        from .integrations.mqtt_publishers import HomeAssistantPublisher

        home_assistant = HomeAssistantPublisher(
            host=settings.mqtt_host,
            port=settings.mqtt_port,
            username=settings.mqtt_username,
            password=settings.mqtt_password,
            tls=settings.mqtt_tls,
            discovery_prefix=settings.mqtt_discovery_prefix,
            rooms=list(environment.raw["rooms"]),
        )
        home_assistant.start()
        integrations.append(home_assistant)
    if settings.alexa_iot_enabled:
        required = (
            settings.aws_iot_endpoint,
            settings.aws_iot_cert,
            settings.aws_iot_key,
            settings.aws_iot_ca,
        )
        if not all(required):
            raise ValueError(
                "RF_AWS_IOT_ENDPOINT/CERT/KEY/CA são obrigatórios quando "
                "RF_ALEXA_IOT_ENABLED=true"
            )
        from .integrations.mqtt_publishers import AwsIotShadowPublisher

        alexa = AwsIotShadowPublisher(
            endpoint=settings.aws_iot_endpoint or "",
            thing_name=settings.aws_iot_thing_name,
            cert=settings.aws_iot_cert or "",
            key=settings.aws_iot_key or "",
            ca=settings.aws_iot_ca or "",
        )
        alexa.start()
        integrations.append(alexa)
    if integrations:
        integration_task = asyncio.create_task(
            _publish_integrations(spatial, engine, integrations),
            name="rf-sense-integrations",
        )
    try:
        yield
    finally:
        udp_transport.close()
        if simulator_task:
            simulator_task.cancel()
            await asyncio.gather(simulator_task, return_exceptions=True)
        if integration_task:
            integration_task.cancel()
            await asyncio.gather(integration_task, return_exceptions=True)
        for integration in reversed(integrations):
            integration.stop()


async def _publish_integrations(
    spatial: SpatialEngine,
    engine: SensorEngine,
    integrations: list[object],
) -> None:
    while True:
        snapshot = spatial.snapshot(engine)
        for integration in integrations:
            publish = getattr(integration, "publish", None)
            if publish:
                publish(snapshot)
        await asyncio.sleep(2)


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


def get_spatial(request: Request) -> SpatialEngine:
    return request.app.state.spatial


def latest_payload(request: Request) -> dict[str, object]:
    engine: SensorEngine = request.app.state.engine
    spatial: SpatialEngine = request.app.state.spatial
    return {**engine.latest(), "spatial": spatial.snapshot(engine)}


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


class SpatialObservationRequest(BaseModel):
    track_key: str = Field(min_length=1, max_length=64)
    node_id: int = Field(ge=0, le=255)
    distance_m: float = Field(gt=0, le=100)
    confidence: float = Field(ge=0, le=1)
    breathing_bpm: float | None = Field(default=None, ge=4, le=50)
    breathing_confidence: float = Field(default=0, ge=0, le=1)
    heart_bpm: float | None = Field(default=None, ge=25, le=240)
    heart_confidence: float = Field(default=0, ge=0, le=1)


class SpatialObservationsRequest(BaseModel):
    observations: list[SpatialObservationRequest] = Field(
        min_length=1, max_length=128
    )


@app.get("/health")
async def health(request: Request) -> dict[str, object]:
    engine: SensorEngine = request.app.state.engine
    return {
        "status": "ok",
        "source": "simulator" if settings.simulator else "esp32",
        "version": __version__,
        "uptime_s": round(time.monotonic() - request.app.state.started_at, 1),
        "nodes": len(engine.nodes),
        "spatial_tracks": len(request.app.state.spatial.tracks),
    }


@app.get("/api/v1/sensing/latest", dependencies=[Depends(require_token)])
async def sensing_latest(
    request: Request,
) -> dict[str, object]:
    return latest_payload(request)


@app.get("/api/v1/spatial/map", dependencies=[Depends(require_token)])
async def spatial_map(
    spatial: SpatialEngine = Depends(get_spatial),
    engine: SensorEngine = Depends(get_engine),
) -> dict[str, object]:
    return spatial.snapshot(engine)


@app.post(
    "/api/v1/spatial/observations",
    dependencies=[Depends(require_token)],
)
async def spatial_observations(
    body: SpatialObservationsRequest,
    spatial: SpatialEngine = Depends(get_spatial),
) -> dict[str, object]:
    accepted = spatial.observe(
        MeshObservation(**observation.model_dump())
        for observation in body.observations
    )
    return {
        "accepted_tracks": accepted,
        "rejected_tracks": (
            len({item.track_key for item in body.observations}) - accepted
        ),
        "minimum_distinct_nodes": 3,
    }


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
    spatial: SpatialEngine = websocket.app.state.spatial
    last_version = (-1, -1)
    try:
        while True:
            version = (engine.version, spatial.version)
            if version != last_version:
                last_version = version
                await websocket.send_json(
                    {**engine.latest(), "spatial": spatial.snapshot(engine)}
                )
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
