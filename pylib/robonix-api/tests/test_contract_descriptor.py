# SPDX-License-Identifier: MulanPSL-2.0

from types import SimpleNamespace

from robonix_api.atlas_types import from_pb_contract
from robonix_api.atlas import _Atlas


def _pb_contract(*, llm_callable=None):
    """Build the protobuf-shaped minimum needed by from_pb_contract."""
    values = {
        "id": "robonix/service/example/run",
        "version": "1",
        "kind": 2,
        "mode": "rpc",
        "io_msg_type": "",
        "io_srv_type": "example/srv/Run",
        "source_toml_path": "example.v1.toml",
        "description": "Run an example.",
        "cross_namespace": False,
        "msg_fields": (),
        "srv_request_fields": (),
        "srv_response_fields": (),
    }
    if llm_callable is not None:
        values["llm_callable"] = llm_callable
    contract = SimpleNamespace(**values)
    contract.HasField = lambda name: name == "llm_callable" and llm_callable is not None
    return contract


def test_contract_descriptor_preserves_explicit_llm_visibility():
    assert not from_pb_contract(_pb_contract(llm_callable=False)).llm_callable
    assert from_pb_contract(_pb_contract(llm_callable=True)).llm_callable


def test_contract_descriptor_defaults_old_wire_to_visible():
    assert from_pb_contract(_pb_contract()).llm_callable


def test_contract_lookup_has_a_deadline():
    timeouts = []

    def query(request, *, timeout):
        timeouts.append(timeout)
        return SimpleNamespace(found=False)

    atlas = _Atlas()
    atlas._stub = SimpleNamespace(QueryContract=query)
    atlas._pb = SimpleNamespace(QueryContractRequest=SimpleNamespace)
    assert atlas.query_contract("robonix/skill/explore/explore") is None
    assert timeouts == [5.0]


def test_failed_startup_unregister_has_a_deadline():
    timeouts = []

    def unregister(request, *, timeout):
        timeouts.append(timeout)
        return SimpleNamespace(was_present=True)

    atlas = _Atlas()
    atlas._stub = SimpleNamespace(Unregister=unregister)
    atlas._pb = SimpleNamespace(UnregisterRequest=SimpleNamespace)
    assert atlas.unregister("explore")
    assert timeouts == [5.0]
