"""Prometheus metrics (exposed at /metrics, local only)."""

from prometheus_client import Counter, Histogram

HTTP_LATENCY = Histogram("tl_http_request_seconds", "HTTP latency", ["method", "route", "status"])
LLM_CALLS = Counter("tl_llm_calls_total", "LLM calls", ["provider", "model", "operation", "status"])
LLM_LATENCY = Histogram("tl_llm_latency_seconds", "LLM latency", ["provider", "operation"])
EMBED_LATENCY = Histogram("tl_embedding_seconds", "Embedding batch latency", ["provider"])
RETRIEVAL_LATENCY = Histogram("tl_retrieval_seconds", "Retrieval latency", ["channel"])
JOBS = Counter("tl_jobs_total", "Background jobs", ["kind", "status"])
EVENTS = Counter("tl_domain_events_total", "Domain events handled", ["type", "status"])
SYNC_ITEMS = Counter("tl_sync_items_total", "Items synced", ["connector", "outcome"])
GRAPH_OPS = Counter("tl_graph_ops_total", "Graph operations", ["op"])
