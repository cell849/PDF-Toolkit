"""Plain, selectable report text without HTML interpretation."""


def document_details_text(details, limits):
    def rows(value, depth=0):
        prefix = "  " * depth
        if isinstance(value, dict):
            for key, child in value.items():
                name = str(key).replace("_", " ").capitalize()
                if isinstance(child, dict | list):
                    yield prefix + name
                    yield from rows(child, depth + 1)
                else:
                    yield prefix + name + ": " + scalar(child)
        elif isinstance(value, list):
            if not value:
                yield prefix + "None detected"
            for child in value:
                if isinstance(child, dict | list):
                    yield from rows(child, depth)
                    yield ""
                else:
                    yield prefix + "• " + scalar(child)

    def scalar(value):
        if value is None:
            return "Unavailable"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return str(value)

    return ["DOCUMENT DETAILS", "", *rows(details), "", "LIMITS", *rows(limits)]
