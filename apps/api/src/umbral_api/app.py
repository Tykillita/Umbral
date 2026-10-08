"""Fábrica de la aplicación FastAPI y rutas /api/v1."""

from __future__ import annotations

import asyncio
import re
import secrets
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import API_PREFIX, __version__
from .auth import is_loopback
from .config import Settings
from .connections import (
    AuthorizationResponse,
    ConnectionsResponse,
    ConnectionStart,
    DisconnectResponse,
    ModelChoice,
    ModelsResponse,
    ProfileChoice,
)
from .errors import ApiError
from .models import (
    CaseView,
    DraftEditRequest,
    DraftRequest,
    DraftResponse,
    ErrorResponse,
    ExportResponse,
    HealthResponse,
    ImpactRequest,
    QueryRequest,
    QueryResponse,
    ReviewRequest,
    RulesRequest,
    RulesResponse,
    SnapshotInfoResponse,
    TopicDetail,
    TopicsResponse,
)
from .public_models import (
    PublicAgendaRequest,
    PublicDraftRequest,
    PublicDraftResponse,
    PublicQueryRequest,
    PublicTopicRequest,
    PublicValidationRequest,
    PublicValidationResponse,
    WorkspaceArchive,
    WorkspaceImportResponse,
)

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "No autenticado"},
    403: {"model": ErrorResponse, "description": "Prohibido (p. ej. adaptador solo localhost)"},
    404: {"model": ErrorResponse, "description": "No encontrado"},
    409: {"model": ErrorResponse, "description": "Conflicto de versión (control optimista)"},
    422: {"model": ErrorResponse, "description": "No procesable / transición inválida"},
    429: {"model": ErrorResponse, "description": "Límite por usuario excedido"},
}


def get_services(request: Request):  # noqa: ANN201
    services = getattr(request.app.state, "services", None)
    if services is None:  # modo solo-esquema (exportación de OpenAPI)
        raise ApiError("Servicios no inicializados.")
    if not hasattr(request.state, "services"):
        request.state.services = services.request_view()
    return request.state.services


def get_user(request: Request) -> str:
    return get_services(request).auth.user_for(request)


User = Annotated[str, Depends(get_user)]


def _cors_origin_regex(settings: Settings) -> str | None:
    """Localhost en ejecución local y, si se configura, los canales de vista previa de PR del proyecto Firebase."""
    patterns = []
    if settings.local_mode:
        patterns.append(r"http://(localhost|127\.0\.0\.1)(:\d+)?")
    if settings.cors_preview_project:
        patterns.append(rf"https://{re.escape(settings.cors_preview_project)}--pr-[0-9]+-[a-z0-9]+\.(web\.app|firebaseapp\.com)")
    return "^(" + "|".join(patterns) + ")$" if patterns else None


def create_app(settings: Settings | None = None, *, build_services: bool = True, services: object | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc = getattr(app.state, "services", None)
        task = None
        if svc is not None and settings.snapshot_feed_url and not settings.offline:
            await asyncio.to_thread(svc.snapshot_feed.refresh)

            async def refresh_loop() -> None:
                while True:
                    await asyncio.sleep(settings.snapshot_refresh_s)
                    await asyncio.to_thread(svc.snapshot_feed.refresh)

            task = asyncio.create_task(refresh_loop())
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(
        title="Umbral API",
        version=__version__,
        description=(
            "API del MVP editorial Umbral (TVN). Contratos compartidos: `snapshotId`, `rulesVersion`, citas y "
            "estado de evidencia. JSON camelCase. Los resultados son borradores y señales para revisión humana."
        ),
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        # en ejecución local cualquier puerto de localhost (p. ej. Astro cambia de puerto si el 4321 está ocupado)
        allow_origin_regex=_cors_origin_regex(settings),
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Retry-After"],
    )

    if services is not None:
        app.state.services = services
    elif build_services:
        from .services import build_services as _build

        app.state.services = _build(settings)

    @app.middleware("http")
    async def workspace_guard(request: Request, call_next):
        path = request.url.path
        if path.startswith(API_PREFIX):
            origin = request.headers.get("origin")
            if settings.desktop_token and (
                not is_loopback(request) or request.url.hostname not in {"localhost", "127.0.0.1", "::1", "testserver"}
                or (origin is not None and urlparse(origin).hostname not in {"localhost", "127.0.0.1", "::1"})
                or not secrets.compare_digest(request.headers.get("x-umbral-desktop-token", ""), settings.desktop_token)
            ):
                return JSONResponse(status_code=403, content={"code": "prohibido", "message": "Sesión de escritorio no válida.", "details": None})
            if settings.auth_mode == "public":
                private_write = request.method not in {"GET", "HEAD", "OPTIONS"} and not path.startswith(API_PREFIX + "/public/")
                if private_write or "/connections/" in path or path.endswith("/auth/callback") or "/workspace/" in path:
                    return JSONResponse(status_code=403, content={"code": "prohibido", "message": "El trabajo editorial se guarda en tu dispositivo; usa la API pública sin estado.", "details": None})
            if path.startswith(API_PREFIX + "/public/") and request.method == "POST":
                if len(await request.body()) > 2 * 1024 * 1024:
                    return JSONResponse(status_code=422, content={"code": "entrada_invalida", "message": "La solicitud excede 2 MiB.", "details": None})
        return await call_next(request)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        body = ErrorResponse(code=exc.code, message=exc.message, details=exc.details)
        return JSONResponse(
            status_code=exc.status_code, content=body.model_dump(by_alias=True), headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Mantiene el contrato ErrorResponse declarado en OpenAPI; no devuelve valores input
        # ni ctx (que pueden contener credenciales u objetos no serializables de Pydantic).
        fields = [{"field": ".".join(str(p) for p in error["loc"]),
            "message": error["msg"], "type": error["type"]} for error in exc.errors()]
        body = ErrorResponse(code="entrada_invalida", message="La solicitud no cumple el contrato de la API.", details={"fields": fields})
        return JSONResponse(status_code=422, content=body.model_dump(by_alias=True))

    from fastapi import APIRouter

    api = APIRouter(prefix=API_PREFIX)

    def personal_connection(request: Request):  # noqa: ANN202
        from .errors import Forbidden

        host = request.url.hostname
        origin = request.headers.get("origin")
        if not settings.local_mode or settings.auth_mode != "local" or not is_loopback(request) or host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            raise Forbidden("Las conexiones personales requieren una sesión local en localhost.")
        if origin and urlparse(origin).hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise Forbidden("El origen de la solicitud no es local.")
        return get_services(request).providers["chatgpt"].connection

    @api.get("/connections/chatgpt", response_model=ConnectionsResponse, tags=["conexiones"], responses=_ERRORS)
    def connection_status(request: Request, user: User) -> ConnectionsResponse:
        return personal_connection(request).status()

    @api.post("/connections/chatgpt/start", response_model=AuthorizationResponse, tags=["conexiones"], responses=_ERRORS)
    def connection_start(body: ConnectionStart, request: Request, user: User) -> AuthorizationResponse:
        connection = personal_connection(request)
        port = request.url.port or 8000
        return connection.start(body, f"http://127.0.0.1:{port}{API_PREFIX}/auth/callback")

    @api.get("/auth/callback", response_model=ConnectionsResponse, tags=["conexiones"], responses=_ERRORS)
    def connection_callback(request: Request, state: str, code: str | None = None, client_id: str | None = None, error: str | None = None) -> ConnectionsResponse:
        try:
            return personal_connection(request).callback(state=state, code=code, client_id=client_id, error=error)
        finally:
            # El código OAuth es efímero pero sensible: evita que el access log conserve la query.
            request.scope["query_string"] = b""

    @api.post("/connections/chatgpt/select", response_model=ConnectionsResponse, tags=["conexiones"], responses=_ERRORS)
    def connection_select(body: ProfileChoice, request: Request, user: User) -> ConnectionsResponse:
        return personal_connection(request).select(body.profile_id)

    @api.get("/connections/chatgpt/models", response_model=ModelsResponse, tags=["conexiones"], responses=_ERRORS)
    def connection_models(request: Request, user: User) -> ModelsResponse:
        return personal_connection(request).models()

    @api.put("/connections/chatgpt/model", response_model=ModelsResponse, tags=["conexiones"], responses=_ERRORS)
    def connection_model(body: ModelChoice, request: Request, user: User) -> ModelsResponse:
        return personal_connection(request).choose_model(body.model)

    @api.delete("/connections/chatgpt/{profile_id}", response_model=DisconnectResponse, tags=["conexiones"], responses=_ERRORS)
    def connection_disconnect(profile_id: str, request: Request, user: User) -> DisconnectResponse:
        return personal_connection(request).disconnect(profile_id)

    @api.get("/health", response_model=HealthResponse, tags=["estado"], summary="Estado y versión de datos")
    def health(svc=Depends(get_services)) -> HealthResponse:
        return svc.health()

    @api.post("/public/agenda", response_model=TopicsResponse, tags=["publico"], responses=_ERRORS)
    def public_agenda(body: PublicAgendaRequest, user: User, svc=Depends(get_services)) -> TopicsResponse:
        contextual = svc.public.context(body.context, user)
        return contextual.list_topics(user, **body.filters.model_dump())

    @api.post("/public/topics/{topic_id}", response_model=TopicDetail, tags=["publico"], responses=_ERRORS)
    def public_topic(topic_id: str, body: PublicTopicRequest, user: User, svc=Depends(get_services)) -> TopicDetail:
        return svc.public.with_evidence(body.context, body.evidence, user, topic_id).topic_detail(user, topic_id)

    @api.post("/public/queries", response_model=QueryResponse, tags=["publico"], responses=_ERRORS)
    def public_query(body: PublicQueryRequest, user: User, svc=Depends(get_services)) -> QueryResponse:
        contextual = svc.public.context(body.context, user)
        return contextual.query(user, QueryRequest(question=body.question, topic_id=body.topic_id, limit=body.limit))

    @api.post("/public/drafts", response_model=PublicDraftResponse, tags=["publico"], responses=_ERRORS)
    def public_draft(body: PublicDraftRequest, user: User, svc=Depends(get_services)) -> PublicDraftResponse:
        return svc.public.draft(body, user)

    @api.post("/public/validate", response_model=PublicValidationResponse, tags=["publico"], responses=_ERRORS)
    def public_validate(body: PublicValidationRequest, user: User, svc=Depends(get_services)) -> PublicValidationResponse:
        return svc.public.validate(body, user)

    @api.get("/workspace/export", response_model=WorkspaceArchive, tags=["revision"], responses=_ERRORS)
    def export_workspace(user: User, svc=Depends(get_services)) -> WorkspaceArchive:
        return svc.export_workspace(user)

    @api.post("/workspace/import", response_model=WorkspaceImportResponse, tags=["revision"], responses=_ERRORS)
    def import_workspace(body: WorkspaceArchive, user: User, svc=Depends(get_services)) -> WorkspaceImportResponse:
        return svc.import_workspace(user, body)

    @api.get("/rules", response_model=RulesResponse, tags=["estado"], summary="Reglas scoring-v1 y changelog")
    def rules(user: User, svc=Depends(get_services)) -> RulesResponse:
        return svc.rules(user)

    @api.put("/rules", response_model=RulesResponse, tags=["agenda"], summary="Cambiar pesos con motivo, autor e historial versionado", responses=_ERRORS)
    def set_rules(body: RulesRequest, user: User, svc=Depends(get_services)) -> RulesResponse:
        return svc.set_rules(user, body)

    @api.get(
        "/snapshot",
        response_model=SnapshotInfoResponse,
        tags=["estado"],
        summary="Fuentes y evaluación: manifest, reporte de calidad, catálogo y métricas reales",
    )
    def snapshot(svc=Depends(get_services)) -> SnapshotInfoResponse:
        return svc.snapshot_info()

    @api.get(
        "/topics",
        response_model=TopicsResponse,
        tags=["agenda"],
        summary="Agenda: temas ordenados por puntaje scoring-v1",
        responses=_ERRORS,
    )
    def list_topics(
        user: User,
        svc=Depends(get_services),
        limit: int = Query(5, ge=1, le=100, description="Por defecto los 5 temas principales"),
        category: str | None = Query(None, description="Categoría (economia, logistica_canal, …)"),
        evidence: str | None = Query(None, description="insuficiente | parcial | suficiente"),
        band: str | None = Query(None, description="bajo | medio | alto"),
        review_status: str | None = Query(None, alias="reviewStatus"),
        q: str | None = Query(None, description="Búsqueda libre (BM25 + RapidFuzz) sobre los temas"),
        include_components: bool = Query(True, alias="includeComponents"),
        scope: str = Query(
            "in_scope",
            pattern="^(in_scope|all)$",
            description="in_scope (defecto): excluye temas de categoría indeterminada (fuera del alcance temático); "
            "all: los incluye. La respuesta trae outOfScopeCount.",
        ),
    ) -> TopicsResponse:
        return svc.list_topics(
            user,
            limit=limit,
            category=category,
            evidence=evidence,
            band=band,
            review_status=review_status,
            q=q,
            include_components=include_components,
            scope=scope,
        )

    @api.get(
        "/topics/{topic_id}",
        response_model=TopicDetail,
        tags=["agenda"],
        summary="Ficha de un tema",
        responses=_ERRORS,
    )
    def topic_detail(topic_id: str, user: User, svc=Depends(get_services)) -> TopicDetail:
        return svc.topic_detail(user, topic_id)

    @api.put(
        "/topics/{topic_id}/impact",
        response_model=CaseView,
        tags=["agenda"],
        summary="Asignación editorial de impacto (con justificación, motivo y versión)",
        responses=_ERRORS,
    )
    def set_impact(topic_id: str, body: ImpactRequest, user: User, svc=Depends(get_services)) -> CaseView:
        return svc.set_impact(user, topic_id, body)

    @api.post(
        "/queries",
        response_model=QueryResponse,
        tags=["consultas"],
        summary="Consulta en español con evidencia, citas y abstención",
        responses=_ERRORS,
    )
    def queries(body: QueryRequest, user: User, svc=Depends(get_services)) -> QueryResponse:
        return svc.query(user, body)

    @api.post(
        "/topics/{topic_id}/drafts",
        response_model=DraftResponse,
        tags=["borradores"],
        summary="Crear un borrador (modelo / recuperado / plantilla)",
        responses=_ERRORS,
    )
    def create_draft(
        topic_id: str, request: Request, user: User, svc=Depends(get_services), body: DraftRequest | None = None
    ) -> DraftResponse:
        return svc.create_draft(user, topic_id, body or DraftRequest(), client_is_local=is_loopback(request))

    @api.get("/cases/{case_id}", response_model=CaseView, tags=["revision"], summary="Caso del usuario", responses=_ERRORS)
    def get_case(case_id: str, user: User, svc=Depends(get_services)) -> CaseView:
        return svc.get_case(user, case_id)

    @api.put(
        "/cases/{case_id}/draft",
        response_model=CaseView,
        tags=["borradores"],
        summary="Guardar edición humana del borrador (brief/guion/copy) con control de versión",
        responses=_ERRORS,
    )
    def edit_draft(case_id: str, body: DraftEditRequest, user: User, svc=Depends(get_services)) -> CaseView:
        return svc.edit_draft(user, case_id, body)

    @api.patch(
        "/cases/{case_id}/review",
        response_model=CaseView,
        tags=["revision"],
        summary="Registrar revisión (transición de estado) con control de versión",
        responses=_ERRORS,
    )
    def review(case_id: str, body: ReviewRequest, user: User, svc=Depends(get_services)) -> CaseView:
        return svc.review(user, case_id, body)

    @api.get(
        "/cases/{case_id}/export",
        response_model=ExportResponse,
        tags=["revision"],
        summary="Exportar ficha a Markdown listo para Notion",
        responses={**_ERRORS, 200: {"content": {"application/json": {}, "text/markdown": {}}}},
    )
    def export(
        case_id: str,
        user: User,
        svc=Depends(get_services),
        format: str = Query("json", pattern="^(json|markdown)$"),
    ):
        result = svc.export(user, case_id)
        if format == "markdown":
            return PlainTextResponse(
                result.markdown,
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
            )
        return result

    app.include_router(api)

    dist = settings.web_dist
    if (build_services or services is not None) and dist.is_dir() and (dist / "index.html").exists():
        # El build de Astro se sirve desde FastAPI (arranque local). Las rutas /api/* ya están registradas.
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")

    return app
