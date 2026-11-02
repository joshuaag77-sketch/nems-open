"""Mimic the Fortran input patterns NEMS uses to read its text files."""

from pathlib import Path


class ListDirectedReader:
    """Fortran list-directed READ (READ(unit,*)) over a text file.

    Each read starts on a fresh record, pulls values across as many records as it
    needs, and drops whatever is left on the last record it touched. Blank records
    are skipped. A non-numeric token is a read error: that read returns None and
    the caller keeps its defaults, as the Fortran ERR= branches do.
    """

    def __init__(self, path: Path, skip_records: int = 0):
        self.records = Path(path).read_text(encoding="latin-1").splitlines()
        self.pos = skip_records

    def skip(self, n: int = 1) -> None:
        self.pos += n

    def read(self, n: int, kind=float, partial: bool = False):
        """n values, or None on a read error. With partial=True an error returns the values
        read before it (the Fortran has already assigned them when it jumps to ERR=)."""
        values = []
        while len(values) < n:
            if self.pos >= len(self.records):
                raise EOFError(f"wanted {n} values, got {len(values)}")
            tokens = self.records[self.pos].replace(",", " ").split()
            self.pos += 1
            for tok in tokens:
                if tok.startswith("!") or tok == "/":
                    break
                try:
                    values.append(kind(float(tok)))
                except ValueError:
                    return values if partial else None
                if len(values) == n:
                    break
        return values


# READ (unit,'(99(/))') reads one record and then 99 more: the 100-line header
# at the top of every commercial input file.
HEADER_RECORDS = 100
