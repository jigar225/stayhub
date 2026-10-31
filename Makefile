SHELL := /bin/sh
DC := docker compose
.PHONY: dev-up dev-down migrate provision lint format-check typecheck test build smoke-auth restart-check

dev-up:
	$(DC) up -d --build --wait

# Does not remove the persistent Postgres volume.
dev-down:
	$(DC) down

migrate:
	$(DC) exec -T api uv run --frozen alembic upgrade head

provision: storage-init
	$(DC) exec -T api uv run --frozen -e PROVISION_MANIFEST=/demo-content/provision.json python -m app.provision_users

lint:
	$(DC) exec -T api uv run --frozen ruff check .
	$(DC) exec -T frontend npm run lint

format-check:
	$(DC) exec -T api uv run --frozen ruff format --check .
	$(DC) exec -T frontend npm run format-check

typecheck:
	$(DC) exec -T api uv run --frozen mypy app tests
	$(DC) exec -T frontend npm run typecheck

test:
	$(DC) --profile test up -d --wait test-db
	$(DC) exec -T api uv run --frozen pytest
	$(DC) exec -T frontend npm test

build:
	$(DC) exec -T frontend npm run build
	$(DC) exec -T api uv run --frozen python -c "from app.main import app; assert app.openapi()['paths']; print('Backend imports/configuration/OpenAPI validated')"

smoke-auth:
	npm --prefix frontend run smoke-auth

restart-check:
	python3 scripts/restart-check.py

.PHONY: storage-init storage-cleanup smoke-listings persistence-listings
storage-init:
	$(DC) exec -T api uv run --frozen python -m app.storage_setup

storage-cleanup:
	$(DC) exec -T api uv run --frozen python -m app.storage_cleanup --dry-run

smoke-listings:
	npm --prefix frontend run smoke-listings

persistence-listings:
	python3 scripts/listings-persistence.py

.PHONY: download-demo-assets smoke-discovery
download-demo-assets:
	python3 scripts/download-demo-assets.py

smoke-discovery:
	npm --prefix frontend run smoke-discovery

.PHONY: smoke-booking expire-requests persistence-booking
smoke-booking:
	npm --prefix frontend run smoke-booking

expire-requests:
	$(DC) exec -T api uv run --frozen python -m app.expire_requests --batch-size 100

persistence-booking:
	python3 scripts/booking-persistence.py

.PHONY: sweep smoke-cancellation-payout review-up review-migrate review-seed persistence-financial
sweep:
	$(DC) exec -T api uv run --frozen python -m app.sweep --batch-size 100

smoke-cancellation-payout:
	SMOKE_BASE_URL=http://localhost:5183 npm --prefix frontend run smoke-cancellation-payout

review-up:
	docker compose -p stayhub-m5-review -f compose.yaml -f compose.m5-review.yaml up -d --build --wait

review-migrate:
	docker compose -p stayhub-m5-review -f compose.yaml -f compose.m5-review.yaml exec -T api uv run --frozen alembic upgrade head

review-seed:
	docker compose -p stayhub-m5-review -f compose.yaml -f compose.m5-review.yaml exec -T api uv run --frozen python -m app.storage_setup
	docker compose -p stayhub-m5-review -f compose.yaml -f compose.m5-review.yaml exec -T api uv run --frozen -e PROVISION_MANIFEST=/demo-content/provision.json python -m app.provision_users

persistence-financial:
	python3 scripts/m5-persistence.py
