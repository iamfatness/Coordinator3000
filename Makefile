.PHONY: install run dev db-init test docker-up docker-down fmt

install:
	pip install -r requirements.txt

# Create the LangGraph checkpoint tables in Postgres.
db-init:
	python -m scripts.init_db

# Run the API + background workers locally (reload for dev).
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000

test:
	python -m pytest -q

docker-up:
	docker compose up --build

docker-down:
	docker compose down
