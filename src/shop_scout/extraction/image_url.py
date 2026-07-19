from urllib.parse import urljoin


def largest_srcset_url(srcset: str, base_url: str) -> str | None:
    candidates: list[tuple[float, str]] = []
    for entry in srcset.split(","):
        pieces = entry.strip().split()
        if not pieces:
            continue
        weight = 1.0
        if len(pieces) > 1:
            descriptor = pieces[-1].lower()
            try:
                weight = float(descriptor.rstrip("wx"))
            except ValueError:
                weight = 1.0
        candidates.append((weight, urljoin(base_url, pieces[0])))
    return max(candidates, default=(0, ""))[1] or None
