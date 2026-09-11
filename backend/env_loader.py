from __future__ import annotations

from pathlib import Path


def load_backend_env() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return

    backend_dir = Path(__file__).parent
    for env_path in (backend_dir.parent / ".env", backend_dir / ".env"):
        if env_path.is_file():
            load_dotenv(env_path, override=False)
