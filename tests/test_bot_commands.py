# AI GC START
from __future__ import annotations

from app.services.bot import parse_bot_command
from app.services.feishu import decode_callback_body


def test_parse_help_command() -> None:
    command = parse_bot_command("帮助")
    assert command is not None
    assert command.name == "help"


def test_parse_import_commands() -> None:
    document = parse_bot_command("抓取文档 https://example.feishu.cn/docx/abc123")
    assert document is not None
    assert document.name == "import_doc"
    assert "abc123" in document.value

    chat = parse_bot_command("/kb chat oc_test 20")
    assert chat is not None
    assert chat.name == "import_chat"
    assert chat.value == "oc_test"
    assert chat.limit == 20

    image = parse_bot_command("/kb image img_xxx")
    assert image is not None
    assert image.name == "import_image"
    assert image.value == "img_xxx"


def test_decode_plain_callback_body() -> None:
    payload = decode_callback_body(
        raw_body=b'{"challenge":"hello","token":"verify"}',
        headers={},
        credentials={
            "feishu_app_id": "cli_demo",
            "feishu_app_secret": "secret",
            "verification_token": "verify",
            "encrypt_key": None,
        },
    )
    assert payload["challenge"] == "hello"
# AI GC END
