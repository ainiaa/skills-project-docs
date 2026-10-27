"""Read Spring routes, DTOs and Gradle/JAR declarations into the API document IR."""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from api_document_ir import (ApiDocument, Endpoint, EnumBinding, EnumOption, Field,
                             ResponseCode, Schema, SCALAR_TYPES, simple_type, _leaf_ref)


def parse_classes(roots: List[Path]) -> Dict[str, List[Field]]:
    return scan_java_document(roots).classes()


def referenced_types(type_name: str) -> set:
    return {name for name in re.findall(r"\b[A-Z]\w*\b", type_name)
            if name not in SCALAR_TYPES and name not in {"List", "Set", "Map", "Object", "T"}}


def parse_class_from_jar(jars: List[Path], name: str) -> Tuple[Dict[str, List[Field]], Dict[str, str]]:
    candidates = []
    target = name.replace(".", "/") + ".class"
    for jar in jars:
        with zipfile.ZipFile(jar) as archive:
            entries = [entry for entry in archive.namelist()
                       if entry == target or "." not in name and entry.endswith("/" + target)]
        candidates.extend((jar, entry) for entry in entries)
    if len(candidates) > 1:
        print("Warning: ambiguous JAR DTO type: " + name, file=sys.stderr)
        return {}, {}
    if candidates:
        jar, entry = candidates[0]
        qualified_name = entry[:-6].replace("/", ".")
        output = subprocess.run(["javap", "-classpath", str(jar), "-private", qualified_name],
                                check=True, text=True, capture_output=True).stdout
        fields = []
        for _, modifiers, type_name, field_name in re.findall(
                r"^\s+(?:(private|protected|public)\s+)?((?:(?:static|final|transient|volatile)\s+)*)"
                r"([^;()]+?)\s+(\w+);$", output, re.M):
            if "static" in modifiers.split() or "transient" in modifiers.split():
                continue
            fields.append(Field(field_name, type_name.replace("java.lang.", "")))
        parent = re.search(r"\bextends\s+([\w.$]+(?:<[^>{]+>)?)", output.split("{", 1)[0])
        return {name: fields}, {"parent": parent.group(1) if parent else ""}
    return {}, {}


def merge_jar_schemas(document: ApiDocument, classpath: List[Path]) -> ApiDocument:
    schemas = dict(document.schemas)
    pending = {schema_id for endpoint in document.endpoints
               for schema_id in [endpoint.response_schema_id] +
               [value.schema_id for value in endpoint.parameters +
                ([endpoint.request_body] if endpoint.request_body else [])]
               if schema_id.startswith("java:") and schema_id not in schemas}
    for schema in schemas.values():
        pending.update(value.schema_id for value in schema.fields
                       if value.schema_id.startswith("java:") and value.schema_id not in schemas)
    checked = set()
    while pending:
        schema_id = pending.pop()
        if schema_id in checked or schema_id in schemas:
            continue
        checked.add(schema_id)
        qualified = schema_id.removeprefix("java:")
        parsed, metadata = parse_class_from_jar(classpath, qualified)
        if not parsed:
            continue
        values = parsed[qualified]
        for value in values:
            raw = _leaf_ref(document._parse_type(value.type_name)).name.replace("[]", "")
            if "." in raw and raw.split(".")[-1] not in SCALAR_TYPES:
                value.schema_id = "java:" + raw
                pending.add(value.schema_id)
        parent = metadata.get("parent", "")
        parent_id = "java:" + parent.split("<", 1)[0] if parent else ""
        if parent_id and parent_id not in schemas:
            pending.add(parent_id)
        if parent:
            parent_ref = document._parse_type(parent)
            nested = list(parent_ref.arguments)
            while nested:
                argument = nested.pop()
                nested.extend(argument.arguments)
                if "." in argument.name and simple_type(argument.name) not in SCALAR_TYPES:
                    pending.add("java:" + argument.name)
        schemas[schema_id] = Schema(schema_id, qualified.rsplit(".", 1)[-1], qualified,
                                    parent, values, parent_schema_id=parent_id)
    return ApiDocument(document.ir_version, document.language, document.framework, document.endpoints, schemas).normalized()


def gradle_modules(controller: Path) -> List[Path]:
    module = next((parent for parent in [controller.parent, *controller.parents] if gradle_build_file(parent)), None)
    if module is None:
        return []
    root = next((parent for parent in [module, *module.parents] if gradle_settings_file(parent)), module)
    pending, visited = [module], set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        text = gradle_build_file(current).read_text(encoding="utf-8")
        for project_name in re.findall(r"project\(\s*(?:path\s*[:=]\s*)?['\"]:([^'\"]+)", text):
            child = root.joinpath(*project_name.split(":"))
            if gradle_build_file(child):
                pending.append(child)
    return list(visited)


def gradle_build_file(directory: Path) -> Optional[Path]:
    return next((directory / name for name in ("build.gradle", "build.gradle.kts")
                 if (directory / name).is_file()), None)


def gradle_settings_file(directory: Path) -> Optional[Path]:
    return next((directory / name for name in ("settings.gradle", "settings.gradle.kts")
                 if (directory / name).is_file()), None)


def resolved_gradle_source_roots(controller: Path) -> List[Path]:
    return [module / "src/main/java" for module in gradle_modules(controller)
            if (module / "src/main/java").is_dir()]


def resolved_gradle_jars(controller: Path) -> List[Path]:
    coordinates = set()
    for module in gradle_modules(controller):
        text = gradle_build_file(module).read_text(encoding="utf-8")
        coordinates.update(re.findall(r"['\"]([\w.-]+):([\w.-]+):([^'\"]+)['\"]", text))
    cache = Path.home() / ".gradle/caches/modules-2/files-2.1"
    jars = []
    for group, artifact, version in coordinates:
        jars.extend((cache / group / artifact / version).glob("*/*.jar"))
    return jars


def package_root(source_file: Path) -> Optional[Path]:
    """Derive the package source root from a Java file's package declaration."""
    try:
        text = source_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"^\s*package\s+([\w.]+)\s*;", text[:4096], re.M)
    segments = match.group(1).split(".") if match else []
    parents = source_file.parents
    if len(parents) <= len(segments):
        return None
    for index, segment in enumerate(reversed(segments)):
        if parents[index].name != segment:
            return None
    return parents[len(segments)]


def scanner_output_dir() -> Path:
    source = Path(__file__).with_name("ApiSaviorAstScanner.java")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    output = Path(tempfile.gettempdir()) / "api-savior-docs" / digest
    class_file = output / "ApiSaviorAstScanner.class"
    if not class_file.is_file():
        output.mkdir(parents=True, exist_ok=True)
        subprocess.run(["javac", "-source", "11", "-target", "11", "-d", str(output), str(source)],
                       check=True, text=True, capture_output=True)
    return output


def scan_java_document(roots: List[Path], controllers: Optional[List[Path]] = None) -> ApiDocument:
    command = ["java", "-cp", str(scanner_output_dir()), "ApiSaviorAstScanner"]
    for root in roots:
        command.extend(["--source", str(root)])
    for controller in controllers or []:
        command.extend(["--controller", str(controller)])
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    data = json.loads(result.stdout)
    raw_schemas = data["schemas"]

    def fields(values: List[dict]) -> List[Field]:
        return [Field(**value) for value in values]

    endpoints = [Endpoint(
        item["name"], item["notes"], item["method"], item["path"], fields(item["parameters"]),
        Field(**item["request_body"]) if item["request_body"] else None,
        item["response_type"], item["source"], item["content_type"], item.get("response_schema_id", ""),
        item.get("interface_notes", ""), [ResponseCode(**code) for code in item.get("response_codes", [])],
        [EnumBinding(**binding) for binding in item.get("enum_bindings", [])]
    ) for item in data["endpoints"]]
    schemas = {
        item["id"]: Schema(item["id"], item["name"], item["qualified_name"], item["parent"],
                             fields(item["fields"]), item.get("parent_schema_id", ""), item.get("type_parameters", []),
                             [EnumOption(**option) for option in item.get("enum_options", [])],
                             item.get("ignored_properties", []), item.get("allow_getters", False),
                             item.get("allow_setters", False))
        for item in raw_schemas
    }
    document = ApiDocument(data["ir_version"], data["language"], data["framework"],
                           sorted(endpoints, key=lambda item: (item.path, item.method, item.name)), schemas)
    return document.normalized()


def merge_jar_classes(classes: Dict[str, List[Field]], endpoints: List[Endpoint], classpath: List[Path]) -> Dict[str, List[Field]]:
    requested = set()
    for endpoint in endpoints:
        requested.update(referenced_types(endpoint.response_type))
        for parameter in endpoint.parameters + ([endpoint.request_body] if endpoint.request_body else []):
            requested.update(referenced_types(parameter.type_name))
    while requested:
        name = requested.pop()
        if name in classes:
            continue
        parsed, _ = parse_class_from_jar(classpath, name)
        if not parsed:
            continue
        classes.update(parsed)
        for field_value in parsed[name]:
            requested.update(referenced_types(field_value.type_name))
    return classes


def parse_endpoints(roots: List[Path]) -> List[Endpoint]:
    return scan_java_document(roots).endpoints
