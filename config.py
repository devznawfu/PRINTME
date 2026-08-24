import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
UPLOAD_DIR = BASE_DIR / "uploads"
PROCESSED_DIR = BASE_DIR / "processed"

ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "jpg", "png", "docx"}
MAX_UPLOAD_SIZE_BYTES = 15 * 1024 * 1024

PRIMARY_PHOTO_SIZES = ("1x1", "2x2", "Passport", "Visa")
MORE_PHOTO_SIZES = ("Wallet", "4x6", "5x7", "4x4")
PHOTO_SIZES = PRIMARY_PHOTO_SIZES + MORE_PHOTO_SIZES
PRINTER_NAMES = ("DCP-L2540DW", "DCP-T420W", "DCP-T430W")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{INSTANCE_DIR / 'printme.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = MAX_UPLOAD_SIZE_BYTES
    UPLOAD_DIR = UPLOAD_DIR
    PROCESSED_DIR = PROCESSED_DIR
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "print")
    UPLOAD_RETENTION_DAYS = 2
    SCHEDULER_ENABLED = True


class DevConfig(Config):
    DEBUG = True
    SCHEDULER_ENABLED = False


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SCHEDULER_ENABLED = False
    WTF_CSRF_ENABLED = False


class ProdConfig(Config):
    DEBUG = False


CONFIG_BY_NAME = {
    "dev": DevConfig,
    "test": TestConfig,
    "prod": ProdConfig,
}
