import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_QML = PROJECT_ROOT / "qml" / "Main.qml"
DIST_QML = PROJECT_ROOT / "dist" / "neko" / "qml" / "Main.qml"


class QmlWorkspaceLayoutTests(unittest.TestCase):
    def setUp(self):
        self.qml = ACTIVE_QML.read_text(encoding="utf-8")

    def test_panel_has_three_explicit_workspaces(self):
        self.assertIn("property int activeWorkspace: 0", self.qml)
        self.assertIn('text: "运行"', self.qml)
        self.assertIn('text: "模型与外观"', self.qml)
        self.assertIn('text: "日志"', self.qml)
        self.assertIn("visible: window.activeWorkspace === 0", self.qml)
        self.assertIn("visible: window.activeWorkspace === 1", self.qml)
        self.assertIn("visible: window.activeWorkspace === 2", self.qml)
        self.assertIn("activeWorkspace = 0", self.qml)
        self.assertNotIn("QML Trial", self.qml)

    def test_run_actions_are_in_a_fixed_bar_outside_the_scroll_view(self):
        scroll_end = self.qml.index("// Fixed run bar")
        scroll_start = self.qml.index("ScrollView {", self.qml.index("id: workspaceLayout"))
        self.assertLess(scroll_start, scroll_end)
        fixed_bar = self.qml[scroll_end:]
        self.assertIn("backend.startPipeline(window.collectSettings())", fixed_bar)
        self.assertIn("backend.stopPipeline()", fixed_bar)

    def test_minimum_window_keeps_sidebar_and_run_bar_reachable(self):
        self.assertIn("id: sidebarScroll", self.qml)
        workspace = self.qml[self.qml.index("id: workspaceLayout"):]
        self.assertIn("Layout.minimumHeight: 0", workspace)
        main_scroll = workspace[workspace.index("id: mainScroll"):]
        self.assertIn("anchors.bottom: fixedRunBar.top", main_scroll)
        self.assertIn("id: fixedRunBar", workspace)
        self.assertIn("function resetPanelScrollPositions()", self.qml)
        self.assertIn("onActiveWorkspaceChanged: Qt.callLater(resetPanelScrollPositions)", self.qml)

    def test_background_and_borders_use_readability_tokens(self):
        self.assertIn("property color panelBorderColor", self.qml)
        self.assertIn("property color sectionBorderColor", self.qml)
        self.assertIn("property color controlBorderColor", self.qml)
        self.assertIn("opacity: 0.22", self.qml)
        self.assertIn('color: window.withAlpha("#000000",', self.qml)

    def test_dist_qml_matches_active_qml(self):
        if not DIST_QML.exists():
            self.skipTest("dist is not tracked in source checkouts")
        self.assertEqual(self.qml, DIST_QML.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
