# retry-parser

`retry_after_seconds(value, now=...)` converts an HTTP `Retry-After` header into
the number of whole seconds a caller should wait.

Supported values:

- non-negative decimal seconds, such as `"120"`;
- an RFC 7231 HTTP-date, such as `"Wed, 21 Oct 2015 07:28:00 GMT"`.

Missing, blank, malformed, and negative delta-second values return `None`.
Past HTTP dates return `0`. Naive `now` values are interpreted as UTC.
