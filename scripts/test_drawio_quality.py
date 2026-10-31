"""Source geometry guards; no desktop renderer is started by these tests."""

import contextlib
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch


def diagram(label="入口", edge_style="noEdgeStyle=1;", points=((200, 130),)):
    model = ET.Element("mxGraphModel", pageWidth="600", pageHeight="400")
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")
    for ident, value, x, y in (("a", label, 20, 100), ("b", "存储", 380, 100)):
        cell = ET.SubElement(root, "mxCell", id=ident, value=value, vertex="1", parent="1",
                             style="whiteSpace=wrap;fontSize=14;spacing=8;")
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y), width="120", height="60")
    edge = ET.SubElement(root, "mxCell", id="ab", value="调用", edge="1", parent="1",
                         source="a", target="b",
                         style=edge_style + "exitX=1;exitY=0.5;entryX=0;entryY=0.5;fontSize=12;")
    geometry = ET.SubElement(edge, "mxGeometry", relative="1")
    array = ET.SubElement(geometry, "Array", {"as": "points"})
    for x, y in points:
        ET.SubElement(array, "mxPoint", x=str(x), y=str(y))
    return model


def add_vertex(model, ident, x, y, width=50, height=50, value=""):
    cell = ET.SubElement(model.find("root"), "mxCell", id=ident, vertex="1", parent="1",
                         value=value, style="fontSize=12;")
    ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y), width=str(width), height=str(height))
    return cell


class DrawioQualityTest(unittest.TestCase):
    def check(self, model):
        from drawio_quality import check_drawio_quality
        return check_drawio_quality(ET.tostring(model, encoding="unicode"))

    def test_valid_chinese_polyline_and_boundary_contact(self):
        model = diagram()
        add_vertex(model, "touch", 180, 130, height=20)
        report = self.check(model)
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["textMeasurement"], "estimated")
        self.assertEqual(report["visualReview"], "required")

    def test_edge_crosses_unrelated_node(self):
        model = diagram()
        add_vertex(model, "blocker", 180, 105)
        self.assertTrue(any("ab" in p and "blocker" in p and "edge_node" in p
                            for p in self.check(model)["problems"]))

    def test_edge_label_collides_with_another_label(self):
        model = diagram()
        add_vertex(model, "caption", 230, 118, width=60, height=24, value="说明文字")
        self.assertTrue(any("label_overlap" in p and "ab" in p and "caption" in p
                            for p in self.check(model)["problems"]))

    def test_edge_label_overlaps_node_even_when_route_clears_it(self):
        model = diagram()
        add_vertex(model, "nearby", 250, 131, width=40, height=40)
        self.assertTrue(any("label_node" in p and "ab" in p and "nearby" in p
                            for p in self.check(model)["problems"]))

    def test_page_guides_are_not_export_bounds(self):
        report = self.check(diagram(points=((250, -20),)))
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["status"], "partial")
        self.assertTrue(any("ab" in p for p in report["unchecked"]))
        model = diagram()
        add_vertex(model, "next_page", 650, 100)
        self.assertEqual(self.check(model)["problems"], [])

    def test_label_crossed_by_unrelated_edge(self):
        model = diagram()
        caption = add_vertex(model, "caption", 180, 115, width=80, height=30, value="说明")
        caption.set("style", "fillColor=none;strokeColor=none;fontSize=12;")
        self.assertTrue(any("label_edge" in p and "caption" in p for p in self.check(model)["problems"]))

    def test_native_text_style_does_not_create_an_invisible_box_obstacle(self):
        model = diagram()
        caption = add_vertex(model, "caption", 180, 90, width=120, height=60, value="注")
        caption.set("style", "text;html=0;align=left;verticalAlign=top;fontSize=12;")
        self.assertEqual(self.check(model)["problems"], [])

    def test_generated_landscape_checks_its_explicit_routes(self):
        from architecture_landscape import render_landscape
        from drawio_quality import check_drawio_quality
        ir = {"title": "服务架构", "scope": {"system": "订单", "container": "订单服务"},
              "elements": [{"id": "a", "type": "service", "name": "服务", "description": "处理订单"},
                           {"id": "b", "type": "database", "name": "数据库", "description": "保存订单"}],
              "relations": [{"from": "a", "to": "b", "kind": "dependency", "label": "保存"}]}
        for kind, expected in (("external_system", "pass"), ("database", "partial")):
            with self.subTest(kind=kind):
                ir["elements"][1]["type"] = kind
                report = check_drawio_quality(render_landscape(ir))
                self.assertEqual(report["problems"], [])
                self.assertEqual(report["status"], expected)

    def test_c4_background_bands_are_not_business_obstacles(self):
        from diagram_profiles import render_view
        from drawio_quality import check_drawio_quality
        ir = {"profile": "c4-context", "title": "C4", "scope": {"system": "Demo"},
              "elements": [{"id": "a", "type": "person", "name": "User", "description": "Caller"},
                           {"id": "b", "type": "software_system", "name": "Orders", "description": "Process"}],
              "relations": [{"from": "a", "to": "b", "label": "Calls"}]}
        self.assertEqual(check_drawio_quality(render_view(ir, "drawio"))["problems"], [])

    def test_swimlane_header_is_partial_instead_of_a_node_obstacle(self):
        model = diagram()
        lane = add_vertex(model, "lane", 10, 80, width=550, height=120, value="泳道标题")
        lane.set("style", "swimlane;html=0;")
        report = self.check(model)
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["status"], "partial")

    def test_sequence_lifelines_do_not_block_message_labels(self):
        from diagram_profiles import render_view
        from drawio_quality import check_drawio_quality
        ir = {"profile": "uml-sequence", "title": "Sequence",
              "elements": [{"id": ident, "name": ident.upper()} for ident in ("a", "b", "c")],
              "relations": [{"from": "a", "to": "c", "order": 1, "kind": "call", "label": "Request"}]}
        report = check_drawio_quality(render_view(ir, "drawio"))
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["status"], "partial")

    def test_text_clipping_and_explicit_line_breaks(self):
        model = diagram("必须完整显示的跨区域订单一致性校验服务名称" * 3)
        self.assertTrue(any("text_fit" in p and "a" in p for p in self.check(model)["problems"]))
        model = diagram("第一行\n第二行")
        self.assertEqual(self.check(model)["problems"], [])

    def test_html_font_size_is_checked_without_discarding_text(self):
        model = diagram()
        cell = model.find("root/mxCell[@id='a']")
        cell.set("style", "html=1;whiteSpace=wrap;spacing=8;")
        cell.set("value", '<div style="font-size:60px">完整中文标题</div>')
        self.assertTrue(any("text_fit" in p and "a" in p for p in self.check(model)["problems"]))

    def test_rich_html_is_not_claimed_fully_measured(self):
        model = diagram()
        cell = model.find("root/mxCell[@id='a']")
        cell.set("style", "html=1;")
        cell.set("value", '<img src="icon.png" width="200">入口')
        self.assertEqual(self.check(model)["status"], "partial")

    def test_html_source_indentation_does_not_create_visible_lines(self):
        model = diagram()
        cell = model.find("root/mxCell[@id='a']")
        cell.set("style", cell.get("style") + "html=1;")
        cell.set("value", '<div>\n    <span>入口</span>\n</div>')
        cell.find("mxGeometry").set("height", "36")
        self.assertEqual(self.check(model)["problems"], [])

    def test_explicit_blank_lines_contribute_to_text_height(self):
        for value, html in (("A\n\n\nB", "0"), ("A<br/><br/><br/>B", "1")):
            with self.subTest(value=value):
                model = diagram(value)
                cell = model.find("root/mxCell[@id='a']")
                cell.set("style", cell.get("style") + "html=" + html + ";")
                self.assertTrue(any("text_fit" in p for p in self.check(model)["problems"]))

    def test_unhandled_html_layout_does_not_produce_fabricated_collisions(self):
        for value in ('<div style="display:none">' + "长文" * 100 + '</div>入口',
                      '<div style="font-size:2em">入口</div>',
                      '<div style="padding:80px">入口</div>'):
            with self.subTest(value=value):
                model = diagram()
                cell = model.find("root/mxCell[@id='a']")
                cell.set("style", cell.get("style") + "html=1;")
                cell.set("value", value)
                report = self.check(model)
                self.assertEqual(report["problems"], [])
                self.assertEqual(report["status"], "partial")

    def test_external_label_is_not_checked_at_its_old_center(self):
        model = diagram()
        caption = add_vertex(model, "caption", 230, 118, width=60, height=24, value="说明")
        caption.set("style", "fillColor=none;strokeColor=none;labelPosition=left;")
        report = self.check(model)
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["status"], "partial")

    def test_rotated_or_relative_terminal_is_partial_instead_of_wrong_route(self):
        for relative in (False, True):
            with self.subTest(relative=relative):
                model = diagram()
                cell = model.find("root/mxCell[@id='a']")
                if relative:
                    cell.find("mxGeometry").set("relative", "1")
                else:
                    cell.set("style", cell.get("style") + "rotation=90;")
                    add_vertex(model, "blocker", 180, 105)
                report = self.check(model)
                self.assertEqual(report["problems"], [])
                self.assertEqual(report["status"], "partial")

    def test_endpoint_offsets_are_not_silently_ignored(self):
        model = diagram()
        edge = model.find("root/mxCell[@id='ab']")
        edge.set("style", edge.get("style") + "exitDy=80;")
        self.assertEqual(self.check(model)["status"], "partial")

    def test_perimeter_projection_is_not_mistaken_for_a_fixed_port(self):
        model = diagram()
        edge = model.find("root/mxCell[@id='ab']")
        edge.set("style", edge.get("style") + "exitX=0.5;exitY=0.5;")
        self.assertEqual(self.check(model)["status"], "partial")

    def test_degenerate_route_is_not_claimed_fully_checked(self):
        model = diagram(points=())
        edge = model.find("root/mxCell[@id='ab']")
        edge.set("target", "a")
        edge.set("style", "noEdgeStyle=1;exitX=1;exitY=0.5;entryX=1;entryY=0.5;")
        self.assertEqual(self.check(model)["status"], "partial")

    def test_empty_html_style_attribute_does_not_crash(self):
        model = diagram()
        cell = model.find("root/mxCell[@id='a']")
        cell.set("style", cell.get("style") + "html=1;")
        cell.set("value", '<div style>入口</div>')
        self.assertEqual(self.check(model)["problems"], [])

    def test_shifted_vertex_and_edge_labels_are_not_checked_at_old_positions(self):
        for target in ("vertex", "edge"):
            with self.subTest(target=target):
                model = diagram()
                if target == "vertex":
                    cell = add_vertex(model, "caption", 230, 118, width=60, height=24, value="说明")
                    cell.set("style", "fillColor=none;strokeColor=none;")
                    ET.SubElement(cell.find("mxGeometry"), "mxPoint", {"as": "offset", "x": "0", "y": "100"})
                else:
                    cell = model.find("root/mxCell[@id='ab']")
                    cell.set("style", cell.get("style") + "textRotation=90;")
                    add_vertex(model, "caption", 250, 131, width=40, height=40, value="说明")
                report = self.check(model)
                self.assertEqual(report["problems"], [])
                self.assertEqual(report["status"], "partial")

    def test_unsupported_shape_or_named_style_is_not_a_rectangular_obstacle(self):
        for style in ("ellipse;", "shape=triangle;", "customPreset;"):
            with self.subTest(style=style):
                model = diagram()
                cell = add_vertex(model, "shape", 180, 105)
                cell.set("style", style)
                report = self.check(model)
                self.assertEqual(report["problems"], [])
                self.assertEqual(report["status"], "partial")

    def test_zero_width_line_and_visible_overflow_are_not_invalid_cards(self):
        model = diagram()
        add_vertex(model, "line", 550, 100, width=0)
        self.assertEqual(self.check(model)["problems"], [])
        self.assertEqual(self.check(model)["status"], "partial")
        model = diagram("长文" * 100)
        cell = model.find("root/mxCell[@id='a']")
        cell.set("style", cell.get("style") + "overflow=visible;")
        self.assertEqual(self.check(model)["problems"], [])
        self.assertEqual(self.check(model)["status"], "partial")

    def test_duplicate_ids_cannot_hide_a_clipped_label(self):
        model = diagram("长文" * 100)
        add_vertex(model, "a", 20, 100, width=120, height=60, value="入口")
        self.assertEqual(self.check(model)["status"], "fail")

    def test_object_wrapper_label_is_not_silently_ignored(self):
        model = diagram()
        root = model.find("root")
        cell = root.find("mxCell[@id='a']")
        root.remove(cell)
        cell.attrib.pop("id")
        cell.attrib.pop("value")
        root.remove(root.find("mxCell[@id='ab']"))
        ET.SubElement(root, "object", id="a", label="长文" * 100).append(cell)
        self.assertNotEqual(self.check(model)["status"], "pass")

    def test_unmarked_parent_role_and_label_placeholders_are_partial(self):
        model = diagram()
        add_vertex(model, "group", 150, 90, width=180, height=100)
        child = add_vertex(model, "child", 5, 5, width=30, height=30)
        child.set("parent", "group")
        self.assertEqual(self.check(model)["status"], "partial")
        model = diagram("%description%")
        model.find("root/mxCell[@id='a']").set("style", "placeholders=1;")
        self.assertEqual(self.check(model)["status"], "partial")

    def test_auto_route_is_not_claimed_checked(self):
        model = diagram(edge_style="edgeStyle=orthogonalEdgeStyle;")
        report = self.check(model)
        self.assertEqual(report["status"], "partial")
        self.assertTrue(any("ab" in p for p in report["unchecked"]))

    def test_noncentral_edge_label_is_not_claimed_checked(self):
        model = diagram()
        model.find("root/mxCell[@id='ab']/mxGeometry").set("x", "0.5")
        self.assertEqual(self.check(model)["status"], "partial")

    def test_native_concept_and_partial_routes_use_existing_engine(self):
        from render_native_diagram import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "concept.drawio"
            for style, expected in (("noEdgeStyle=1;", "pass"),
                                    ("edgeStyle=orthogonalEdgeStyle;", "partial")):
                with self.subTest(style=style):
                    source.write_text(ET.tostring(diagram(edge_style=style), encoding="unicode"))
                    with patch("render_native_diagram.find_engine", return_value="fixture-drawio"), \
                            patch("render_native_diagram._check_diagram", return_value=None) as renderer, \
                            contextlib.redirect_stdout(io.StringIO()) as stdout:
                        code = main(["--engine", "drawio", "--input", str(source), "--output", str(root / "out")])
                    report = json.loads(stdout.getvalue())
                    self.assertEqual(code, 0)
                    self.assertTrue(report["valid"])
                    self.assertEqual(report["sourceEvidence"], "not_checked")
                    self.assertEqual(report["drawioQuality"]["status"], expected)
                    self.assertEqual(report["drawioQuality"]["visualReview"], "required")
                    renderer.assert_called_once()

    def test_nested_parent_coordinates_are_resolved(self):
        model = diagram()
        group = add_vertex(model, "group", 170, 90, width=100, height=100)
        group.set("style", "container=1;")
        child = add_vertex(model, "child", 10, 15)
        child.set("parent", "group")
        self.assertTrue(any("edge_node" in p and "child" in p for p in self.check(model)["problems"]))

    def test_nested_edge_coordinates_are_not_treated_as_page_coordinates(self):
        model = diagram()
        group = add_vertex(model, "group", 10, 10, width=550, height=300)
        group.set("style", "container=1;")
        model.find("root/mxCell[@id='ab']").set("parent", "group")
        self.assertEqual(self.check(model)["status"], "partial")

    def test_relative_native_label_is_partial_instead_of_invalid(self):
        model = diagram()
        child = add_vertex(model, "edge_label", 0, 0, width=60, height=20, value="附加标签")
        child.set("parent", "ab")
        child.find("mxGeometry").set("relative", "1")
        report = self.check(model)
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["status"], "partial")

    def test_relative_child_label_does_not_turn_node_into_a_container(self):
        model = diagram()
        add_vertex(model, "blocker", 180, 105)
        child = add_vertex(model, "child_label", 0, 0, width=40, height=20, value="标签")
        child.set("parent", "blocker")
        child.find("mxGeometry").set("relative", "1")
        self.assertTrue(any("edge_node" in p and "blocker" in p for p in self.check(model)["problems"]))

    def test_mixed_compressed_and_uncompressed_pages_are_partial(self):
        document = ET.Element("mxfile")
        ET.SubElement(document, "diagram", name="good").append(diagram())
        ET.SubElement(document, "diagram", name="compressed").text = "compressed"
        self.assertEqual(self.check(document)["status"], "partial")

    def test_malformed_geometry_is_a_structured_failure(self):
        for value in ("NaN", "inf", "bad", "-5"):
            with self.subTest(value=value):
                model = diagram()
                model.find("root/mxCell[@id='a']/mxGeometry").set("width", value)
                self.assertEqual(self.check(model)["status"], "fail")

    def test_compressed_or_empty_input_is_not_a_false_pass(self):
        from drawio_quality import check_drawio_quality
        for source in ("<mxfile><diagram>compressed</diagram></mxfile>", "<mxGraphModel/>",
                       '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>'):
            self.assertNotEqual(check_drawio_quality(source)["status"], "pass")

    def test_each_page_is_checked(self):
        document = ET.Element("mxfile")
        for name, model in (("good", diagram()), ("bad", diagram("长文字" * 100))):
            ET.SubElement(document, "diagram", name=name).append(model)
        self.assertTrue(any("bad" in p and "text_fit" in p for p in self.check(document)["problems"]))

    def test_native_failure_prevents_renderer_and_keeps_existing_output(self):
        from render_native_diagram import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.drawio"
            source.write_text(ET.tostring(diagram("长文字" * 100), encoding="unicode"))
            output = root / "out"
            output.mkdir()
            previous = output / "diagram.drawio.png"
            previous.write_bytes(b"previous")
            with patch("render_native_diagram.find_engine") as engine, contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = main(["--engine", "drawio", "--input", str(source), "--output", str(output)])
            self.assertEqual(code, 1)
            engine.assert_not_called()
            self.assertFalse(json.loads(stdout.getvalue())["valid"])
            self.assertEqual(previous.read_bytes(), b"previous")

    def test_generated_failure_prevents_renderer(self):
        from generate_architecture import main
        from test_architecture_delivery import ArchitectureDeliveryTest
        fixture = ArchitectureDeliveryTest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        _, _, source = fixture._fixture()
        bad = ET.tostring(diagram("长文字" * 100), encoding="unicode")
        with patch("generate_architecture.render_view", return_value=bad), \
                patch("generate_architecture.find_engine") as engine, \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = main(["render", "--source", str(fixture.root), "--ir", str(source),
                         "--output", str(fixture.root / "out"), "--format", "drawio"])
        self.assertEqual(code, 1)
        engine.assert_not_called()
        self.assertEqual(json.loads(stdout.getvalue())["drawioQuality"]["status"], "fail")


if __name__ == "__main__":
    unittest.main()
