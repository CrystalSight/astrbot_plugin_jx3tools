# AstrBot plugin instructions

- Use the global `$astrbot-plugin-dev` Skill for every implementation, review, debugging, test, compatibility, or release task.
- Treat `SPEC.md` as the feature contract. Update acceptance criteria before non-trivial behavior changes.
- Limit changes to this plugin unless the user explicitly authorizes AstrBot core changes.
- Use Chinese for requirements and collaboration. Use English for identifiers, comments, docstrings, logs, and commits.
- Target Python 3.12+ and the `astrbot_version` declared in `metadata.yaml`.
- Run `ruff check .`, `pyright`, and `pytest` before handoff. Run matching-version Docker validation for event, provider, storage, Pages, dependency, and lifecycle changes.
- Ask before adding runtime dependencies, migrating/deleting data, pushing commits, or publishing.
- Never commit credentials or persist user data in the plugin source directory.
