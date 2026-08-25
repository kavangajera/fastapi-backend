# Smoke tests

End-to-end tests for the delete/inventory/validation/audit work and the
temperature device flow. They run against a **throwaway MySQL in Docker** —
never your real database.

## Run

```bash
docker run -d --name queuerx-mysql \
  -e MYSQL_ROOT_PASSWORD=queuerx_test_pw -e MYSQL_DATABASE=queuerx_test \
  -p 3307:3306 mysql:8.0 \
  --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci

export DATABASE_URL="mysql+asyncmy://root:queuerx_test_pw@127.0.0.1:3307/queuerx_test"
uv run alembic upgrade head
uv run uvicorn main:app --host 127.0.0.1 --port 5099 &

CREDS=$(uv run python smoketest/seed.py)
OWNER=$(echo "$CREDS" | grep OWNER_TOKEN | cut -d= -f2)
TECH=$(echo "$CREDS" | grep TECH_TOKEN | cut -d= -f2)
uv run python smoketest/smoke.py  "$OWNER" "$TECH" 1   # 39 checks
uv run python smoketest/smoke2.py "$OWNER" 1           # 35 checks
```

Teardown: `docker rm -f queuerx-mysql`

## Note

`seed.py` prints JWTs signed with the SECRET_KEY from your `.env`. Keep them
out of version control — do not redirect its output into a file in the repo.
`seed.py` TRUNCATEs every domain table, so only ever point it at the test DB.
