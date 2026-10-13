"""Optional tracing with OpenTelemetry.

Off by default. Set NOVA_TRACING=1 to switch it on. Finished spans are written
as one JSON line each to the file named in NOVA_TRACE_FILE, or to stderr when
that is not set.

If opentelemetry-sdk is not installed, tracing stays off and everything else
works as before. Spans hold names, counts and token totals only, never message
text or tool arguments.

Use it as:  with tracing.span("nova.tool", {"nova.tool_name": name}) as s:
"""
import logging
import os
import sys
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_tracer: Any = None
_configured = False


def enabled() -> bool:
    value = os.environ.get("NOVA_TRACING", "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _default_exporter(console_exporter: Any) -> Any:
    path = os.environ.get("NOVA_TRACE_FILE", "").strip()
    out = open(path, "a", encoding="utf-8") if path else sys.stderr
    return console_exporter(
        out=out, formatter=lambda finished: finished.to_json(indent=None) + os.linesep
    )


def setup_tracing(exporter: Any = None) -> bool:
    """Switch tracing on. Returns True if spans will be recorded.

    A ready-made exporter can be passed in (tests do this). Only the first
    call has an effect, until reset() is called.
    """
    global _tracer, _configured
    if _configured:
        return _tracer is not None
    _configured = True
    if exporter is None and not enabled():
        return False
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )
    except ImportError:
        logger.warning("NOVA_TRACING is on, but opentelemetry-sdk is not installed.")
        return False
    try:
        if exporter is None:
            exporter = _default_exporter(ConsoleSpanExporter)
        provider = TracerProvider(resource=Resource.create({"service.name": "nova"}))
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        _tracer = provider.get_tracer("nova")
    except OSError as exc:
        logger.warning("Could not start tracing: %s", exc)
        _tracer = None
        return False
    return True


def reset() -> None:
    """Forget the current setup. For tests."""
    global _tracer, _configured
    _tracer = None
    _configured = False


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Record a span around a block. Does nothing when tracing is off."""
    if not _configured:
        setup_tracing()
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as current:
        for key, value in (attributes or {}).items():
            if value is not None:
                current.set_attribute(key, value)
        yield current


def set_attribute(current: Any, key: str, value: Any) -> None:
    """Add an attribute to a span from span(). Safe when it is None."""
    if current is not None and value is not None:
        current.set_attribute(key, value)