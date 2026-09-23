from __future__ import annotations

import copy
from typing import Any

from .candidate_anchor import build_candidate_discovery
from .canonical_resolution_gate import validate_canonical_resolution_proof
from .opportunity_domain import validate_product_opportunity
from .recovery_semantics_v63 import canonical_v63_wal_request_sha256, snapshot_sha256
from .runtime_durable_backend_v63 import V63_DURABLE_BACKEND_BINDING_STRATEGY, V63_DURABLE_BACKEND_SCHEMA
from .wal_contract_v63 import V63_WAL_BINDINGS, validate_v63_durable_event_proof


class ExistingProductionStoreBackend:
    backend_schema = V63_DURABLE_BACKEND_SCHEMA
    binding_strategy = V63_DURABLE_BACKEND_BINDING_STRATEGY
    parallel_state_store_allowed = False
    requires_existing_mutation_correlation = True
    raw_idempotency_key_persisted = False
    side_effect_reexecution_allowed = False

    @staticmethod
    def _investigation_id(arguments: dict[str, Any]) -> str:
        value = str(arguments.get('investigation_id') or '').strip()
        if not value:
            raise ValueError('investigation_id is required')
        return value

    @staticmethod
    def _append(runtime: Any, investigation_id: str, event_type: str, payload: dict[str, Any]) -> Any:
        store = getattr(runtime, 'store', None)
        append = getattr(store, 'append', None)
        if not callable(append):
            raise RuntimeError('V63_EXISTING_PRODUCTION_STORE_APPEND_UNAVAILABLE')
        return append(investigation_id, event_type, copy.deepcopy(payload))

    def append_candidate_discovery(self, runtime: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        args = copy.deepcopy(dict(arguments or {}))
        inv = self._investigation_id(args)
        candidate = build_candidate_discovery(dict(args.get('candidate') or {}))
        payload = {
            **copy.deepcopy(candidate),
            'investigation_id': inv,
            'request_sha256': canonical_v63_wal_request_sha256('append_candidate_discovery', args),
            'raw_idempotency_key_persisted': False,
        }
        self._append(runtime, inv, 'V63_CANDIDATE_DISCOVERED', payload)
        return {
            'status': 'DISCOVERED',
            'candidate_id': candidate['candidate_id'],
            'discovered_from_anchor_id': candidate['discovered_from_anchor_id'],
            'branch_group': candidate['branch_group'],
            'branch': candidate['branch'],
            'company_name': candidate['company_name'],
            'product_profile_id': candidate['product_profile_id'],
            'stage': candidate['stage'],
            'inherited_anchor_facts': candidate['inherited_anchor_facts'],
        }

    def create_product_opportunity(self, runtime: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        args = copy.deepcopy(dict(arguments or {}))
        inv = self._investigation_id(args)
        resolution = validate_canonical_resolution_proof(dict(args.get('canonical_resolution') or {}))
        if not resolution['opportunity_creation_allowed']:
            raise ValueError('canonical resolution blocked: ' + ','.join(resolution['blockers']))
        opportunity = copy.deepcopy(dict(args.get('opportunity') or {}))
        opportunity_id = str(opportunity.get('opportunity_id') or '').strip()
        account_id = str(opportunity.get('account_id') or '').strip()
        profile_id = str(opportunity.get('product_profile_id') or '').strip().upper()
        profile_version = str(opportunity.get('product_profile_version') or '').strip()
        profile_sha = str(opportunity.get('product_profile_sha256') or '').strip().lower()
        if not opportunity_id or not account_id or not profile_id or not profile_version or len(profile_sha) != 64:
            raise ValueError('opportunity identity and product profile pin are required')
        if str(resolution.get('canonical_account_id') or '') != account_id:
            raise ValueError('canonical account mismatch')
        result = {
            'status': 'CREATED', 'opportunity_id': opportunity_id, 'account_id': account_id,
            'product_profile_id': profile_id, 'product_profile_version': profile_version,
            'product_profile_sha256': profile_sha, 'stage': 'OPPORTUNITY_CREATED',
        }
        for name in ('application_ids','buyer_archetype_ids','market_cell_ids'):
            if name in opportunity:
                result[name] = copy.deepcopy(opportunity.get(name) or [])

        payload = {
            'investigation_id': inv,
            'request_sha256': canonical_v63_wal_request_sha256('create_product_opportunity', args),
            'canonical_resolution': copy.deepcopy(resolution),
            'opportunity': opportunity,
            'result_snapshot': copy.deepcopy(result),
            'result_snapshot_sha256': snapshot_sha256(result),
            'raw_idempotency_key_persisted': False,
        }

        store = getattr(runtime, "store", None)
        reader = getattr(store, "read", None)
        current_request_sha256 = str(payload["request_sha256"]).strip().lower()

        def replay_or_conflict(events: Any) -> dict[str, Any] | None:
            if not isinstance(events, list):
                return None
            matching_snapshots: list[dict[str, Any]] = []
            for existing_event in events:
                if not isinstance(existing_event, dict):
                    continue
                if str(existing_event.get("event_type") or "") != "V63_PRODUCT_OPPORTUNITY_CREATED":
                    continue
                # SessionStore envelopes the mutation payload under `payload`;
                # the fallback keeps small adapter fakes readable without ever
                # treating an unrelated top-level field as durable authority.
                event_payload = existing_event.get("payload")
                if not isinstance(event_payload, dict):
                    event_payload = existing_event
                existing_snapshot = event_payload.get("result_snapshot")
                if not isinstance(existing_snapshot, dict):
                    raise ValueError("V63_EXISTING_OPPORTUNITY_EVENT_INVALID")
                correlation = existing_event.get("mutation_correlation")
                if (
                    not isinstance(correlation, dict)
                    or correlation.get("schema") != "cbi.mutation-correlation.v6.1"
                    or correlation.get("tool") != "create_product_opportunity"
                    or not str(correlation.get("correlation_id") or "").strip()
                ):
                    raise ValueError(
                        "V63_EXISTING_OPPORTUNITY_EVENT_INVALID:CORRELATION_BINDING_INVALID"
                    )
                normalized_event = copy.deepcopy(event_payload)
                normalized_event["event_type"] = existing_event.get("event_type")
                normalized_event["correlation_id"] = correlation.get("correlation_id")
                proof = validate_v63_durable_event_proof(
                    V63_WAL_BINDINGS["create_product_opportunity"],
                    normalized_event,
                )
                if not proof["valid"]:
                    raise ValueError(
                        "V63_EXISTING_OPPORTUNITY_EVENT_INVALID:"
                        + ",".join(proof["blockers"])
                    )
                expected_snapshot_hash = str(
                    existing_snapshot.get("result_snapshot_sha256")
                    or event_payload.get("result_snapshot_sha256")
                    or ""
                ).lower()
                actual_snapshot_hash = snapshot_sha256(existing_snapshot).lower()
                if expected_snapshot_hash != actual_snapshot_hash:
                    raise ValueError("V63_EXISTING_OPPORTUNITY_SNAPSHOT_HASH_MISMATCH")
                try:
                    validate_product_opportunity({
                        **existing_snapshot,
                        "lifecycle_stage": str(
                            existing_snapshot.get("stage")
                            or existing_snapshot.get("lifecycle_stage")
                            or "OPPORTUNITY_CREATED"
                        ).upper(),
                    })
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError("V63_EXISTING_OPPORTUNITY_SNAPSHOT_INVALID") from exc
                if str(existing_snapshot.get("opportunity_id") or "").strip() != opportunity_id:
                    continue
                stored_request_sha256 = str(
                    event_payload.get("request_sha256") or ""
                ).strip().lower()
                if stored_request_sha256 != current_request_sha256:
                    raise ValueError("V63_OPPORTUNITY_IDENTITY_CONFLICT:request_sha256")
                matching_snapshots.append(copy.deepcopy(existing_snapshot))
            if len(matching_snapshots) > 1:
                raise ValueError("V63_OPPORTUNITY_DUPLICATE_DURABLE_PROOF")
            if not matching_snapshots:
                return None
            existing_snapshot = matching_snapshots[0]
            conflicts: list[str] = []
            for field in (
                "account_id",
                "product_profile_id",
                "product_profile_version",
                "product_profile_sha256",
                "application_ids",
                "buyer_archetype_ids",
                "market_cell_ids",
            ):
                if field not in result and field not in existing_snapshot:
                    continue
                left = result.get(field)
                right = existing_snapshot.get(field)
                if field == "product_profile_id":
                    left = str(left or "").upper()
                    right = str(right or "").upper()
                if left != right:
                    conflicts.append(field)
            if conflicts:
                raise ValueError(
                    "V63_OPPORTUNITY_IDENTITY_CONFLICT:" + ",".join(sorted(set(conflicts)))
                )
            replay = copy.deepcopy(existing_snapshot)
            replay["status"] = "REPLAYED"
            replay["replayed"] = True
            replay["persistent_mutation_performed"] = False
            return replay

        existing_events = reader(inv) if callable(reader) else []
        replay = replay_or_conflict(existing_events)
        if replay is not None:
            return replay

        # SessionStore exposes append_if_tail, which makes the identity check
        # and durable append a compare-and-swap.  A concurrent retry that loses
        # the CAS is reconciled from the now-authoritative event stream and is
        # returned as an exact replay instead of appending a duplicate.
        append_if_tail = getattr(store, "append_if_tail", None)
        tail_hash = None
        if isinstance(existing_events, list) and existing_events:
            tail_hash = str(existing_events[-1].get("event_hash") or "").strip()
        if callable(append_if_tail) and tail_hash:
            try:
                append_if_tail(inv, tail_hash, 'V63_PRODUCT_OPPORTUNITY_CREATED', payload)
            except Exception:
                refreshed = reader(inv) if callable(reader) else []
                replay = replay_or_conflict(refreshed)
                if replay is not None:
                    return replay
                raise
        elif isinstance(existing_events, list) and existing_events:
            raise RuntimeError("V63_ATOMIC_APPEND_UNAVAILABLE")
        else:
            # A store with no existing session tail can still be initialized by
            # its normal append primitive.  Once a durable chain exists, the
            # compare-and-swap above is mandatory to prevent duplicate creates.
            self._append(runtime, inv, 'V63_PRODUCT_OPPORTUNITY_CREATED', payload)
        return result

    def promote_opportunity_anchor(self, runtime: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        args = copy.deepcopy(dict(arguments or {}))
        inv = self._investigation_id(args)
        opportunity_id = str(args.get('opportunity_id') or '').strip()
        promotion_reason = str(args.get('promotion_reason') or '').strip()
        eligibility = copy.deepcopy(args.get('anchor_eligibility'))
        if not opportunity_id or not promotion_reason:
            raise ValueError('opportunity_id and promotion_reason are required')
        if not isinstance(eligibility, dict) or eligibility.get('anchor_eligible') is not True:
            raise ValueError('opportunity must be anchor eligible')
        if args.get('cycle_dedup_complete') is not True:
            raise ValueError('cycle dedup must be complete before anchor promotion')
        anchor_id = f'ANCHOR-{opportunity_id}'
        cycle = {'cycle_dedup_complete': True}
        payload = {
            'investigation_id': inv,
            'request_sha256': canonical_v63_wal_request_sha256('promote_opportunity_anchor', args),
            'opportunity_id': opportunity_id,
            'anchor_id': anchor_id,
            'promotion_reason': promotion_reason,
            'stage': 'PROMOTED_ANCHOR',
            'anchor_eligibility_snapshot': eligibility,
            'cycle_dedup_snapshot': cycle,
            'raw_idempotency_key_persisted': False,
        }
        self._append(runtime, inv, 'V63_OPPORTUNITY_ANCHOR_PROMOTED', payload)
        return {
            'status': 'PROMOTED', 'opportunity_id': opportunity_id, 'anchor_id': anchor_id,
            'promotion_reason': promotion_reason, 'stage': 'PROMOTED_ANCHOR',
            'anchor_eligibility_snapshot': eligibility, 'cycle_dedup_snapshot': cycle,
        }
