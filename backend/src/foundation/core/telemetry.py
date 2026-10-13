"""OpenTelemetry: traces and metrics over OTLP/HTTP.

Disabled unless OTEL_EXPORTER_OTLP_ENDPOINT is set. setup_telemetry() then installs
the global tracer/meter providers and instruments SQLAlchemy and outgoing HTTP
(the Stripe SDK uses requests/httpx). Incoming requests are traced and measured by
FastAPI's native telemetry (APP_TELEMETRY, passed to FastAPI()), which reports to
these global providers and stays inert while they are unset.

Logs are not exported from here: they go to stdout (redacted; JSON in production)
where the Alloy agent collects them, and the logging processor stamps the active
trace/span id onto each line so Grafana can jump from a log line to its trace.

Instruments below are created against the global proxies, so they are no-ops
until setup_telemetry() runs - tests and telemetry-less setups pay nothing. The SDK,
exporters and instrumentors are lazy imports, loaded only by setup_telemetry().
"""

import os
import re
import time
from collections.abc import Generator, Iterable
from contextlib import contextmanager

from fastapi.telemetry import TelemetryConfig
from opentelemetry import metrics, trace
from opentelemetry.metrics import CallbackOptions, Observation
lazy from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
lazy from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
lazy from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
lazy from opentelemetry.instrumentation.requests import RequestsInstrumentor
lazy from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
lazy from opentelemetry.sdk.metrics import MeterProvider
lazy from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
lazy from opentelemetry.sdk.resources import Resource
lazy from opentelemetry.sdk.trace import TracerProvider
lazy from opentelemetry.sdk.trace.export import BatchSpanProcessor

from src.foundation.core.config import settings
from src.foundation.core.database import engine

_tracer = trace.get_tracer("src.foundation")
_meter = metrics.get_meter("src.foundation")

_enabled = False


def setup_telemetry(service: str) -> None:
    """Configure exporters for this process ("api" / "worker"). No-op when
    OTEL_EXPORTER_OTLP_ENDPOINT is unset."""
    global _enabled  # noqa: PLW0603 - process-wide singleton
    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
    if not endpoint or _enabled:
        return
    _enabled = True
    # Stable HTTP semantic conventions (http.server.request.duration in seconds,
    # http.route / http.response.status_code) - the dashboards and alerts use them
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")

    resource = Resource.create(
        {
            "service.name": service,
            "service.namespace": re.sub(r"[^a-z0-9]+", "-", settings.app_name.lower()),
            "deployment.environment.name": settings.app_env,
        },
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")),
    )
    trace.set_tracer_provider(tracer_provider)

    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
        export_interval_millis=15_000,
    )
    metrics.set_meter_provider(
        MeterProvider(resource=resource, metric_readers=[reader]),
    )

    # The instrumentor declares sqlalchemy < 2.1 and refuses to run on 2.1.x, but
    # its engine event hooks work unchanged there; drop skip_dep_check once it
    # widens the pin
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine, skip_dep_check=True)
    RequestsInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()


# Trace every request (minus health checks) and record the standard HTTP server
# metrics (http.server.request.duration by route and status) the dashboards use
APP_TELEMETRY: TelemetryConfig = {"exclude": lambda scope: scope["path"] == "/health"}


# --- Worker loops ------------------------------------------------------------

_worker_runs = _meter.create_counter(
    "worker.runs",
    unit="{run}",
    description="Worker loop iterations by outcome",
)
_worker_duration = _meter.create_histogram(
    "worker.run.duration",
    unit="s",
    description="Worker loop iteration duration",
)
_last_success: dict[str, float] = {}
_intervals: dict[str, float] = {}


def _observe_last_success(_options: CallbackOptions) -> Iterable[Observation]:
    for worker, timestamp in _last_success.items():
        yield Observation(timestamp, {"worker": worker})


def _observe_interval(_options: CallbackOptions) -> Iterable[Observation]:
    for worker, interval in _intervals.items():
        yield Observation(interval, {"worker": worker})


_meter.create_observable_gauge(
    "worker.last_success",
    callbacks=[_observe_last_success],
    unit="s",
    description="Unix time of the worker's last successful iteration",
)
_meter.create_observable_gauge(
    "worker.interval",
    callbacks=[_observe_interval],
    unit="s",
    description="Configured sleep between worker iterations",
)


@contextmanager
def track_worker_run(worker: str, interval_seconds: float) -> Generator[None]:
    """Wrap one iteration of a worker loop: a trace span, duration/outcome
    metrics, and the last-success timestamp that the heartbeat alert compares
    against the loop's interval. Exceptions are recorded and re-raised."""
    _intervals[worker] = interval_seconds
    outcome = "success"
    start = time.perf_counter()
    with _tracer.start_as_current_span(
        f"worker {worker}",
        attributes={"worker": worker},
    ):
        try:
            yield
        except Exception:
            outcome = "error"
            raise
        finally:
            attributes = {"worker": worker, "outcome": outcome}
            _worker_runs.add(1, attributes)
            _worker_duration.record(time.perf_counter() - start, attributes)
            if outcome == "success":
                _last_success[worker] = time.time()
