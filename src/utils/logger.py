import logging
import sys

class ColoredFormatter(logging.Formatter):
    """
    Custom formatter to add colors to log levels.
    """
    
    # ANSI Escape codes
    GREY = "\x1b[38;20m"
    CYAN = "\x1b[36;20m"
    GREEN = "\x1b[32;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"
    
    FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    FORMATS = {
        logging.DEBUG: CYAN + FORMAT + RESET,
        logging.INFO: GREEN + FORMAT + RESET,
        logging.WARNING: YELLOW + FORMAT + RESET,
        logging.ERROR: RED + FORMAT + RESET,
        logging.CRITICAL: BOLD_RED + FORMAT + RESET
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt="%H:%M:%S")
        return formatter.format(record)

def setup_logger(name: str = "programmatic_seo", level=logging.DEBUG):
    """
    Sets up a logger with the specified name and level.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Check if handler already exists to avoid duplicates
    if not logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(ColoredFormatter())
        logger.addHandler(console_handler)
    
    return logger
