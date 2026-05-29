"""Data ingestion adapters.

Each adapter normalises an external source into the canonical `Trade` schema.
Adapters share a synthetic-fallback contract: if the real source is unavailable
(network blocked, API key missing, archive corrupt) they emit a deterministic
synthetic dataset that exercises the same code paths.
"""
