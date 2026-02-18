import re

def get_safe_filename(title: str) -> str:
    """
    Sanitizes a string to be used as a filename.
    Matches the logic used in both pre-check (main.py) and saving (compiler.py).
    """
    s = title.lower().strip()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[\s_-]+', '_', s)
    return s[:60]
