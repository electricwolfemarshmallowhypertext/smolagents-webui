# Release checklist

- Confirm the repo is clean with `git status --short`.
- Install verification tooling with `pip install -r constraints-dev.txt`.
- Run `node --check src/smolagents_webui/static/app.js`.
- Run `python -m py_compile src/smolagents_webui/server.py src/smolagents_webui/runner.py src/smolagents_webui/model_factory.py src/smolagents_webui/store.py src/smolagents_webui/workspace.py src/smolagents_webui/serialization.py`.
- Run `python -m pytest tests/webui -q --noconftest -p no:cacheprovider`.
- Run `python -m build`.
- Inspect the wheel and sdist.
- Verify no upstream `smolagents` source is bundled.
- Verify `docs/source` is absent from the sdist.
- Verify `NOTICE` is included.
- Tag the release.
- Push the tag.
- Draft a GitHub release.
- Attach the wheel and tarball.
