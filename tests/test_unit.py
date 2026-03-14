"""Unit tests  no running server, no database required.

Covers:
  * app/auth.py       password hashing, JWT creation/validation, permission guard
  * app/config.py     Settings defaults, cors_origins_list, warn_insecure_defaults
  * app/database.py   get_db only commits when writes are pending
"""

import asyncio
import os
import sys
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _run(coro):
    """Run a coroutine in a fresh event loop (works on Python 3.10+ / Windows)."""
    return asyncio.run(coro)


# 
# app/auth.py  password hashing
# 

class TestPasswordHashing:
    def setup_method(self):
        from app.auth import hash_password, verify_password
        self.hash_password = hash_password
        self.verify_password = verify_password

    def test_hash_returns_string(self):
        assert isinstance(self.hash_password("secret123"), str)

    def test_hash_is_not_plaintext(self):
        assert "secret123" not in self.hash_password("secret123")

    def test_hash_different_each_call(self):
        assert self.hash_password("same") != self.hash_password("same")

    def test_verify_correct_password(self):
        h = self.hash_password("correcthorsebattery")
        assert self.verify_password("correcthorsebattery", h) is True

    def test_verify_wrong_password(self):
        h = self.hash_password("correcthorsebattery")
        assert self.verify_password("wrong", h) is False

    def test_verify_empty_password_fails(self):
        h = self.hash_password("nonempty")
        assert self.verify_password("", h) is False


# 
# app/auth.py  JWT
# 

class TestJWT:
    def setup_method(self):
        from app.auth import create_access_token
        from app.config import get_settings
        self.create_token = create_access_token
        self.settings = get_settings()

    def test_token_is_string(self):
        assert isinstance(self.create_token({"sub": "x"}), str)

    def test_token_encodes_subject(self):
        from jose import jwt
        token = self.create_token({"sub": "abc-def"})
        payload = jwt.decode(token, self.settings.secret_key, algorithms=[self.settings.algorithm])
        assert payload["sub"] == "abc-def"

    def test_token_contains_expiry(self):
        from jose import jwt
        token = self.create_token({"sub": "x"})
        payload = jwt.decode(token, self.settings.secret_key, algorithms=[self.settings.algorithm])
        assert "exp" in payload

    def test_custom_expiry(self):
        import time
        from jose import jwt
        token = self.create_token({"sub": "x"}, expires_delta=timedelta(seconds=60))
        payload = jwt.decode(token, self.settings.secret_key, algorithms=[self.settings.algorithm])
        assert payload["exp"] > int(time.time()) + 55

    def test_expired_token_raises(self):
        from jose import jwt, JWTError
        token = self.create_token({"sub": "x"}, expires_delta=timedelta(seconds=-1))
        with pytest.raises(JWTError):
            jwt.decode(token, self.settings.secret_key, algorithms=[self.settings.algorithm])

    def test_tampered_token_raises(self):
        from jose import jwt, JWTError
        token = self.create_token({"sub": "x"})
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        with pytest.raises(JWTError):
            jwt.decode(tampered, self.settings.secret_key, algorithms=[self.settings.algorithm])

    def test_wrong_secret_raises(self):
        from jose import jwt, JWTError
        token = self.create_token({"sub": "x"})
        with pytest.raises(JWTError):
            jwt.decode(token, "wrong-secret", algorithms=[self.settings.algorithm])


# 
# app/auth.py  get_current_user (mocked DB)
# 

def _db_returning(user):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    return db


class TestGetCurrentUser:
    def _user(self, active=True):
        u = MagicMock()
        u.id = str(uuid.uuid4())
        u.is_active = active
        return u

    def test_valid_token_returns_user(self):
        from app.auth import create_access_token, get_current_user
        user = self._user()
        token = create_access_token({"sub": user.id})
        result = _run(get_current_user(token=token, db=_db_returning(user)))
        assert result is user

    def test_inactive_user_raises_401(self):
        from app.auth import create_access_token, get_current_user
        from fastapi import HTTPException
        user = self._user(active=False)
        token = create_access_token({"sub": user.id})
        with pytest.raises(HTTPException) as exc:
            _run(get_current_user(token=token, db=_db_returning(user)))
        assert exc.value.status_code == 401

    def test_missing_user_raises_401(self):
        from app.auth import create_access_token, get_current_user
        from fastapi import HTTPException
        token = create_access_token({"sub": str(uuid.uuid4())})
        with pytest.raises(HTTPException) as exc:
            _run(get_current_user(token=token, db=_db_returning(None)))
        assert exc.value.status_code == 401

    def test_garbage_token_raises_401(self):
        from app.auth import get_current_user
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(get_current_user(token="not.a.token", db=AsyncMock()))
        assert exc.value.status_code == 401


# 
# app/auth.py  require_permission guard
# 

def _db_with_permissions(perms: dict):
    role = MagicMock()
    role.permissions = perms
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = role
    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    return db


def _db_no_role():
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    return db


def _user_role(role_value: str):
    u = MagicMock()
    u.role.value = role_value
    return u


class TestRequirePermission:
    def test_user_with_permission_passes(self):
        from app.auth import require_permission
        user = _user_role("admin")
        result = _run(require_permission("flows.create")(user=user, db=_db_with_permissions({"flows.create": True})))
        assert result is user

    def test_user_without_permission_raises_403(self):
        from app.auth import require_permission
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(require_permission("flows.create")(user=_user_role("agent"), db=_db_with_permissions({"flows.view": True})))
        assert exc.value.status_code == 403

    def test_false_permission_raises_403(self):
        from app.auth import require_permission
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(require_permission("flows.create")(user=_user_role("agent"), db=_db_with_permissions({"flows.create": False})))
        assert exc.value.status_code == 403

    def test_no_role_record_raises_403(self):
        from app.auth import require_permission
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(require_permission("flows.create")(user=_user_role("unknown"), db=_db_no_role()))
        assert exc.value.status_code == 403


# 
# app/config.py  Settings
# 

# Vars that might leak from the real .env file
_SCRUB = ["ADMIN_INITIAL_PASSWORD", "CORS_ORIGINS", "SECRET_KEY", "DATABASE_URL", "DATABASE_URL_SYNC"]


def _fresh_settings(**overrides):
    """Create an isolated Settings instance that ignores the on-disk .env."""
    from app.config import Settings
    clean = {k: v for k, v in os.environ.items() if k not in _SCRUB}
    clean.update({k.upper(): str(v) for k, v in overrides.items()})
    with patch.dict(os.environ, clean, clear=True):
        return Settings(_env_file=None)


class TestSettings:
    def test_cors_origins_list_single(self):
        s = _fresh_settings(cors_origins="http://localhost:8090")
        assert s.cors_origins_list == ["http://localhost:8090"]

    def test_cors_origins_list_multiple(self):
        s = _fresh_settings(cors_origins="http://a.com, http://b.com , http://c.com")
        assert s.cors_origins_list == ["http://a.com", "http://b.com", "http://c.com"]

    def test_cors_origins_list_strips_empty(self):
        s = _fresh_settings(cors_origins="http://a.com,, ,http://b.com")
        result = s.cors_origins_list
        assert "" not in result
        assert len(result) == 2

    def test_admin_initial_password_default_is_empty(self):
        s = _fresh_settings()  # no ADMIN_INITIAL_PASSWORD in env
        assert s.admin_initial_password == ""

    def test_admin_initial_password_from_env(self):
        s = _fresh_settings(admin_initial_password="S3cr3t!")
        assert s.admin_initial_password == "S3cr3t!"

    def test_warn_insecure_defaults_fires_for_dev_secret(self):
        from app.config import _DEV_SECRET
        s = _fresh_settings(secret_key=_DEV_SECRET)
        with patch("app.config._log") as mock_log:
            s.warn_insecure_defaults()
        assert mock_log.warning.called
        msgs = " ".join(str(c) for c in mock_log.warning.call_args_list)
        assert "SECRET_KEY" in msgs

    def test_warn_insecure_defaults_silent_with_custom_secret(self):
        s = _fresh_settings(
            secret_key="a-very-long-custom-production-secret-key",
            database_url="postgresql+asyncpg://prod:prod@prod-host:5432/proddb",
        )
        with patch("app.config._log") as mock_log:
            s.warn_insecure_defaults()
        assert not mock_log.warning.called


# 
# app/database.py  get_db commit-only-when-dirty
# 

def _mock_session_cm(has_writes: bool):
    session = AsyncMock()
    session.new = {MagicMock()} if has_writes else set()
    session.dirty = set()
    session.deleted = set()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return session, cm


async def _drive_get_db(cm, raise_exc=None):
    import app.database as db_module
    with patch.object(db_module, "async_session", return_value=cm):
        async for _ in db_module.get_db():
            if raise_exc:
                raise raise_exc


class TestGetDbCommitBehavior:
    def test_commit_called_when_writes_pending(self):
        session, cm = _mock_session_cm(has_writes=True)
        _run(_drive_get_db(cm))
        session.commit.assert_awaited_once()

    def test_no_commit_on_readonly(self):
        session, cm = _mock_session_cm(has_writes=False)
        _run(_drive_get_db(cm))
        session.commit.assert_not_awaited()

    def test_rollback_on_commit_failure(self):
        """rollback() is called when session.commit() raises (e.g. DB constraint error)."""
        session, cm = _mock_session_cm(has_writes=True)
        session.commit = AsyncMock(side_effect=RuntimeError("constraint violation"))

        async def _run_commit_fail():
            import app.database as db_module
            with patch.object(db_module, "async_session", return_value=cm):
                async for _ in db_module.get_db():
                    pass  # no consumer error; commit fails inside generator

        with pytest.raises(RuntimeError, match="constraint violation"):
            _run(_run_commit_fail())
        session.rollback.assert_awaited_once()

    def test_close_always_called(self):
        session, cm = _mock_session_cm(has_writes=False)
        _run(_drive_get_db(cm))
        session.close.assert_awaited_once()


# ──────────────────────────────────────────────────────────────────────────────
# apply_outcome_to_session — end_interaction and flow_redirect paths
# ──────────────────────────────────────────────────────────────────────────────

class TestApplyOutcomeToSession:
    """Unit tests for ``apply_outcome_to_session`` (no DB / WS required)."""

    def _make_session(self, agent_id=None):
        sess = MagicMock()
        sess.agent_id        = uuid.UUID(agent_id) if agent_id else None
        sess.status          = "with_agent"
        sess.waiting_node_id = "some-node"
        sess.flow_context    = {"greeting": "hello"}
        sess.disconnect_outcome = None
        return sess

    def _make_outcome(self, action_type, code="resolved", redirect_flow_id=None):
        o = MagicMock()
        o.action_type       = action_type
        o.code              = code
        o.redirect_flow_id  = uuid.UUID(redirect_flow_id) if redirect_flow_id else None
        return o

    # ── end_interaction ──────────────────────────────────────────────────────

    def test_end_interaction_closes_session(self):
        from app.routers.chat_ws import apply_outcome_to_session

        agent_id = str(uuid.uuid4())
        sess     = self._make_session(agent_id=agent_id)
        outcome  = self._make_outcome("end_interaction", code="resolved")
        load     = {agent_id: 2}

        action, code = apply_outcome_to_session(sess, outcome, load, agent_id)

        assert action == "end"
        assert code   == "resolved"
        assert sess.status == "closed"
        assert sess.disconnect_outcome == "resolved"
        # Agent load should decrease by 1
        assert load[agent_id] == 1

    def test_resolve_fallback_closes_session(self):
        """Passing outcome=None (built-in Resolve) also ends the interaction."""
        from app.routers.chat_ws import apply_outcome_to_session

        agent_id = str(uuid.uuid4())
        sess     = self._make_session(agent_id=agent_id)
        load     = {agent_id: 1}

        action, code = apply_outcome_to_session(sess, None, load, agent_id)

        assert action == "end"
        assert code   == "resolve"
        assert sess.status == "closed"
        assert sess.disconnect_outcome == "resolve"
        assert load[agent_id] == 0

    def test_end_interaction_does_not_go_below_zero_load(self):
        """agent_load never goes negative."""
        from app.routers.chat_ws import apply_outcome_to_session

        agent_id = str(uuid.uuid4())
        sess     = self._make_session(agent_id=agent_id)
        outcome  = self._make_outcome("end_interaction")
        load     = {agent_id: 0}  # already zero

        apply_outcome_to_session(sess, outcome, load, agent_id)

        assert load[agent_id] == 0

    # ── flow_redirect ────────────────────────────────────────────────────────

    def test_flow_redirect_activates_session(self):
        from app.routers.chat_ws import apply_outcome_to_session

        agent_id  = str(uuid.uuid4())
        flow_id   = str(uuid.uuid4())
        sess      = self._make_session(agent_id=agent_id)
        outcome   = self._make_outcome("flow_redirect", code="escalate", redirect_flow_id=flow_id)
        load      = {agent_id: 3}

        action, code = apply_outcome_to_session(sess, outcome, load, agent_id)

        assert action == "redirect"
        assert code   == "escalate"
        assert sess.status == "active"
        assert sess.agent_id is None
        assert sess.waiting_node_id is None
        assert sess.disconnect_outcome == "escalate"
        assert sess.flow_context["_current_flow_id"] == flow_id
        assert load[agent_id] == 2

    def test_flow_redirect_preserves_existing_context_keys(self):
        """Redirecting to a flow keeps prior flow context variables intact."""
        from app.routers.chat_ws import apply_outcome_to_session

        flow_id  = str(uuid.uuid4())
        sess     = self._make_session()
        sess.flow_context = {"name": "Alice", "lang": "en"}
        outcome  = self._make_outcome("flow_redirect", redirect_flow_id=flow_id)
        load     = {}

        apply_outcome_to_session(sess, outcome, load, "other-agent")

        assert sess.flow_context["name"] == "Alice"
        assert sess.flow_context["lang"] == "en"
        assert sess.flow_context["_current_flow_id"] == flow_id

    def test_flow_redirect_without_flow_id_falls_back_to_end(self):
        """A flow_redirect outcome with no redirect_flow_id closes the session."""
        from app.routers.chat_ws import apply_outcome_to_session

        sess    = self._make_session()
        outcome = self._make_outcome("flow_redirect", code="noop")
        outcome.redirect_flow_id = None  # misconfigured — no target flow
        load    = {}

        action, code = apply_outcome_to_session(sess, outcome, load, "agent-x")

        assert action == "end"
        assert sess.status == "closed"
