.PHONY: install build check test-unit test-integration fmt lint type clean

BUILD_VERSION ?= $(shell scripts/build-version.sh)

ifdef INSTALL_DIR
INSTALL_PREFIX := UV_TOOL_BIN_DIR=$(INSTALL_DIR)
endif

install:
	@printf 'Build version: %s\n' '$(BUILD_VERSION)'
	rm -rf build
	PI_APPLY_BUILD_VERSION="$(BUILD_VERSION)" $(INSTALL_PREFIX) uv tool install \
		--force --reinstall-package pi-apply --refresh-package pi-apply .
	@command -v pi-apply >/dev/null 2>&1 && command -v pi-apply || true

build:
	@printf 'Build version: %s\n' '$(BUILD_VERSION)'
	PI_APPLY_BUILD_VERSION="$(BUILD_VERSION)" uv build

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
	rm -rf build dist .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf '{}' +
