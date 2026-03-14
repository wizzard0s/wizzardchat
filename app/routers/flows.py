"""Flow Designer API – CRUD for flows, nodes, edges + bulk save + simulation."""

import copy
import re
from uuid import UUID
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from datetime import datetime, timedelta
from app.models import Flow, FlowNode, FlowEdge, FlowVersion, FlowNodeStats, FlowNodeVisitLog, User, FlowType, FlowStatus, Connector, Campaign, Outcome
from app.routers.node_types import ENTRY_NODE_KEYS
from app.schemas import (
    FlowCreate, FlowUpdate, FlowOut, FlowDetail,
    FlowNodeCreate, FlowNodeUpdate, FlowNodeOut,
    FlowEdgeCreate, FlowEdgeOut,
    FlowDesignerSave, DesignerEdgeRef,
    FlowSimulateRequest, FlowSimulateResponse, SimulateStep,
    FlowVersionOut,
)
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/flows",
    tags=["flows"],
    dependencies=[Depends(get_current_user)],
)


# ──────────── Version helpers ────────────

def _next_save_version(version: str) -> str:
    """Increment the minor part of a 'major.minor' version string."""
    try:
        major, minor = version.split(".")
        return f"{int(major)}.{int(minor) + 1}"
    except Exception:
        return "1.1"  # fallback for malformed legacy values


def _next_publish_version(version: str) -> str:
    """Increment the major part and reset minor to 0."""
    try:
        major = version.split(".")[0]
        return f"{int(major) + 1}.0"
    except Exception:
        return "2.0"


# ──────────── Flow CRUD ────────────

@router.get("", response_model=List[FlowOut])
async def list_flows(
    name: str | None = None,
    status: FlowStatus | None = None,
    flow_type: FlowType | None = None,
    published_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    query = select(Flow)
    if name:
        query = query.where(Flow.name.ilike(f"%{name}%"))
    if status:
        query = query.where(Flow.status == status)
    if flow_type:
        query = query.where(Flow.flow_type == flow_type)
    if published_only:
        query = query.where(Flow.is_published == True)
    result = await db.execute(query.order_by(Flow.updated_at.desc()))
    return [FlowOut.model_validate(f) for f in result.scalars().all()]


@router.post("", response_model=FlowDetail, status_code=201)
async def create_flow(
    body: FlowCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    flow = Flow(name=body.name, description=body.description, channel=body.channel, flow_type=body.flow_type, created_by=user.id)
    # Add default start node
    start_node = FlowNode(node_type="start", label="Start", position_x=250, position_y=50, position=0, config={})
    flow.nodes.append(start_node)
    db.add(flow)
    await db.flush()
    await db.refresh(flow, attribute_names=["nodes", "edges"])
    return FlowDetail.model_validate(flow)


@router.get("/{flow_id}", response_model=FlowDetail)
async def get_flow(flow_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Flow)
        .where(Flow.id == flow_id)
        .options(selectinload(Flow.nodes), selectinload(Flow.edges))
    )
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return FlowDetail.model_validate(flow)


@router.patch("/{flow_id}", response_model=FlowOut)
async def update_flow(flow_id: UUID, body: FlowUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Flow).where(Flow.id == flow_id))
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(flow, field, value)
    await db.flush()
    await db.refresh(flow)
    return FlowOut.model_validate(flow)


@router.get("/{flow_id}/usage")
async def get_flow_usage(flow_id: UUID, db: AsyncSession = Depends(get_db)):
    """Return every entity that references this flow so the UI can warn before deletion."""
    # Connectors that route to this flow
    conn_result = await db.execute(
        select(Connector.id, Connector.name, Connector.is_active)
        .where(Connector.flow_id == flow_id)
    )
    connectors = [
        {"id": str(r.id), "name": r.name, "is_active": r.is_active}
        for r in conn_result.all()
    ]

    # Flows that contain a sub_flow node pointing to this flow.
    # config is JSONB so we use the ->> operator via text().
    from sqlalchemy import text as sa_text
    subflow_result = await db.execute(
        select(Flow.id, Flow.name, FlowNode.label)
        .join(FlowNode, FlowNode.flow_id == Flow.id)
        .where(
            FlowNode.node_type == "sub_flow",
            sa_text("flow_nodes.config->>'flow_id' = :fid").bindparams(fid=str(flow_id)),
        )
    )
    sub_flow_parents = [
        {"flow_id": str(r.id), "flow_name": r.name, "node_label": r.label or "(unlabelled)"}
        for r in subflow_result.all()
    ]

    # Campaigns that directly reference this flow
    camp_result = await db.execute(
        select(Campaign.id, Campaign.name)
        .where(Campaign.flow_id == flow_id)
    )
    campaigns = [{"id": str(r.id), "name": r.name} for r in camp_result.all()]

    # Outcomes that redirect to this flow
    outcome_result = await db.execute(
        select(Outcome.id, Outcome.label)
        .where(Outcome.redirect_flow_id == flow_id)
    )
    outcomes = [{"id": str(r.id), "label": r.label} for r in outcome_result.all()]

    return {
        "connectors": connectors,
        "sub_flow_parents": sub_flow_parents,
        "campaigns": campaigns,
        "outcomes": outcomes,
    }


@router.delete("/{flow_id}", status_code=204)
async def delete_flow(flow_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Flow).where(Flow.id == flow_id))
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    await db.delete(flow)
    await db.commit()


@router.post("/{flow_id}/clone", response_model=FlowDetail, status_code=201)
async def clone_flow(
    flow_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a full copy of a flow with all its nodes and edges."""
    result = await db.execute(
        select(Flow).where(Flow.id == flow_id)
        .options(selectinload(Flow.nodes), selectinload(Flow.edges))
    )
    src = result.scalar_one_or_none()
    if not src:
        raise HTTPException(status_code=404, detail="Flow not found")

    # Create new flow record (start fresh: draft, not published)
    clone = Flow(
        name=f"{src.name} (copy)",
        description=src.description,
        channel=src.channel,
        flow_type=src.flow_type,
        status=FlowStatus.DRAFT,
        is_active=False,
        is_published=False,
        version="1.0",
        disconnect_timeout_seconds=src.disconnect_timeout_seconds,
        disconnect_outcome_id=src.disconnect_outcome_id,
        created_by=user.id,
    )
    db.add(clone)
    await db.flush()
    await db.refresh(clone)

    # Copy nodes and build old-id → new-id map for edge resolution
    id_map: dict[str, str] = {}
    for n in src.nodes:
        new_node = FlowNode(
            flow_id=clone.id,
            node_type=n.node_type,
            label=n.label,
            position_x=n.position_x,
            position_y=n.position_y,
            position=n.position,
            config=n.config,
        )
        db.add(new_node)
        await db.flush()
        await db.refresh(new_node)
        id_map[str(n.id)] = str(new_node.id)

    # Copy edges using the id map
    for e in src.edges:
        src_id = id_map.get(str(e.source_node_id))
        tgt_id = id_map.get(str(e.target_node_id))
        if src_id and tgt_id:
            db.add(FlowEdge(
                flow_id=clone.id,
                source_node_id=src_id,
                target_node_id=tgt_id,
                source_handle=e.source_handle,
                label=e.label,
                condition=e.condition,
                priority=e.priority,
            ))

    await db.flush()
    result2 = await db.execute(
        select(Flow).where(Flow.id == clone.id)
        .options(selectinload(Flow.nodes), selectinload(Flow.edges))
    )
    return FlowDetail.model_validate(result2.scalar_one())


# ──────────── Bulk save from designer ────────────

@router.put("/{flow_id}/designer", response_model=FlowDetail)
async def save_flow_from_designer(
    flow_id: UUID,
    body: FlowDesignerSave,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Replace all nodes & edges with the state from the visual designer."""
    result = await db.execute(
        select(Flow).where(Flow.id == flow_id).options(selectinload(Flow.nodes), selectinload(Flow.edges))
    )
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    # Update flow metadata if provided
    if body.name is not None:
        flow.name = body.name
    if body.description is not None:
        flow.description = body.description
    if body.channel is not None:
        flow.channel = body.channel

    flow.updated_by = user.id
    old_version = flow.version  # capture before bumping
    flow.version = _next_save_version(old_version)
    flow.is_restored = False     # a fresh save clears the restored marker

    # ── Snapshot current nodes+edges BEFORE overwriting ──────────────────────
    snapshot_nodes = [
        {
            "id": str(n.id), "node_type": n.node_type, "label": n.label,
            "position_x": n.position_x, "position_y": n.position_y,
            "position": n.position, "config": n.config,
        }
        for n in flow.nodes
    ]
    snapshot_edges = [
        {
            "id": str(e.id), "source_node_id": str(e.source_node_id),
            "target_node_id": str(e.target_node_id),
            "source_handle": e.source_handle, "label": e.label,
            "condition": e.condition, "priority": e.priority,
        }
        for e in flow.edges
    ]
    if snapshot_nodes:  # don't snapshot an empty flow
        version_record = FlowVersion(
            flow_id=flow_id,
            version_number=old_version,  # label with the version we're replacing
            label=flow.name,
            snapshot={"nodes": snapshot_nodes, "edges": snapshot_edges},
            saved_at=datetime.utcnow(),
            saved_by=user.id,
        )
        db.add(version_record)

    # Clear stale node stats — IDs change on every save
    await db.execute(delete(FlowNodeStats).where(FlowNodeStats.flow_id == flow_id))

    # Delete old nodes & edges
    await db.execute(delete(FlowEdge).where(FlowEdge.flow_id == flow_id))
    await db.execute(delete(FlowNode).where(FlowNode.flow_id == flow_id))
    await db.flush()

    # Create new nodes & collect temp-id → real-id mapping
    node_map: dict[str, UUID] = {}  # temp client id → db UUID
    new_nodes = []
    for idx, n in enumerate(body.nodes):
        node = FlowNode(
            flow_id=flow_id,
            node_type=n.node_type,
            label=n.label,
            position_x=n.position_x,
            position_y=n.position_y,
            position=n.position or idx,
            config=n.config,
        )
        db.add(node)
        new_nodes.append(node)
    await db.flush()

    # Map: the designer sends node IDs that match the previous DB ids or temp ids.
    # We rely on list-order matching for the mapping.
    for idx, node in enumerate(new_nodes):
        await db.refresh(node)
        # If the designer sent a UUID in 'config._clientId', use it for mapping
        client_id = body.nodes[idx].config.get("_clientId", str(body.nodes[idx].position))
        node_map[client_id] = node.id
        # Also map by old id if present
        old_id = body.nodes[idx].config.get("_dbId")
        if old_id:
            node_map[old_id] = node.id

    # Create edges – resolve client-side IDs (temp_1, DB UUIDs) via node_map
    for e in body.edges:
        src = node_map.get(e.source_node_id)
        tgt = node_map.get(e.target_node_id)
        if not src or not tgt:
            # Skip edges with unresolvable references
            continue
        edge = FlowEdge(
            flow_id=flow_id,
            source_node_id=src,
            target_node_id=tgt,
            source_handle=e.source_handle,
            label=e.label,
            condition=e.condition,
            priority=e.priority,
        )
        db.add(edge)
    await db.flush()

    # Reload full flow
    result2 = await db.execute(
        select(Flow).where(Flow.id == flow_id).options(selectinload(Flow.nodes), selectinload(Flow.edges))
    )
    flow = result2.scalar_one()
    return FlowDetail.model_validate(flow)


# ──────────── Publish / activate ────────────

@router.post("/{flow_id}/publish", response_model=FlowOut)
async def publish_flow(flow_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Flow).where(Flow.id == flow_id).options(selectinload(Flow.nodes))
    )
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    if len(flow.nodes) < 2:
        raise HTTPException(status_code=400, detail="Flow needs at least a start and one other node")
    flow.is_published = True
    flow.is_active = True
    flow.status = FlowStatus.ACTIVE
    flow.version = _next_publish_version(flow.version)
    flow.published_version = flow.version
    flow.is_restored = False
    await db.commit()
    await db.refresh(flow)
    return FlowOut.model_validate(flow)


# ──────────── Individual Node CRUD ────────────

@router.post("/{flow_id}/nodes", response_model=FlowNodeOut, status_code=201)
async def add_node(flow_id: UUID, body: FlowNodeCreate, db: AsyncSession = Depends(get_db)):
    node = FlowNode(flow_id=flow_id, **body.model_dump())
    db.add(node)
    await db.flush()
    await db.refresh(node)
    return FlowNodeOut.model_validate(node)


@router.patch("/{flow_id}/nodes/{node_id}", response_model=FlowNodeOut)
async def update_node(flow_id: UUID, node_id: UUID, body: FlowNodeUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FlowNode).where(FlowNode.id == node_id, FlowNode.flow_id == flow_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(node, field, value)
    await db.flush()
    await db.refresh(node)
    return FlowNodeOut.model_validate(node)


@router.delete("/{flow_id}/nodes/{node_id}", status_code=204)
async def delete_node(flow_id: UUID, node_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FlowNode).where(FlowNode.id == node_id, FlowNode.flow_id == flow_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await db.delete(node)


# ──────────── Edge CRUD ────────────

@router.post("/{flow_id}/edges", response_model=FlowEdgeOut, status_code=201)
async def add_edge(flow_id: UUID, body: FlowEdgeCreate, db: AsyncSession = Depends(get_db)):
    edge = FlowEdge(flow_id=flow_id, **body.model_dump())
    db.add(edge)
    await db.flush()
    await db.refresh(edge)
    return FlowEdgeOut.model_validate(edge)


@router.delete("/{flow_id}/edges/{edge_id}", status_code=204)
async def delete_edge(flow_id: UUID, edge_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FlowEdge).where(FlowEdge.id == edge_id, FlowEdge.flow_id == flow_id)
    )
    edge = result.scalar_one_or_none()
    if not edge:
        raise HTTPException(status_code=404, detail="Edge not found")
    await db.delete(edge)


# ──────────────── Flow Simulator ────────────────

# JSONata builtins that start with $ — do NOT substitute these as context vars
_JSONATA_BUILTINS = {
    'string','length','substring','substringBefore','substringAfter','contains','split',
    'join','uppercase','lowercase','trim','pad','match','replace','now','millis',
    'fromMillis','toMillis','number','abs','floor','ceil','round','power','sqrt',
    'random','boolean','not','exists','count','append','reverse','sort','zip','keys',
    'values','lookup','merge','sift','each','error','assert','type','isError',
    'toBase64','fromBase64','encodeUrl','decodeUrl','encodeUrlComponent','decodeUrlComponent',
    'base64encode','base64decode',
}


def _substitute_context_vars(expr: str, ctx: dict) -> str:
    """Replace $varName (where varName is a context key, not a JSONata builtin/function)
    with the actual context value, so users can write $myVar instead of $.myVar."""
    def replacer(m: re.Match) -> str:
        name = m.group(1)
        if name in _JSONATA_BUILTINS:
            return m.group(0)  # leave built-ins alone
        if name not in ctx:
            return m.group(0)  # not in context either — leave as-is
        val = ctx[name]
        if val is None:
            return 'null'
        if isinstance(val, bool):
            return 'true' if val else 'false'
        if isinstance(val, (int, float)):
            return str(val)
        escaped = str(val).replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'

    # Match $identifier NOT followed by ( — those are function calls
    return re.sub(r'\$([a-zA-Z_][a-zA-Z0-9_]*)(?!\s*\()', replacer, expr)


def _resolve_template(text: str, ctx: dict) -> str:
    """Resolve {{varName}} and $varName placeholders in plain text strings."""
    if not text:
        return text
    # {{varName}} style
    def repl_braces(m: re.Match) -> str:
        val = _resolve_path(ctx, m.group(1).strip())
        return str(val) if val is not None else m.group(0)
    text = re.sub(r'\{\{([^}]+)\}\}', repl_braces, text)
    # $varName style (only if key is in context)
    def repl_dollar(m: re.Match) -> str:
        name = m.group(1)
        if name in _JSONATA_BUILTINS or name not in ctx:
            return m.group(0)
        val = ctx[name]
        return str(val) if val is not None else m.group(0)
    text = re.sub(r'\$([a-zA-Z_][a-zA-Z0-9_]*)', repl_dollar, text)
    return text


def _resolve_path(ctx: dict, path: str) -> Any:
    """Resolve a dot-notation path (e.g. 'contact.name') in a nested dict."""
    parts = path.strip().split(".")
    val: Any = ctx
    for part in parts:
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return None
    return val


def _set_path(ctx: dict, path: str, value: Any) -> None:
    """Set a value at a dot-notation path, creating intermediary dicts as needed."""
    parts = path.strip().split(".")
    d = ctx
    for part in parts[:-1]:
        if part not in d or not isinstance(d[part], dict):
            d[part] = {}
        d = d[part]
    d[parts[-1]] = value


def _evaluate_condition(ctx: dict, config: dict) -> bool:
    """Evaluate a condition node config against the current context."""
    variable = config.get("variable", "")
    operator = config.get("operator", "equals")
    compare_value = config.get("value", "")

    actual = _resolve_path(ctx, variable)

    if operator == "is_empty":
        return actual is None or actual == "" or actual == [] or actual == {}
    if operator == "is_not_empty":
        return not (actual is None or actual == "" or actual == [] or actual == {})
    if operator == "is_array":
        return isinstance(actual, list)
    if operator == "is_not_array":
        return not isinstance(actual, list)
    if operator == "is_object":
        return isinstance(actual, dict)
    if operator == "is_not_object":
        return not isinstance(actual, dict)
    if operator == "is_true":
        return actual is True or str(actual).lower() in ("true", "1", "yes")
    if operator == "is_false":
        return actual is False or actual is None or str(actual).lower() in ("false", "0", "no", "")

    actual_str = str(actual).lower() if actual is not None else ""
    compare_str = str(compare_value).lower()

    if operator == "equals":
        return actual_str == compare_str
    if operator == "not_equals":
        return actual_str != compare_str
    if operator == "contains":
        return compare_str in actual_str
    if operator == "not_contains":
        return compare_str not in actual_str
    if operator == "starts_with":
        return actual_str.startswith(compare_str)
    if operator == "ends_with":
        return actual_str.endswith(compare_str)
    if operator in ("greater_than", "less_than"):
        try:
            a, b = float(actual), float(compare_value)
            return a > b if operator == "greater_than" else a < b
        except (TypeError, ValueError):
            return actual_str > compare_str if operator == "greater_than" else actual_str < compare_str
    if operator == "regex":
        try:
            return bool(re.search(compare_value, str(actual or "")))
        except re.error:
            return False
    return False


def _apply_set_variable(ctx: dict, config: dict) -> dict:
    """Apply set_variable node: update context with new field values."""
    new_ctx = copy.deepcopy(ctx)
    fields = config.get("fields", [])

    for field in fields:
        name = (field.get("name") or "").strip()
        if not name:
            continue
        value = field.get("value")
        input_mode = field.get("input_mode", "text")

        if input_mode == "expression":
            expr_str = str(value or "")
            # Use new_ctx so fields set earlier in the SAME node are visible
            expr_resolved = _substitute_context_vars(expr_str, new_ctx)
            try:
                import jsonata as _jsonata  # type: ignore
                value = _jsonata.Jsonata(expr_resolved).evaluate(new_ctx)
            except ImportError:
                # Fallback: plain template substitution (also uses new_ctx)
                value = _resolve_template(expr_str, new_ctx)
            except Exception as e:
                value = f"<error:{e}> (expr: {expr_resolved})"
        else:
            # Text mode: still interpolate $varName and {{varName}} placeholders
            if isinstance(value, str):
                value = _resolve_template(value, new_ctx)

        _set_path(new_ctx, name, value)
    return new_ctx


def _diff_context(before: dict, after: dict) -> List[dict]:
    """Return a list of changed keys between two flat/nested dicts (top-level keys only)."""
    changes = []
    all_keys = set(before) | set(after)
    for k in sorted(all_keys):
        b_val = before.get(k)
        a_val = after.get(k)
        if b_val != a_val:
            changes.append({"key": k, "before": b_val, "after": a_val})
    return changes


@router.post("/{flow_id}/simulate", response_model=FlowSimulateResponse)
async def simulate_flow(
    flow_id: UUID,
    body: FlowSimulateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Dry-run a flow. Applies node logic (conditions, set_variable, etc.) without
    making real external calls. Input/menu/dtmf nodes use the supplied `inputs` dict;
    if an input is missing the trace halts with status='blocked'.
    """
    flow_result = await db.execute(
        select(Flow)
        .where(Flow.id == flow_id)
        .options(selectinload(Flow.nodes), selectinload(Flow.edges))
    )
    flow = flow_result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    # Build look-up maps
    node_map: dict[str, FlowNode] = {str(n.id): n for n in flow.nodes}
    edges_from: dict[str, list[FlowEdge]] = {}
    for e in flow.edges:
        src = str(e.source_node_id)
        edges_from.setdefault(src, []).append(e)

    # Find start node — accepts any entry-point node type
    # If entry_node_id is provided, use that specific node; otherwise fall back to first entry node
    entry_nodes = [n for n in flow.nodes if n.node_type in ENTRY_NODE_KEYS]
    if not entry_nodes:
        raise HTTPException(status_code=400, detail="Flow has no entry node (start, start_chat, start_whatsapp, start_api, or start_voice)")

    if body.entry_node_id:
        start_node = next((n for n in entry_nodes if str(n.id) == body.entry_node_id), None)
        if not start_node:
            raise HTTPException(status_code=400, detail=f"Entry node '{body.entry_node_id}' not found in this flow")
    else:
        start_node = entry_nodes[0]  # Default: first entry node

    context: dict = copy.deepcopy(body.context)
    inputs: dict = dict(body.inputs)
    trace: list[SimulateStep] = []
    current: FlowNode | None = start_node
    max_steps = 60
    step_num = 0
    sim_status = "completed"
    sim_message: str | None = None

    while current is not None and step_num < max_steps:
        step_num += 1
        nid = str(current.id)
        ntype = current.node_type
        label = current.label or ntype
        cfg = current.config or {}
        ctx_before = copy.deepcopy(context)
        output: str | None = None
        edge_taken: str | None = None
        step_status = "executed"
        note: str | None = None
        halt = False

        # ── Node-type handling ──────────────────────────────────────────────
        if ntype in ENTRY_NODE_KEYS:
            if ntype == "start":
                trigger = cfg.get("trigger", "inbound_call")
                note = f"Flow started — trigger: {trigger}"
            elif ntype == "start_chat":
                label = cfg.get("entry_label") or "Chat Entry"
                connector = cfg.get("connector_id") or "any connector"
                note = f"Flow started — inbound chat via {label} (connector: {connector})"
            elif ntype == "start_whatsapp":
                label = cfg.get("entry_label") or "WhatsApp Entry"
                note = f"Flow started — inbound WhatsApp message via {label}"
            elif ntype == "start_api":
                key = cfg.get("trigger_key") or "(no key set)"
                note = f"Flow started — API trigger key: {key}"
            elif ntype == "start_voice":
                label = cfg.get("entry_label") or "Voice Entry"
                did = cfg.get("did_number") or "any DID"
                note = f"Flow started — inbound voice call via {label} (DID: {did})"
                # Pre-populate caller variables for simulation
                if cfg.get("caller_id_variable"):
                    context.setdefault(cfg["caller_id_variable"], "+27 00 000 0000")
                if cfg.get("dialled_variable"):
                    context.setdefault(cfg["dialled_variable"], did)
            else:
                note = f"Flow started — entry: {ntype}"

        elif ntype == "end":
            step_status = "end"
            end_status = cfg.get("status", "completed")
            end_msg = cfg.get("message") or ""
            output = end_msg or None
            note = f"Flow ended — status: {end_status}"
            halt = True

        elif ntype == "message":
            text = _resolve_template(cfg.get("text") or cfg.get("message", ""), context)
            output = text or None
            note = "Message sent to contact"

        elif ntype == "input":
            var = cfg.get("variable", "user_input")
            prompt = cfg.get("prompt", "")
            max_retries = int(cfg.get("max_retries", 3) or 3)
            retry_key = f"_retries_{nid}"
            if nid in inputs:
                context[var] = inputs[nid]
                context.pop(retry_key, None)  # reset counter on successful input
                output = prompt
                note = f"User responded: {inputs[nid]!r}  →  saved to {var!r}  →  edge 'default'"
            else:
                retries = context.get(retry_key, 0)
                if retries >= max_retries:
                    context.pop(retry_key, None)
                    edge_taken = "timeout"
                    note = (f"Input retry limit reached ({max_retries})  →  edge 'timeout' "
                            f"(no valid response for {var!r})")
                else:
                    context[retry_key] = retries + 1
                    step_status = "needs_input"
                    note = (f"Waiting for user input — prompt: {prompt!r}  →  variable: {var!r} "
                            f"(attempt {retries + 1}/{max_retries})")
                    sim_status = "blocked"
                    sim_message = f"'{label}' needs input for variable '{var}'"
                    halt = True

        elif ntype == "menu":
            prompt = cfg.get("prompt", "")
            opts = cfg.get("options", [])
            if nid in inputs:
                chosen = str(inputs[nid])
                context["menu_choice"] = chosen
                opt_label = next((o.get("text", "") for o in opts if str(o.get("key")) == chosen), chosen)
                output = prompt
                note = f"User chose key {chosen!r} ({opt_label})"
            else:
                step_status = "needs_input"
                choices = ", ".join(f"{o.get('key')}={o.get('text')}" for o in opts)
                note = f"Waiting for menu choice — options: [{choices}]"
                sim_status = "blocked"
                sim_message = f"'{label}' needs a menu selection"
                halt = True

        elif ntype == "dtmf":
            var = cfg.get("variable", "dtmf_input")
            max_digits = cfg.get("max_digits", 1)
            if nid in inputs:
                context[var] = str(inputs[nid])
                note = f"DTMF received: {inputs[nid]!r}  →  {var!r}"
            else:
                step_status = "needs_input"
                note = f"Waiting for DTMF input (max {max_digits} digit{'s' if max_digits != 1 else ''})  →  {var!r}"
                sim_status = "blocked"
                sim_message = f"'{label}' needs DTMF input"
                halt = True

        elif ntype == "condition":
            # Resolve $var in the compare-value too
            resolved_cfg = dict(cfg)
            resolved_cfg["value"] = _resolve_template(str(cfg.get("value", "")), context)
            result_bool = _evaluate_condition(context, resolved_cfg)
            edge_taken = "true" if result_bool else "false"
            var = cfg.get("variable", "")
            op = cfg.get("operator", "equals")
            val = resolved_cfg["value"]
            actual = _resolve_path(context, var)
            note = f"Condition: {var!r} ({actual!r}) {op} {val!r}  →  {result_bool} → edge '{edge_taken}'"
        elif ntype == "ab_split":
            import random as _random
            split_percent = float(cfg.get("split_percent", 50))
            tag_a = cfg.get("tag_a") or "branch_a"
            tag_b = cfg.get("tag_b") or "branch_b"
            if _random.random() * 100 < split_percent:
                edge_taken = "branch_a"
                context["_ab_variant"] = tag_a
                note = f"A/B Split: rolled into Branch A ({split_percent}%) → tag set to {tag_a!r}"
            else:
                edge_taken = "branch_b"
                context["_ab_variant"] = tag_b
                note = f"A/B Split: rolled into Branch B ({100 - split_percent}%) → tag set to {tag_b!r}"
        elif ntype == "loop":
            array_var = cfg.get("array_variable", "")
            item_var = cfg.get("item_variable", "item") or "item"
            index_var = cfg.get("index_variable", "loop_index") or "loop_index"
            max_iter = int(cfg.get("max_iterations", 50) or 50)
            state_key = f"_loop_{nid}"
            arr = _resolve_path(context, array_var)
            if not isinstance(arr, list):
                context.pop(state_key, None)
                edge_taken = "done"
                note = f"Loop: '{array_var}' is not an array → skipping to 'done'"
            else:
                idx = context.get(state_key, 0)
                if idx >= len(arr) or idx >= max_iter:
                    context.pop(state_key, None)
                    edge_taken = "done"
                    note = f"Loop: completed all {idx} iteration(s) → 'done'"
                else:
                    context[item_var] = arr[idx]
                    context[index_var] = idx
                    context[state_key] = idx + 1
                    edge_taken = "loop"
                    note = f"Loop: iteration {idx + 1}/{len(arr)} — {item_var}={arr[idx]!r}, {index_var}={idx}"
        elif ntype == "time_gate":
            from datetime import datetime as _dt
            from zoneinfo import ZoneInfo as _ZI
            tz_name = cfg.get("timezone", "Africa/Johannesburg") or "Africa/Johannesburg"
            try:
                _tz = _ZI(tz_name)
            except Exception:
                _tz = _ZI("Africa/Johannesburg")
            _now = _dt.now(_tz)
            _day_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
            _today = _day_map[_now.weekday()]
            _raw_days = cfg.get("days", "Mon,Tue,Wed,Thu,Fri") or "Mon,Tue,Wed,Thu,Fri"
            _allowed = [d.strip() for d in _raw_days.split(",") if d.strip()]
            try:
                _sh, _sm = (int(x) for x in cfg.get("start_time", "08:00").split(":"))
                _eh, _em = (int(x) for x in cfg.get("end_time", "17:00").split(":"))
                _now_m = _now.hour * 60 + _now.minute
                _is_open = _today in _allowed and (_sh * 60 + _sm) <= _now_m < (_eh * 60 + _em)
            except Exception:
                _is_open = False
            edge_taken = "open" if _is_open else "closed"
            note = (f"Time Gate: {_today} {_now.strftime('%H:%M')} {tz_name} → "
                    f"schedule {cfg.get('days', 'Mon-Fri')} "
                    f"{cfg.get('start_time','08:00')}-{cfg.get('end_time','17:00')} "
                    f"→ '{edge_taken}'")
        elif ntype == "switch":
            cases = cfg.get("cases") or []
            chosen_handle = "default"
            matched_label = None
            for idx, case_def in enumerate(cases):
                conditions = case_def.get("conditions")
                if conditions:
                    var_conditions = [c for c in conditions if c.get("variable")]
                    case_matched = bool(var_conditions) and all(
                        _evaluate_condition(context, {
                            "variable": cond.get("variable", ""),
                            "operator": cond.get("operator", "equals"),
                            "value": _resolve_template(str(cond.get("value", "")), context),
                        })
                        for cond in var_conditions
                    )
                else:  # legacy single-condition
                    legacy_var = cfg.get("variable", "")
                    case_matched = _evaluate_condition(context, {
                        "variable": legacy_var,
                        "operator": case_def.get("operator", "equals"),
                        "value": _resolve_template(str(case_def.get("value", "")), context),
                    })
                if case_matched:
                    chosen_handle = f"case_{idx}"
                    matched_label = case_def.get("label", f"case_{idx}")
                    break
            edge_taken = chosen_handle
            if chosen_handle == "default":
                note = "Switch: no case matched \u2192 edge 'default'"
            else:
                case_idx_num = int(chosen_handle.split('_')[1])
                cond_parts = cases[case_idx_num].get('conditions') or []
                cond_summary = "; ".join(
                    f"{c.get('variable')} {c.get('operator')} {c.get('value','')!r}"
                    for c in cond_parts if c.get('variable')
                )
                note = f"Switch: case '{matched_label}' matched ({cond_summary}) \u2192 edge '{chosen_handle}'"
        elif ntype == "set_variable":
            context = _apply_set_variable(context, cfg)
            fields = cfg.get("fields", [])
            names = [f.get("name", "?") for f in fields if f.get("name")]
            note = f"Set variable(s): {', '.join(names)}"

        elif ntype == "wait":
            duration = cfg.get("duration", 5)
            note = f"Wait {duration}s (simulated — not actually paused)"

        elif ntype == "play_audio":
            url = cfg.get("audio_url", "")
            note = f"Playing audio: {url}"

        elif ntype == "record":
            var = cfg.get("variable", "recording_url")
            duration = cfg.get("max_duration", 60)
            context[var] = "__simulated_recording.wav"
            note = f"Recording simulated ({duration}s max)  →  {var!r}"

        elif ntype == "http_request":
            method = cfg.get("method", "GET")
            url = _resolve_template(cfg.get("url", ""), context)
            resp_var = cfg.get("response_var", "") or cfg.get("response_variable", "")
            err_var = cfg.get("error_variable", "")
            # Simulation always succeeds (200) so the happy path is exercised by default
            sim_status_code = 200
            if sim_status_code >= 200 and sim_status_code < 300:
                edge_taken = "success"
                if resp_var:
                    context[resp_var] = {"__simulated": True, "status": sim_status_code, "body": {}}
                step_status = "external"
                note = f"HTTP {method} {url!r}  →  simulated {sim_status_code} → edge 'success'"
                if resp_var:
                    note += f"  →  {resp_var!r} set to simulated response"
            else:
                edge_taken = "error"
                if err_var:
                    context[err_var] = {"__simulated": True, "status": sim_status_code,
                                        "error": f"HTTP {sim_status_code}"}
                step_status = "external"
                note = f"HTTP {method} {url!r}  →  simulated {sim_status_code} → edge 'error'"
                if err_var:
                    note += f"  →  {err_var!r} set to error details"

        elif ntype == "webhook":
            method = cfg.get("method", "POST")
            url = _resolve_template(cfg.get("url", ""), context)
            step_status = "external"
            note = f"Webhook {method} {url!r}  →  not called in simulation"

        elif ntype == "ai_bot":
            model = cfg.get("model", "gpt-4o")
            out_var = cfg.get("output_variable", "")
            if out_var:
                context[out_var] = "[AI response — simulated]"
            step_status = "external"
            note = f"AI Bot ({model}) simulated"

        elif ntype == "kb_search":
            query_var  = cfg.get("query_variable", "user_input")
            result_var = cfg.get("result_variable", "kb_result")
            found_var  = cfg.get("found_variable", "kb_found")
            query_val  = context.get(query_var, query_var)
            context[result_var] = {
                "__simulated": True,
                "title":   "Simulated KB Article",
                "url":     "https://help.mweb.co.za/hc/en-us/articles/example",
                "excerpt": "This is a simulated knowledge-base result.",
            }
            context[found_var] = True
            note = (
                f"KB search: {query_var}={query_val!r} "
                f"→ {result_var!r} set to simulated article, {found_var!r}=True"
            )

        elif ntype == "queue":
            queue_name = cfg.get("queue_name", "")
            priority = cfg.get("priority", 0)
            step_status = "external"
            note = f"Queued to '{queue_name}' (priority {priority}) — not executed in simulation"

        elif ntype == "transfer":
            target = cfg.get("target", "")
            ttype = cfg.get("transfer_type", "blind")
            step_status = "external"
            note = f"Transfer ({ttype}) to '{target}' — not executed in simulation"

        elif ntype == "sub_flow":
            sub_id = cfg.get("flow_id", "")
            out_var = cfg.get("output_variable", "")
            if out_var:
                context[out_var] = "__sub_flow_result"
            step_status = "external"
            note = f"Sub-flow '{sub_id}' — not executed in simulation"

        elif ntype == "goto":
            target = cfg.get("target_node", "")
            note = f"GoTo node '{target}'"

        elif ntype == "translate":
            mode       = cfg.get("mode", "translate")
            input_var  = cfg.get("input_variable", "message")
            result_var = cfg.get("result_variable", "translated_text")
            lang_var   = cfg.get("language_variable", "contact.language")
            target_lang = _resolve_template(cfg.get("target_language", "en"), context)
            input_text  = str(_resolve_path(context, input_var) or "").strip() or "sample text"
            if mode == "detect_only":
                _set_path(context, lang_var, "en")
                edge_taken = "success"
                step_status = "external"
                note = (
                    f"Detect-only: {input_var}={input_text!r:.40} "
                    f"→ {lang_var!r}='en' (simulated)"
                )
            else:
                _set_path(context, result_var, f"[Translated to {target_lang}: {input_text[:40]}]")
                _set_path(context, lang_var, "en")  # simulated detected source
                edge_taken = "success"
                step_status = "external"
                note = (
                    f"Translate {input_var}={input_text!r:.40} → {target_lang!r} "
                    f"→ {result_var!r} set (simulated), {lang_var!r}='en'"
                )

        else:
            note = f"Unknown node type '{ntype}' — skipped"

        # ── Resolve next node ───────────────────────────────────────────────
        ctx_after = copy.deepcopy(context)
        outgoing = edges_from.get(nid, [])
        next_node: FlowNode | None = None

        if not halt:
            if edge_taken:
                chosen_edge = next((e for e in outgoing if e.source_handle == edge_taken), None)
            else:
                # Prefer 'default' handle, then any edge
                chosen_edge = (
                    next((e for e in outgoing if e.source_handle == "default"), None)
                    or (outgoing[0] if outgoing else None)
                )
                if chosen_edge:
                    edge_taken = chosen_edge.source_handle or "default"

            if chosen_edge:
                next_node = node_map.get(str(chosen_edge.target_node_id))

        # ── Append step ─────────────────────────────────────────────────────
        trace.append(SimulateStep(
            step=step_num,
            node_id=nid,
            node_type=ntype,
            label=label,
            context_before=ctx_before,
            context_after=ctx_after,
            output=output,
            edge_taken=edge_taken,
            status=step_status,
            note=note,
        ))

        if halt:
            break
        current = next_node

    if step_num >= max_steps and sim_status == "completed":
        sim_status = "max_steps"
        sim_message = f"Simulation stopped after {max_steps} steps — possible infinite loop"

    return FlowSimulateResponse(
        trace=trace,
        final_context=context,
        status=sim_status,
        message=sim_message,
    )


# ──────────── Version history ────────────

@router.get("/{flow_id}/versions", response_model=List[FlowVersionOut])
async def list_flow_versions(flow_id: UUID, db: AsyncSession = Depends(get_db)):
    """Return all saved snapshots for a flow, newest first."""
    result = await db.execute(
        select(FlowVersion)
        .where(FlowVersion.flow_id == flow_id)
        .order_by(FlowVersion.saved_at.desc())
    )
    return [FlowVersionOut.model_validate(v) for v in result.scalars().all()]


@router.post("/{flow_id}/versions/{version_id}/restore", response_model=FlowDetail)
async def restore_flow_version(
    flow_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Restore a flow to the state stored in a snapshot."""
    ver_result = await db.execute(
        select(FlowVersion).where(FlowVersion.id == version_id, FlowVersion.flow_id == flow_id)
    )
    version = ver_result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    flow_result = await db.execute(
        select(Flow).where(Flow.id == flow_id)
        .options(selectinload(Flow.nodes), selectinload(Flow.edges))
    )
    flow = flow_result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    # Save current state as a new snapshot before overwriting
    cur_nodes = [
        {"id": str(n.id), "node_type": n.node_type, "label": n.label,
         "position_x": n.position_x, "position_y": n.position_y,
         "position": n.position, "config": n.config}
        for n in flow.nodes
    ]
    cur_edges = [
        {"id": str(e.id), "source_node_id": str(e.source_node_id),
         "target_node_id": str(e.target_node_id), "source_handle": e.source_handle,
         "label": e.label, "condition": e.condition, "priority": e.priority}
        for e in flow.edges
    ]
    if cur_nodes:
        old_version = flow.version
        flow.version = _next_save_version(old_version)
        pre_restore_snap = FlowVersion(
            flow_id=flow_id,
            version_number=old_version,
            label=f"{flow.name} (pre-restore)",
            snapshot={"nodes": cur_nodes, "edges": cur_edges},
            saved_at=datetime.utcnow(),
            saved_by=user.id,
        )
        db.add(pre_restore_snap)

    # Flag the flow as a restore so the UI can show the indicator
    flow.is_restored = True
    flow.restored_from_version = version.version_number

    # Wipe current state
    await db.execute(delete(FlowEdge).where(FlowEdge.flow_id == flow_id))
    await db.execute(delete(FlowNode).where(FlowNode.flow_id == flow_id))
    await db.execute(delete(FlowNodeStats).where(FlowNodeStats.flow_id == flow_id))
    await db.flush()

    # Replay snapshot — build a new id map so edges resolve correctly
    snap = version.snapshot
    id_map: dict[str, str] = {}
    for n_data in snap.get("nodes", []):
        new_node = FlowNode(
            flow_id=flow_id,
            node_type=n_data["node_type"],
            label=n_data.get("label", ""),
            position_x=n_data.get("position_x", 0),
            position_y=n_data.get("position_y", 0),
            position=n_data.get("position", 0),
            config=n_data.get("config") or {},
        )
        db.add(new_node)
        await db.flush()
        await db.refresh(new_node)
        id_map[n_data["id"]] = str(new_node.id)

    for e_data in snap.get("edges", []):
        src = id_map.get(e_data["source_node_id"])
        tgt = id_map.get(e_data["target_node_id"])
        if src and tgt:
            db.add(FlowEdge(
                flow_id=flow_id,
                source_node_id=src,
                target_node_id=tgt,
                source_handle=e_data.get("source_handle", "default"),
                label=e_data.get("label", ""),
                condition=e_data.get("condition"),
                priority=e_data.get("priority", 0),
            ))

    flow.updated_by = user.id
    await db.flush()

    result2 = await db.execute(
        select(Flow).where(Flow.id == flow_id)
        .options(selectinload(Flow.nodes), selectinload(Flow.edges))
    )
    return FlowDetail.model_validate(result2.scalar_one())


# ──────────── Flow Analytics ────────────

@router.get("/{flow_id}/analytics")
async def get_flow_analytics(
    flow_id: UUID,
    window: int = Query(60, description="Time window in minutes; 0 = all-time cumulative"),
    db: AsyncSession = Depends(get_db),
):
    """Return per-node visit counts + per-edge transition counts for the analytics overlay.

    ``window`` filters by the visit log (recent traffic).
    ``window=0`` falls back to the all-time cumulative counter table (nodes only).
    """
    if window > 0:
        cutoff = datetime.utcnow() - timedelta(minutes=window)
        base_where = (
            FlowNodeVisitLog.flow_id == flow_id,
            FlowNodeVisitLog.visited_at >= cutoff,
        )
        # ── Per-node counts ──
        node_result = await db.execute(
            select(
                FlowNodeVisitLog.node_id,
                FlowNodeVisitLog.node_label,
                FlowNodeVisitLog.node_type,
                func.count(FlowNodeVisitLog.id).filter(
                    FlowNodeVisitLog.event_type == 'visit'
                ).label("visit_count"),
                func.count(FlowNodeVisitLog.id).filter(
                    FlowNodeVisitLog.event_type == 'error'
                ).label("error_count"),
                func.count(FlowNodeVisitLog.id).filter(
                    FlowNodeVisitLog.event_type == 'abandon'
                ).label("abandon_count"),
                func.max(FlowNodeVisitLog.visited_at).label("last_visited_at"),
            )
            .where(*base_where)
            .group_by(
                FlowNodeVisitLog.node_id,
                FlowNodeVisitLog.node_label,
                FlowNodeVisitLog.node_type,
            )
            .order_by(func.count(FlowNodeVisitLog.id).desc())
        )
        nodes_out = [
            {
                "node_id": str(row.node_id),
                "node_label": row.node_label,
                "node_type": row.node_type,
                "visit_count": row.visit_count,
                "error_count": row.error_count,
                "abandon_count": row.abandon_count,
                "last_visited_at": row.last_visited_at.isoformat() if row.last_visited_at else None,
            }
            for row in node_result.all()
        ]
        # ── Per-edge transition counts (from_node_id → node_id) ──
        edge_result = await db.execute(
            select(
                FlowNodeVisitLog.from_node_id,
                FlowNodeVisitLog.node_id,
                func.count(FlowNodeVisitLog.id).label("count"),
            )
            .where(*base_where)
            .where(FlowNodeVisitLog.from_node_id.isnot(None))
            .group_by(FlowNodeVisitLog.from_node_id, FlowNodeVisitLog.node_id)
        )
        edges_out = [
            {
                "source_id": str(row.from_node_id),
                "target_id": str(row.node_id),
                "count": row.count,
            }
            for row in edge_result.all()
        ]
        return {"nodes": nodes_out, "edges": edges_out}
    else:
        # window=0 → all-time from cumulative counter table (no per-edge data)
        result = await db.execute(
            select(FlowNodeStats)
            .where(FlowNodeStats.flow_id == flow_id)
            .order_by(FlowNodeStats.visit_count.desc())
        )
        stats = result.scalars().all()
        nodes_out = [
            {
                "node_id": str(s.node_id),
                "node_label": s.node_label,
                "node_type": s.node_type,
                "visit_count": s.visit_count,
                "last_visited_at": s.last_visited_at.isoformat() if s.last_visited_at else None,
            }
            for s in stats
        ]
        return {"nodes": nodes_out, "edges": []}
