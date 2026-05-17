# Pitch Tank two-process Docker stack: web (FastAPI) + worker (LiveKit Agent).
#
# NOTE: An older one-off container `sharktank-debug` may still be running
# and bound to port 8000. If `make up` fails with a port conflict, run
# `make clean-debug` first to stop and remove it.

.PHONY: up down logs rebuild restart shell clean-debug pre-up

pre-up: clean-debug

clean-debug:
	-docker rm -f sharktank-debug 2>/dev/null || true

up: clean-debug
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

rebuild:
	docker compose build --no-cache

restart:
	docker compose down && docker compose up -d

shell:
	docker compose exec web bash
