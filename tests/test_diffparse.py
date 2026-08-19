from pr_review_agent.diffparse import parse_added_lines, touched_files

SAMPLE_DIFF = """\
diff --git a/app/foo.py b/app/foo.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/app/foo.py
@@ -0,0 +1,3 @@
+def foo():
+    return 1
+
"""


def test_parse_added_lines_extracts_file_and_line_numbers():
    lines = parse_added_lines(SAMPLE_DIFF)
    assert [l.text for l in lines] == ["def foo():", "    return 1"]
    assert lines[0].file == "app/foo.py"
    assert lines[0].line_no == 1
    assert lines[1].line_no == 2


def test_parse_added_lines_skips_blank_lines():
    lines = parse_added_lines(SAMPLE_DIFF)
    assert all(l.text.strip() for l in lines)


def test_touched_files():
    assert touched_files(SAMPLE_DIFF) == ["app/foo.py"]
