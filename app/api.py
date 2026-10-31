import secrets
import asyncio
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Header
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.config import Settings


class ModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["OFF", "PAPER", "LIVE", "BOTH", "PAPER_ON", "PAPER_OFF", "LIVE_ON", "LIVE_OFF"]
    revision: int = Field(ge=0)


class PaperConfigRequest(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    revision: int = Field(ge=0)
    initial_cash: str = Field(max_length=24)
    per_order_budget: str = Field(max_length=24)
    max_positions: int = Field(ge=1,le=5)
    max_daily_loss: str = Field(max_length=24)
    max_exposure: str = Field(max_length=24)
    max_daily_symbols: int = Field(ge=1,le=5)


class LiveConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=0)
    allocated_usdc: str = Field(max_length=24)
    per_order_budget: str = Field(max_length=24)
    max_positions: int = Field(ge=1, le=5)
    max_daily_loss: str = Field(max_length=24)
    max_exposure: str = Field(max_length=24)
    max_daily_symbols: int = Field(ge=1, le=5)
    take_profit_pct: str = Field(default="0.0175", max_length=16)
    stop_loss_pct: str = Field(default="0.0080", max_length=16)


def create_app(settings=None):
    settings = settings or Settings.from_env()
    @asynccontextmanager
    async def lifespan(app):
        if settings.runtime_enabled:
            from app.runtime import Runtime
            runtime = Runtime(settings)
            app.state.runtime = runtime
            try:
                await runtime.start()
                yield
            finally:
                await runtime.stop()
        else:
            yield

    app = FastAPI(title="OBR Math", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.runtime = None
    static = Path(__file__).parent/"static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(static/"index.html")
    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None or not secrets.compare_digest(credentials.credentials.encode(), settings.api_token.encode()):
            raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/healthz")
    def health():
        return {"alive": True}

    @app.get("/api/v1/status", dependencies=[Depends(authenticate)])
    def status():
        if app.state.runtime:
            return app.state.runtime.status()
        return {"health": "DEGRADED", "mode": "WATCH_ONLY", "paper_mode": True,
                "live_trading_enabled": False, "version": "0.6.0",
                "performance": "NOT_TESTED", "market_connection": "NOT_STARTED",
                "blockers": ["UNIVERSE_NOT_VERIFIED", "VOLUME_NOT_VERIFIED", "FEES_NOT_VERIFIED"]}

    def runtime():
        if app.state.runtime is None:
            raise HTTPException(503, "Runtime not enabled")
        return app.state.runtime

    def control_authorization(x_obr_control_token: str = Header(default="")):
        if len(settings.control_token)<32 or settings.control_token==settings.api_token:
            raise HTTPException(503,"CONTROL_NOT_CONFIGURED")
        if not secrets.compare_digest(x_obr_control_token.encode(),settings.control_token.encode()):
            raise HTTPException(403,"CONTROL_TOKEN_REQUIRED")

    @app.get("/api/v1/trading-mode", dependencies=[Depends(authenticate)])
    def trading_mode():
        return runtime().mode_status()

    @app.post("/api/v1/trading-mode", dependencies=[Depends(authenticate),Depends(control_authorization)])
    async def set_trading_mode(request: ModeRequest):
        from app.trading_modes import ModeConflict
        try:
            return await runtime().change_mode(request.mode,request.revision)
        except ModeConflict as error:
            raise HTTPException(409,str(error)) from None
        except Exception:
            raise HTTPException(503,"MODE_CHANGE_FAILED_REFRESH_REQUIRED") from None

    @app.get("/api/v1/metrics", dependencies=[Depends(authenticate)])
    async def metrics():
        current = runtime()
        return {"latest": current.last_snapshot, "history": await asyncio.to_thread(current.store.recent, "metrics", 120)}

    @app.get("/api/v1/paper-config", dependencies=[Depends(authenticate)])
    def paper_config():return runtime().config_status()

    @app.post("/api/v1/paper-config", dependencies=[Depends(authenticate),Depends(control_authorization)])
    async def set_paper_config(request: PaperConfigRequest):
        from app.paper_config import PaperConfig
        try:
            config=PaperConfig(**request.model_dump(exclude={"revision"}))
            return await runtime().change_paper_config(config,request.revision)
        except ValueError as error:raise HTTPException(409,str(error)) from None
        except Exception:raise HTTPException(503,"CONFIG_SAVE_FAILED_REFRESH_REQUIRED") from None

    @app.get("/api/v1/live-config", dependencies=[Depends(authenticate)])
    def live_config():
        return runtime().live_config_status()

    @app.post("/api/v1/live-config", dependencies=[Depends(authenticate), Depends(control_authorization)])
    async def set_live_config(request: LiveConfigRequest):
        from app.paper_config import LiveConfig
        try:
            config = LiveConfig(**request.model_dump(exclude={"revision"}))
            return await runtime().change_live_config(config, request.revision)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        except Exception:
            raise HTTPException(503, "LIVE_CONFIG_SAVE_FAILED_REFRESH_REQUIRED") from None

    @app.get("/api/v1/demo", dependencies=[Depends(authenticate)])
    async def demo():
        from app.demo import demonstration
        return await asyncio.to_thread(demonstration)

    @app.get("/api/v1/signals", dependencies=[Depends(authenticate)])
    async def signals():
        return await asyncio.to_thread(runtime().store.recent, "signals")

    @app.get("/api/v1/outcomes", dependencies=[Depends(authenticate)])
    async def outcomes():
        return await asyncio.to_thread(runtime().store.recent, "outcomes")

    @app.get("/api/v1/alerts", dependencies=[Depends(authenticate)])
    async def alerts():
        return await asyncio.to_thread(runtime().store.recent, "alerts")

    @app.get("/api/v1/reports", dependencies=[Depends(authenticate)])
    async def reports():
        return await asyncio.to_thread(runtime().store.recent, "reports", 30)

    @app.get("/api/v1/reports/{day}", dependencies=[Depends(authenticate)], response_class=PlainTextResponse)
    async def report(day: date):
        result = await asyncio.to_thread(runtime().store.report, day.isoformat())
        if result is None:
            raise HTTPException(404, "Report not found")
        return result

    @app.get("/api/v1/universe", dependencies=[Depends(authenticate)])
    def universe():
        current = runtime()
        inst = current.instruments.summary(current.candidates, current.now_ms())
        return {"version": current.universe["version"], "symbols": sorted(current.candidates),
                "focus": current.focus, "rules": current.rules, "rules_verified": current.rules_verified,
                "metadata_status": inst["status"],
                "instrument_verification": inst}

    @app.get("/api/v1/positions", dependencies=[Depends(authenticate)])
    def positions():
        from app.paper_config import PaperConfig
        current = app.state.runtime
        if current:
            return {**current.paper.cached,"fee_status":"VERIFIED" if current.paper_verified["fees"] else "UNVERIFIED",
                    "entry_blockers":current.status()["blockers"],
                    "shared_signal":True,
                    "live":current.live.status_summary(current.trading_modes.live_enabled),
                    "live_config":current.live_config_status()}
        config = current.paper_config if current else (PaperConfig.load(settings.paper_config_file) if settings.paper_config_file else PaperConfig())
        return {"enabled": False, "reason": "AUTO_TRADING_NOT_CONNECTED", "positions": [],
                "configuration": config.public(), "fee_status": "UNVERIFIED"}

    @app.get("/api/v1/fees", dependencies=[Depends(authenticate)])
    async def fees():
        import time
        from app.fee_watch import view
        return await asyncio.to_thread(view, settings.data_dir/"fee-watch.json", time.time_ns()//1000000)

    return app
