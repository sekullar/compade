# Compade

**Compade** = *Company* + *ADE* (Agentic Development Environment). A Windows desktop app where one chief agent
(Claude Code) runs a team of coding agents the way a small company would: it plans the work, hands each task to the
right role, checks the result and decides what happens next. The workers are the coding CLIs you already have:
**Codex CLI**, **OpenCode** (including its free models) and **Antigravity / Gemini CLI**. The aim is to get real work
done while spending as few of the chief's (Claude's) tokens as possible.

[Türkçe README](README.tr.md)

## Features

- **Chief chat (Office).** Talk to the chief like in Claude Code. It answers, asks questions, or writes a plan
  (tasks, roles, dependencies, difficulty) that you approve or let it run automatically.
- **Decision loop.** After every task the chief reads the worker's report and decides: accept, retry with a
  correction, give it to another role, ask you, or stop. Retries are capped.
- **Safe writes with git worktrees.** In a git project, every writing task runs on its own branch in
  `~/.compade/worktrees/`. Your folder is not touched until you approve. After each task the project's tests run
  automatically (pytest, unittest, npm test, cargo, go, or your own command). Failing work is not merged.
- **Changes card.** See every changed file with a colored diff, then apply the selected files, apply all, or discard.
- **Smart model routing.** Each task gets a difficulty. A policy (saver / balanced / quality) maps it to a cheap,
  mid or strong model from the role's own list, plus a reasoning level for Codex and Claude. A retry moves up a tier.
  Writing tasks never go to a free model when the role has another option.
- **Roles and team.** Define roles (backend, QA, design...) with their own model lists, or let the chief design a
  team for a project. A model can be pinned per role.
- **Multiple accounts.** Several Codex accounts (one `CODEX_HOME` each) and several Antigravity logins. When an
  account hits its limit, the job moves to the next account or to a fallback provider.
- **Costs page.** Real token counts from each provider, the chief's cost in API-equivalent dollars, daily chart,
  and per-model and per-role tables with success rates.
- **Project memory.** A `COMPADE.md` file in the project root is added to every worker's prompt.
- **Quality of life.** Chat history, message queue while the chief is busy, task templates, desktop notifications
  when the window is in the background, light/dark themes.
- **Updates.** Compade checks GitHub Releases and shows an **Update** button in the status bar
  (see [Updates](#updates)).

## Requirements

- Windows 10 or 11.
- Microsoft Edge (Compade opens its window as an Edge app window; any browser works with `compade web --no-window`).
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) for the chief, signed in.
- At least one worker CLI: [Codex CLI](https://github.com/openai/codex), [OpenCode](https://opencode.ai), or
  Antigravity (`agy`).
- Git, for isolated writes (without git, Compade can still plan and run read-only tasks).

## Install

**Installer:** download `Compade-Setup-<version>.exe` from the [latest release](../../releases/latest) and run it.
It installs per user into `%LOCALAPPDATA%\Programs\Compade` (no admin rights). The installer is not code-signed, so
Windows SmartScreen may ask you to confirm ("More info" → "Run anyway").

**Sentinel Hub:** Compade is also in the [Sentinel Hub](https://github.com/sekullar/sentinel-hub) catalog, which
installs, updates and launches it for you.

**From source** (Python 3.13, standard library only):

```bash
git clone https://github.com/sekullar/compade.git
cd compade
python -m compade                 # opens the app
python -m compade web --no-window --port 8778   # server only, open http://127.0.0.1:8778 yourself
```

## Updates

Compade compares its version with the latest GitHub Release (checked at start and every 6 hours; click the version
in the status bar to check now). What the **Update** button does depends on how it was installed:

| Installed with | Update |
| --- | --- |
| Compade installer | Downloads the new installer from this repo's Releases, installs it silently and reopens Compade. |
| Sentinel Hub | The Hub shows its own green **Update** button and does the update. |
| Source checkout | Opens the release page; update with `git pull`. |

Your data in `~/.compade` (accounts, chats, history) is never touched by updates or by uninstalling.

## Data

Everything lives in `~/.compade/` (set `COMPADE_HOME` to move it): `config.json`, `roles.json`, `ledger.jsonl`
(every run with tokens and timing), `runs/`, `chats/`, `accounts/`, `worktrees/`.
Login tokens of the CLIs are never read into Compade's logs or UI; only the account e-mail and plan are shown.

## Command line

```bash
python -m compade run --task task.md --model codex [--role backend] [--write] [--verify "npm test"]
python -m compade accounts        # accounts and limit status
python -m compade ledger          # per-model history
python -m compade ram             # memory use
python -m unittest discover -s tests
```

## Building and releasing (maintainer notes)

```bash
pip install pyinstaller
python packaging/build.py   # dist/Compade/Compade.exe and dist/Compade-Setup-<version>.exe (needs NSIS)
```

To release: bump `__version__` in `compade/__init__.py`, commit, then push a matching tag:

```bash
git tag v0.1.1 && git push origin v0.1.1
```

GitHub Actions builds the installer and publishes the release. Installed copies and Sentinel Hub see it on their next
check.

## Known limits

- Not yet tested end to end with real models on a large project; the test suite uses fake agents.
- Limit messages of Codex and Antigravity are matched with generic patterns until real ones are seen.
- Using several accounts to get around provider limits may break a provider's terms of service. That is your
  responsibility.

## License

MIT
