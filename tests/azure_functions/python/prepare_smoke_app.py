"""Stage a fixture as a normal consumer app in a disposable pipeline checkout.

Never overwrite application files. Local tests pass a temporary destination;
the build-only pipeline uses its fresh checkout root.
"""
from pathlib import Path
import shutil
import sys

FIXTURE = Path(__file__).parent / "fixtures" / "function_app"
RUNTIME_REQUIREMENTS = Path(__file__).resolve().parents[3] / "requirements/azure-functions/python/smoke-runtime.txt"
APP_PATHS = ("src", "function_app.py", "host.json", "requirements.txt")


def prepare(destination):
    destination = Path(destination)
    for name in APP_PATHS:
        if (destination / name).exists():
            raise FileExistsError(f"Refusing to overwrite {destination / name}")
    destination.mkdir(parents=True, exist_ok=True)
    for name in APP_PATHS:
        source = RUNTIME_REQUIREMENTS if name == "requirements.txt" else FIXTURE / name
        if source.is_dir():
            shutil.copytree(source, destination / name, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(source, destination / name)


if __name__ == "__main__":
    prepare(sys.argv[1])
