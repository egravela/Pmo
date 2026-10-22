"""La chiave Anthropic deve essere letta sia come ANTHROPIC_API_KEY sia come PMO_ANTHROPIC_API_KEY."""

from __future__ import annotations

from pmo.config import Settings


def test_chiave_anthropic_da_file_env_senza_prefisso(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PMO_ANTHROPIC_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant-di-prova\n", encoding="utf-8")
    assert Settings(_env_file=env).anthropic_api_key == "sk-ant-di-prova"


def test_chiave_anthropic_con_prefisso_pmo(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PMO_ANTHROPIC_API_KEY", "sk-ant-con-prefisso")
    assert Settings(_env_file=tmp_path / "inesistente.env").anthropic_api_key == "sk-ant-con-prefisso"
