# One way to run it, and only one.
.PHONY: help tendance check clean

PY := python3

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

tendance: ## Reproduce the trend figures for both gates (clones the pinned ATLAS sources if needed)
	$(PY) tendance.py

check: ## Run the tests, including the solver validation
	$(PY) -m pytest -q tests/

clean: ## Remove derived output (never the pinned data)
	rm -rf out
