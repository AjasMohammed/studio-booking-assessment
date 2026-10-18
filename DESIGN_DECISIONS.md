# Design Decisions

These decisions describe the current assessment implementation.

## Access

- Users have a `staff` or `member` role, separate from Django admin permissions.
- Public staff signup is intentional so assessment reviewers can test both roles.
- Staff manage all studios. Members can browse all classes, but spend credits
  only at the studio that granted them.
- Private bookings, waitlists, and credits are selected using the logged-in user.
- JWT refresh tokens rotate; the previous refresh token is blacklisted.

## Credits

- Each grant creates a separate pack so its expiry is preserved.
- Bookings spend the earliest-expiring eligible credits first; pack ID breaks ties.
- `credits_remaining` supports current spending. Signed movements record grants,
  charges, and refunds and reconstruct past balances using `effective_at`.
- Expired packs cannot fund bookings. History calculates expiry events without
  changing stored balances or writing extra rows.
- Refunds return to the original packs. Refunded credits remain unavailable if
  those packs have expired.

## Bookings and waitlists

- Bookings capture their price and cancellation deadline when created.
- The cutoff uses the studio's local timezone. Ambiguous DST deadlines use the
  first occurrence; nonexistent deadlines shift forward. Zero cutoff means the
  exact class start.
- Cancellation at or before the deadline refunds credits; later cancellation
  forfeits them. Repeat cancellation cannot refund again.
- Cancelled bookings and withdrawn waitlist entries remain as history.
- A successful direct booking withdraws any active waitlist entry for that class
  in the same transaction, preventing rebooking after a later cancellation.
- Cancellation promotes the earliest waiting member who can afford the class.
  Unaffordable members keep their place. Promotion runs within the cancellation
  transaction, without a background worker.

## Retries and consistency

- Booking keys belong to a member. Reusing a successful key for the same class
  returns the original response; using it for another class returns HTTP 409.
- Failed attempts do not save a success record. New keys cannot create duplicate
  confirmed bookings for the same member/class.
- Replay returns the original response even after cancellation. Booking history
  shows the current state.
- Transactions group related writes. Row locks coordinate concurrent requests;
  database constraints restrict duplicate active records and invalid states.
- Direct booking locks the member, class, and packs. Promotion locks the class,
  waiting entries, and packs, so there is no single lock order across all paths.

## Code structure

- Django ORM handles persistence; serializers handle API validation and output.
- Views handle HTTP, permission classes handle access, and services handle
  business writes and transactions.
- Selectors contain balance queries. Shared types, validators, and exceptions
  have dedicated modules. No extra repository abstraction is needed.
- PostgreSQL is used to verify row locking. Docker uses Django's development
  server for the assessment, with secrets supplied at runtime.

## Known issues still deferred

1. Promotions across different classes sharing credit packs can deadlock.
2. Extremely large cutoffs can overflow datetime arithmetic and return an error.

These issues remain unresolved; passing tests do not establish full correctness.
