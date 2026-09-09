"""Desktop entry point and compatibility facade for the Kill Zone engine."""

from engine.compat import EXPORTS, resolve

__all__ = [name for name in EXPORTS if not name.startswith("_")]


def __getattr__(name):
    return resolve(name)


def __dir__():
    return sorted(set(globals()) | set(EXPORTS))


if __name__ == "__main__":
    resolve("main")()
