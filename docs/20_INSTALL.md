# Install

Spatial Field Engine targets Python 3.10+ and runs locally.

## Prerequisites

- Python 3.10+
- Git
- Aider for normal `workspace_write` runs

`make install` can offer to install Aider after confirmation. To install it
yourself:

```bash
pipx install aider-chat
aider --version
```

If `pipx` is missing, install it first:

```bash
python -m pip install --user pipx
python -m pipx ensurepath
exec $SHELL -l
```

## Install SFE

```bash
git clone https://github.com/Patrice-Gaudicheau/sfe.git
cd sfe
make install
make doctor
make sfe-tui
```

`make install`:

- checks for Python 3.10+;
- creates `.venv` only when it does not already exist;
- installs SFE with `pip install -e .`;
- checks whether Git is available;
- creates `.env` from `.env.example` when `.env` does not exist;
- never overwrites an existing `.env`;
- checks whether Aider is available.

The installer does not silently run global package-manager commands. If Aider
is missing, it explains that Aider is required for normal `workspace_write`
runs, offers `pipx install aider-chat`, and continues if you decline. If `pipx`
is missing, it recommends `python -m pip install --user pipx` and asks before
running it. Existing Aider installs are not upgraded unless you confirm
interactively or set `SFE_INSTALL_ALLOW_UPDATES=1`.

If virtual environment creation fails because `python3-venv` is missing, the
installer prints a Debian/Ubuntu command suggestion and asks before any `apt`
command is attempted.

`make doctor` checks the local setup and reports missing pieces without
changing files. Makefile targets use the project virtualenv automatically.

## Manual Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Use this if you want to manage all prerequisites yourself.

Activating `.venv` is optional when you use the Makefile targets. Use it only
when running Python commands directly.

## Installer Options

- `SFE_INSTALL_SKIP_AIDER=1 make install`: install only the Python package.
- `SFE_INSTALL_DRY_RUN=1 make install`: print commands without running them.
- `SFE_INSTALL_ASSUME_YES=1 make install`: auto-confirm local prerequisite
  recovery prompts such as `python3-venv`.
- `SFE_INSTALL_AIDER=1 make install`: install Aider with `pipx` without an
  interactive prompt.
- `SFE_INSTALL_PIPX=1 make install`: install `pipx` with
  `python -m pip install --user pipx` without an interactive prompt.
- `SFE_INSTALL_VENV_DIR=.venv-local make install`: use another local venv path.

Use opt-in variables only in environments where those external install actions
are expected.
