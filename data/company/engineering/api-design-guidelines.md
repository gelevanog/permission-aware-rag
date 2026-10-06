# API Design Guidelines

These guidelines apply to every public RouteIQ API endpoint and, where practical, to internal service-to-service APIs. New endpoints must be reviewed against this document by a member of the API guild before release.

## REST conventions

- Resources are plural nouns in kebab-case: `/v2/routes`, `/v2/delivery-windows`, `/v2/vehicles/{vehicle_id}/positions`.
- Use standard HTTP methods: `GET` to read, `POST` to create, `PATCH` for partial updates, `PUT` only for full replacement, `DELETE` to remove.
- JSON field names are `snake_case`. Timestamps are ISO 8601 in UTC with a `Z` suffix; durations are integers in seconds; distances are in metres; weights in kilograms.
- IDs are opaque strings with a type prefix, for example `rte_8f2k1x` for a route and `veh_3ma9q0` for a vehicle.
- Long-running operations such as optimising a 5,000-stop plan return `202 Accepted` with a `job` resource that clients poll or receive by webhook.
- Every write endpoint accepts an `Idempotency-Key` header; keys are retained for 24 hours.

## Versioning

The major version lives in the URL: `/v1/`, `/v2/`. We only create a new major version for breaking changes. Within a version, we may add optional fields, new endpoints and new enum values, so clients must ignore unknown fields. API v2 is current; v1 is in maintenance mode and receives security fixes only. A deprecated version is announced at least 9 months before it is switched off, with `Deprecation` and `Sunset` headers on every response.

## Pagination

All list endpoints use **cursor pagination**. Do not use offset pagination for new endpoints.

```
GET /v2/routes?limit=50&cursor=eyJpZCI6InJ0ZV84ZjJrMXgifQ
```

The response includes `data` (the items) and `next_cursor`, which is `null` on the last page. The default `limit` is 50 and the maximum is 200. Results are ordered by creation time unless a documented `sort` parameter is provided.

## Error format

Errors use a consistent JSON body and the correct HTTP status code:

```json
{
  "error": {
    "type": "validation_error",
    "code": "time_window_invalid",
    "message": "Delivery window end must be after start.",
    "field": "stops[3].window.end",
    "request_id": "req_01HZX4"
  }
}
```

Error `type` is one of `validation_error` (400/422), `authentication_error` (401), `permission_error` (403), `not_found` (404), `conflict` (409), `rate_limited` (429) or `internal_error` (500). Never expose stack traces or internal hostnames in messages.

## Rate limits and documentation

Rate limits are per API key and reported in `RateLimit-Limit` and `RateLimit-Remaining` headers. Every endpoint is described in the OpenAPI 3.1 spec in the `api-spec` repository; the spec is the source of truth for the public documentation and the generated SDKs.
