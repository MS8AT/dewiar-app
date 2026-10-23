"""Граница обновлений форка: upstream — справка, а не установщик наших дополнений.

Доверенный канал подписанных полных выпусков пока не настроен. Не выдаём наличие
новой версии upstream за готовность обновления форка и не запускаем её EXE.
Состояние доступно API/интерфейсу; никакой фоновой задачи этот модуль не создаёт.
"""
PRODUCT = "MS8AT8DWiar"
BUILD = 11
REQUIRED_FEATURES = ("codex_local", "codex_task_quota_grants", "brain_routes", "brain_watch", "diagnostics_v1",
                     "task_observability_v1", "codex_task_delegation_v1", "human_memory_mcp_v1",
                     "codex_confirmation_recovery_v1", "language_voice_switch_v1", "windows_task_commands_v1",
                     "custom_dialogs_v1", "overlay_v1")
BLOCK_REASON = "Канал обновления форка ещё не настроен. Обычный установщик Dewiar может удалить дополнения; автоматическая установка заблокирована."


def status():
    return {"product": PRODUCT, "build": BUILD, "state": "unconfigured", "auto_download": False,
            "auto_install": False, "required_features": list(REQUIRED_FEATURES),
            "blockers": ["trusted_release_feed", "publisher_verification", "verified_package", "closed_app_installer"],
            "message": BLOCK_REASON}
