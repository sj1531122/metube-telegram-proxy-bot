class BotIntegrationError(RuntimeError):
    """Base exception for remote integration failures."""


class TelegramApiError(BotIntegrationError):
    """Telegram API call failed."""


class MeTubeApiError(BotIntegrationError):
    """MeTube API call failed."""
