# RentOut Integration Tracker

## Status Legend
- Todo
- In Progress
- Blocked
- In Review
- Done
- Deferred

---

## Auth

| Endpoint | Screen | Status | Owner | Blockers |
|-----------|--------|--------|--------|----------|
| POST /api/v1/auth/register/ | Register | Todo |  |  |
| POST /api/v1/auth/login/ | Login | Todo |  |  |
| POST /api/v1/auth/token/refresh/ | Token Refresh | Todo |  |  |
| POST /api/v1/auth/logout/ | Logout | Todo |  |  |

---

## Rooms

| Endpoint | Screen | Status | Owner | Blockers |
|-----------|--------|--------|--------|----------|
| GET /api/v1/rooms/ | Browse Rooms | Todo |  |  |
| GET /api/v1/rooms/{id}/ | Room Details | Todo |  |  |
| POST /api/v1/rooms/ | Create Listing | Todo |  |  |
| PATCH /api/v1/rooms/{id}/ | Edit Listing | Todo |  |  |
| POST /api/v1/rooms/{id}/soft-delete/ | Delete Listing | Todo |  |  |

---

## Photos

| Endpoint | Screen | Status | Owner | Blockers |
|-----------|--------|--------|--------|----------|
| POST /api/v1/rooms/{id}/photos/ | Upload Photos | Todo |  |  |
| DELETE /api/v1/rooms/{id}/photos/{photo_id}/ | Delete Photo | Todo |  |  |

---

## Payments

| Endpoint | Screen | Status | Owner | Blockers |
|-----------|--------|--------|--------|----------|
| POST /api/v1/payments/checkout/rooms/{id}/ | Checkout | Todo |  |  |
| GET /api/v1/payments/success/ | Payment Success | Todo |  |  |
| GET /api/v1/payments/cancel/ | Payment Cancel | Todo |  |  |
| POST /api/v1/payments/webhook/ | Stripe Webhook | Todo |  |  |

---

## Messaging

| Endpoint | Screen | Status | Owner | Blockers |
|-----------|--------|--------|--------|----------|
| GET /api/v1/inbox/ | Inbox | Todo |  |  |
| GET /api/v1/messages/threads/ | Threads | Todo |  |  |
| POST /api/v1/messages/threads/ | Create Thread | Todo |  |  |
| POST /api/v1/messages/threads/{thread_id}/messages/ | Send Message | Todo |  |  |

---

## Tenancies

| Endpoint | Screen | Status | Owner | Blockers |
|-----------|--------|--------|--------|----------|
| GET /api/v1/tenancies/mine/ | My Tenancies | Todo |  |  |
| POST /api/v1/tenancies/propose/ | Propose Tenancy | Todo |  |  |

---
