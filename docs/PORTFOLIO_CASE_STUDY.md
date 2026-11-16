# UptimePilot — Engineering Case Study & Quality Roadmap

**Portfolio:** [Digital Solution9](https://github.com/shakaleita/teamforge-saas/blob/main/PORTFOLIO.md) · **Repository:** [Source](https://github.com/shakaleita/UptimePilot-API-Monitoring)  
**Stack:** React, FastAPI, SQLite · **Status:** Local portfolio MVP; not certified production software.

## Implemented domain workflow
Endpoint uptime checks, latency reports, host allowlisting and URL validation.

Descriptions reflect the public project's existing README. They are not a statement that a new deployment or independent penetration test was completed.

## Domain invariants
No check may reach local, private or metadata addresses; redirects must not bypass the allowlist; check workers require timeouts and concurrency ceilings.

## Verification backlog
- Reject localhost, RFC1918 addresses and metadata targets
- Deny redirect/DNS rebinding bypasses under controlled mocks
- Uptime reports correctly handle missing and failed checks

## High-value engineering upgrades
1. Review SSRF protections using a threat model and controlled DNS mocks
2. Add durable scheduler, retries and alert escalation
3. Add Prometheus-style metrics, health checks and load testing

## Production release gate

A production claim requires repeatable API and browser tests, threat modelling, verified authorization boundaries, database migration and restoration rehearsals, monitored staging deployment, accessibility verification and published performance evidence. Do not introduce real client, patient or other sensitive information into demo data.

**Engineering honesty:** This case study identifies current work and concrete improvements; it does not claim those outstanding checks passed.
