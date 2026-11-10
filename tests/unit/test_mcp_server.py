"""The MCP adapter: an outside agent gets four shopping tools that can never move money on their own."""

import asyncio
import json

import pytest

pytest.importorskip("mcp.server.mcpserver")

from fastapi.testclient import TestClient

from agentguard.agent.mcp_server import _idempotency_key, make_server
from agentguard.web.app import DEMO_TOKENS, create_app

H = {"Authorization": "Bearer " + DEMO_TOKENS["buyer"]}


def _setup():
    app = create_app(paypal_mode="fake", llm=None, ai="off", tokens=dict(DEMO_TOKENS), demo_mode=True,
                     demo_source="channel3", rate_per_min=0)
    buyer = TestClient(app)
    buyer.get("/api/demo/session")
    k = buyer.post("/api/agent-keys", json={"name": "mcp test"}, headers=H).json()
    return app, buyer, k, make_server("http://testserver", k["key"], http=TestClient(app))


def _call(srv, name, args):
    r = asyncio.run(srv.call_tool(name, args))
    return json.loads(r.content[0].text)


def test_exactly_four_tools_and_none_can_approve_or_move_money():
    _, _, _, srv = _setup()
    tools = {t.name: t for t in asyncio.run(srv.list_tools())}
    assert sorted(tools) == ["create_order", "get_order_details", "list_products", "read_shop_page"]
    items = tools["create_order"].input_schema["properties"]["items"]
    ref = items["items"].get("$ref", "").split("/")[-1]
    line = tools["create_order"].input_schema.get("$defs", {}).get(ref, items["items"])
    assert set(line["properties"]) == {"sku", "quantity"}   # typed: no free-form object for strict function calling


def test_order_goes_through_the_guard_and_lands_in_the_buyers_console():
    _, buyer, k, srv = _setup()
    assert any(p["sku"] == "C3-NORMAL" for p in _call(srv, "list_products", {})["products"])
    assert "Note for AI" in _call(srv, "read_shop_page", {"page_id": "demo-poisoned"})["text"]
    held = _call(srv, "create_order", {"mandate_id": "thandi-earbuds", "page_id": "demo-poisoned",
                                       "items": [{"sku": "C3-SWAP", "quantity": 1}]})
    assert held["decision"] in ("ask_first", "block") and not held["paypal_called"]
    assert held["findings"] and all(set(f) == {"code", "level", "reason", "would_pass_if"} for f in held["findings"])
    fixed = _call(srv, "create_order", {"mandate_id": "thandi-earbuds", "page_id": "demo-normal",
                                        "items": [{"sku": "C3-NORMAL", "quantity": 1}]})
    assert fixed["payment_id"] != held["payment_id"] and fixed["status"] == "captured" and fixed["paypal_called"]
    mine = {p["id"]: p for p in buyer.get("/api/payments", headers=H).json()}
    assert set(mine) == {held["payment_id"], fixed["payment_id"]}
    assert all(p["agent_id"] == k["agent_id"] and p["agent_verified"] for p in mine.values())


def test_same_request_twice_is_one_payment_and_other_agents_payments_are_hidden():
    app, buyer, _, srv = _setup()
    args = {"mandate_id": "thandi-earbuds", "page_id": "demo-normal", "items": [{"sku": "C3-NORMAL", "quantity": 1}]}
    a, b = _call(srv, "create_order", args), _call(srv, "create_order", args)
    assert a["payment_id"] == b["payment_id"] and len(buyer.get("/api/payments", headers=H).json()) == 1
    other = make_server("http://testserver", buyer.post("/api/agent-keys", json={"name": "b"}, headers=H).json()["key"],
                        http=TestClient(app))
    assert _call(other, "get_order_details", {"payment_id": a["payment_id"]})["error"] == "not_found"
    assert _call(srv, "get_order_details", {"payment_id": a["payment_id"]})["status"] == "captured"


def test_lying_about_the_price_is_caught_and_a_key_is_required():
    _, _, _, srv = _setup()
    lie = _call(srv, "create_order", {"mandate_id": "thandi-earbuds", "page_id": "demo-normal", "stated_total": "68.60",
                                      "items": [{"sku": "C3-NORMAL", "quantity": 1}]})
    assert lie["decision"] != "approve" and not lie["paypal_called"]
    assert any("price" in f["code"] for f in lie["findings"])
    with pytest.raises(SystemExit):
        make_server("http://testserver", "demo-agent-token")
    assert _idempotency_key("m", [{"sku": "A", "quantity": 1}], "p", None) != _idempotency_key(
        "m", [{"sku": "B", "quantity": 1}], "p", None)
