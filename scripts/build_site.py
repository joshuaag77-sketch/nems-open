"""Assemble the public site into one folder Vercel can deploy: the static pages plus the hosted Ask function.

    python scripts/build_site.py              # writes dist/site/
    cd dist/site && vercel deploy             # a preview; production only with Josh's OK (docs/hosting.md)

The folder holds web/ (the pages), site/api/*.py and site/vercel.json, site/requirements.txt (anthropic and numpy,
nothing else), and the policy agent's own code under src/nems_open/agent with a two-line paths module. The repo's
pyproject.toml (pandas, linopy, HiGHS), EIA's inputs and the oracles never reach Vercel. No key is written anywhere:
the function reads ANTHROPIC_API_KEY from the Vercel project's environment.
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "real_build")
PATHS_SHIM = '''"""Hosted copy: only the repo root is needed (the agent reads web/data). EIA's checkout is not deployed."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
'''


def build(out: Path) -> Path:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "web", out / "web", ignore=SKIP)
    shutil.copytree(ROOT / "site" / "api", out / "api", ignore=SKIP)
    for name in ("vercel.json", "requirements.txt"):
        shutil.copy2(ROOT / "site" / name, out / name)
    pkg = out / "src" / "nems_open"
    shutil.copytree(ROOT / "src" / "nems_open" / "agent", pkg / "agent", ignore=SKIP)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "paths.py").write_text(PATHS_SHIM, encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "dist" / "site")
    out = build(ap.parse_args(argv).out)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"{out}: {size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
