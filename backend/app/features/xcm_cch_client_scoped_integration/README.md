# Client-scoped Maconomy to CCH/XCM integration

The first stage exposes `POST /api/v1/xcm-cch-client-scoped/sync` with the
standard `X-API-KEY` header. The request body accepts `jobnumbers` as an array
of strings or `null`; omitting the field has the same meaning as `null`.

```json
{"jobnumbers": ["12345", "67890"]}
```

The endpoint authenticates with Maconomy once, keeps the reconnect token on
the Maconomy service instance for subsequent steps in the same request, and
returns eligible jobs from the Maconomy `jobs/filter` API. With `jobnumbers`
set to `null`, omitted, or an empty list, it selects eligible jobs created
since yesterday using `createddate>=date(year,month,day)` in Maconomy's
zero-based month format. With a non-empty list, it adds grouped `jobnumber`
alternatives without a created-date condition. Both paths make one filter call
with `limit: 5000` and `offset: 0`, returning at most 5,000 matching jobs.

Both request paths require `template=false`, `locationname='2'`,
`closed=false`, and `text20=''`. For each returned Maconomy job, the endpoint
searches CCH clients using the job's `jobnumber` as `AccountNumber`. It sends
`POST /xcmrestservices/vnext/api/v2/Client/search/advanced` once, with an OR
filter for each distinct job number, `pageIndex: 1`, and `pageCount` equal to
the number of Maconomy jobs returned. It adds `is_exist_in_chh` to each
job. A job is marked `true` only when a returned CCH `accountNumber` matches
its job number; jobs with no matching account number in the returned results
are marked `false`. CCH authentication is performed once for the run. No CCH
client or task is created in this step.

It has its own integration service registration, initially inactive, separate
from the old CCH task-mapping integration.
