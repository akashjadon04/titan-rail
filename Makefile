.PHONY: test lint build run help

help:
	@echo "Titan Rail Engine Commands:"
	@echo "  make test   - Run full pytest test suite (83 test cases)"
	@echo "  make run    - Run FastAPI development server on port 8000"
	@echo "  make build  - Build Docker container"

test:
	pytest

run:
	uvicorn titan_rail.app:create_app --factory --reload --port 8000

build:
	docker compose build
