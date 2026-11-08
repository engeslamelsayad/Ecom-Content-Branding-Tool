import logging

import app.main  # noqa: F401  — the app's logging setup


def collector(logger):
    """Attach a recording handler (pytest's caplog would see records via its own handlers)."""
    seen = []
    handler = logging.Handler()
    handler.emit = seen.append
    logger.addHandler(handler)
    return seen, handler


def test_font_subsetting_chatter_stays_out_of_the_app_log():
    """Mirror WeasyPrint's capture_logs('fontTools'): DEBUG level plus its own handler."""
    root, fonttools = logging.getLogger(), logging.getLogger('fontTools')
    app_log, app_handler = collector(root)  # stands in for the stderr handler Railway reads
    caught, weasy_handler = collector(fonttools)
    levels = root.level, fonttools.level
    root.setLevel(logging.DEBUG)
    fonttools.setLevel(logging.DEBUG)
    try:
        logging.getLogger('fontTools.ttLib.ttFont').debug("Compiling 'glyf' table")
        logging.getLogger('fontTools.subset').warning('glyph missing')
    finally:
        root.removeHandler(app_handler)
        fonttools.removeHandler(weasy_handler)
        root.setLevel(levels[0])
        fonttools.setLevel(levels[1])

    assert not [r for r in app_log if r.name.startswith('fontTools')]
    # WeasyPrint's own handler still sees the warning, and re-logs it as 'weasyprint'.
    assert [r.getMessage() for r in caught if r.levelno >= logging.WARNING] == ['glyph missing']
