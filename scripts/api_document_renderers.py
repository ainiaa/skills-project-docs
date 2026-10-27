"""Render API document IR as Markdown, Postman and cURL without reading source."""
import json
import re
import shlex
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from api_document_ir import (ApiDocument, Endpoint, EnumOption, Field, TypeRef,
                             SCALAR_TYPES, simple_type, _nested_ref, _leaf_ref)


def generic_argument(type_name: str) -> Optional[str]:
    start = type_name.find("<")
    if start < 0:
        return None
    depth = 0
    for index, character in enumerate(type_name[start:], start):
        if character == "<":
            depth += 1
        elif character == ">":
            depth -= 1
            if depth == 0:
                return type_name[start + 1:index].strip()
    return None


def fields_for(type_name: str, classes: Dict[str, List[Field]]) -> List[Field]:
    argument = generic_argument(type_name)
    return [Field(item.name, re.sub(r"\bT\b", argument, item.type_name) if argument else item.type_name,
                  item.description, item.required, item.notes, item.example, item.location, item.schema_id)
            for item in classes.get(simple_type(type_name), [])]


def example_for(type_name: str, classes: Dict[str, List[Field]], seen: Optional[set] = None):
    seen = seen or set()
    raw = simple_type(type_name)
    if raw in {"List", "Set", "Collection", "Iterable"} or type_name.endswith("[]"):
        return [example_for(generic_argument(type_name) or "String", classes, seen)]
    if raw in {"boolean", "Boolean"}:
        return False
    if raw in {"byte", "Byte", "short", "Short", "int", "Integer", "long", "Long", "float", "Float", "double", "Double", "BigDecimal"}:
        return 1
    if raw in {"Date", "LocalDate", "LocalDateTime"}:
        return "2012-05-28T13:14:00.520+0000"
    if raw in SCALAR_TYPES or raw == "void":
        return "HelloWorld" if raw != "void" else None
    if raw in seen or raw not in classes:
        return {}
    seen.add(raw)
    return {item.name: item.example or example_for(item.type_name, classes, seen.copy())
            for item in fields_for(type_name, classes)}


def field_rows(value: Field, classes: Dict[str, List[Field]], level: int = 1, seen: Optional[set] = None) -> List[Field]:
    rows, seen = [], seen or set()
    raw = simple_type(value.type_name)
    prefix = "" if level < 2 else "&ensp;&ensp;&ensp;&ensp;" * (level - 2) + "└─"
    rows.append(Field(prefix + " " + value.name, value.type_name, value.description,
                      value.required, value.notes, value.example, value.location, value.schema_id))
    nested_type = generic_argument(value.type_name) if raw in {"List", "Set"} else value.type_name
    if nested_type and simple_type(nested_type) not in seen:
        for child in fields_for(nested_type, classes):
            rows.extend(field_rows(child, classes, level + 1, seen | {raw}))
    return rows


def markdown_type(type_name: str) -> str:
    return type_name.replace("<", "\\<").replace(">", "\\>")


def document_rows(values: List[Field], classes: Dict[str, List[Field]]) -> List[Field]:
    result = []
    for value in values:
        raw = simple_type(value.type_name)
        if raw in classes and value.name in {"request", "return"}:
            for child in fields_for(value.type_name, classes):
                result.extend(field_rows(child, classes))
        else:
            result.extend(field_rows(value, classes))
    return result


def schema_known(value: TypeRef, document: ApiDocument) -> bool:
    leaf = _leaf_ref(value)
    return leaf.schema_id in document.schemas if leaf.schema_id else document._schema_for_type(leaf.name) is not None


def example_resolved(value: TypeRef, document: ApiDocument, seen=None) -> bool:
    raw = simple_type(value.name)
    if raw in SCALAR_TYPES | {"str", "int", "float", "bool", "bytes", "date", "datetime",
                              "None", "NoneType", "Any", "Object"}:
        return True
    if raw in {"List", "Set", "Collection", "Iterable", "list", "set", "Map", "dict"}:
        return all(example_resolved(item, document, seen) for item in value.arguments)
    if raw in {"Optional", "Annotated", "Union", "ResponseEntity"}:
        return bool(value.arguments) and example_resolved(_nested_ref(value), document, seen)
    schema = document.schemas.get(value.schema_id) if value.schema_id else document._schema_for_type(value.name)
    if not schema:
        return False
    seen = seen or set()
    key = (schema.id, value.display_name())
    if key in seen:
        return True
    if schema.parent and simple_type(schema.parent) != "Object":
        bindings = dict(zip(schema.type_parameters or (["T"] if value.arguments else []), value.arguments))
        parent = document._substitute(document._parse_type(schema.parent, schema.parent_schema_id), bindings)
        if not example_resolved(parent, document, seen | {key}):
            return False
    return all(example_resolved(document.type_ref(field), document, seen | {key})
               for field in document.fields_for_type(value))


def json_content_type(value: str) -> bool:
    media = (value or "application/json").split(";", 1)[0].strip().lower()
    return media == "application/json" or media.endswith("+json")


def enum_options_for(value: Field, document: ApiDocument) -> Tuple[List[EnumOption], bool]:
    nested = _leaf_ref(document.type_ref(value))
    direct = document.schemas.get(nested.schema_id)
    linked = document.schemas.get(value.enum_schema_id)
    if direct and direct.enum_options:
        return direct.enum_options, False
    if linked and linked.enum_options:
        return linked.enum_options, True
    return [], False


def enum_property(option: EnumOption, hint: str) -> str:
    return next((name for name in option.properties if name.lower() == hint.lower()), "") if hint else ""


def enum_value(option: EnumOption, linked: bool, hint: str = ""):
    selected = enum_property(option, hint) if linked else ""
    if selected:
        return option.properties[selected]
    return option.reference_value if linked else option.api_value


def enum_resolved(option: EnumOption, linked: bool, hint: str = "") -> bool:
    if linked and enum_property(option, hint):
        return True
    return option.reference_resolved if linked else option.value_resolved


def enum_attributes(option: EnumOption, linked: bool, hint: str = "") -> str:
    selected = enum_property(option, hint) if linked else ""
    if selected:
        return "；".join(f"{name}={value}" for name, value in option.properties.items()
                        if name not in {selected, option.description_property})
    return option.reference_attributes if linked else option.attributes


def typed_example(type_name: str, value):
    raw = simple_type(type_name)
    try:
        if raw in {"byte", "Byte", "short", "Short", "int", "Integer", "long", "Long"}:
            return int(value)
        if raw in {"float", "Float", "double", "Double", "BigDecimal"}:
            return float(value)
        if raw in {"boolean", "Boolean"}:
            if str(value).lower() in {"true", "false"}:
                return str(value).lower() == "true"
            return None
        return str(value)
    except (TypeError, ValueError):
        return None


def meaningful_string(value: Field) -> str:
    meaning = value.description or value.name or "请填写"
    for separator in ("（", "(", "，", ",", "。", "\n"):
        meaning = meaning.split(separator, 1)[0]
    return "<" + meaning.strip() + ">"


def example_for_field(value: Field, document: ApiDocument, seen: Optional[set] = None):
    if value.example is not None:
        declared = typed_example(value.type_name, value.example) if document.language == "java" else value.example
        if declared is not None:
            return declared
    type_ref = document.type_ref(value)
    if value.type_name.strip().endswith("[]") or simple_type(type_ref.name) in {"List", "Set", "Collection", "Iterable", "list", "set", "Map", "dict"}:
        options, linked = enum_options_for(value, document)
        if options and simple_type(type_ref.name) in {"List", "Set", "Collection", "Iterable", "list", "set"}:
            first = options[0]
            if enum_resolved(first, linked, value.enum_value_hint):
                return [enum_value(first, linked, value.enum_value_hint)]
        return example_for_ref(type_ref, document, seen)
    options, linked = enum_options_for(value, document)
    if options:
        first = options[0]
        if enum_resolved(first, linked, value.enum_value_hint):
            candidate = enum_value(first, linked, value.enum_value_hint)
            if not linked:
                return candidate
            compatible = typed_example(value.type_name, candidate)
            if compatible is not None:
                return compatible
        if document.language != "java":
            return None
        if not linked:
            return meaningful_string(value)
    if document.language == "java":
        raw = simple_type(value.type_name)
        if raw in {"String", "CharSequence", "char", "Character"}:
            return meaningful_string(value)
        if raw in {"byte", "Byte", "short", "Short", "int", "Integer", "long", "Long",
                   "float", "Float", "double", "Double", "BigDecimal"}:
            if raw in {"long", "Long"} and ("time" in value.name.lower() or value.name.lower().startswith("date")
                                                or "毫秒" in value.description):
                return 1700000000000
            return value.minimum if value.minimum is not None else 0
    return example_for_ref(document.type_ref(value), document, seen)


def example_for_ref(value: TypeRef, document: ApiDocument, seen: Optional[set] = None):
    seen = seen or set()
    raw = simple_type(value.name)
    schema = document.schemas.get(value.schema_id)
    if schema and schema.enum_options:
        first = schema.enum_options[0]
        return first.api_value if first.value_resolved else ("<请填写>" if document.language == "java" else None)
    if raw in {"List", "Set", "Collection", "Iterable", "list", "set"}:
        nested = _nested_ref(value)
        return [] if nested is value else [example_for_ref(nested, document, seen)]
    if raw in {"Map", "dict"}:
        nested = _nested_ref(value)
        return {"key": example_for_ref(nested, document, seen) if nested is not value
                else ("<请填写>" if document.language == "java" else "HelloWorld")}
    if raw in {"Optional", "Annotated", "Union", "ResponseEntity"}:
        nested = _nested_ref(value)
        return {} if nested is value else example_for_ref(nested, document, seen)
    if raw in {"boolean", "Boolean", "bool"}:
        return False
    if raw in {"byte", "Byte", "short", "Short", "int", "Integer", "long", "Long", "float", "Float", "double", "Double", "BigDecimal"}:
        return 0 if document.language == "java" else 1
    if raw in {"Date", "LocalDate", "LocalDateTime", "date", "datetime"}:
        return "2012-05-28T13:14:00.520+0000"
    if raw in SCALAR_TYPES | {"str", "bytes", "UUID", "void", "None", "NoneType"}:
        if raw in {"void", "None", "NoneType"}:
            return None
        return "<请填写>" if document.language == "java" else "HelloWorld"
    key = value.schema_id or value.display_name()
    if key in seen:
        return {}
    fields = document.fields_for_type(value)
    if not fields:
        return {}
    return {item.wire_name or item.name: example_for_field(item, document, seen | {key})
            for item in fields}


def field_rows_ref(value: Field, document: ApiDocument, level: int = 1, seen: Optional[set] = None) -> List[Field]:
    rows, seen = [], seen or set()
    type_ref = document.type_ref(value)
    prefix = "" if level < 2 else "&ensp;&ensp;&ensp;&ensp;" * (level - 2) + "└─"
    rows.append(Field(prefix + " " + (value.wire_name or value.name), value.type_name, value.description,
                      value.required, value.notes, value.example, value.location, value.schema_id, type_ref,
                      value.enum_schema_id, value.minimum, value.enum_value_hint, value.wire_name))
    nested = _leaf_ref(type_ref)
    key = nested.schema_id or nested.display_name()
    if key not in seen:
        for child in document.fields_for_type(nested):
            rows.extend(field_rows_ref(child, document, level + 1, seen | {key}))
    return rows


def document_rows_ref(values: List[Field], document: ApiDocument) -> List[Field]:
    result = []
    for value in values:
        type_ref = document.type_ref(value)
        nested = _leaf_ref(type_ref) if value.name in {"request", "return"} else type_ref
        if value.name in {"request", "return"} and document.fields_for_type(nested):
            for child in document.fields_for_type(nested):
                result.extend(field_rows_ref(child, document))
        else:
            result.extend(field_rows_ref(value, document))
    return result


def markdown_cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def field_notes(value: Field, document: ApiDocument) -> str:
    options, linked = enum_options_for(value, document)
    parts = [value.notes] if value.notes else []
    if options:
        labels = []
        for option in options:
            if enum_resolved(option, linked, value.enum_value_hint):
                api_value = enum_value(option, linked, value.enum_value_hint)
                label = str(api_value)
                if option.description:
                    label += f"：{option.description}"
                if enum_attributes(option, linked, value.enum_value_hint):
                    label += f"（{enum_attributes(option, linked, value.enum_value_hint)}）"
                if not linked and option.member_name != str(api_value):
                    label = f"{option.member_name}（{label}）"
            else:
                label = option.member_name + "（取值未解析）"
            labels.append(label)
        parts.append("枚举取值：" + "；".join(labels))
    return markdown_cell("；".join(parts))


def enum_tables(output: List[str], request_rows: List[Field], response_rows: List[Field],
                request_document: ApiDocument, response_document: ApiDocument) -> None:
    groups = []
    for title, rows, document in (("入参", request_rows, request_document),
                                  ("出参", response_rows, response_document)):
        for row in rows:
            options, linked = enum_options_for(row, document)
            if options:
                groups.append((title, row.name.rsplit("└─", 1)[-1].replace("&ensp;", "").strip(),
                               options, linked, row.enum_value_hint))
    if not groups:
        return
    output.extend(["", "## 枚举说明", ""])
    for title, name, options, linked, hint in groups:
        output.extend([f"### {title} {name}", "", "| 枚举成员 | 取值 | 含义 | 其他属性 |",
                       "| --- | --- | --- | --- |"])
        for option in options:
            api_value = markdown_cell(enum_value(option, linked, hint)) if enum_resolved(option, linked, hint) else "-"
            output.append(f"| {markdown_cell(option.member_name)} | {api_value} | {markdown_cell(option.description)} | {markdown_cell(enum_attributes(option, linked, hint) or '-')} |")
        output.append("")


def bulk_values(values: List[Field], document: ApiDocument) -> List[Tuple[str, str, bool]]:
    result: List[Tuple[str, str, bool]] = []

    def visit(value: Field, name: str, seen: set) -> None:
        type_ref = document.type_ref(value)
        key = type_ref.schema_id or type_ref.display_name()
        children = [] if key in seen else document.fields_for_type(type_ref)
        if children:
            for child in children:
                visit(child, name + "." + (child.wire_name or child.name), seen | {key})
            return
        example = example_for_field(value, document)
        if isinstance(example, list):
            for index, item in enumerate(example):
                key = name if value.location in {"query", "file"} else f"{name}[{index}]"
                result.append((key, str(item), value.required))
        elif isinstance(example, dict):
            result.append((name, "{}", value.required))
        else:
            result.append((name, str(example).lower() if isinstance(example, bool) else str(example), value.required))

    for field in values:
        visit(field, field.wire_name or field.name, set())
    return result


def request_url(endpoint: Endpoint, document: ApiDocument, base_url: str) -> str:
    url = base_url.rstrip("/") + endpoint.path

    def encode(value: str) -> str:
        return value if value.startswith("<") and value.endswith(">") else quote(value, safe="")

    for field in endpoint.parameters:
        if field.location == "path":
            name = field.wire_name or field.name
            url = re.sub(r"\{" + re.escape(name) + r"(?::[^}]+)?\}",
                         lambda _: encode(str(example_for_field(field, document))), url)
    query = bulk_values([field for field in endpoint.parameters if field.location in {"", "query"}], document)
    if query:
        url += "?" + "&".join(quote(name, safe="[].") + "=" + encode(value)
                                    for name, value, _ in query)
    return url


def render_markdown(document: ApiDocument, base_url: str) -> str:
    document = document.normalized()
    output = []
    for endpoint in document.endpoints:
        endpoint_document = document.for_endpoint(endpoint)
        endpoint = endpoint_document.endpoints[0]
        request_document = endpoint_document.for_direction("request")
        response_document = endpoint_document.for_direction("response")
        url = request_url(endpoint, request_document, base_url)
        output.append(f"# {endpoint.notes}")
        if endpoint.interface_notes:
            output.append("> " + endpoint.interface_notes)
        output.extend(["", "## 请求信息", "", "### 请求地址", "```", url, "```",
                       "", "### 请求方法", "```", endpoint.method, "```", ""])
        if endpoint.content_type and endpoint.method != "GET":
            output.extend(["### 请求体类型", "```", endpoint.content_type, "```", ""])
        output.extend(["## 入参"])
        request_fields = endpoint.parameters + ([endpoint.request_body] if endpoint.request_body else [])
        has_request_example = False
        if request_fields:
            if endpoint.request_body:
                example = example_for_field(endpoint.request_body, request_document)
                request_ref = request_document.type_ref(endpoint.request_body)
                known = example_resolved(request_ref, request_document)
                if json_content_type(endpoint.content_type) and known and (example != {} or schema_known(request_ref, request_document)):
                    output.extend(["### 请求结构示例 (RequestBody)", "> 占位值需替换为符合接口校验和当前环境主数据的真实值。", "",
                                   "```json", json.dumps(example, ensure_ascii=False, indent=2), "```", ""])
                    has_request_example = True
            else:
                bulk = bulk_values(endpoint.parameters, request_document)
                if bulk:
                    output.extend(["### 入参示例 (Postman Bulk Edit)", "```json"])
                    output.extend(("" if required else "//") + name + ":" + value
                                  for name, value, required in bulk)
                    output.extend(["```", ""])
                    has_request_example = True
            if not has_request_example:
                if endpoint.request_body:
                    message = (f"请求体类型 {markdown_cell(endpoint.request_body.type_name)} 未解析，无法生成示例"
                               if not example_resolved(request_document.type_ref(endpoint.request_body), request_document)
                               else "非 JSON 请求体，无法生成 JSON 示例")
                    output.extend(["> " + message, ""])
            rows = document_rows_ref(request_fields, request_document)
            if rows:
                output.extend(["### 入参字段说明", "", "| **字段** | **类型** | **必填** | **含义** | **其他参考信息** |",
                               "| -------- | -------- | -------- | -------- | -------- |"])
                for item in rows:
                    output.append(f"|{markdown_cell(item.name)}     | **{markdown_cell(markdown_type(item.type_name))}**     | {'**是**' if item.required else '否'}  |  {markdown_cell(item.description)} | {field_notes(item, request_document)}  |")
        else:
            output.extend(["> 此接口无任何入参", ""])
        output.extend(["", "## 出参"])
        if not endpoint.response_type:
            output.extend(["> 未声明出参类型，无法生成示例", ""])
        else:
            response = example_for_ref(response_document.response_ref(endpoint), response_document)
            response_ref = response_document.response_ref(endpoint)
            if response is not None and example_resolved(response_ref, response_document) and (response != {} or schema_known(response_ref, response_document)):
                output.extend(["### 出参示例", "```json", json.dumps(response, ensure_ascii=False, indent=2), "```", ""])
            else:
                if endpoint.response_type in {"void", "None", "NoneType"}:
                    output.extend(["> 此接口无任何出参", ""])
                else:
                    output.extend([f"> 出参类型 {markdown_cell(endpoint.response_type)} 未解析，无法生成示例", ""])
        rows = [] if endpoint.response_type in {"", "void", "None", "NoneType"} else document_rows_ref(
            [Field("return", endpoint.response_type, schema_id=endpoint.response_schema_id)], response_document)
        if rows:
            output.extend(["### 出参字段说明", "", "| **字段** | **类型**  | **含义** | **其他参考信息** |",
                           "| -------- | -------- | -------- | -------- |"])
            for item in rows:
                output.append(f"|{markdown_cell(item.name)}     | **{markdown_cell(markdown_type(item.type_name))}**    |  {markdown_cell(item.description)} | {field_notes(item, response_document)}  |")
        enum_tables(output, document_rows_ref(request_fields, request_document), rows,
                    request_document, response_document)
        if endpoint.response_codes:
            output.extend(["## 更多信息", "### Code 更多含义", "", "| Code | 含义 |", "| -------- | -------- |"])
            output.extend(f"| **{markdown_cell(code.code)}** | {markdown_cell(code.message)} |"
                          for code in endpoint.response_codes)
        output.append("")
    return "\n".join(output)


def _postman_item(endpoint: Endpoint, document: ApiDocument, base_url: str) -> dict:
    url = request_url(endpoint, document, base_url)
    request = {"method": endpoint.method, "header": [], "url": url}
    query = bulk_values([field for field in endpoint.parameters if field.location in {"", "query"}], document)
    form = bulk_values([field for field in endpoint.parameters if field.location in {"form", "file", "RequestPart"}], document)
    if query and not endpoint.request_body:
        request["url"] = {"raw": url, "query": [
            {"key": name, "value": value, "disabled": not required}
            for name, value, required in query]}
    for field in endpoint.parameters:
        if field.location == "header":
            request["header"].append({"key": field.wire_name or field.name,
                                      "value": str(example_for_field(field, document))})
    cookies = [(field.wire_name or field.name) + "=" + str(example_for_field(field, document))
               for field in endpoint.parameters if field.location == "cookie"]
    if cookies:
        request["header"].append({"key": "Cookie", "value": "; ".join(cookies)})
    if endpoint.request_body:
        content_type = endpoint.content_type or "application/json"
        example = example_for_field(endpoint.request_body, document)
        request_ref = document.type_ref(endpoint.request_body)
        if json_content_type(content_type) and example_resolved(request_ref, document) and (example != {} or schema_known(request_ref, document)):
            request["header"].append({"key": "Content-Type", "value": content_type})
            request["body"] = {"mode": "raw", "raw": json.dumps(example, ensure_ascii=False, indent=2)}
    elif form:
        if endpoint.content_type == "multipart/form-data":
            file_names = {field.wire_name or field.name for field in endpoint.parameters if field.location == "file"}
            request["body"] = {"mode": "formdata", "formdata": [
                ({"key": name, "src": "/path/to/file", "type": "file", "disabled": not required}
                 if any(name == file_name or name.startswith(file_name + "[") for file_name in file_names) else
                 {"key": name, "value": value, "type": "text", "disabled": not required})
                for name, value, required in form]}
        elif endpoint.content_type == "application/x-www-form-urlencoded":
            request["body"] = {"mode": "urlencoded", "urlencoded": [
                {"key": name, "value": value, "disabled": not required}
                for name, value, required in form]}
    return {"name": endpoint.notes, "request": request, "response": []}


def render_postman(document: ApiDocument, base_url: str) -> dict:
    document = document.normalized()
    items = []
    for endpoint in document.endpoints:
        specialized = document.for_endpoint(endpoint)
        items.append(_postman_item(specialized.endpoints[0], specialized.for_direction("request"), base_url))
    return {"info": {"name": "API Savior", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "item": items}


def render_curl(document: ApiDocument, base_url: str) -> str:
    document = document.normalized()
    result = ["#!/usr/bin/env sh", "set -eu", ""]
    for endpoint in document.endpoints:
        endpoint_document = document.for_endpoint(endpoint).for_direction("request")
        endpoint = endpoint_document.endpoints[0]
        url = request_url(endpoint, endpoint_document, base_url or
                          ("http://localhost:8000" if document.language == "python" else "http://localhost:8080"))
        command = ["curl", "-X", endpoint.method, shlex.quote(url)]
        for field in endpoint.parameters:
            if field.location == "header":
                command += ["-H", shlex.quote((field.wire_name or field.name) + ": " + str(example_for_field(field, endpoint_document)))]
            elif field.location == "cookie":
                command += ["-b", shlex.quote((field.wire_name or field.name) + "=" + str(example_for_field(field, endpoint_document)))]
        if endpoint.request_body:
            content_type = endpoint.content_type or "application/json"
            example = example_for_field(endpoint.request_body, endpoint_document)
            request_ref = endpoint_document.type_ref(endpoint.request_body)
            if json_content_type(content_type) and example_resolved(request_ref, endpoint_document) and (example != {} or schema_known(request_ref, endpoint_document)):
                command += ["-H", shlex.quote("Content-Type: " + content_type), "--data",
                            shlex.quote(json.dumps(example, ensure_ascii=False))]
        else:
            parameters = bulk_values([item for item in endpoint.parameters if item.location in {"form", "file", "RequestPart"}], endpoint_document)
            if endpoint.content_type == "multipart/form-data":
                file_names = {field.wire_name or field.name for field in endpoint.parameters if field.location == "file"}
                for name, value, _ in parameters:
                    is_file = any(name == file_name or name.startswith(file_name + "[") for file_name in file_names)
                    command += ["-F" if is_file else "--form-string",
                                shlex.quote(name + "=" + ("@/path/to/file" if is_file else value))]
            elif endpoint.content_type == "application/x-www-form-urlencoded":
                for name, value, _ in parameters:
                    command += ["--data-urlencode", shlex.quote(name + "=" + value)]
        result.extend([*("# " + line for line in endpoint.notes.splitlines()), " ".join(command), ""])
    return "\n".join(result)
