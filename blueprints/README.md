# Titan Rail Scenario Blueprints

This directory contains production-tested scenario blueprints for Make.com that interface directly with the Titan Rail decision microservice.

## Scenarios Overview

### 1. `order_export_failsafe.json`
- **Direction**: Ingress ERP order events to Third-Party Logistics (3PL) order fulfillment.
- **Fail-Safe Route**: Directs invalid orders to an operational triage queue containing exact validation error fields.
- **Fuzzy Carrier Fallback**: If an order specifies an unmapped carrier or delivery tier, the scenario holds the transaction and presents ranked carrier candidates for human sign-off.
- **Resilience**: Configured with `builtin:Break` error directives to automatically retry against 3PL downtime and queue unresolved bundles in Make's Incomplete Executions DLQ.

### 2. `tracking_sync_failsafe.json`
- **Direction**: Inbound 3PL delivery updates to ERP shipment status reconciliation.
- **Deduplication**: Filters out duplicate tracking webhooks via the SHA-256 idempotency cache.
- **Reconciliation Engine**: Calculates split fulfillment, backorders, and unit count discrepancies before updating ERP records.

## Import & Configuration Instructions

1. Open your Make.com workspace and create a new scenario.
2. Select **More Options (...)** -> **Import Blueprint**.
3. Choose either `order_export_failsafe.json` or `tracking_sync_failsafe.json`.
4. Update the endpoint placeholder variables (`YOUR_SERVICE_HOST`, `YOUR_3PL_API`, `YOUR_ERP_API`) to point to your live Titan Rail deployment and upstream endpoints.
