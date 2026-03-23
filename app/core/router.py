from app.services.config_loader import get_config


def get_route(task_type: str, classification_route: str | None = None) -> str:
    """Returns the canonical route for a classified task."""
    config = get_config()
    if classification_route and classification_route in config.routes:
        return classification_route
    input_cfg = config.input_types.get(task_type)
    if input_cfg:
        return input_cfg.default_route
    return "default"


def get_suggested_tools(route: str) -> list[str]:
    config = get_config()
    route_cfg = config.routes.get(route) or config.routes.get("default")
    return route_cfg.tools if route_cfg else []
