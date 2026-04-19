"""Blueprint 登録。"""

from .admin import bp_admin
from .api import bp_api
from .gallery import bp_gallery
from .media import bp_media
from .setup import bp_setup


def register_blueprints(app) -> None:
    app.register_blueprint(bp_setup)
    app.register_blueprint(bp_gallery)
    app.register_blueprint(bp_api)
    app.register_blueprint(bp_media)
    app.register_blueprint(bp_admin)
