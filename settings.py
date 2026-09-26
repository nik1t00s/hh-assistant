"""Settings and OS credential storage, shared by both applications."""
import hashlib
import os
import uuid

from storage import read_json, write_json

SECRET_KEYS = ("hh_cookie", "superjob_cookie")


class CredentialDependencyError(RuntimeError):
    """The Python used to start the application lacks the credential backend."""


def _service(path):
    identity = hashlib.sha256(os.path.normcase(os.path.abspath(path)).encode()).hexdigest()[:16]
    return f"hh-assistant-{identity}"


def _keyring():
    try:
        import keyring
        return keyring
    except ImportError as exc:
        raise CredentialDependencyError(
            "В этом Python не установлен keyring. Запустите start.cmd или "
            "установите зависимости: python -m pip install -r requirements.txt.") from exc


def load_settings(path, defaults, with_secrets=True):
    data = read_json(path, {})
    if not isinstance(data, dict):
        raise RuntimeError("config.json должен содержать JSON-объект.")
    cfg = dict(defaults)
    cfg.update(data)
    cfg.pop("_credential_errors", None)
    if with_secrets:
        for key in SECRET_KEYS:
            if data.get(key):  # Legacy migration occurs on the next successful save.
                continue
            entry = data.get("credentials", {}).get(key)
            if entry:
                try:
                    vault = _keyring()
                    pieces = [vault.get_password(f"{_service(path)}-{entry['id']}-{i}", key)
                              for i in range(entry["count"])]
                    if not pieces or any(piece is None for piece in pieces):
                        raise RuntimeError("Cookie не найдены в системном хранилище.")
                    cfg[key] = "".join(pieces)
                except Exception as exc:
                    cfg[key] = ""
                    message = (str(exc) if isinstance(exc, CredentialDependencyError) else
                               "Не удалось прочитать сохранённые cookies. "
                               "Они не удалены. Проверьте доступ к системному хранилищу "
                               "или введите cookies заново в настройках аккаунта.")
                    cfg.setdefault("_credential_errors", {})[key] = message
    else:
        for key in SECRET_KEYS:
            cfg.pop(key, None)
    return cfg


def save_settings(path, cfg):
    clean = {key: value for key, value in cfg.items()
             if key not in SECRET_KEYS and key != "_credential_errors"}
    previous = read_json(path, {})
    if not isinstance(previous, dict):
        raise RuntimeError("config.json должен содержать JSON-объект.")
    created = []
    active = {}
    try:
        for key in SECRET_KEYS:
            value = cfg.get(key, "")
            if not value:
                # An unreadable credential is not an intentionally cleared field.
                if key in cfg.get("_credential_errors", {}) and key in previous.get("credentials", {}):
                    active[key] = previous["credentials"][key]
                continue
            vault = _keyring()
            entry = {"id": uuid.uuid4().hex, "count": (len(value) + 499) // 500}
            # Windows Credential Manager limits each blob. Use independent,
            # versioned chunks so failure never overwrites the working secret.
            for i in range(entry["count"]):
                service = f"{_service(path)}-{entry['id']}-{i}"
                vault.set_password(service, key, value[i * 500:(i + 1) * 500])
                created.append((service, key))
            active[key] = entry
        clean.pop("credential_keys", None)
        clean["credentials"] = active
        write_json(path, clean)
    except Exception as exc:
        for service, key in created:
            try:
                _keyring().delete_password(service, key)
            except Exception:
                pass
        raise RuntimeError("Не удалось сохранить настройки/cookies. "
                           "config.json не изменён.") from exc
    for key, entry in previous.get("credentials", {}).items():
        if active.get(key) == entry:
            continue
        for i in range(entry["count"]):
            try:
                _keyring().delete_password(f"{_service(path)}-{entry['id']}-{i}", key)
            except Exception:
                pass  # A stale credential must not invalidate a successful save.
    for key in list(cfg.get("_credential_errors", {})):
        if cfg.get(key):
            cfg["_credential_errors"].pop(key)
