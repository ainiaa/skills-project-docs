#!/usr/bin/env python3
"""Discover Java/Python APIs and coordinate adapters and document renderers."""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from api_document_ir import ApiDocument, Endpoint, EnumBinding, EnumOption, Field, ResponseCode, Schema, TypeRef
from discovery import CLASS_KINDS, METHOD_KINDS, SymbolLocation, select_engine
from python_fastapi_adapter import scan_python_document
from python_runtime import require_python

# Keep historical Python imports available alongside the unchanged CLI.
from api_document_ir import SCALAR_TYPES, simple_type, _nested_ref, _leaf_ref
from java_spring_adapter import (
    parse_classes,
    referenced_types,
    parse_class_from_jar,
    merge_jar_schemas,
    gradle_modules,
    gradle_build_file,
    gradle_settings_file,
    resolved_gradle_source_roots,
    resolved_gradle_jars,
    package_root,
    scanner_output_dir,
    scan_java_document,
    merge_jar_classes,
    parse_endpoints,
)
from api_document_renderers import (
    generic_argument,
    fields_for,
    example_for,
    field_rows,
    markdown_type,
    document_rows,
    schema_known,
    example_resolved,
    json_content_type,
    enum_options_for,
    enum_property,
    enum_value,
    enum_resolved,
    enum_attributes,
    typed_example,
    meaningful_string,
    example_for_field,
    example_for_ref,
    field_rows_ref,
    document_rows_ref,
    markdown_cell,
    field_notes,
    enum_tables,
    bulk_values,
    request_url,
    render_markdown,
    _postman_item,
    render_postman,
    render_curl,
)


CONTROLLER_ANNOTATION_PATTERN = re.compile(r"@(RestController|Controller|FeignClient)\b")
ROUTE_DECORATOR_PATTERN = re.compile(r"@\w+\.(?:get|post|put|patch|delete|head|options|api_route)\s*\(")


def is_controller_file(source_file: Path) -> bool:
    try:
        text = source_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return CONTROLLER_ANNOTATION_PATTERN.search(text) is not None


def endpoint_source_file(source: str) -> str:
    """Strip the trailing ":line" the scanner appends to the controller source path."""
    return re.sub(r":\d+$", "", source)


def is_route_file(source_file: Path) -> bool:
    """FastAPI route files carry method decorators like @app.get("/x")."""
    try:
        text = source_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return ROUTE_DECORATOR_PATTERN.search(text) is not None


def python_package_root(source_file: Path) -> Path:
    """Topmost directory of the file's __init__.py package chain.

    Mirrors the adapter's module_name derivation: namespace layouts without
    __init__.py resolve to the file's own directory and simply stay unresolved.
    """
    directory = source_file.parent
    while (directory / "__init__.py").is_file():
        directory = directory.parent
    return directory


def endpoint_selector_names(selectors: List[str]) -> List[str]:
    names = []
    for selector in selectors:
        name = selector.rsplit("#", 1)[-1].partition("@")[0]
        if name and name not in names:
            names.append(name)
    return names


def controller_candidates(engine, endpoint_names: List[str]) -> Optional[List[Path]]:
    """Controller files covering every endpoint name, or None when one name cannot be resolved."""
    merged: Dict[str, Set[Path]] = {}
    for name in endpoint_names:
        files = {location.path for location in engine.locate(name, METHOD_KINDS)
                 if location.path.is_file() and is_controller_file(location.path)}
        if not files:
            return None
        merged[name] = files
    union: Set[Path] = set()
    for files in merged.values():
        union.update(files)
    return sorted(union, key=str)


def qualified_name_matches(qualified_name: str, package: str, simple: str) -> bool:
    """Match an engine-reported qualified name (e.g. "com.example::Result") against a package."""
    if not qualified_name:
        return True
    return qualified_name.replace("::", ".").startswith(package + ".")


def heal_unresolved_roots(engine, unresolved: List[str], known_roots: Set[Path],
                          language: str = "java") -> Dict[Path, str]:
    """Map unresolved type names to candidate source roots via the discovery engine.

    Package-qualified names are resolved first and filtered by package, so a
    same-simple-name class in an unrelated package cannot seed a wrong root.
    """
    additions: Dict[Path, str] = {}
    for name in sorted(unresolved, key=lambda item: ("." not in item, item)):
        simple = name.rsplit(".", 1)[-1]
        package = name.rsplit(".", 1)[0] if "." in name else ""
        for location in engine.locate(simple, CLASS_KINDS):
            if not location.path.is_file():
                continue
            if package and not qualified_name_matches(location.qualified_name, package, simple):
                continue
            root = package_root(location.path) if language == "java" else python_package_root(location.path)
            if root is None or root in known_roots or root in additions:
                continue
            additions[root] = name
    return additions


def select_endpoints(document: ApiDocument, selectors: List[str], parser) -> None:
    selected = []
    for selector in selectors:
        selector = selector.rsplit("#", 1)[-1]
        name, separator, route = selector.partition("@")
        method, colon, path = route.partition(":") if separator else ("", "", "")
        if separator and (not colon or not path.startswith("/")):
            parser.error("invalid endpoint selector: " + selector + "; use name@METHOD:/path")
        matches = [endpoint for endpoint in document.endpoints if endpoint.name == name
                   and (not separator or (endpoint.method == method.upper() and endpoint.path == path))]
        if not matches:
            parser.error("endpoint not found: " + selector)
        if len(matches) > 1:
            choices = ", ".join(sorted({f"{item.name}@{item.method}:{item.path}" for item in matches}))
            parser.error("ambiguous endpoint: " + selector + "; use one of: " + choices)
        if matches[0] not in selected:
            selected.append(matches[0])
    document.endpoints = selected


def build_java_document(arguments, roots: List[Path], controller_paths: List[Path],
                        classpath: List[Path], parser) -> Tuple[ApiDocument, Dict[str, List[Field]]]:
    document = scan_java_document(roots, controller_paths or None)
    if arguments.endpoint:
        select_endpoints(document, arguments.endpoint, parser)
    classes = document.classes()
    if classpath:
        document = merge_jar_schemas(document, classpath)
        classes = document.classes()
        classes = merge_jar_classes(classes, document.endpoints, classpath)
        document = document.with_classes({name: fields for name, fields in classes.items()
                                          if name not in document.classes()})
    return document, classes


def affected_endpoints(document: ApiDocument, engine, changed: List[Path]) -> List[Endpoint]:
    """Endpoints whose controller source or transitively referenced DTO types intersect the changed files.

    Two-pass design: reachability and unresolved candidates are computed from
    the IR alone (no engine calls), then the union of candidate names is
    located in one batch — so unrelated schemas never trigger engine queries
    and each backend pays at most one batched lookup.
    """
    changed_paths = {path.resolve() for path in changed}
    plans = []
    candidate_names = set()
    for endpoint in document.endpoints:
        seeds = [endpoint.response_schema_id] + [field.schema_id for field in endpoint.parameters
                                                 + ([endpoint.request_body] if endpoint.request_body else [])]
        reachable, pending = set(), list(seeds)
        while pending:
            schema_id = pending.pop()
            if not schema_id or schema_id in reachable:
                continue
            reachable.add(schema_id)
            schema = document.schemas.get(schema_id)
            if schema is None:
                continue
            pending.extend(field.schema_id for field in schema.fields if field.schema_id)
            if schema.parent_schema_id:
                pending.append(schema.parent_schema_id)
        reachable_names = {document.schemas[schema_id].name for schema_id in reachable
                           if schema_id in document.schemas}
        unresolved_names = set(referenced_types(endpoint.response_type))
        for field in endpoint.parameters + ([endpoint.request_body] if endpoint.request_body else []):
            unresolved_names.update(referenced_types(field.type_name))
        unresolved_names -= set(document.classes()) | reachable_names
        plans.append((endpoint, reachable_names, unresolved_names))
        candidate_names.update(reachable_names)
        candidate_names.update(unresolved_names)

    located = engine.locate_many(sorted(candidate_names), CLASS_KINDS)
    changed_names = {name for name, locations in located.items()
                     if any(location.path in changed_paths and location.path.is_file()
                            for location in locations)}

    result = []
    for endpoint, reachable_names, unresolved_names in plans:
        if Path(endpoint_source_file(endpoint.source)).resolve() in changed_paths:
            result.append(endpoint)
        elif reachable_names & changed_names or unresolved_names & changed_names:
            result.append(endpoint)
    return result


def unresolved_types(endpoints: List[Endpoint], classes: Dict[str, List[Field]],
                     schemas: Optional[Dict[str, Schema]] = None) -> List[str]:
    framework = {"List", "Set", "Map", "Collection", "Iterable", "Optional", "ResponseEntity",
                 "MultipartFile", "HttpServletRequest", "HttpServletResponse", "ServletRequest",
                 "ServletResponse", "Principal", "BindingResult", "Model", "ModelMap",
                 "Any", "Union", "Literal"}
    requested = set()
    pending = []
    for endpoint in endpoints:
        pending.extend(referenced_types(endpoint.response_type))
        for parameter in endpoint.parameters + ([endpoint.request_body] if endpoint.request_body else []):
            pending.extend(referenced_types(parameter.type_name))
    while pending:
        name = pending.pop()
        if name in requested or name not in classes:
            requested.add(name)
            continue
        requested.add(name)
        for field in classes[name]:
            pending.extend(referenced_types(field.type_name))
    resolved_ids = {endpoint.response_schema_id for endpoint in endpoints}
    resolved_ids.update(field.schema_id for endpoint in endpoints
                        for field in endpoint.parameters + ([endpoint.request_body] if endpoint.request_body else []))
    source_names = set()
    missing_ids = set()
    missing_parents = set()
    if schemas:
        document = ApiDocument(1, "java", "spring", [], schemas)
        pending_schemas = list(resolved_ids)
        checked_schemas = set()
        while pending_schemas:
            schema_id = pending_schemas.pop()
            if schema_id in checked_schemas:
                continue
            checked_schemas.add(schema_id)
            if schema_id not in schemas:
                if schema_id.startswith("java:") and simple_type(schema_id[5:]) not in SCALAR_TYPES | framework:
                    missing_ids.add(schema_id[5:])
                continue
            schema = schemas[schema_id]
            source_names.add(schema.name)
            pending_schemas.extend(field.schema_id for field in schema.fields if field.schema_id)
            if schema.parent and simple_type(schema.parent) != "Object":
                parent = document._parse_type(schema.parent, schema.parent_schema_id)
                if parent.schema_id in schemas:
                    pending_schemas.append(parent.schema_id)
                else:
                    missing_parents.add(parent.name)
    return sorted({name for name in requested if name not in classes and name not in source_names
                   and name not in framework} | missing_ids | missing_parents)


def endpoint_values(endpoint: Endpoint) -> List[Field]:
    values = endpoint.parameters + ([endpoint.request_body] if endpoint.request_body else [])
    return values + [Field("return", endpoint.response_type, schema_id=endpoint.response_schema_id)]


def main() -> int:
    require_python()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("java", "python"), default="java")
    parser.add_argument("--source", action="append", required=True, type=Path, help="Source root; repeat as needed")
    parser.add_argument("--output", type=Path, help="Directory for api-docs.md, Postman collection, and cURL script")
    parser.add_argument("--output-file", type=Path, help="Markdown file for the selected endpoint(s)")
    parser.add_argument("--endpoint", action="append", help="Method name or name@METHOD:/path; repeat as needed")
    parser.add_argument("--controller", action="append", type=Path, help="Controller source file for fast single-endpoint generation")
    parser.add_argument("--classpath", action="append", type=Path, help="Dependency JAR used when a DTO is not in source")
    parser.add_argument("--changed", action="append", type=Path, help="Changed source file; regenerate only the endpoints it affects (requires a code discovery index)")
    parser.add_argument("--no-codegraph", action="store_true", help="Disable the optional code discovery engine (.codegraph)")
    parser.add_argument("--base-url", default="")
    arguments = parser.parse_args()
    if not arguments.output and not arguments.output_file:
        parser.error("one of --output or --output-file is required")
    roots = [path.resolve() for path in arguments.source]
    missing = [str(path) for path in roots if not path.exists()]
    if missing:
        parser.error("Source root does not exist: " + ", ".join(missing))
    controller_paths = [path.resolve() for path in arguments.controller or []]
    missing = [str(path) for path in controller_paths if not path.is_file()]
    if missing:
        parser.error("Controller source does not exist: " + ", ".join(missing))
    if controller_paths:
        if arguments.language != "java":
            parser.error("--controller is currently supported only for --language java")
        roots = list(dict.fromkeys(roots + resolved_gradle_source_roots(controller_paths[0])))
    classpath = [path.resolve() for path in arguments.classpath or []]
    missing = [str(path) for path in classpath if not path.is_file()]
    if missing:
        parser.error("Classpath JAR does not exist: " + ", ".join(missing))
    if arguments.changed and arguments.endpoint:
        parser.error("--changed cannot be combined with --endpoint")
    engine = select_engine(roots, enabled=not arguments.no_codegraph)
    if engine and arguments.endpoint and not controller_paths:
        names = endpoint_selector_names(arguments.endpoint)
        if arguments.language == "java":
            candidates = controller_candidates(engine, names)
            if candidates:
                print(f"[{engine.name}] narrowed scan to {len(candidates)} controller file(s) for: " + ", ".join(names),
                      file=sys.stderr)
                controller_paths = candidates
                roots = list(dict.fromkeys(roots + [root for controller in candidates
                                                    for root in resolved_gradle_source_roots(controller)]))
        else:
            located = engine.locate_many(names, METHOD_KINDS)
            if any(location.path.is_file() and is_route_file(location.path)
                   for locations in located.values() for location in locations):
                print(f"[{engine.name}] located route function(s) for: " + ", ".join(names), file=sys.stderr)
    if controller_paths and not classpath:
        classpath = resolved_gradle_jars(controller_paths[0])
    if arguments.language != "java" and classpath:
        parser.error("--classpath is currently supported only for --language java")
    scan_roots: List[Path] = list(roots)
    added_roots: Set[Path] = set()
    for attempt in range(3):
        if arguments.language == "java":
            document, classes = build_java_document(arguments, scan_roots, controller_paths, classpath, parser)
        else:
            document = scan_python_document(scan_roots)
            if arguments.endpoint:
                select_endpoints(document, arguments.endpoint, parser)
            classes = document.classes()
        unresolved = unresolved_types(document.endpoints, classes, document.schemas)
        if engine is None or not unresolved or attempt == 2:
            break
        additions = heal_unresolved_roots(engine, unresolved, set(scan_roots) | added_roots, arguments.language)
        if not additions:
            break
        for root, name in sorted(additions.items(), key=lambda item: str(item[0])):
            print(f"[{engine.name}] auto-added source root {root} for {name}", file=sys.stderr)
        added_roots.update(additions)
        scan_roots.extend(sorted(additions, key=str))
    if arguments.changed:
        if engine is None:
            parser.error("--changed requires a discovery engine; install codegraph "
                         "(and run `codegraph init`) or the tree-sitter packages "
                         "(pip3 install tree-sitter tree-sitter-python tree-sitter-java)")
        affected = affected_endpoints(document, engine, arguments.changed)
        if not affected:
            print("No endpoints affected by the changed files")
            return 0
        document.endpoints = affected
        unresolved = unresolved_types(document.endpoints, classes, document.schemas)
    if unresolved:
        print("Warning: unresolved DTO types: " + ", ".join(unresolved), file=sys.stderr)
    markdown = render_markdown(document, arguments.base_url)
    if arguments.output:
        arguments.output.mkdir(parents=True, exist_ok=True)
        (arguments.output / "api-docs.md").write_text(markdown, encoding="utf-8")
        collection = render_postman(document, arguments.base_url)
        (arguments.output / "postman-collection.json").write_text(json.dumps(collection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        curl_path = arguments.output / "curl.sh"
        curl_path.write_text(render_curl(document, arguments.base_url), encoding="utf-8")
        curl_path.chmod(0o755)
    if arguments.output_file:
        arguments.output_file.parent.mkdir(parents=True, exist_ok=True)
        arguments.output_file.write_text(markdown, encoding="utf-8")
    print(f"Generated {len(document.endpoints)} endpoint(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
