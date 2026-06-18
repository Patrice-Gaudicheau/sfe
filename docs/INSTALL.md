# Install

Spatial Field Engine targets Python 3.10+ and runs locally.

## Prerequisites

- Python 3.10+
- Git
- Aider for normal `workspace_write` runs

Install Aider separately:

```bash
pipx install aider-chat
aider --version
```

On Debian, Ubuntu, or WSL, install `pipx` first if needed:

```bash
sudo apt install pipx
pipx ensurepath
exec $SHELL -l
```

## Install SFE

```bash
git clone git@github.com:Patrice-Gaudicheau/sfe.git
cd sfe
make install
source .venv/bin/activate
```

`make install`:

- checks for Python 3.10+;
- creates `.venv` only when it does not already exist;
- installs SFE with `pip install -e .`;
- checks whether Aider is available.

The installer does not silently run global package-manager commands. If Python
support packages, `pipx`, or Aider are missing, it prints guidance and asks
before running external install commands. Existing Aider installs are not
upgraded unless you confirm interactively or set `SFE_INSTALL_ALLOW_UPDATES=1`.

## Manual Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Use this if you want to manage all prerequisites yourself.

## Installer Options

- `SFE_INSTALL_SKIP_AIDER=1 make install`: install only the Python package.
- `SFE_INSTALL_DRY_RUN=1 make install`: print commands without running them.
- `SFE_INSTALL_ASSUME_YES=1 make install`: auto-confirm installer prompts.
- `SFE_INSTALL_VENV_DIR=.venv-local make install`: use another local venv path.

Use auto-confirmation only in environments where external install actions are
expected.
