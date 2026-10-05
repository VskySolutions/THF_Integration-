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
searches CCH clients using the job's `jobnumber` as `AccountNumber`. Distinct
job numbers are searched in batches of at most 20. For example, 100 numbers
make five CCH search calls. Each
`POST /xcmrestservices/vnext/api/v2/Client/search/advanced` call uses OR
filters for its batch, `pageIndex: 1`, and `pageCount` equal to the batch size
plus the existing 50-result buffer. Matches are combined before adding
`is_exist_in_chh` to every Maconomy job. A job is marked `true` only when a
returned CCH `accountNumber` matches its job number; jobs with no matching
account number in the returned results are marked `false`. CCH authentication
is performed once for the run and reused for client creation.

For the returned jobs, the endpoint fetches Maconomy reference records to
enrich each job. It gathers distinct
`customernumber` values for `customercard/filter` and distinct
`projectmanagernumber`, `specification5name`, and `employeenumber6` values for
`employees/filter`. Those calls use OR restrictions, `limit: 5000`, and
`offset: 0`. The customer fields are `customernumber`, `name1`, and
`fiscalyearendmonth`; employee fields are `employeenumber` and
`electronicmailaddress`.

The endpoint also fetches `specification2name` and `description` from
`specification2/filter`, and `specification1name` and `description` from
`specification1/filter`. Each specification call is unfiltered with
`limit: 1000` and `offset: 0`. All calls reuse the Maconomy reconnect token.

The response is a list of job objects. Each job includes
`fiscalyearendmonth` from its customer and `periodenddate` derived from
`theyear` and the last day of that month in `MM/DD/YYYY` format. Numeric
months, full month names, and abbreviations are accepted; missing or invalid
values produce `null`. Jobs also include `specification1_description` and
`specification2_description` from the matching specifications, plus
`projectmanager_email`, `employee6_email`, and `spec5_email` from the matching
employees. A missing match produces `null` for that field. The route currently
passes the first 40 eligible jobs to the CCH lookup. For each job flagged
`is_exist_in_chh: false`, it posts a new client to
`/xcmrestservices/vnext/api/v2.1/Client` using the joined values. It maps
`projectmanager_email` to `responsiblePerson`, job `electronicmailaddress` to
`emailId`, `name1` to `last_Entity_Name`, `telephone` to `phoneNumber`,
`jobnumber` to `accountNumber`, `specification2_description` to `primaryTask`,
`periodenddate` to `periodEndDate`, `spec5_email` to `auditStaff`, and
`employee6_email` to `taxPartner`. `clientType` is `Individual` when
`specification1_description` is `individual` (case insensitive), or `Entity`
otherwise. `originatingLocationName` is `HQ` and `active` is `Y`.

After a client is created, the endpoint directly creates its task through
`/xcmrestservices/vnext/api/v2/Task`. It does not search for an existing task,
because this path only processes newly created clients. The task uses the
client's `jobnumber` account number, `specification2_description` task type,
`periodenddate`, and `projectmanager_email` as its responsible person. A blank
specification description uses `Tax - 1040 Individual` as the task type.

Each returned job includes `cchclientcreation` and `cchtaskcreation` status
objects. Client creation failure marks the task as `skipped`. Task failure is
recorded independently after a successful client creation. A failure for one
job does not stop processing of later jobs.

It has its own integration service registration, initially inactive, separate
from the old CCH task-mapping integration.
