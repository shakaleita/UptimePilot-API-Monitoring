# UptimePilot engineering notes

- Captures HTTP check status and latency, plus aggregated per-monitor reliability.
- Requires ALLOWED_MONITOR_HOSTS allowlist before making an outbound request.
- Rejects private address resolution, credentials in URLs and non-standard ports.
- DNS rebinding/TOCTOU remains a deployment risk; use network egress controls and pinned IP resolution before production. Do not expose to arbitrary users.
- Owner-only session protection and secure setup token.
