"""Pure, conservative checks for a declared ComfyUI workflow capability.

These checks validate declarations and graph structure, not image quality or the
model's actual reference-editing ability. Those still require recorded review.
"""
from __future__ import annotations

from collections import deque
import math


def _integer(value, label, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{label} must be an integer >= {minimum}')
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text')
    return value


def validate_capabilities(config, job, candidate_count, reference_count) -> dict:
    """Validate a complete, previously reviewed capability declaration.

    Return a separate dictionary for execution records. ``validation_evidence``
    is an agent-reviewed claim; its presence does not prove model behavior.
    """
    if not isinstance(config, dict) or not isinstance(job, dict):
        raise ValueError('Workflow configuration and job must be objects')
    caps = config.get('capabilities')
    if not isinstance(caps, dict):
        raise ValueError('Workflow needs a capabilities declaration')
    required = {'mode', 'model', 'max_references', 'supported_sizes', 'validation_evidence'}
    if not required.issubset(caps):
        raise ValueError('Incomplete workflow capabilities: ' + ', '.join(sorted(required - caps.keys())))
    if caps['mode'] not in ('background', 'reference_edit'):
        raise ValueError('Workflow mode must be background or reference_edit')
    _text(caps['model'], 'Workflow model')
    _text(caps['validation_evidence'], 'Workflow validation evidence')
    _integer(caps['max_references'], 'max_references')
    _integer(reference_count, 'reference_count')
    _integer(candidate_count, 'candidate_count', minimum=1)
    if reference_count and caps['mode'] != 'reference_edit':
        raise ValueError('Reference images require a reviewed reference_edit workflow')
    if reference_count > caps['max_references']:
        raise ValueError('Workflow reference limit exceeded')
    sizes = caps['supported_sizes']
    if not isinstance(sizes, list):
        raise ValueError('supported_sizes must be a list of [width, height] pairs')
    checked_sizes = []
    for size in sizes:
        if not isinstance(size, (list, tuple)) or len(size) != 2:
            raise ValueError('supported_sizes must contain [width, height] pairs')
        checked_sizes.append([_integer(size[0], 'Supported width', minimum=1),
                              _integer(size[1], 'Supported height', minimum=1)])
    width = _integer(job.get('width'), 'Job width', minimum=1)
    height = _integer(job.get('height'), 'Job height', minimum=1)
    if [width, height] not in checked_sizes:
        raise ValueError('Job dimensions are not in supported_sizes')
    return {**caps, 'supported_sizes': checked_sizes}


def _declaration(declaration, label):
    if not isinstance(declaration, (list, tuple)) or not declaration:
        raise ValueError(f'{label} has an invalid input declaration')
    kind = declaration[0]
    options = declaration[1] if len(declaration) > 1 else {}
    if not isinstance(options, dict):
        raise ValueError(f'{label} has invalid input options')
    if not isinstance(kind, (str, list, tuple)) or not kind:
        raise ValueError(f'{label} has an invalid input type')
    return kind, options


def _finite_number(value, label):
    if type(value) not in (int, float):
        raise ValueError(f'{label} must be a finite number')
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if not finite:
        raise ValueError(f'{label} must be a finite number')
    return value


def validate_literal(value, declaration, label) -> None:
    """Validate a literal; never infer that a two-element list is a link.

    ``validate_graph`` resolves links in their graph context and skips this
    function only after proving that the source and its output slot exist.
    Custom node types require a connection or an explicit future adapter.
    """
    kind, options = _declaration(declaration, label)
    if isinstance(kind, (list, tuple)):
        # Avoid Python treating True as the enum member 1 (and False as 0).
        if not any(value == member and (type(value) is bool) == (type(member) is bool)
                   for member in kind):
            raise ValueError(f'{label} is not a declared enum value')
        return
    if kind == 'INT':
        if type(value) is not int:
            raise ValueError(f'{label} must be INT (not bool or a link-shaped literal)')
        _finite_number(value, label)
    elif kind == 'FLOAT':
        _finite_number(value, label)
    elif kind == 'STRING':
        if not isinstance(value, str):
            raise ValueError(f'{label} must be STRING')
        return
    elif kind == 'BOOLEAN':
        if type(value) is not bool:
            raise ValueError(f'{label} must be BOOLEAN')
        return
    elif kind == '*':
        return
    else:
        raise ValueError(f'{label}: custom type {kind!r} requires a link or a dedicated literal adapter')
    bounds = {}
    for key in ('min', 'max', 'step'):
        if key in options:
            bounds[key] = _finite_number(options[key], f'{label} {key}')
    if 'min' in bounds and 'max' in bounds and bounds['min'] > bounds['max']:
        raise ValueError(f'{label} has contradictory numeric bounds')
    if 'min' in bounds and value < bounds['min']:
        raise ValueError(f'{label} is below min')
    if 'max' in bounds and value > bounds['max']:
        raise ValueError(f'{label} is above max')
    if 'step' in bounds:
        step = bounds['step']
        if step <= 0:
            raise ValueError(f'{label} step must be positive')
        origin = bounds.get('min', 0)
        if all(type(number) is int for number in (value, origin, step)):
            if (value - origin) % step:
                raise ValueError(f'{label} does not follow the declared step')
            return
        quotient = (value - origin) / step
        if not math.isfinite(quotient) or not math.isclose(quotient, round(quotient), rel_tol=0, abs_tol=1e-7):
            raise ValueError(f'{label} does not follow the declared step')


def _input_definitions(definition, label):
    inputs = definition.get('input', {})
    if not isinstance(inputs, dict):
        raise ValueError(f'{label} has invalid node input definitions')
    required, optional = inputs.get('required', {}), inputs.get('optional', {})
    if not isinstance(required, dict) or not isinstance(optional, dict):
        raise ValueError(f'{label} has invalid required/optional inputs')
    return required, {**required, **optional}


def _link(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and isinstance(value[0], str) and isinstance(value[1], int))


def _check_link_types(source_type, destination, label):
    expected, _ = _declaration(destination, label)
    if source_type == '*' or expected == '*':
        return
    if isinstance(expected, (list, tuple)):
        # ComfyUI combo widgets can receive string values, but the actual
        # connected value is runtime data and cannot be checked for membership.
        if source_type not in ('STRING', 'COMBO'):
            raise ValueError(f'{label} cannot link {source_type!r} to an enum input')
    elif isinstance(source_type, str) and source_type != expected:
        raise ValueError(f'{label} link type mismatch: {source_type!r} -> {expected!r}')


def validate_graph(graph, object_info, output_node, bound_reference_nodes) -> None:
    """Check an API graph and whether all bound references reach its output.

    A path proves structural participation only. It cannot prove reference
    fidelity, identify the model being executed, or measure image quality.
    """
    if not isinstance(graph, dict) or not graph or 'nodes' in graph:
        raise ValueError('Use a nonempty API-format workflow')
    if not isinstance(object_info, dict):
        raise ValueError('object_info must contain node definitions')
    if not isinstance(output_node, str) or output_node not in graph:
        raise ValueError('Missing output node')
    if not isinstance(bound_reference_nodes, (list, tuple, set, frozenset)):
        raise ValueError('bound_reference_nodes must be a collection of node IDs')
    definitions = {}
    for node_id, node in graph.items():
        if not isinstance(node_id, str) or not node_id or not isinstance(node, dict):
            raise ValueError('Workflow nodes need nonempty string IDs and object values')
        class_type = node.get('class_type')
        if not isinstance(class_type, str) or class_type not in object_info:
            raise ValueError(f'Missing remote node: {class_type!r}')
        definition = object_info[class_type]
        if not isinstance(definition, dict):
            raise ValueError(f'Invalid definition for remote node {class_type}')
        definitions[node_id] = definition
    parents = {node_id: set() for node_id in graph}
    children = {node_id: set() for node_id in graph}
    for node_id, node in graph.items():
        required, declared = _input_definitions(definitions[node_id], node_id)
        actual = node.get('inputs')
        if not isinstance(actual, dict):
            raise ValueError(f'{node_id} inputs must be an object')
        if not required.keys() <= actual.keys():
            raise ValueError(f'{node_id} is missing required inputs: ' + ', '.join(sorted(required.keys() - actual.keys())))
        for name, value in actual.items():
            label = f'{node_id}.{name}'
            if name not in declared:
                raise ValueError(f'{label} is not a declared required/optional input')
            _declaration(declared[name], label)
            if not _link(value):
                validate_literal(value, declared[name], label)
                continue
            source, slot = value
            _integer(slot, f'{label} output slot')
            if source not in graph:
                raise ValueError(f'{label} links to a missing source node: {source}')
            source_outputs = definitions[source].get('output')
            if 'output' in definitions[source]:
                if not isinstance(source_outputs, (list, tuple)):
                    raise ValueError(f'{source} has invalid output definitions')
                if slot >= len(source_outputs):
                    raise ValueError(f'{label} links to an out-of-range output slot')
                _check_link_types(source_outputs[slot], declared[name], label)
            parents[node_id].add(source)
            children[source].add(node_id)
    # API execution graphs must not contain cycles, even in unused branches.
    remaining = {node_id: len(sources) for node_id, sources in parents.items()}
    ready = deque(node_id for node_id, count in remaining.items() if count == 0)
    visited_count = 0
    while ready:
        node_id = ready.popleft()
        visited_count += 1
        for child in children[node_id]:
            remaining[child] -= 1
            if remaining[child] == 0:
                ready.append(child)
    if visited_count != len(graph):
        raise ValueError('Workflow contains a connection cycle')
    ancestors, pending = set(), list(parents[output_node])
    while pending:
        node_id = pending.pop()
        if node_id not in ancestors:
            ancestors.add(node_id)
            pending.extend(parents[node_id])
    for node_id in bound_reference_nodes:
        if not isinstance(node_id, str) or node_id not in graph:
            raise ValueError('A bound reference node does not exist')
        if node_id not in ancestors:
            raise ValueError(f'Bound reference {node_id} does not reach the output node')
