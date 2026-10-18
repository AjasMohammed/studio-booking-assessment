# Studio

A Django REST API for boutique fitness studios. Staff configure studios, schedule
classes, and grant credit packs. Members spend studio-specific credits to book
classes, cancel bookings, and join waitlists. A cancellation can automatically
promote the first waiting member who can afford the class.

Built with Python 3.13, Django 5.2, Django REST Framework, Simple JWT, PostgreSQL 17,
and uv. Exact Python dependency versions are recorded in `uv.lock`. There is no
payment flow or frontend. See [the assessment](sde2_developer_task.md) and
[the recorded access decisions](DESIGN_DECISIONS.md).

## Run with Docker

Install Docker Engine with the Compose plugin (or Docker Desktop). On first setup,
copy the example environment file and adjust its values as needed:

```bash
git clone https://github.com/AjasMohammed/studio-booking-assessment.git
cd studio-booking-assessment
cp .env.example .env
```

Keep `DATABASE_URL` credentials and database name aligned with `DB_USER`,
`DB_PASSWORD`, and `DB_NAME`. Existing `.env` files can be kept.

Start Django and PostgreSQL with one command; no host Python installation is needed:

```bash
docker compose up --build -d --wait
```

The API is available at `http://localhost:8000`. The app waits for PostgreSQL to
be healthy, applies migrations, then starts Django. Inside Docker, `DB_HOST=db`
and `DB_PORT=5432` override the host connection address in `DATABASE_URL`.
Host development continues using PostgreSQL at `localhost:5423`.

Check status and logs:

```bash
docker compose ps
docker compose logs app
```

Stop the stack with `docker compose down`. Database data remains in the named
volume and survives container recreation. Run the startup command again after
changing application code to rebuild the image.

This setup uses Django’s development server for the assessment. Secrets are
provided at runtime through `.env`; `.env`, Git metadata, local caches, and
`docs/` are excluded from the Docker build context.

## Optional host development

With Python 3.13 and uv installed, use the same `.env` setup and run:

```bash
docker compose up -d db
uv sync --frozen
uv run --frozen python manage.py migrate
uv run --frozen python manage.py runserver
```

The host process uses `DATABASE_URL` at `localhost:5423`. Stop the Docker `app`
service first if it is already using port 8000: `docker compose stop app`.

## Architecture and business rules

- [Accounts](apps/accounts/) contains the custom `User` model and JWT endpoints.
  Application roles (`staff` and `member`) are separate from Django admin flags.
  Protected endpoints require authentication; staff permissions guard studio
  administration and credit grants. Member queries use the authenticated user.
- [Studio models](apps/studios/models/) define `Studio`, `ClassSessions`,
  `CreditPack`, and `CreditMovement`. A pack belongs to one member and one studio.
  Each grant creates a separate pack with its own expiry. `credits_remaining`
  supports current spending; signed movements preserve accounting history.
- [Booking models](apps/bookings/models.py) define `Booking`, `WaitlistEntry`,
  and `IdempotencyRecord`. A booking captures its charged cost and cancellation
  deadline. Cancelled bookings and past waitlist attempts remain as history.
  Database constraints restrict duplicate active bookings/entries and invalid
  lifecycle states.
- Serializers validate and represent API data; views handle HTTP and permissions.
  [Booking services](apps/bookings/services.py) implement atomic booking,
  cancellation, and waitlist changes. Row locks coordinate capacity and credit
  updates. A failed transaction rolls back its writes, including cancellation
  refunds and promotions. The cross-class locking limitation is recorded below.
- [Credit services](apps/studios/services.py) atomically grant packs and build
  credit history. [Selectors](apps/studios/selectors.py) build balance queries;
  validators and custom types have dedicated modules. This keeps business writes,
  read queries, validation, and HTTP handling separate without adding a repository
  abstraction over Django's ORM.

Credits are spent in expiry order, with pack ID breaking ties. A pack is usable
from its grant timestamp up to, but excluding, its expiry. Historical balances
are reconstructed from effective movement timestamps. History includes calculated
expiry events; a refund into an expired pack receives a matching expiry event and
never becomes spendable again. Calculated events have null database IDs and are
not stored or deducted a second time.

Cancellation at or before the captured deadline refunds the original allocations;
a later cancellation forfeits them. The deadline subtracts cutoff hours in the
studio's IANA timezone, then converts to UTC. For DST transitions, ambiguous
local deadlines use the first occurrence; nonexistent deadlines shift forward by
the gap. A zero-hour cutoff uses the exact class start instant.

Waitlists use join time, then entry ID, as their order. When a cancellation frees
a seat before class start, promotion charges an affordable waiting member and
links the new booking to the entry. Unaffordable members remain waiting in their
original position. No background worker is required; promotion runs within the
cancellation transaction.

## Authentication and access

- `POST /accounts/auth/signup` accepts `username`, `email`, `password`, and an
  optional `role`. Omitting the role creates a member.
- `POST /accounts/auth/login` accepts `username` and `password`, returning
  `access` and `refresh` JWTs.
- Protected requests use `Authorization: Bearer <access-token>`.
- `POST /accounts/auth/refresh` accepts `{"refresh":"<refresh-token>"}` and returns
  a new access token and rotated refresh token. Store the replacement refresh
  token; its predecessor is blacklisted. Access tokens last 120 minutes; refresh
  tokens last one day.

Public staff signup is intentional for assessment review; it does not grant
Django admin access. Staff may administer all studios. Members are not enrolled
in specific studios and can browse classes across studios, but spending requires
credits for the class's studio. See [design decisions](DESIGN_DECISIONS.md).

## Main-flow walkthrough

Start the Docker stack first. These examples use **Bash, curl, and jq** and should
be run in order in the same shell. They create new demo accounts and records in
your application database. Names include a timestamp so the walkthrough can be
repeated. API paths have no trailing slash.

### 1. Create staff and member accounts, then authenticate

`api` is only a shell helper for these examples. Its arguments are method, path,
access token (empty for public endpoints), JSON body (empty for GET), and any
additional curl options. Failed HTTP responses cause curl to return an error.

```bash
BASE_URL="${BASE_URL:-http://localhost:8000}"
RUN_ID=$(date +%s)
DEMO_PASSWORD='DemoOnly!Cedar-473'

api() {
  local method=$1 path=$2 token=$3 payload=$4
  shift 4
  local args=(--fail-with-body --silent --show-error --request "$method" "$BASE_URL$path")
  if [[ -n "$token" ]]; then
    args+=(-H "Authorization: Bearer $token")
  fi
  if [[ -n "$payload" ]]; then
    args+=(-H 'Content-Type: application/json' --data "$payload")
  fi
  curl "${args[@]}" "$@"
}

for name in staff alice bob; do
  role=member
  [[ "$name" != staff ]] || role=staff
  api POST /accounts/auth/signup '' "$(jq -nc \
    --arg username "$name-$RUN_ID" --arg role "$role" \
    --arg password "$DEMO_PASSWORD" \
    '{username:$username,email:($username+"@example.com"),password:$password,role:$role}')"
  printf '\n'
done

login() {
  api POST /accounts/auth/login '' "$(jq -nc \
    --arg username "$1-$RUN_ID" --arg password "$DEMO_PASSWORD" \
    '{username:$username,password:$password}')"
}
STAFF_ACCESS=$(login staff | jq -er '.access')
ALICE_LOGIN=$(login alice)
ALICE_ACCESS=$(printf '%s' "$ALICE_LOGIN" | jq -er '.access')
ALICE_REFRESH=$(printf '%s' "$ALICE_LOGIN" | jq -er '.refresh')
BOB_ACCESS=$(login bob | jq -er '.access')

MEMBERS=$(api GET /accounts/members/list "$STAFF_ACCESS" '')
ALICE_ID=$(printf '%s' "$MEMBERS" | jq -er --arg u "alice-$RUN_ID" '.[] | select(.username==$u) | .id')
BOB_ID=$(printf '%s' "$MEMBERS" | jq -er --arg u "bob-$RUN_ID" '.[] | select(.username==$u) | .id')
```

### 2. Create a studio and a one-seat class

Dates are computed using Python inside the running container, so they stay in the
future without requiring Python on the host. Send ISO 8601 timestamps with `Z`
or an explicit UTC offset. The studio ID in the URL selects the class's studio.

```bash
CLASS_START=$(docker compose exec -T app python -c \
  'from datetime import UTC, datetime, timedelta; print((datetime.now(UTC)+timedelta(days=2)).isoformat())')
PACK_EXPIRY=$(docker compose exec -T app python -c \
  'from datetime import UTC, datetime, timedelta; print((datetime.now(UTC)+timedelta(days=30)).isoformat())')

STUDIO_ID=$(api POST /studio/create "$STAFF_ACCESS" "$(jq -nc \
  --arg name "Demo Studio $RUN_ID" \
  '{name:$name,timezone:"Asia/Kolkata",cancellation_cutoff_hours:4}')" | jq -er '.studio_id')
CLASS_ID=$(api POST "/studio/$STUDIO_ID/session/create" "$STAFF_ACCESS" "$(jq -nc \
  --arg starts_at "$CLASS_START" \
  '{starts_at:$starts_at,duration_minutes:60,capacity:1,credit_cost:3}')" | jq -er '.session_id')

CLASS_DATE=${CLASS_START%%T*}
api GET "/studio/classes?start_date=$CLASS_DATE&end_date=$CLASS_DATE" "$ALICE_ACCESS" '' | jq
```

Class browsing returns future classes with `no_of_seats_available`. Date filters
use UTC calendar dates; supply both `start_date` and `end_date` when filtering.

### 3. Grant each member five credits

`credits_remaining` is the grant request's credit amount. The server captures the
grant timestamp and authenticated staff user; every call creates a new pack.

```bash
for member_id in "$ALICE_ID" "$BOB_ID"; do
  api POST "/studio/$STUDIO_ID/credit/grant" "$STAFF_ACCESS" "$(jq -nc \
    --argjson member "$member_id" --arg expires_at "$PACK_EXPIRY" \
    '{member:$member,credits_remaining:5,expires_at:$expires_at}')" | jq
done

SNAPSHOT=$(docker compose exec -T app python -c \
  'from datetime import UTC, datetime; print(datetime.now(UTC).isoformat())')
api GET /studio/credit/balance "$ALICE_ACCESS" '' | jq
```

Alice and Bob each have a balance of five in this studio. `SNAPSHOT` records a
moment after the grants and before any booking.

### 4. Book the only seat and retry the same request

```bash
BOOKING_KEY="demo-alice-$RUN_ID"
BOOKING=$(api POST "/bookings/classes/$CLASS_ID/book" "$ALICE_ACCESS" '{}' \
  -H "Idempotency-Key: $BOOKING_KEY")
BOOKING_ID=$(printf '%s' "$BOOKING" | jq -er '.id')
printf '%s' "$BOOKING" | jq

api POST "/bookings/classes/$CLASS_ID/book" "$ALICE_ACCESS" '{}' \
  -H "Idempotency-Key: $BOOKING_KEY" | jq
api GET /studio/credit/balance "$ALICE_ACCESS" '' | jq
```

Both booking requests return the same booking ID with HTTP 201. Alice is charged
three credits once and has two left. The class is now full.

### 5. Join Bob to the waitlist, then cancel Alice's booking

```bash
api POST "/bookings/classes/$CLASS_ID/waitlist/join" "$BOB_ACCESS" '{}' | jq
api GET /bookings/waitlist/me "$BOB_ACCESS" '' | jq

api POST "/bookings/$BOOKING_ID/cancel" "$ALICE_ACCESS" '{}' | jq

api GET /bookings/me "$ALICE_ACCESS" '' | jq
api GET /bookings/me "$BOB_ACCESS" '' | jq
api GET /bookings/waitlist/me "$BOB_ACCESS" '' | jq
api GET /studio/credit/balance "$ALICE_ACCESS" '' | jq
api GET /studio/credit/balance "$BOB_ACCESS" '' | jq
```

Bob's entry first has status `waiting`. Alice cancels before the cutoff, so her
booking becomes `cancelled` and her balance returns to five. During that same
request Bob receives a confirmed booking, his entry becomes `promoted`, and his
balance falls to two. The class remains full.

A waiting member can instead leave with
`POST /bookings/classes/<class_id>/waitlist/withdraw`. This applies to waiting
entries; Bob cannot withdraw his already-promoted entry.

### 6. Inspect movements, reconstruct a past balance, and refresh a token

```bash
api GET /studio/credit/movements "$ALICE_ACCESS" '' | jq
api GET /studio/credit/movements "$BOB_ACCESS" '' | jq
api GET /studio/credit/balance "$ALICE_ACCESS" '' \
  --get --data-urlencode "at=$SNAPSHOT" | jq

REFRESHED=$(api POST /accounts/auth/refresh '' "$(jq -nc \
  --arg refresh "$ALICE_REFRESH" '{refresh:$refresh}')")
ALICE_ACCESS=$(printf '%s' "$REFRESHED" | jq -er '.access')
ALICE_REFRESH=$(printf '%s' "$REFRESHED" | jq -er '.refresh')
```

Alice's movements show +5 grant, -3 booking, and +3 refund. Bob's show +5 grant
and -3 booking. The historical balance at `SNAPSHOT` is five; future snapshots
are rejected. After a pack expires, the movement history also explains the
expired remainder. Current and historical balance responses group totals and
eligible packs by studio.

## Booking idempotency

Every direct booking request needs a nonblank `Idempotency-Key` of at most 255
characters. Generate a new key for a new booking attempt and reuse it when
retrying that same request after a network failure.

Keys are scoped to the authenticated member. Repeating a successful key for the
same class replays its original response and status without another booking or
charge. Reusing it for a different class returns HTTP 409. Failed booking
attempts do not save a success record, so the same key can be retried after the
cause is resolved. A different key does not allow a second confirmed booking for
the same member/class.

Replay returns the original response even after cancellation; use `GET
/bookings/me` for the current booking state. Cancellation can succeed only once;
a repeated cancellation returns HTTP 400 without refunding again.

## Known limitations

- Public staff signup and global staff access are intentional assessment
  decisions, described in [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md).
- Concurrent promotions across different classes sharing members' credit packs
  can deadlock. Broader locking changes and promotion-race coverage were deferred.
- A member booking directly can retain an existing waiting entry for that class.
  Resolving this stale entry automatically was deferred.
- Extremely large cancellation cutoffs can overflow deadline arithmetic and return
  a server error. Validation for that case was deferred.
- The Docker app uses Django's development server. Production serving and
  deployment are outside the current setup.

## Postman API collection

Import both files into Postman:

- [Studio collection](postman/Studio.postman_collection.json)
- [Studio local environment](postman/Studio.postman_environment.json)

Start the Docker stack, select **Studio local**, and keep `base_url` set to
`http://localhost:8000` (or change it to your server address). Open the collection
in **Runner**, select all five folders, and run them in their numbered order.
No account creation, token copying, or ID editing is needed beforehand.

The first request generates new demo usernames, a password, future class/expiry
dates, and idempotency keys. Login and response scripts fill the environment's
tokens and IDs. Each run creates application data: three accounts, one studio,
two classes, credit packs, bookings, and waitlist history. Re-running the complete
collection generates fresh names. To send a later request individually, first
run its preceding setup requests in that same selected environment.

The 46 requests demonstrate authentication and refresh rotation, staff access,
studio/class creation and browsing, grants, booking retries, waitlist withdrawal
and rejoining, cancellation/refunds, promotion, movements, historical balances,
and member ownership. Expected 400/401/403/404/409 responses are tested explicitly
and count as successful checks. The historical timestamp comes from the server's
grant movement to avoid client-clock assumptions. Run the Django suite separately
for concurrency, expiry, and other edge cases.

With Node.js and npm installed, the same collection can run from a terminal using
pinned Newman 6.2.1:

```bash
npm exec --yes --package=newman@6.2.1 -- newman run \
  postman/Studio.postman_collection.json \
  --environment postman/Studio.postman_environment.json --bail
```

For a different server, append `--env-var base_url=http://localhost:8001`.
Newman exits with a failure status if a request or assertion fails. The committed
environment has empty credentials and IDs; runtime values stay in Postman/Newman
unless explicitly exported. Keep exports containing tokens out of the repository.

## Run tests with Docker

After configuring `.env`, run the full suite with one command:

```bash
docker compose run --build --rm app python manage.py test --settings=config.test_settings --noinput
```

This builds the application image when needed, starts PostgreSQL if necessary,
waits for its health check, and runs tests in a temporary application container.
The command replaces the normal migration/server startup command, so the API
server does not need to be running. It does not publish the application port.

Tests use PostgreSQL, including the real transaction/concurrency tests. Django
creates and deletes the separate `test_studio_edge_cases` database; application
data remains in the database configured by `DATABASE_URL`. Reserve that test
name for tests and run only one suite at a time against the same database server.

The temporary application container is removed when the command finishes, and
its exit code reports success or failure. The PostgreSQL service remains running;
`docker compose down` stops the stack while preserving its named data volume.
The database user initialized by this Compose setup can create the test database.
An externally managed database user needs the PostgreSQL `CREATEDB` privilege.

## Strict type checking

Install the locked development dependencies:

```bash
uv sync --frozen
```

Configure `.env` using `.env.example` when setting up the project. The Django
typing plugin loads `config.settings`, so it needs the same environment variables
as the application. It does not need a running database for this project's checks.

Run strict type checking and linting from the repository root:

```bash
uv run --frozen mypy
uv run --frozen ruff check .
```

Mypy checks application code, Django configuration, and `manage.py` in strict mode,
using the Django and Django REST Framework plugins. Test modules and shared
fixtures are checked too; only generated migrations are excluded. Run the runtime
tests separately:

```bash
uv run --frozen python manage.py test --settings=config.test_settings --noinput
```

## Continuous integration

GitHub Actions runs `.github/workflows/ci.yml` on pushes and pull requests.
One Ubuntu job installs Python 3.13 and uv, verifies and installs `uv.lock`, then
runs Ruff, strict mypy, the migration-drift check, and the full PostgreSQL test
suite, including concurrency tests. A failed check fails the job.

The workflow starts its own PostgreSQL 17 service using disposable CI credentials.
It supplies Django configuration through environment variables and needs no
repository secrets or local `.env` file. Results appear in the repository's
**Actions** tab and as checks on pull requests.
