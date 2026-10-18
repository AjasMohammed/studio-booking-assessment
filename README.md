# Studio

## Run with Docker

Install Docker Engine with the Compose plugin (or Docker Desktop). On first setup,
copy the example environment file and adjust its values as needed:

```bash
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
