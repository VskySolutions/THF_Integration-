# CCH XCM - Authentication API

## Endpoint

```
POST {base_url}/xcmrestservices/vnext/api/v2/Authenticate/user
```

## Base URL

```
https://sandboxworkflow.cchaxcess.com
```

## Full URL

```
https://sandboxworkflow.cchaxcess.com/xcmrestservices/vnext/api/v2/Authenticate/user
```

## Headers

| Header | Value | Required |
|--------|-------|----------|
| APIKey | {your-api-key} | Yes |
| accept | application/json | Yes |
| Content-Type | application/json | Yes |

## Request Body

```json
{
  "userName": "string",
  "password": "string"
}
```

## Success Response (200)

```json
{
  "token": "string"
}
```

## Error Responses

### 400 Bad Request

```json
{
  "errors": {
    "additionalProp1": [
      "string"
    ],
    "additionalProp2": [
      "string"
    ],
    "additionalProp3": [
      "string"
    ]
  },
  "type": "string",
  "title": "string",
  "status": 0,
  "detail": "string",
  "instance": "string",
  "additionalProp1": "string",
  "additionalProp2": "string",
  "additionalProp3": "string"
}
```

### 401 Unauthorized

```json
{
  "message": "string"
}
```

### 500 Internal Server Error

```json
{
  "type": "string",
  "title": "string",
  "status": 0,
  "detail": "string",
  "instance": "string",
  "additionalProp1": "string",
  "additionalProp2": "string",
  "additionalProp3": "string"
}
```

## Example cURL

```bash
curl -X 'POST' \
  'https://sandboxworkflow.cchaxcess.com/xcmrestservices/vnext/api/v2/Authenticate/user' \
  -H 'accept: application/json' \
  -H 'APIKey: your-api-key' \
  -H 'Content-Type: application/json' \
  -d '{
  "userName": "your-username",
  "password": "your-password"
}'
```

## Tested with Postman

```bash
curl --location 'https://sandboxworkflow.cchaxcess.com/xcmrestservices/vnext/api/v2/Authenticate/user' \
--header 'Accept: application/json' \
--header 'Content-Type: application/json' \
--header 'APIKey: ******' \
--data-raw '{
  "userName": "usernam@email.com",
  "password": "***"
}'
```

**Note:** APIKey header is mandatory for this endpoint.

## Notes

- Token returned is used in subsequent API calls via `securitytoken` header
- APIKey header is required for all XCM API calls
- The token is a JWT token with embedded claims (accountId, firmId, expiration)
