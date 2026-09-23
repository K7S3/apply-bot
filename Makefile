# candid Docker helpers (POSIX make compatible).
#
#   make docker-build                 build the candid:local image
#   make docker-shell                 open a shell inside the candid container
#   make docker-run CMD="..."         run any CLI command, e.g.
#                                     make docker-run CMD="match --jd jd.txt"
#                                     make docker-run CMD="onboard"
#   make docker-dashboard             run the web dashboard on :8765
#   make docker-dev                   run the dashboard with live code reload
#                                     (bind-mounts the repo over /app)
#   make docker-clean                 stop containers and delete the data volume

IMAGE ?= candid:local

.PHONY: docker-build docker-shell docker-run docker-dashboard docker-dev docker-clean

docker-build:
	docker compose build

docker-shell:
	docker compose run --rm candid /bin/sh

docker-run:
	docker compose run --rm candid $(CMD)

docker-dashboard:
	docker compose up dashboard

docker-dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up dashboard

docker-clean:
	docker compose down -v
