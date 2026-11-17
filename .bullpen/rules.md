# Rules for this repository

## Show visible changes in the pull request

A change is visible when it alters something a person looks at: the overview
panel or any other UI, or log output an operator reads.

- **Visible change:** put before/after screenshots in the PR description. Take
  "before" from the base branch and "after" from the task's branch. If a true
  "before" cannot be produced (the thing did not exist, for example), one
  screenshot of the new behaviour is enough.
- **Nothing visible** (CI, refactors, internal behaviour): say so in one line
  in the summary. Do not take screenshots.

Get the screenshots from the integration setup: `make integration` starts the
fixture SearXNG instance from `compose.test.yml` with the local fixture
provider and drives it with Playwright. `docs/development.md` ("Integration
tests") has the setup steps; run `make integration-down` when finished.

Render the images outside the repository and attach them to the pull request:

```sh
gh pr edit <n> --attach '<file>#<alt text>'
```

Never commit images or push asset branches for this.
