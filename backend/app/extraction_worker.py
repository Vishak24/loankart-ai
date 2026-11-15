"""Reads one uploaded PDF in a throw-away process: python -I extraction_worker.py <path> <max_pages>.

Runs with no API keys (the parent passes an empty environment) and with CPU, memory and file-size limits, so a hostile
or pathological PDF can hang or exhaust only this process. Prints one JSON object: the extraction result, or {"error": ...}.
"""

import json
import resource
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))      # -I removes the script folder from sys.path


def main(path: str, max_pages: int) -> dict:
    for limit, soft in ((resource.RLIMIT_CPU, 20), (resource.RLIMIT_AS, 1536 * 1024 * 1024), (resource.RLIMIT_FSIZE, 0)):
        try:
            resource.setrlimit(limit, (soft, soft))
        except (ValueError, OSError):      # macOS ignores RLIMIT_AS; the timeout in the parent still applies
            pass
    import pdfplumber
    from app import extraction

    try:
        with pdfplumber.open(path) as pdf:
            if len(pdf.pages) > max_pages:
                return {"error": f"The PDF has more than {max_pages} pages."}
    except Exception:
        return {"error": "The PDF could not be opened. It may be damaged or password-protected."}
    return extraction.extract_document(Path(path))


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1], int(sys.argv[2]))))
