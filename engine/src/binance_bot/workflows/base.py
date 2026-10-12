from typing import Protocol


class Workflow(Protocol):
    """Satu alur otomasi yang dijalankan dari CLI. Alur baru cukup mengimplementasikan `run`."""

    name: str

    def run(self) -> None: ...
