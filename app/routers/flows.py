"""Flow Designer API – CRUD for flows, nodes, edges + bulk save + simulation."""

import copy
import re
from uuid import UUID
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Flow, FlowNode, FlowEdge, User, FlowType, FlowStatus
from app.schemas import (
    FlowCreate, FlowUpdate, FlowOut, FlowDetail,
    FlowNodeCreate, FlowNodeUpdate, FlowNodeOut,
    FlowEdgeCreate, FlowEdgeOut,
    FlowDesignerSave, DesignerEdgeRef,
    FlowSimulateRequest, FlowSimulateResponse, SimulateStep,
)
from app.auth import get_current_user

router = APIRouter(
    prefix="/api/v1/flows",
    tags=["flows"],
    dependencies=[Depends(get_current_user)],
)


# ──────────── Flow CRUD ────────────

@router.get("", response_model=List[FlowOut])
async def list_flows(
    name: str | None = None,
    status: FlowStatus | None = None,
    flow_type: FlowType | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Flow)
    if name:
        query = query.where(Flow.name.ilike(f"%{name}%"))
    if status:
        query = query.where(Flow.status == status)
    if flow_type:
        query = query.where(Flow.flow_type == flow_type)
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


@router.delete("/{flow_id}", status_code=204)
async def delete_flow(flow_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Flow).where(Flow.id == flow_id))
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    await db.delete(flow)


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
    flow.version += 1

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
    await db.flush()
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

    # Find start node
    start_node = next((n for n in flow.nodes if n.node_type == "start"), None)
    if not start_node:
        raise HTTPException(status_code=400, detail="Flow has no start node")

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
        if ntype == "start":
            trigger = cfg.get("trigger", "inbound_call")
            note = f"Flow started — trigger: {trigger}"

        elif ntype == "end":
            step_status = "end"
            end_status = cfg.get("status", "completed")
            end_msg = cfg.get("message") or ""
            output = end_msg or None
            note = f"Flow ended — status: {end_status}"
            halt = True

        elif ntype == "message":
            text = _resolve_template(cfg.get("text", ""), context)
            output = text
            note = "Message sent to contact"

        elif ntype == "input":
            var = cfg.get("variable", "user_input")
            prompt = cfg.get("prompt", "")
            if nid in inputs:
                context[var] = inputs[nid]
                output = prompt
                note = f"User responded: {inputs[nid]!r}  →  saved to {var!r}"
            else:
                step_status = "needs_input"
                note = f"Waiting for user input — prompt: {prompt!r}  →  variable: {var!r}"
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

        elif ntype in ("http_request", "webhook"):
            method = cfg.get("method", "GET")
            url = _resolve_template(cfg.get("url", ""), context)
            resp_var = cfg.get("response_var", "") or cfg.get("response_variable", "")
            if resp_var:
                context[resp_var] = {"__simulated": True, "status": 200, "body": {}}
            step_status = "external"
            note = f"HTTP {method} {url!r}  →  not called in simulation"
            if resp_var:
                note += f"  →  {resp_var!r} set to simulated response"

        elif ntype == "ai_bot":
            model = cfg.get("model", "gpt-4o")
            out_var = cfg.get("output_variable", "")
            if out_var:
                context[out_var] = "[AI response — simulated]"
            step_status = "external"
            note = f"AI Bot ({model}) simulated"

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
