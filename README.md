# Studio

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
