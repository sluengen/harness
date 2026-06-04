# Harness Bootstrap

Sets up the harness in an existing repo. Run once; commit the symlinks.

## Prerequisites

- git
- One of: Docker, or Python 3.11+ with `pip`

## 1. Clone harness

```bash
git clone git@github.com:sluengen/harness.git .harness
echo '.harness/' >> .gitignore
```

## 2. Create symlinks

Run from your repo root. Creates `h-` prefixed entries in `agents/`, `skills/`, and `commands/` pointing into `.harness/`.

```bash
# Agents
ln -s ../.harness/agents/python-dev.md agents/h-python-dev.md
ln -s ../.harness/agents/reviewer.md agents/h-reviewer.md

# Commands
ln -s ../.harness/commands/build-workflow.md commands/h-build-workflow.md
ln -s ../.harness/commands/start.md commands/h-start.md

# Skills
ln -s ../.harness/skills/code-review.md skills/h-code-review.md
ln -s ../.harness/skills/scope-discipline.md skills/h-scope-discipline.md
ln -s ../.harness/skills/test-driven-development.md skills/h-test-driven-development.md
ln -s ../.harness/skills/verification-before-completion.md skills/h-verification-before-completion.md
ln -s ../.harness/skills/workflow-author-ergonomics.md skills/h-workflow-author-ergonomics.md
ln -s ../.harness/skills/workflow-authoring.md skills/h-workflow-authoring.md
ln -s ../.harness/skills/worktree-isolation.md skills/h-worktree-isolation.md
```

Commit the symlinks — they're the only harness artifact that lives in your repo:

```bash
git add agents/h-* skills/h-* commands/h-*
git commit -m "chore: add harness agent layer"
```

## 3. Environment

Create a `.env` in your repo root (add it to `.gitignore`):

```bash
export ANTHROPIC_API_KEY=     # required — Claude dispatch
export LINEAR_API_KEY=        # required — Linear integration
```

## 4. Run

### Docker (recommended)

Prompts and runtime are baked into the image. Build it once from the cloned harness source:

```bash
docker build -t harness:local -f .harness/docker/Dockerfile .harness
```

Then run any workflow, mounting your repo at `/workspace`:

```bash
source .env && docker run --rm \
  -v "$(pwd)":/workspace -w /workspace \
  -e ANTHROPIC_API_KEY -e LINEAR_API_KEY \
  harness:local run <workflow-file> [--key=value ...]
```

### Direct (Python 3.11+)

```bash
pip install git+ssh://git@github.com/sluengen/harness.git
source .env && harness run <workflow-file> [--key=value ...]
```

## 5. Workflows

Place your workflow YAML files in `workflows/`. Reference examples at `.harness/workflows/`, or use the `h-build-workflow` command to generate one from a description.

## Updating

### Pin to a release tag (recommended)

```bash
git -C .harness fetch --tags
git -C .harness checkout v<X.Y.Z>
```

If you're using Docker, rebuild the image after every checkout:

```bash
docker build -t harness:local -f .harness/docker/Dockerfile .harness
```

If you're using the direct pip install, upgrade to the tag:

```bash
pip install --upgrade "git+ssh://git@github.com/sluengen/harness.git@v<X.Y.Z>"
```

### Track latest (rolling)

```bash
git -C .harness pull
```

Docker users still need to rebuild after pulling. Symlinks resolve automatically — no re-linking needed either way.
