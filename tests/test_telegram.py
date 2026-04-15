"""Tests для telegram command handler (без real API calls)."""
import pytest

from momentum import config, db, telegram_bot


@pytest.fixture
def owner_id(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_OWNER_ID", "12345")
    return 12345


def test_non_command_returns_none(owner_id):
    assert telegram_bot.handle_command("hello world", owner_id) is None


def test_non_owner_rejected():
    assert telegram_bot.handle_command("/status", 99999) == "не для тебя :3"


def test_help_lists_commands(owner_id):
    r = telegram_bot.handle_command("/help", owner_id)
    assert "/status" in r
    assert "/pause" in r


def test_status_without_data(owner_id):
    r = telegram_bot.handle_command("/status", owner_id)
    assert "momentum-bot" in r


def test_pause_sets_db_flag(owner_id):
    telegram_bot.handle_command("/pause", owner_id)
    assert db.get_state("paused") is True


def test_resume_clears_flag(owner_id):
    db.set_state("paused", True)
    telegram_bot.handle_command("/resume", owner_id)
    assert db.get_state("paused") is False


def test_stop_sets_emergency(owner_id):
    telegram_bot.handle_command("/stop", owner_id)
    assert db.get_state("emergency_stop") is True


def test_params_shows_config(owner_id):
    r = telegram_bot.handle_command("/params", owner_id)
    assert "variant" in r
    assert "lookback" in r


def test_unknown_command(owner_id):
    r = telegram_bot.handle_command("/foobar", owner_id)
    assert "unknown" in r.lower()
