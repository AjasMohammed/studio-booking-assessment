# Machine Task — "Studio"

---

## 1. The product

A backend for boutique fitness studios.

Studios sell credit packs. Members spend credits to book classes. Classes have a limited number of spots, cancellation rules, and a waitlist.

Build the booking core.

---

## 2. Timebox

Target effort: 6-8 hours. Deadline: 3 days.

Anything beyond the scope in §5 is not needed. If time runs short, prefer a smaller working scope over a larger incomplete one, and note what was left out.

---

## 3. Stack

Pick one:

- Django 5.x with DRF or Django Ninja
- FastAPI with SQLAlchemy 2.0 and Alembic

Python 3.13+. PostgreSQL 15+ or SQLite. Task queue and cache are your choice.

---

## 4. Business rules

1. A studio has a name, an IANA timezone, and a cancellation cutoff in hours (default 4).
2. A class is scheduled at a studio with a start time, a duration, a number of spots, and a cost in credits.
3. Staff grant a member a credit pack: a whole number of credits, a grant date, and an expiry date. There is no payment flow.
4. Credits are whole numbers.
5. Booking a class costs that class's credit cost. Where a member holds credits across several packs, the credits expiring soonest are spent first. Expired credits cannot be spent.
6. A class must never confirm more bookings than it has spots. This holds regardless of how or when requests arrive.
7. Cancelling at or before the cutoff returns the credits in full. Cancelling after the cutoff forfeits them.
8. The cutoff is measured against the studio's local time, not the server's.
9. When a class is full, members may join a waitlist. When a confirmed spot is released, the longest-waiting member who can still afford the class takes it and is charged. Members who cannot currently afford it keep their place in line.
10. For any member, at any point in their history, it must be possible to show their balance and account for every credit that moved into or out of it.
11. Clients retry on network failure. A booking request carrying an `Idempotency-Key` header that has already been processed must not produce a second booking.
12. A member may only read and act on their own bookings and credits.
13. A booking can be cancelled once. A repeated cancellation must not return credits a second time.

Where a rule is unspecified, choose an approach and record it.

---

## 5. Scope

**Studios** — create a studio and configure its name, timezone, and cancellation cutoff.

**Classes** — schedule a class under a studio. Browse classes across a date range, each showing the spots still available.

**Access** — authenticate a caller. Distinguish staff from members. Enforce that members reach only their own data.

**Credit packs** — staff grant a pack to a member. A member may hold several packs at once with different expiry dates.

**Credits** — report a member's current balance and which packs make it up, with expiry dates. Report every movement into and out of the balance with its cause. Reconstruct the balance as it stood at a past moment.

**Booking** — book a spot on a class. List a member's bookings.

**Cancellation** — cancel a booking, release the spot, and settle the credits according to the cutoff.

**Waitlist** — join a full class's waitlist, and leave it. List a member's waitlist entries. Promote from the waitlist when a spot is released.

Design the API surface yourself.

Not required: payments, notifications or email, attendance and no-show tracking, instructors, recurring schedules, cash refunds, or a frontend.

---

## 6. Engineering requirements

- SOLID and DRY. Use design patterns where they earn their place, and document which and why.
- Automated tests.
- Strict type checking and a linter, both clean, both configured in the repo.
- On a clean machine with Docker: one command to bring the stack up, one to run the tests.
- Dependencies pinned. CI running lint, types, and tests.
- Incremental commits with meaningful messages.
- Use the framework's own capabilities rather than working around them.

---

## 7. Deliverables

| | |
|---|---|
| `README.md` | Setup, architecture, a walkthrough of the main flow, how to run tests and linters. |
| API collection | Postman Collection or Generated OpenAPI spec. Should run end to end: authenticate, grant credits, book, fill the class, waitlist, cancel. |