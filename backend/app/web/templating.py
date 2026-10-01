from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.core.config import get_settings

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)
templates.env.globals["app_env"] = get_settings().app_env
