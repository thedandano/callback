.PHONY: install build check test-unit test-integration fmt lint type clean

ifdef INSTALL_DIR
INSTALL_PREFIX := UV_TOOL_BIN_DIR=$(INSTALL_DIR)
endif

install:
	$(INSTALL_PREFIX) uv tool install --force .
	@command -v pi-apply >/dev/null 2>&1 && command -v pi-apply || true

build:
	uv build

check: fmt lint type test-unit

test-unit:
	uv run pytest tests/ -m "not integration"

test-integration:
	uv run pytest tests/ -m integration

fmt:
	uv run ruff format .

lint:
	uv run ruff check .

type:
	uv run pyright

clean:
	rm -rf dist .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf '{}' +
