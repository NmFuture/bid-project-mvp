import unittest

import run_from_manifest as runner


class BusinessOutlineRunnerMatchingTest(unittest.TestCase):
    def test_short_generic_candidate_title_does_not_match_unrelated_history_title(self):
        candidates = [
            {
                "title": "用",
                "rawText": "科技创新及“自主可控”技术应用：按照以下自主可控技术研发和推广工作开展情况，进行评分。",
            },
            {
                "title": "文件",
                "rawText": "1.1.5 技术资料：指各种纸质及电子载体的相关文件。",
            },
        ]

        self.assertIsNone(runner.first_matching_candidate("1.5 投标专用章效力说明 26", candidates))
        self.assertIsNone(runner.first_matching_candidate("7.2 投标单位股权结构说明及相关证明文件", candidates))

    def test_specific_candidate_title_can_match_history_title(self):
        candidates = [
            {
                "title": "投标单位股权结构说明及相关证明文件",
                "rawText": "投标单位股权结构说明及相关证明文件(附件7B)。",
            },
        ]

        matched = runner.first_matching_candidate("7.2 投标单位股权结构说明及相关证明文件 117", candidates)

        self.assertIsNotNone(matched)
        self.assertEqual(matched["rawText"], "投标单位股权结构说明及相关证明文件(附件7B)。")

    def test_source_ref_marks_tender_basis_for_frontend_focus(self):
        ref = runner.source_ref(
            {
                "fileId": "TEN-1",
                "fileName": "招标文件.docx",
                "paragraphIndex": 12,
                "rawText": "附件7B 投标单位股权结构说明及相关证明文件。",
            }
        )

        self.assertEqual(ref["type"], "tender")
        self.assertEqual(ref["role"], "basis")
        self.assertEqual(ref["searchText"], "附件7B 投标单位股权结构说明及相关证明文件。")
        self.assertEqual(ref["basisText"], "附件7B 投标单位股权结构说明及相关证明文件。")

    def test_outline_sections_preserve_fourth_level_template_candidates(self):
        template_outline = [
            {"number": "7", "title": "资格证明文件", "level": 1, "rawText": "7 资格证明文件"},
            {"number": "7.1", "title": "资格证明材料", "level": 2, "rawText": "7.1 资格证明材料"},
            {"number": "7.1.1", "title": "认证证书", "level": 3, "rawText": "7.1.1 认证证书"},
            {"number": "7.1.1.1", "title": "EW10.0-220 设计认证证书", "level": 4, "rawText": "7.1.1.1 EW10.0-220 设计认证证书"},
        ]

        sections = runner.outline_sections_from_template(template_outline, [])

        self.assertEqual(sections[0]["number"], "7")
        child = sections[0]["children"][0]
        grandchild = child["children"][0]
        fourth_level = grandchild["children"][0]
        self.assertEqual(fourth_level["number"], "7.1.1.1")
        self.assertEqual(fourth_level["level"], 4)
        self.assertEqual(fourth_level["title"], "EW10.0-220 设计认证证书")


if __name__ == "__main__":
    unittest.main()
