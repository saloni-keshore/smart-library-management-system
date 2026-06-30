import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "smart_library_secret")
    DEBUG = False


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
