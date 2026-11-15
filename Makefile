# `make` alone only lists targets: `check` rewrites files, so it stays opt-in.
.DEFAULT_GOAL := help
.PHONY: help test check serve

PORT ?= 8000

help:
	@echo 'make test   run the unit tests'
	@echo 'make check  run every pre-commit hook on all tracked files (same as CI)'
	@echo 'make serve  preview public/ at http://127.0.0.1:$(PORT)'

test:
	python3 -m unittest discover -s tests -v

check:
	pre-commit run --all-files --show-diff-on-failure

# http.server ignores public/_headers, so security headers only appear on Cloudflare.
serve:
	python3 -m http.server $(PORT) --bind 127.0.0.1 --directory public
