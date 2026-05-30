# Cloudflare Worker build helpers.
#
# Wrangler bundles whatever is under src/. The algorithm + matching +
# parsing live at the repo root (so the CLI scripts share them); this
# Makefile copies the latest versions into src/ before each deploy so
# the worker and the CLI never drift.

SHARED := hc_algorithm.py hc_matching.py hc_parsing.py

.PHONY: shared dev deploy clean

shared:
	@for f in $(SHARED); do \
	  cp ../$$f src/$$f; \
	done
	@echo "synced: $(SHARED)"

dev: shared
	wrangler dev

deploy: shared
	wrangler deploy

clean:
	@for f in $(SHARED); do \
	  rm -f src/$$f; \
	done
