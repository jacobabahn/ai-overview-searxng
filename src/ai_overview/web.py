import json
import logging
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any, Optional
from urllib.parse import urlsplit

from flask import Blueprint, Flask, Response, jsonify, render_template, request, stream_with_context
from markupsafe import Markup

from .catalog import ModelCatalog
from .errors import OverviewError
from .models import Conversation, Event
from .service import GenerationService
from .state import MAX_STATE_BYTES

log = logging.getLogger(__name__)
ROOT = Path(__file__).parent


def sse_event(event: Event) -> str:
    return f"event: {event.name}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"


def register(
    app: Flask, service: GenerationService, catalog: Optional[ModelCatalog] = None
) -> None:
    catalog = catalog or ModelCatalog(service.config)
    bp = Blueprint(
        "ai_overview",
        __name__,
        url_prefix="/ai-overview",
        static_folder="static",
        template_folder="templates",
    )
    slots = BoundedSemaphore(service.config.max_concurrent)

    @bp.post("/models")
    def models() -> Response:
        try:
            body = _json_request({"token"})
            service.signer.loads(body.get("token"))
            if not service.config.model_picker:
                raise OverviewError("invalid_request", "The model picker is disabled.")
            result = catalog.list()
            response = jsonify(asdict(result))
            response.headers["Cache-Control"] = "no-store"
            return response
        except OverviewError as error:
            return _json_error(error)

    @bp.post("/select")
    def select() -> Response:
        try:
            body = _json_request({"token", "profile", "model"})
            state = service.signer.loads(body.get("token"))
            selected = catalog.select(state, body.get("profile"), body.get("model"))
            response = jsonify(token=service.signer.dumps(selected))
            response.headers["Cache-Control"] = "no-store"
            return response
        except OverviewError as error:
            return _json_error(error)

    @bp.post("/stream")
    def stream() -> Response:
        try:
            _same_origin()
            request.max_content_length = MAX_STATE_BYTES + 10000
            if not request.is_json:
                raise OverviewError("invalid_request", "Send a JSON request.")
            body = request.get_json(silent=True)
            if not isinstance(body, dict) or set(body) - {"token", "question"}:
                raise OverviewError("invalid_request", "Invalid overview request.")
            state = service.signer.loads(body.get("token"))
            question = body.get("question")
            if question is not None:
                if not isinstance(question, str) or not question.strip() or len(question) > 2000:
                    raise OverviewError(
                        "invalid_request", "Enter a question under 2,000 characters."
                    )
                question = question.strip()
        except OverviewError as error:
            return _error_response(error, 403 if error.code == "invalid_state" else 400)
        if not slots.acquire(blocking=False):
            return _error_response(
                OverviewError("busy", "AI Summary is busy. Try again shortly."), 429
            )

        def generate() -> Iterator[str]:
            try:
                yield ": connected\n\n"
                yield from (sse_event(event) for event in service.run(state, question))
            except OverviewError as error:
                yield sse_event(Event("error", {"code": error.code, "message": error.message}))
            except Exception as error:
                # Record only the exception class, never provider bodies, queries, or keys.
                log.warning("Overview failed (%s)", type(error).__name__)
                yield sse_event(
                    Event(
                        "error", {"code": "internal", "message": "The overview failed. Try again."}
                    )
                )
            finally:
                slots.release()

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
                "X-Content-Type-Options": "nosniff",
            },
        )

    app.register_blueprint(bp)


def render_panel(service: GenerationService, state: Conversation) -> Markup:
    profile = service.config.profiles[state.profile]
    return Markup(
        render_template(
            "overview.html",
            token=service.signer.dumps(state),
            model_picker=service.config.model_picker,
            profile=state.profile,
            model=state.model or profile.model,
        )
    )


def _json_request(allowed: set[str]) -> dict[str, Any]:
    _same_origin()
    request.max_content_length = MAX_STATE_BYTES + 10000
    body = request.get_json(silent=True) if request.is_json else None
    if not isinstance(body, dict) or set(body) - allowed:
        raise OverviewError("invalid_request", "Invalid model selection request.")
    return body


def _json_error(error: OverviewError) -> Response:
    response = jsonify(code=error.code, message=error.message)
    response.status_code = 403 if error.code == "invalid_state" else 400
    response.headers["Cache-Control"] = "no-store"
    return response


def _error_response(error: OverviewError, status: int) -> Response:
    return Response(
        sse_event(Event("error", {"code": error.code, "message": error.message})),
        status=status,
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-store"},
    )


def _same_origin() -> None:
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise OverviewError("invalid_request", "Use the overview from your search page.")
    origin = request.headers.get("Origin")
    expected = urlsplit(request.host_url)
    actual = urlsplit(origin) if origin else None
    if actual and (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
        raise OverviewError("invalid_request", "Use the overview from your search page.")
