"""Check PRD structure and local prototype links; never certify business semantics."""

import argparse
import json
import re
import shlex
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ID_PATTERN = r"(?:(?:FR|AC|SRC|Q)-[0-9]+|Q[0-9]+)"
IDENTIFIER = re.compile(rf"^{ID_PATTERN}$")
DECLARATION = re.compile(rf"^(#{{3,4}})\s+({ID_PATTERN})\s+(.+)$")
STATUSES = {"草稿", "待确认", "已确认"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def prose(content):
    """Read declarations and resources from CommonMark tokens, never rendered HTML."""
    try:
        from markdown_it import MarkdownIt
    except ImportError as error:
        requirements = Path(__file__).with_name("requirements-product.txt")
        command = shlex.join([sys.executable, "-m", "pip", "install", "-r", str(requirements)])
        raise ValueError(f"缺少 Markdown 解析依赖；请执行 {command}") from error
    parser = MarkdownIt("commonmark")
    # Parse unsafe destinations too so local_link can reject them; nothing is rendered.
    parser.validateLink = lambda target: True
    environment = {}
    tokens = parser.parse(content, environment)
    lines, resources, quotes = [], [], 0
    html = Prototype()
    for index, token in enumerate(tokens):
        if token.type == "html_block":
            html.feed(token.content)
        elif token.type == "blockquote_open":
            quotes += 1
        elif token.type == "blockquote_close":
            quotes -= 1
        elif token.type == "inline":
            text = "".join(child.content if child.type in {"text", "code_inline", "image"}
                           else "\n" if child.type in {"softbreak", "hardbreak"} else ""
                           for child in token.children or [])
            previous = tokens[index - 1]
            if previous.type == "heading_open":
                if previous.level and re.match(rf"^{ID_PATTERN}(?:\s|$)", text):
                    raise ValueError("FR、AC、SRC、Q 标题必须位于文档顶层，不能放在引用或列表中")
                lines.append(("\\" if previous.level else "") + "#" * int(previous.tag[1:]) + " " + text)
            else:
                # Literal Markdown punctuation in a paragraph must not create declarations.
                lines.extend(("> " if quotes else "") + ("\\" if line.startswith(("#", ">")) else "") + line
                             for line in text.splitlines())
            for child in token.children or []:
                if child.type in {"link_open", "image"}:
                    resources.append(child.attrGet("src" if child.type == "image" else "href"))
                elif child.type == "html_inline":
                    html.feed(child.content)
    html.close()
    if html.errors:
        raise ValueError("；".join(html.errors))
    resources.extend(target for target, _ in html.resources)
    for style in html.styles:
        resources.extend(stylesheet_resources(style))
    resources.extend(reference["href"] for reference in environment.get("references", {}).values())
    return "\n".join(lines), resources


def field(content, name, quoted=False):
    prefix = r">\s*" if quoted else ""
    matches = re.findall(rf"(?m)^{prefix}{re.escape(name)}[：:]\s*([^\n]+)$", content)
    return matches[0].strip() if len(matches) == 1 else None


def local_link(target, root, base, allow_https=True, source_roots=()):
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        if allow_https and parsed.scheme == "https" and parsed.netloc:
            return None
        return f"不支持的外部资源：{target}"
    path = unquote(parsed.path)
    if not path:
        return None
    relative = Path(path)
    if relative.is_absolute() or "\\" in path:
        return f"资源必须是交付目录内的相对路径：{target}"
    resolved = (base / relative).resolve()
    if not any(resolved.is_relative_to(allowed.resolve()) for allowed in (root, *source_roots)):
        return f"资源超出交付目录：{target}"
    if not resolved.is_file():
        return f"资源不存在：{target}"
    return None


def prototype_link(target, root, base, allow_https=False):
    problem = local_link(target, root, base, allow_https)
    parsed = urlsplit(target)
    if not problem and not parsed.scheme and not parsed.netloc and parsed.path:
        relative = (base / unquote(parsed.path)).resolve().relative_to(root.resolve())
        if relative.parts[0] == "evidence" or relative.as_posix() in {"bundle.json", "review.md"}:
            return f"原型不能引用验收输出作为输入：{target}"
    return problem


def stylesheet_resources(content):
    """Keep portable CSS resource syntax small and explicit."""
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.S)
    if "\\" in content or re.search(r"@import\b", content, flags=re.I):
        raise ValueError("原型 CSS 不支持转义或 @import；请使用直接链接的本地样式与资源")
    return [next(value for value in match.groups() if value is not None).strip()
            for match in re.finditer(r"url\s*\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)]*))\s*\)", content, flags=re.I)]


def stylesheet_errors(content, root, base):
    try:
        targets = stylesheet_resources(content)
    except ValueError as error:
        return [str(error)]
    errors = []
    for target in targets:
        error = prototype_link(target, root, base)
        if error:
            errors.append(error)
    return errors


class Prototype(HTMLParser):
    def __init__(self):
        super().__init__()
        self.versions = []
        self.requirements = set()
        self.scenarios = {}
        self.resources = []
        self.parents = []
        self.styles = []
        self.stylesheets = set()
        self.errors = []
        self.pages = []
        self.changes = []

    def handle_starttag(self, tag, attrs):
        if len({name for name, _ in attrs}) != len(attrs):
            self.errors.append("HTML 不支持重复属性，请保留唯一值")
        if tag == "base":
            self.errors.append("原型不支持 base 元素，请使用交付目录内的直接相对链接")
        attrs = dict(attrs)
        resources = ("src", "href", "poster") + (("data",) if tag == "object" else ())
        for name in ("data-requirement", "data-scenario", "data-page", "data-change", "data-change-note", "srcset", "imagesrcset", *resources):
            if name in attrs and attrs[name] is None:
                self.errors.append(f"原型属性缺少值：{name}")
                attrs[name] = ""
        if tag == "meta" and attrs.get("name") == "product-version":
            self.versions.append(attrs.get("content", ""))
        inherited = self.parents[-1][1] if self.parents else set()
        requirements = set(attrs.get("data-requirement", "").split()) if "data-requirement" in attrs else inherited
        self.requirements.update(requirements)
        page = attrs.get("data-page", self.parents[-1][2] if self.parents else "")
        if "data-page" in attrs:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", page):
                self.errors.append("页面标识须为简短字母、数字、连字符或下划线")
            self.pages.append(page)
        if "data-change" in attrs:
            self.changes.append((attrs["data-change"], attrs.get("data-change-note", "").strip(),
                                 page, requirements, set(attrs.get("data-scenario", "").split())))
        for scenario in attrs.get("data-scenario", "").split():
            self.scenarios.setdefault(scenario, []).append(requirements)
        for name in resources:
            if name in attrs:
                self.resources.append((attrs[name], tag == "a" and name == "href"))
        for name in ("srcset", "imagesrcset"):
            if name in attrs:
                for candidate in attrs[name].split(","):
                    parts = candidate.split()
                    if not 1 <= len(parts) <= 2 or len(parts) == 2 and not re.fullmatch(r"(?:[0-9]+w|[0-9]+(?:\.[0-9]+)?x)", parts[1]):
                        self.errors.append(f"原型响应式资源格式错误：{name}")
                    else:
                        self.resources.append((parts[0], False))
        if attrs.get("style"):
            self.styles.append(attrs["style"])
        if tag == "link" and "stylesheet" in (attrs.get("rel") or "").lower().split():
            self.stylesheets.add(attrs.get("href", ""))
        if tag not in VOID_TAGS:
            self.parents.append((tag, requirements, page))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.parents) - 1, -1, -1):
            if self.parents[index][0] == tag:
                del self.parents[index:]
                break

    def handle_data(self, data):
        if self.parents and self.parents[-1][0] == "style":
            self.styles.append(data)


def approval_sections(content, tracking=False):
    """Keep raw rule bodies and shared context; ignore only visible version metadata."""
    _, resources = prose(content)
    from markdown_it import MarkdownIt
    tokens = MarkdownIt("commonmark").parse(content)
    lines, headings, opaque = content.splitlines(), [], set()
    for index, token in enumerate(tokens):
        if token.type in {"fence", "code_block", "html_block"} and token.map:
            opaque.update(range(*token.map))
        if token.type == "heading_open" and token.level == 0 and int(token.tag[1:]) <= 3:
            title = "".join(child.content for child in tokens[index + 1].children or []
                            if child.type in {"text", "code_inline", "image"})
            match = re.match(r"^((?:FR|SRC)-[0-9]+)\s+", title) if token.tag == "h3" else None
            headings.append((token.map[0], match[1] if match else None))
    boundaries = [(0, None), *headings, (len(lines), None)]
    sections, shared = {}, []
    for (start, identifier), (end, _) in zip(boundaries, boundaries[1:]):
        if identifier:
            sections[identifier] = "\n".join(lines[start:end]).rstrip()
        else:
            context = []
            for number in range(start, end):
                line = lines[number]
                normalized = prose(line)[0] if number not in opaque and line.lstrip().startswith(">") else ""
                if (field(normalized, "产品版本", quoted=True) or field(normalized, "状态", quoted=True)
                        or tracking and field(normalized, "追踪版本", quoted=True)):
                    continue
                context.append(line)
            shared.append("\n".join(context).rstrip())
    return sections, "\n".join(shared), resources


def approval_content(content, companion=None, internal_resources=()):
    """Use independent CommonMark source positions; never flatten approved rule structure."""
    sections, shared, resources = approval_sections(content)
    if companion is not None:
        other_sections, other_shared, other_resources = approval_sections(companion, tracking=True)
        sections.update(other_sections)
        shared += "\n\n## 文档边界\n\n" + other_shared
        resources += other_resources
    resources = [target for target in resources if target not in internal_resources]
    values = {}
    for identifier, body in sections.items():
        if identifier.startswith("FR-"):
            declaration = re.split(r"(?m)^####[ \t]+", prose(body)[0], maxsplit=1)[0]
            refs = (field(declaration, "依据") or "").split()
            values[identifier] = (body, tuple((ref, sections.get(ref, "")) for ref in refs),
                                  shared, tuple(resources))
    return values


def document_contract(content, previous=None, *, parsed=None, meaning=None, confirmation_resources=None):
    errors, requirements, scenarios, sources, questions = [], {}, {}, {}, []
    if meaning is None:
        meaning = approval_content(content)
    clean, resources = prose(content) if parsed is None else parsed
    confirmation_resources = resources if confirmation_resources is None else confirmation_resources
    titles = re.findall(r"(?m)^#[ \t]+([^\n]*)$", clean)
    if len(titles) != 1 or not titles[0].strip():
        errors.append("PRD 必须有且仅有一个非空一级标题")
    version = field(clean, "产品版本", quoted=True)
    status = field(clean, "状态", quoted=True)
    if not version or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", version):
        errors.append("缺少或非法的产品版本")
    if status not in STATUSES:
        errors.append("文档状态必须是草稿、待确认或已确认")
    if "<!-- TEMPLATE:" in content:
        errors.append("仍有模板提示未移除")
    lines = clean.splitlines()
    seen, current = set(), None
    for index, line in enumerate(lines):
        match = DECLARATION.match(line)
        if not match:
            if re.match(rf"^#{{1,6}}\s+(?:{ID_PATTERN}(?:\s|$)|(?:FR|AC|SRC|Q)-)", line):
                errors.append(f"非法标识或标题层级：{line}")
            if re.match(r"^#{1,3}\s", line):
                current = None
            continue
        level, identifier, _title = match.groups()
        if identifier in seen:
            errors.append(f"重复标识：{identifier}")
        seen.add(identifier)
        end = index + 1
        while end < len(lines) and not re.match(r"^#{1,4}\s", lines[end]):
            end += 1
        body = "\n".join(lines[index + 1:end]).strip()
        kind = identifier.split("-")[0]
        expected = "####" if kind == "AC" else "###"
        if level != expected:
            errors.append(f"标识标题层级错误：{identifier}")
        if not body:
            errors.append(f"标识缺少内容：{identifier}")
        if kind == "FR":
            current = identifier if level == "###" else None
            requirements[identifier] = {"status": field(body, "状态"), "source": field(body, "依据"),
                                        "prototype": field(body, "原型"), "confirmation": field(body, "确认记录")}
        elif kind == "AC":
            scenarios[identifier] = current
            if current is None:
                errors.append(f"验收场景没有所属需求：{identifier}")
        else:
            current = None
            if kind == "SRC":
                sources[identifier] = body
            else:
                questions.append(identifier)
    if not requirements:
        errors.append("至少声明一个 FR 需求及其 AC 验收场景")
    for identifier, requirement in requirements.items():
        if requirement["status"] not in STATUSES:
            errors.append(f"需求缺少有效状态：{identifier}")
        refs = (requirement["source"] or "").split()
        if not refs or any(ref not in sources for ref in refs):
            errors.append(f"需求来源未声明：{identifier}")
        if requirement["prototype"] not in {"是", "否"}:
            errors.append(f"需求原型范围必须为是或否：{identifier}")
        if identifier not in scenarios.values():
            errors.append(f"需求缺少验收场景：{identifier}")
        if requirement["status"] == "已确认":
            record = requirement["confirmation"] or ""
            if not record or any(word in record for word in ("待确认", "建议", "默认", "示例")):
                errors.append(f"已确认需求缺少明确确认记录：{identifier}")
            elif previous and identifier in previous and previous[identifier][0] == record and previous[identifier][1] != meaning.get(identifier):
                errors.append(f"需求内容已变更，必须重新确认：{identifier}")
            elif not version or not re.search(rf"(?<![A-Za-z0-9._-]){re.escape(version)}(?![A-Za-z0-9._-])", record):
                if any(urlsplit(resource).scheme or urlsplit(resource).path for resource in confirmation_resources):
                    errors.append(f"引用资料未冻结，旧确认须人工复核：{identifier}")
                elif not previous or previous.get(identifier) != (record, meaning.get(identifier)):
                    errors.append(f"确认记录未绑定当前产品版本且无未变更基线证明：{identifier}")
    if status == "已确认" and (questions or any(req["status"] != "已确认" for req in requirements.values())):
        errors.append("已确认文档仍有未决事项或未确认需求")
    return errors, version, requirements, scenarios, resources


def document_input(document, tracking=None):
    document = Path(document).resolve()
    content = document.read_text(encoding="utf-8")
    parsed, split_meaning, confirmation_resources = None, None, None
    if tracking is not None:
        tracking = Path(tracking).resolve()
        # Explicit sibling only: source allowlists must never widen the delivery contract.
        if tracking == document or tracking.parent != document.parent or not tracking.is_file():
            raise ValueError("追踪文件必须是业务主文同目录下实际存在的独立文件")
        main_prose, main_resources = prose(content)
        main_version = field(main_prose, "产品版本", quoted=True)
        main_titles = re.findall(r"(?m)^#[ \t]+([^\n]*)$", main_prose)
        if (not main_version or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", main_version)
                or field(main_prose, "状态", quoted=True) not in STATUSES
                or len(main_titles) != 1 or not main_titles[0].strip()):
            raise ValueError("业务主文须独立声明有效产品版本、状态及唯一一级标题")
        linked = any(not urlsplit(target).scheme and not urlsplit(target).netloc
                     and urlsplit(target).path
                     and (document.parent / unquote(urlsplit(target).path)).resolve() == tracking
                     for target in main_resources)
        if not linked:
            raise ValueError("业务主文必须链接显式指定的追踪文件")
        tracking_content = tracking.read_text(encoding="utf-8")
        tracking_prose, tracking_resources = prose(tracking_content)
        if field(tracking_prose, "追踪版本", quoted=True) != main_version:
            raise ValueError("追踪版本必须与业务主文产品版本一致")
        resources = main_resources + tracking_resources
        # Parse files independently so an open fence/comment cannot swallow the other file.
        parsed = (main_prose + "\n\n## 文档边界\n\n" + tracking_prose, resources)
        # Only the two explicit files are frozen here; other referenced files stay unproven.
        internal = [target for target in resources
                    if not urlsplit(target).scheme and not urlsplit(target).netloc
                    and urlsplit(target).path
                    and (document.parent / unquote(urlsplit(target).path)).resolve() in {document, tracking}]
        confirmation_resources = [target for target in resources if target not in internal]
        split_meaning = approval_content(content, tracking_content, internal)
        content += "\n\n" + tracking_content
    return content, parsed, split_meaning, confirmation_resources


def resource_errors(resources, root, source_roots=()):
    errors = []
    for resource in resources:
        error = local_link(resource, root, root, source_roots=source_roots)
        if error:
            errors.append(error)
        elif not urlsplit(resource).scheme and Path(unquote(urlsplit(resource).path)).suffix.lower() == ".css":
            stylesheet = (root / unquote(urlsplit(resource).path)).resolve()
            if stylesheet.is_relative_to(root):
                errors.extend(stylesheet_errors(stylesheet.read_text(encoding="utf-8"), root, stylesheet.parent))
    return errors


def validate(document, prototype=None, baselines=(), source_roots=(), tracking=None):
    source_roots = tuple(Path(path).resolve() for path in source_roots)
    if any(not path.is_dir() for path in source_roots):
        raise ValueError("来源根目录必须是已存在的目录")
    document = Path(document).resolve()
    content, parsed, split_meaning, confirmation_resources = document_input(document, tracking)
    previous, baseline_errors = None, []
    for baseline in baselines:
        paths = (baseline,) if isinstance(baseline, (str, Path)) else baseline
        if len(paths) not in {1, 2}:
            raise ValueError("每个历史基线须显式给出一个主文，或主文及同版追踪两个文件")
        old_content, old_parsed, meanings, old_resources = document_input(*paths)
        old_errors, _, old_requirements, _, old_links = document_contract(
            old_content, previous, parsed=old_parsed, meaning=meanings, confirmation_resources=old_resources)
        old_errors.extend(resource_errors(old_links, Path(paths[0]).resolve().parent, source_roots))
        baseline_errors.extend(f"历史基线无效：{problem}" for problem in old_errors)
        meanings = approval_content(old_content) if meanings is None else meanings
        previous = {key: (value["confirmation"], meanings[key]) for key, value in old_requirements.items()
                    if value["status"] == "已确认" and key in meanings} if not baseline_errors else None
    errors, version, requirements, scenarios, resources = document_contract(
        content, previous, parsed=parsed, meaning=split_meaning, confirmation_resources=confirmation_resources)
    errors = baseline_errors + errors
    root = document.parent
    errors.extend(resource_errors(resources, root, source_roots))
    if prototype is not None:
        prototype = Path(prototype).resolve()
        if not prototype.is_relative_to(root):
            errors.append("原型必须位于 PRD 交付目录内")
        else:
            errors.extend(validate_prototype_pages(prototype, root, version, requirements, scenarios))
    return errors


def validate_prototype_pages(prototype, root, version, requirements, scenarios):
    """Check linked local HTML declarations; reachability and meaning need browser/content review."""
    errors, pending, visited, page_ids, covered_fr, covered_ac = [], [prototype], set(), set(), set(), set()
    while pending:
        path = pending.pop().resolve()
        if path in visited:
            continue
        if len(visited) >= 4096 or path.stat().st_size > 8 * 1024 * 1024:
            errors.append("原型 HTML 超出输入快照上限")
            break
        visited.add(path)
        page = Prototype()
        page.feed(path.read_text(encoding="utf-8"))
        page.close()
        errors.extend(page.errors)
        if page.versions != [version]:
            errors.append(f"原型产品版本缺失、重复或与 PRD 不一致：{path.name}")
        for identifier in page.pages:
            if identifier in page_ids:
                errors.append(f"原型页面标识重复：{identifier}")
            page_ids.add(identifier)
        for identifier in page.requirements:
            if identifier not in requirements:
                errors.append(f"原型引用未知需求：{identifier}")
        for scenario, usages in page.scenarios.items():
            for owners in usages:
                if scenario not in scenarios or scenarios[scenario] not in owners:
                    errors.append(f"原型验收场景与需求不匹配：{scenario}")
        for kind, note, owner_page, owners, acceptance in page.changes:
            if kind not in {"added", "modified", "removed", "unchanged"} or not note or not owner_page \
                    or not owners or not owners <= requirements.keys() or not acceptance \
                    or any(ac not in scenarios or scenarios[ac] not in owners for ac in acceptance):
                errors.append("变更标注须声明类型、说明、所属页面及有效 FR/AC")
        covered_fr.update(page.requirements)
        covered_ac.update(page.scenarios)
        for resource, external_link in page.resources:
            error = prototype_link(resource, root, path.parent, allow_https=external_link)
            if error:
                errors.append(error)
                continue
            parsed = urlsplit(resource)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            linked = (path.parent / unquote(parsed.path)).resolve()
            if linked.suffix.lower() in {".html", ".htm"}:
                pending.append(linked)
            elif not external_link and (resource in page.stylesheets or linked.suffix.lower() == ".css"):
                errors.extend(stylesheet_errors(linked.read_text(encoding="utf-8"), root, linked.parent))
        for style in page.styles:
            errors.extend(stylesheet_errors(style, root, path.parent))
    for identifier, requirement in requirements.items():
        if requirement["prototype"] == "是":
            if identifier not in covered_fr:
                errors.append(f"原型未覆盖需求：{identifier}")
            for scenario, owner in scenarios.items():
                if owner == identifier and scenario not in covered_ac:
                    errors.append(f"原型未覆盖场景：{scenario}")
    return errors


def review_product_content(content):
    """Inventory visible headings; these signals never certify content quality."""
    text, _ = prose(content)
    headings = re.findall(r"(?m)^#{1,4} (.+)$", text)
    dimensions = (
        ("背景与目标", ("背景", "目标", "background", "goal")),
        ("目标用户与场景", ("用户", "角色", "user", "actor")),
        ("范围与优先级", ("范围", "优先级", "scope", "priority")),
        ("功能规则", ("需求", "规则", "requirement", "rule")),
        ("用例与验收", ("用例", "验收", "AC-", "acceptance", "use case")),
        ("交互与原型", ("交互", "原型", "interaction", "prototype")),
        ("非功能与依赖", ("非功能", "依赖", "约束", "constraint", "nonfunctional", "dependency")),
        ("未决与交接", ("未决", "待确认", "交接", "handoff", "open question")),
    )
    observations = []
    for name, words in dimensions:
        signals = [heading for heading in headings if any(word.lower() in heading.lower() for word in words)]
        observations.append({"dimension": name, "status": "mentioned" if signals else "not_observed",
                             "headings": signals})
    questions = {
        "business": ["本次变化能解决谁的什么问题，范围和效果依据是否清楚？",
                     "关键规则、例外和职责变化是否已明确，哪些仍需业务决定？"],
        "engineering": ["现状依据、变更前后、历史及进行中对象、兼容和依赖是否可追溯？",
                        "规则、图和原型是否一致，哪些业务阻塞项及技术设计问题尚未解决？"],
        "qa": ["每条 FR 是否有可观察 AC，含边界、权限、状态及失败恢复？",
               "历史回归范围、数据条件、跨角色完整旅程和未覆盖证据是否清楚？"],
    }
    return {"dimensions": observations, "semanticReview": "required", "humanConfirmation": "not_proven",
            "workflow": "not_connected", "handoffReview": {"status": "not_run", "questions": questions}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--prototype", type=Path)
    parser.add_argument("--tracking", type=Path, help="显式组合主文所链接的同目录追踪文件；追踪版本须一致")
    parser.add_argument("--baseline", type=Path, action="append", nargs="+", default=[], metavar="FILE",
                        help="历史主文 [同版追踪]，每组1或2个文件，按从旧到新重复传入；不证明用户授权")
    parser.add_argument("--source-root", type=Path, action="append", default=[], help="显式允许PRD引用该目录内的来源文件，可重复；不放宽原型资源边界")
    parser.add_argument("--review", action="store_true", help="附加八维标题观察及分角色交接问题，不判定业务语义或人工确认")
    args = parser.parse_args()
    try:
        problems = validate(args.file, args.prototype, args.baseline, args.source_root, args.tracking)
    except (OSError, UnicodeError, ValueError) as error:
        problems = [f"无法校验交付物：{error}"]
    report = {"valid": not problems, "file": str(args.file), "problems": problems,
              "prototypeChecked": args.prototype is not None, "semanticCheck": "not_proven", "browserCheck": "not_run"}
    if args.tracking is not None:
        report["trackingFile"] = str(args.tracking)
    if args.review:
        report["review"] = review_product_content(args.file.read_text(encoding="utf-8")) if not problems else None
    print(json.dumps(report, ensure_ascii=False))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
