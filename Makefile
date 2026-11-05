.PHONY: build serve preview new clean

# Newest day's output page, e.g. 2026-10-13.html (empty if no sources yet).
LATEST := $(notdir $(lastword $(sort $(wildcard records/*.md))))
LATEST_HTML := $(LATEST:.md=.html)

# Generate the static site into docs/ for local preview only.
# docs/ is git-ignored; on push, GitHub Actions rebuilds and deploys it.
build:
	python3 build.py

# Build, then preview locally (plain server; open any page yourself).
serve: build
	python3 -m http.server 8000 --directory docs

# Watch sources, auto-rebuild on save, auto-open + live-reload the newest day.
# The live-reload script is injected only in this --watch mode, never into the
# committed/CI docs/ output. Ctrl-C to stop.
preview:
	@( sleep 1; open "http://localhost:8000/$(LATEST_HTML)" ) &
	python3 build.py --watch

# Scaffold today's record file in records/ (no-op if it already exists).
new:
	python3 build.py --new

clean:
	rm -rf docs
