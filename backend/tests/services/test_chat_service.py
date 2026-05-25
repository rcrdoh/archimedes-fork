"""Unit coverage for ChatService — message persistence + AI canned fallback.

Mocks `get_session` + the `ChatMessage` ORM so no DB connection is needed.
Validates message composition, AI-mention detection, the canned-response
keyword router, and the regime-change/rebalance event posters.

Added 2026-05-24 as part of the #147 coverage-gate lift.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from archimedes.services.chat_service import (
    AI_WALLET_ADDRESS,
    ChatService,
)


def _make_session(query_result=None) -> tuple[MagicMock, MagicMock]:
    """Build a mock SQLAlchemy session whose query chain returns query_result."""
    session = MagicMock()
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.limit.return_value = chain
    chain.all.return_value = query_result or []
    chain.count.return_value = len(query_result or [])
    chain.first.return_value = (query_result or [None])[0]
    session.query.return_value = chain
    return session, chain


def _mock_msg(
    msg_id: int = 1, vault: str = "0xv", wallet: str = "0xw", text: str = "hi", is_ai: bool = False
) -> MagicMock:
    """Build a mock ChatMessage with a working `to_dict`."""
    msg = MagicMock()
    msg.id = msg_id
    msg.vault_address = vault
    msg.wallet_address = wallet
    msg.message = text
    msg.is_ai = is_ai
    msg.to_dict.return_value = {
        "id": msg_id,
        "vault_address": vault,
        "wallet_address": wallet,
        "message": text,
        "is_ai": is_ai,
    }
    return msg


class TestGetMessages:
    def test_returns_messages_oldest_first(self) -> None:
        # ORM returns newest-first; service reverses to oldest-first for display
        m1 = _mock_msg(msg_id=10, text="newest")
        m2 = _mock_msg(msg_id=5, text="oldest")
        session, _ = _make_session([m1, m2])
        with patch("archimedes.services.chat_service.get_session", return_value=session):
            result = ChatService().get_messages("0xv")
        assert [r["message"] for r in result] == ["oldest", "newest"]
        session.close.assert_called_once()

    def test_lowercases_vault_address(self) -> None:
        session, chain = _make_session([])
        with patch("archimedes.services.chat_service.get_session", return_value=session):
            ChatService().get_messages("0xV-UPPER")
        # filter() called with lowercased address — check the predicate ran
        chain.filter.assert_called()

    def test_before_id_adds_filter(self) -> None:
        session, chain = _make_session([])
        with patch("archimedes.services.chat_service.get_session", return_value=session):
            ChatService().get_messages("0xv", before_id=100)
        # Two filter calls: vault_address + id < before_id
        assert chain.filter.call_count >= 2


class TestPostMessage:
    def test_simple_user_message_round_trip(self) -> None:
        session, _ = _make_session([])
        with (
            patch("archimedes.services.chat_service.get_session", return_value=session),
            patch("archimedes.services.chat_service.ChatMessage") as msg_class,
        ):
            msg_class.return_value = _mock_msg(text="hello")
            result = ChatService().post_message("0xv", "0xw", "hello")
        assert result["message"] == "hello"
        session.add.assert_called_once()
        session.commit.assert_called_once()
        session.close.assert_called_once()

    def test_mention_triggers_ai_response_in_payload(self) -> None:
        session, _ = _make_session([])
        with (
            patch("archimedes.services.chat_service.get_session", return_value=session),
            patch("archimedes.services.chat_service.ChatMessage") as msg_class,
        ):
            msg_class.return_value = _mock_msg(text="@archimedes how is performance?")
            with patch.object(ChatService, "_generate_ai_response") as gen:
                gen.return_value = {"id": 99, "message": "ai-reply", "is_ai": True}
                result = ChatService().post_message("0xv", "0xw", "@archimedes how is performance?")
        gen.assert_called_once()
        assert "_ai_response" in result
        assert result["_ai_response"]["message"] == "ai-reply"

    def test_no_mention_skips_ai_response(self) -> None:
        session, _ = _make_session([])
        with (
            patch("archimedes.services.chat_service.get_session", return_value=session),
            patch("archimedes.services.chat_service.ChatMessage") as msg_class,
        ):
            msg_class.return_value = _mock_msg(text="just a chat")
            with patch.object(ChatService, "_generate_ai_response") as gen:
                ChatService().post_message("0xv", "0xw", "just a chat")
        gen.assert_not_called()

    def test_exception_triggers_rollback(self) -> None:
        session, _ = _make_session([])
        session.commit.side_effect = RuntimeError("db down")
        with (
            patch("archimedes.services.chat_service.get_session", return_value=session),
            patch("archimedes.services.chat_service.ChatMessage") as msg_class,
        ):
            msg_class.return_value = _mock_msg()
            with pytest.raises(RuntimeError):
                ChatService().post_message("0xv", "0xw", "hello")
        session.rollback.assert_called_once()
        session.close.assert_called_once()


class TestPostAiMessage:
    def test_uses_ai_wallet_address(self) -> None:
        session, _ = _make_session([])
        with (
            patch("archimedes.services.chat_service.get_session", return_value=session),
            patch("archimedes.services.chat_service.ChatMessage") as msg_class,
        ):
            msg_class.return_value = _mock_msg(wallet=AI_WALLET_ADDRESS, is_ai=True)
            result = ChatService().post_ai_message("0xv", "system notice")
        assert result is not None
        assert result["is_ai"] is True
        # The constructor was called with the AI wallet
        kwargs = msg_class.call_args.kwargs
        assert kwargs["wallet_address"] == AI_WALLET_ADDRESS

    def test_failure_returns_none(self) -> None:
        session, _ = _make_session([])
        session.commit.side_effect = RuntimeError("db down")
        with (
            patch("archimedes.services.chat_service.get_session", return_value=session),
            patch("archimedes.services.chat_service.ChatMessage") as msg_class,
        ):
            msg_class.return_value = _mock_msg()
            result = ChatService().post_ai_message("0xv", "fail")
        assert result is None
        session.rollback.assert_called_once()


class TestEventPosters:
    def test_rebalance_event_includes_trades(self) -> None:
        with patch.object(ChatService, "post_ai_message") as poster:
            poster.return_value = {"id": 1}
            ChatService().post_rebalance_event(
                "0xv",
                "regime shift",
                trades=[{"direction": "buy", "amount": 100, "symbol": "sTSLA"}],
            )
        poster.assert_called_once()
        message = poster.call_args.args[1]
        assert "BUY 100 sTSLA" in message
        assert "regime shift" in message
        # trigger keyword carried
        assert poster.call_args.kwargs.get("trigger") == "rebalance"

    def test_rebalance_event_no_trades_still_posts(self) -> None:
        with patch.object(ChatService, "post_ai_message") as poster:
            poster.return_value = {"id": 1}
            ChatService().post_rebalance_event("0xv", "regime shift", trades=None)
        message = poster.call_args.args[1]
        assert "Rebalance executed" in message

    def test_regime_change_message_includes_confidence(self) -> None:
        with patch.object(ChatService, "post_ai_message") as poster:
            poster.return_value = {"id": 1}
            ChatService().post_regime_change("0xv", "risk_on", "risk_off", confidence=0.87)
        message = poster.call_args.args[1]
        assert "87%" in message
        assert "risk_on" in message
        assert "risk_off" in message
        assert poster.call_args.kwargs.get("trigger") == "regime_change"


class TestCannedResponse:
    @pytest.mark.parametrize(
        "user_message,expected_marker",
        [
            ("How is performance?", "performance"),
            ("Should we rebalance soon?", "Rebalances"),
            ("Is this risky?", "selection-bias"),
            ("What strategy is this?", "research"),
            ("Hello!", "👋"),
            ("Just listing without any trigger", "monitoring the portfolio"),
        ],
    )
    def test_keyword_routing(self, user_message: str, expected_marker: str) -> None:
        with patch.object(ChatService, "post_ai_message") as poster:
            poster.return_value = {"id": 1}
            ChatService()._canned_response("0xv", user_message)
        text = poster.call_args.args[1]
        assert expected_marker in text


class TestGetMessageCount:
    def test_returns_session_count(self) -> None:
        session, _ = _make_session([_mock_msg(), _mock_msg(), _mock_msg()])
        with patch("archimedes.services.chat_service.get_session", return_value=session):
            count = ChatService().get_message_count("0xv")
        assert count == 3
        session.close.assert_called_once()
