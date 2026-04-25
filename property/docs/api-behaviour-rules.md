# RentOut API Behaviour Rules (v1)

This document defines stable behaviour rules so the frontend knows what to expect.

## Pagination (all list endpoints)

### Response shape
All list endpoints that return collections should return a paginated envelope:

- `count` (int)
- `next` (url or null)
- `previous` (url or null)
- `results` (array)

Example:
```json
{
  "count": 123,
  "next": "https://.../?limit=20&offset=20",
  "previous": null,
  "results": []
}



