# Replay Lab v0.3.1

Replay Lab combines local historical replay, simulated orders, configurable indicators, Python strategies, and report export. The browser and VS Code interfaces share one local service. Downloaded bars and user records remain in the project directory.

The project supports 1-minute, 1-hour, and daily base data, with higher display intervals aggregated from those bars. It includes crypto spot and perpetual data, selected Chinese/US/Japanese/Korean indices, manual CSV import, a market data adapter interface, and a manually invoked paid-provider import hook.

The bundled data sources are public and may limit availability, historical coverage, or volume quality. Paid-provider access and index entitlements require independent confirmation. VS Code and browser use the same frontend resources.

See [the README](../README.md) for installation, usage, data adapter instructions, and model limits. See [third-party notices](../THIRD_PARTY_NOTICES.md) for component licenses and data source notes.

0.3.1 adds queued UI operations, pre-session indicator editing, date coverage correction, transactional session replacement, configurable causal pre-start history, and confirmed bulk record deletion with shared strategy snapshot retention. Regression tests cover both UI transports and isolated backend storage.
