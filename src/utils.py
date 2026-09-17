from pathlib import Path

BASE = Path(__file__).resolve().parents[1]  # root repo

def static_init(cls):
    if getattr(cls, "static_init", None):
        cls.static_init()
    return cls

def get_yaml(name: str) -> str | None:
    # Check if there is a file with the given name and extension .yaml searching it in the following paths:
    # 1. Folder .parametrized-llm under the user's home directory
    # 2. BASE directory
    # 3. The current working directory
    paths = [
        Path.home() / ".parametrized-llm" / f"{name}.yaml",
        BASE / f"{name}.yaml",
        Path.cwd() / f"{name}.yaml",
    ]
    for path in paths:
        if path.exists():
            return str(path)
    return None

def get_yamls(path: str) -> list[str] | None:
    # Check if there are files with extension .yaml searching them in a subfolder named path under the following locations, then return a list of their paths:
    # 1. The user's home directory
    # 2. BASE directory
    # 3. The current working directory
    paths = [
        Path.home() / ".parametrized-llm" / path,
        BASE / path,
        Path.cwd() / path,
    ]

    for p in paths:
        if p.exists() and p.is_dir() and any(p.glob("*.yaml")):
            return [str(f) for f in p.glob("*.yaml")]

    return None
    