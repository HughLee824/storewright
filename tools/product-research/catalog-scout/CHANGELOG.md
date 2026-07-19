# Changelog

All notable changes to StoreWright Catalog Scout are documented here.

## Unreleased

- Add a guarded, repository-level multi-tool release script with independent tool versions, automatic patch/minor/major bumps, tags, checks, and optional atomic publishing.

## 0.1.1 - 2026-07-19

- Make finite detail batches, screening pauses, 60-second pacing, hourly budgets, and persisted risk cooldowns the production defaults.
- Prevent concurrent browser-mutating commands in one workspace and fail closed on login, verification, blocking, anomalous responses, or invalid detail pages.

## 0.1.0 - 2026-07-19

- Add the auditable and resumable product-screening pipeline.
- Add Taobao and Tmall catalog discovery and detail extraction.
- Add SerpApi Google Lens exact-match screening with API key-pool failover.
- Add deterministic category quotas, shop early stopping, reports, and archive rebuilding.
- Publish the `storewright-scout` CLI as the `storewright-catalog-scout` package.
