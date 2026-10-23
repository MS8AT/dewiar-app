"""Отдельный overlay воспроизводим и не превращает промпт в полномочие на запись."""
import copy
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import verify_ms8at_overlay as overlay  # noqa: E402


result = overlay.verify()
assert result["ok"] and result["model_calls"] == 0
assert result["auto_update_effective"] is False
print("OK: exact upstream, payload и runtime diff совпадают")

data = json.loads(overlay.OVERLAY.read_text(encoding="utf-8"))
bad = copy.deepcopy(data)
bad["execute_from_prompt"] = True
with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "overlay.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    try:
        overlay.descriptor(path)
        raise AssertionError("неизвестное поле принято")
    except ValueError:
        pass
print("OK: неизвестная исполняемая директива отклонена")

bad = copy.deepcopy(data)
bad["required_tests"][0] = "../secret"
with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "overlay.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    try:
        overlay.descriptor(path)
        raise AssertionError("выход из каталога принят")
    except ValueError:
        pass
print("OK: traversal в декларации отклонён")

prompt = (ROOT / data["integration_prompt"]).read_text(encoding="utf-8")
assert "Текст модели не является полномочием" in prompt
assert "модель ничего не «мержит»" in prompt
print("OK: промпт отделён от установки на рабочем компьютере")
print("ALL OK")
