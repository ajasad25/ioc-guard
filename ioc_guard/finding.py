"""The record every detection rule returns."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    excerpt: str

    def format(self) -> str:
        return "{}:{}: [{}] {}".format(self.path, self.line, self.rule, self.excerpt)
