"""Run with: python -m unittest discover -s tests -v (self-contained fixtures)."""

from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile

from h5p_question_set import QuizError, parse_questions

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "h5p_question_set.py"
EXAMPLES = [
    ("Synthetic quiz A.txt", "Synthetic quiz A.h5p"),
    ("Synthetic quiz B.txt", "Synthetic quiz B.h5p"),
    ("Synthetic quiz C.txt", "Synthetic quiz C.h5p"),
]


def get_json(path):
    with zipfile.ZipFile(path) as arc:
        return json.loads(arc.read("h5p.json")), json.loads(arc.read("content/content.json"))


def create_synthetic_fixtures(directory):
    """Create independent test inputs without bundling H5P library source or private quizzes.

    ZIP bundles here are intentionally *minimal*, not playable H5P releases.
    They exercise ZIP, manifest, parser and transformation logic only.
    """
    from h5p_question_set import parse_questions

    for example_number, (text_name, h5p_name) in enumerate(EXAMPLES, start=1):
        question_blocks = []
        for question_number in range(1, 11):
            lines = [f"Sample {example_number}, question {question_number}?"]
            correct_indices = {0} if question_number % 2 else {0, 2}
            for answer_index in range(5):
                marker = "*" if answer_index in correct_indices else ""
                lines.append(
                    f"{marker}Option {answer_index + 1}:Hint {answer_index + 1}:"
                    f"Chosen {answer_index + 1}:Not chosen {answer_index + 1}"
                )
            question_blocks.append("\n".join(lines))
        text_file = directory / text_name
        text_file.write_text("\n\n".join(question_blocks) + "\n", encoding="utf-8")
        parsed = parse_questions(text_file)
        questions = []
        for replacement in parsed:
            questions.append({
                "library": "H5P.MultiChoice 1.16",
                "subContentId": str(uuid.uuid4()),
                "metadata": {"title": "Untitled Multiple Choice"},
                "params": {
                    "question": replacement["question"],
                    "answers": replacement["answers"],
                    "media": {},
                    "behaviour": {
                        "singleAnswer": True,
                        "type": "auto",
                        "singlePoint": True,
                        "randomAnswers": False,
                        "showSolutionsRequiresInput": False,
                        "autoCheck": False,
                    },
                },
            })
        manifest = {
            "title": "Fixture question set",
            "extraTitle": "Fixture question set",
            "mainLibrary": "H5P.QuestionSet",
            "language": "en",
            "preloadedDependencies": [
                {"machineName": "H5P.QuestionSet", "majorVersion": 1, "minorVersion": 20},
                {"machineName": "H5P.MultiChoice", "majorVersion": 1, "minorVersion": 16},
            ],
        }
        content = {"questions": questions, "progressType": "dots", "passPercentage": 50}
        with zipfile.ZipFile(directory / h5p_name, "w") as archive:
            archive.writestr("h5p.json", json.dumps(manifest))
            archive.writestr("content/content.json", json.dumps(content))
            archive.writestr("H5P.MultiChoice-1.16/semantics.json", "[]")
            archive.writestr("content/config.json", json.dumps({"source": "C:/fixture/local-path"}))
            archive.writestr("fixture/marker.txt", "Retained with no modification")


class QuestionSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_temp = tempfile.TemporaryDirectory()
        cls.fixtures = Path(cls.fixture_temp.name)
        create_synthetic_fixtures(cls.fixtures)

    @classmethod
    def tearDownClass(cls):
        cls.fixture_temp.cleanup()

    def run_script(self, *args, exit=0):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, exit, result.stdout + result.stderr)
        return result

    def test_all_examples_match_exactly(self):
        for txt, h5p in EXAMPLES:
            with self.subTest(txt=txt):
                data = parse_questions(self.fixtures / txt)
                _, original = get_json(self.fixtures / h5p)
                self.assertEqual(len(data), 10)
                for replacement, existing in zip(data, original["questions"]):
                    self.assertEqual(replacement["question"], existing["params"]["question"])
                    self.assertEqual(replacement["answers"], existing["params"]["answers"])

    def test_create_all_three_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            for txt, h5p in EXAMPLES:
                with self.subTest(txt=txt):
                    target = Path(tmp) / (Path(txt).stem + ".h5p")
                    self.run_script("create", "--text", self.fixtures / txt, "--template", self.fixtures / h5p,
                                    "--output", target)
                    with zipfile.ZipFile(target) as arc:
                        self.assertIsNone(arc.testzip())
                    meta, content = get_json(target)
                    old_meta, old_content = get_json(self.fixtures / h5p)
                    self.assertEqual(meta["title"], Path(txt).stem)
                    self.assertEqual(meta.get("extraTitle"), Path(txt).stem)
                    self.assertEqual({k: v for k, v in meta.items() if k not in ("title", "extraTitle")},
                                     {k: v for k, v in old_meta.items() if k not in ("title", "extraTitle")})
                    self.assertEqual({k:v for k,v in content.items() if k!="questions"},
                                     {k:v for k,v in old_content.items() if k!="questions"})
                    ids = [q["subContentId"] for q in content["questions"]]
                    self.assertEqual(len(ids), len(set(ids)))
                    for i, original in enumerate(old_content["questions"]):
                        self.assertEqual(content["questions"][i]["params"], original["params"])
                        self.assertNotEqual(ids[i], original["subContentId"])
                        uuid.UUID(ids[i])

    def test_update_keeps_question_config_but_renews_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.h5p"
            source = self.fixtures / EXAMPLES[0][1]
            before_manifest, before = get_json(source)
            txt = self.fixtures / EXAMPLES[1][0]
            self.run_script("update", "--text", txt, "--source", source, "--output", output)
            manifest, after = get_json(output)
            self.assertEqual(manifest["title"], txt.stem)
            self.assertEqual(manifest.get("extraTitle"), txt.stem)
            self.assertEqual({k: v for k, v in manifest.items() if k not in ("title", "extraTitle")},
                             {k: v for k, v in before_manifest.items() if k not in ("title", "extraTitle")})
            original_ids = {q["subContentId"] for q in before["questions"]}
            new_ids = {q["subContentId"] for q in after["questions"]}
            self.assertEqual(len(new_ids), len(after["questions"]))
            self.assertTrue(new_ids.isdisjoint(original_ids))
            for old, new, replacement in zip(before["questions"], after["questions"], parse_questions(txt)):
                uuid.UUID(new["subContentId"])
                self.assertEqual(new["params"]["behaviour"], old["params"]["behaviour"])
                self.assertEqual(new["params"]["question"], replacement["question"])
            self.assertEqual(get_json(source)[1], before)

    def test_default_create_positional_file_and_template_beside_script(self):
        """Simulates a dropped file with spaces, from an unrelated working directory."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool_dir = root / "tool folder"
            text_dir = root / "questions with spaces"
            tool_dir.mkdir()
            text_dir.mkdir()
            script = tool_dir / SCRIPT.name
            shutil.copyfile(SCRIPT, script)
            shutil.copyfile(self.fixtures / EXAMPLES[0][1], tool_dir / "template.h5p")
            text_file = text_dir / "Quiz for Video - Example.txt"
            text_file.write_text("My question?\n*Correct:tip:yes:no\nIncorrect:tip:no:yes\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(script), str(text_file)],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            destination = text_file.with_suffix(".h5p")
            self.assertTrue(destination.is_file())
            meta, content = get_json(destination)
            self.assertEqual(meta["title"], "Quiz for Video - Example")
            self.assertEqual(len(content["questions"]), 1)
            self.assertEqual(content["questions"][0]["params"]["question"], "My question?")

    def test_create_default_with_text_option_and_explicit_template_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text_file = root / "quiz.txt"
            text_file.write_text("Q?\n*Yes:tip:yes:no\n", encoding="utf-8")
            target = root / "other.h5p"
            self.run_script("--text", text_file, "--template", self.fixtures / EXAMPLES[1][1],
                            "--output", target, "--random-answers", "true")
            self.assertTrue(target.is_file())
            _, content = get_json(target)
            self.assertIs(content["questions"][0]["params"]["behaviour"]["randomAnswers"], True)

    def test_positional_text_in_explicit_update_and_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            text_file = Path(tmp) / "another quiz.txt"
            text_file.write_text("Q?\n*Yes:tip:yes:no\n", encoding="utf-8")
            created = Path(tmp) / "created.h5p"
            self.run_script("create", text_file, "--template", self.fixtures / EXAMPLES[0][1],
                            "--output", created)
            updated = Path(tmp) / "updated.h5p"
            self.run_script("update", text_file, "--source", created, "--output", updated)
            old_id = get_json(created)[1]["questions"][0]["subContentId"]
            new_id = get_json(updated)[1]["questions"][0]["subContentId"]
            self.assertNotEqual(old_id, new_id)

    def test_missing_template_and_conflicting_text_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / SCRIPT.name
            shutil.copyfile(SCRIPT, script)
            text_file = root / "quiz.txt"
            text_file.write_text("Q?\n*Yes:tip:yes:no\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(script), str(text_file)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("template.h5p", result.stderr)
            self.assertFalse(text_file.with_suffix(".h5p").exists())
            result = self.run_script("create", text_file, "--text", text_file,
                                     "--template", self.fixtures / EXAMPLES[0][1], exit=2)
            self.assertIn("either a positional text file or --text", result.stderr)

    def test_windows_shortcut_launcher_exists(self):
        launcher = ROOT / "Import-H5P.cmd"
        contents = launcher.read_text(encoding="utf-8")
        self.assertIn('"%~dp0h5p_question_set.py"', contents)
        self.assertIn('"%~1"', contents)
        self.assertIn("pause", contents)

    def test_default_output_and_title_in_both_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp)
            text_file = target_dir / "My Quiz.v2.txt"
            text_file.write_text("Q?\n*Yes:hint:chosen:not chosen\n", encoding="utf-8")
            source = self.fixtures / EXAMPLES[0][1]
            expected = target_dir / "My Quiz.v2.h5p"
            self.run_script("create", "--text", text_file, "--template", source)
            self.assertTrue(expected.is_file())
            meta, created = get_json(expected)
            self.assertEqual(meta["title"], "My Quiz v2")
            self.assertEqual(meta.get("extraTitle"), "My Quiz v2")
            initial_id = created["questions"][0]["subContentId"]
            self.run_script("update", "--text", text_file, "--source", expected,
                            "--overwrite")
            meta, updated = get_json(expected)
            self.assertEqual(meta["title"], "My Quiz v2")
            self.assertEqual(updated["questions"][0]["params"], created["questions"][0]["params"])
            self.assertNotEqual(updated["questions"][0]["subContentId"], initial_id)

    def test_filename_title_cleanup_and_explicit_title_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            text_file = Path(tmp) / "Quiz_for_Video.v2.txt"
            text_file.write_text("Q?\n*Yes:hint:chosen:not chosen\n", encoding="utf-8")
            source = self.fixtures / EXAMPLES[0][1]
            self.run_script("create", "--text", text_file, "--template", source)
            output = text_file.with_suffix(".h5p")
            self.assertTrue(output.is_file())
            manifest, _ = get_json(output)
            self.assertEqual(manifest["title"], "Quiz for Video v2")
            self.assertEqual(manifest.get("extraTitle"), "Quiz for Video v2")
            explicit = Path(tmp) / "explicit.h5p"
            self.run_script("update", "--text", text_file, "--source", output,
                            "--output", explicit, "--title", "Custom_title.v2")
            manifest, _ = get_json(explicit)
            self.assertEqual(manifest["title"], "Custom_title.v2")
            self.assertEqual(manifest.get("extraTitle"), "Custom_title.v2")
    def test_default_title_and_explicit_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "custom-output.h5p"
            txt = self.fixtures / EXAMPLES[1][0]
            self.run_script("update", "--text", txt, "--source", self.fixtures / EXAMPLES[1][1],
                            "--output", target)
            meta, _ = get_json(target)
            self.assertEqual(meta["title"], txt.stem)
            self.assertEqual(meta["extraTitle"], txt.stem)

    def test_updated_ids_fresh_on_each_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt = self.fixtures / EXAMPLES[0][0]
            original = self.fixtures / EXAMPLES[0][1]
            outputs = [Path(tmp) / f"run{i}.h5p" for i in range(2)]
            for output in outputs:
                self.run_script("update", "--text", txt, "--source", original,
                                "--output", output)
            first = {q["subContentId"] for q in get_json(outputs[0])[1]["questions"]}
            second = {q["subContentId"] for q in get_json(outputs[1])[1]["questions"]}
            old = {q["subContentId"] for q in get_json(original)[1]["questions"]}
            self.assertTrue(first.isdisjoint(old))
            self.assertTrue(second.isdisjoint(old))
            self.assertTrue(first.isdisjoint(second))

    def test_overrides_true_false_and_leave_missing_unchanged(self):
        source = self.fixtures / EXAMPLES[0][1]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "overrides.h5p"
            self.run_script("update", "--text", self.fixtures / EXAMPLES[0][0], "--source", source,
                            "--output", output, "--single-point", "false", "--random-answers", "true",
                            "--require-answer", "true")
            _, content = get_json(output)
            for q in content["questions"]:
                b = q["params"]["behaviour"]
                self.assertIs(b["singlePoint"], False)
                self.assertIs(b["randomAnswers"], True)
                self.assertIs(b["showSolutionsRequiresInput"], True)
                self.assertIs(b["autoCheck"], False)
            output2 = Path(tmp) / "partial.h5p"
            self.run_script("update", "--text", self.fixtures / EXAMPLES[0][0], "--source", output,
                            "--output", output2, "--single-point", "true")
            _, changed = get_json(output2)
            for q in changed["questions"]:
                b = q["params"]["behaviour"]
                self.assertIs(b["singlePoint"], True)
                self.assertIs(b["randomAnswers"], True)
                self.assertIs(b["showSolutionsRequiresInput"], True)

    def test_variable_question_and_answer_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt = Path(tmp) / "mini.txt"
            txt.write_text("One?\n*Yes:hint:chosen:not chosen\nNo:hint:chosen:not chosen\n\n"
                           "Two?\n*Only:hint:chosen:not chosen\n\n"
                           "Three?\n*Alpha:hint:chosen:not chosen\n*Beta:hint:chosen:not chosen\n"
                           "Gamma:hint:chosen:not chosen\nDelta:hint:chosen:not chosen\n", encoding="utf8")
            new = Path(tmp) / "out.h5p"
            self.run_script("create", "--text", txt, "--template", self.fixtures / EXAMPLES[0][1], "--output", new)
            _, content = get_json(new)
            self.assertEqual([len(q["params"]["answers"]) for q in content["questions"]], [2,1,4])
            self.assertEqual(len(set(q["subContentId"] for q in content["questions"])), 3)
            update = Path(tmp) / "out2.h5p"
            self.run_script("update", "--text", txt, "--source", self.fixtures / EXAMPLES[0][1], "--output", update)
            _, updated = get_json(update)
            self.assertEqual(len(updated["questions"]), 3)

    def test_add_questions_to_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt = Path(tmp) / "eleven.txt"
            txt.write_text((self.fixtures / EXAMPLES[0][0]).read_text(encoding="utf-8") +
                           "\nExtra question?\n*Yes:tip:yes:no\nNo:tip:no:yes\n", encoding="utf-8")
            output = Path(tmp) / "out.h5p"
            self.run_script("update", "--text", txt, "--source", self.fixtures / EXAMPLES[0][1], "--output", output)
            _, content = get_json(output)
            self.assertEqual(len(content["questions"]),11)
            self.assertNotIn(content["questions"][-1]["subContentId"],
                             [q["subContentId"] for q in content["questions"][:-1]])

    def test_title_and_remove_config_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.h5p"
            self.run_script("create", "--text", self.fixtures / EXAMPLES[1][0],
                            "--template", self.fixtures / EXAMPLES[1][1], "--output", output,
                            "--title", "My New Quiz")
            manifest, _ = get_json(output)
            self.assertEqual(manifest["title"], "My New Quiz")
            self.assertEqual(manifest["extraTitle"], "My New Quiz")
            with zipfile.ZipFile(output) as arc:
                self.assertNotIn("content/config.json", arc.namelist())

    def test_local_config_removed_by_default_in_both_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ("create", "update"):
                with self.subTest(mode=mode):
                    source = self.fixtures / EXAMPLES[0][1]
                    args = ["--template", source] if mode == "create" else ["--source", source]
                    output = Path(tmp) / f"{mode}.h5p"
                    self.run_script(mode, self.fixtures / EXAMPLES[0][0], *args, "--output", output)
                    with zipfile.ZipFile(output) as arc:
                        self.assertNotIn("content/config.json", arc.namelist())
                        self.assertIn("fixture/marker.txt", arc.namelist())

    def test_keep_local_config_explicitly_in_both_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ("create", "update"):
                with self.subTest(mode=mode):
                    source = self.fixtures / EXAMPLES[0][1]
                    args = ["--template", source] if mode == "create" else ["--source", source]
                    output = Path(tmp) / f"{mode}.h5p"
                    self.run_script(mode, self.fixtures / EXAMPLES[0][0], *args,
                                    "--output", output, "--keep-local-config")
                    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output) as out:
                        self.assertEqual(out.read("content/config.json"), original.read("content/config.json"))

    def test_legacy_remove_local_config_flag_and_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.fixtures / EXAMPLES[0][1]
            text = self.fixtures / EXAMPLES[0][0]
            output = Path(tmp) / "explicit.h5p"
            self.run_script("create", text, "--template", source,
                            "--output", output, "--remove-local-config")
            with zipfile.ZipFile(output) as archive:
                self.assertNotIn("content/config.json", archive.namelist())
            self.run_script("create", text, "--template", source,
                            "--output", output, "--remove-local-config",
                            "--keep-local-config", exit=2)

    def test_inplace_requires_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "test.h5p"
            source.write_bytes((self.fixtures / EXAMPLES[0][1]).read_bytes())
            self.run_script("update", "--text", self.fixtures / EXAMPLES[1][0],
                            "--source", source, "--output", source, exit=2)
            self.run_script("update", "--text", self.fixtures / EXAMPLES[1][0],
                            "--source", source, "--output", source, "--overwrite")
            _, result = get_json(source)
            self.assertEqual(result["questions"][0]["params"]["question"],
                             parse_questions(self.fixtures / EXAMPLES[1][0])[0]["question"])

    def test_ambiguous_input_errors(self):
        for bad in [
            "Q?\nNo:tip:chosen:no\n",  # No correct answer
            "Q?\n*Yes:tip:chosen:no:ambiguous\n",  # Extra separator
            "Q?\n",  # No answers
            "Q?\n*Yes:tip:chosen\n",  # Missing field
            "Q?\n *Yes:tip:chosen:no\n",  # Leading whitespace
            "\n\n",  # Empty file
        ]:
            with tempfile.TemporaryDirectory() as tmp:
                txt = Path(tmp) / "bad.txt"
                txt.write_text(bad, encoding="utf8")
                with self.assertRaises(QuizError):
                    parse_questions(txt)

    def test_html_escaped_as_literal_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt = Path(tmp) / "special.txt"
            txt.write_text("Is x < 7 & y > 2?\n*Yes & no:Tip with <x>:Chosen:Not chosen\n", encoding="utf-8")
            result = parse_questions(txt)
            self.assertEqual(result[0]["question"], "Is x &lt; 7 &amp; y &gt; 2?")
            self.assertEqual(result[0]["answers"][0]["tipsAndFeedback"]["tip"], "Tip with &lt;x&gt;")

    def test_original_package_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.fixtures / EXAMPLES[0][1]
            before = source.read_bytes()
            target = Path(tmp) / "result.h5p"
            self.run_script("create", self.fixtures / EXAMPLES[0][0], "--template", source,
                            "--output", target)
            self.assertEqual(source.read_bytes(), before)
            with zipfile.ZipFile(source) as a, zipfile.ZipFile(target) as b:
                self.assertNotIn("content/config.json", b.namelist())
                for name in a.namelist():
                    if name not in ("h5p.json", "content/content.json", "content/config.json"):
                        self.assertEqual(a.read(name), b.read(name))

    def make_versioned_fixture(self, destination, *, question_set=(1, 20),
                               multi_choice=(1, 16), question_ref=(1, 16),
                               semantics=(1, 16), missing_dependency=None,
                               missing_semantics=False, other_library=False):
        source = self.fixtures / EXAMPLES[0][1]
        with zipfile.ZipFile(source) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        info = json.loads(entries["h5p.json"])
        for dep in info["preloadedDependencies"]:
            if dep["machineName"] == "H5P.QuestionSet":
                dep["majorVersion"], dep["minorVersion"] = question_set
            if dep["machineName"] == "H5P.MultiChoice":
                dep["majorVersion"], dep["minorVersion"] = multi_choice
        if missing_dependency:
            info["preloadedDependencies"] = [d for d in info["preloadedDependencies"]
                                              if d["machineName"] != missing_dependency]
        entries["h5p.json"] = json.dumps(info).encode("utf-8")
        entries[f"H5P.QuestionSet-{question_set[0]}.{question_set[1]}/semantics.json"] = b"[]"
        content = json.loads(entries["content/content.json"])
        for q in content["questions"]:
            q["library"] = f"H5P.MultiChoice {question_ref[0]}.{question_ref[1]}"
        if other_library:
            content["questions"][0]["library"] = "H5P.TrueFalse 1.8"
        entries["content/content.json"] = json.dumps(content).encode("utf-8")
        old_path = "H5P.MultiChoice-1.16/semantics.json"
        value = entries.pop(old_path)
        if not missing_semantics:
            entries[f"H5P.MultiChoice-{semantics[0]}.{semantics[1]}/semantics.json"] = value
        with zipfile.ZipFile(destination, "w") as archive:
            for name, value in entries.items():
                archive.writestr(name, value)

    def test_mismatched_versions_warn_and_continue_in_both_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "alternate_versions.h5p"
            self.make_versioned_fixture(source, question_set=(2, 0), multi_choice=(1, 17),
                                        question_ref=(1, 17), semantics=(1, 17))
            for mode in ("create", "update"):
                with self.subTest(mode=mode):
                    output = Path(tmp) / f"{mode}.h5p"
                    source_arg = "--template" if mode == "create" else "--source"
                    result = self.run_script(mode, self.fixtures / EXAMPLES[0][0],
                                             source_arg, source, "--output", output)
                    self.assertIn("WARNING: H5P.QuestionSet version differs", result.stderr)
                    self.assertIn("validated 1.20", result.stderr)
                    self.assertIn("dependency: 2.0", result.stderr)
                    self.assertIn("semantics folder: 2.0", result.stderr)
                    self.assertIn("WARNING: H5P.MultiChoice version differs", result.stderr)
                    self.assertIn("dependency: 1.17", result.stderr)
                    self.assertIn("question references: 1.17", result.stderr)
                    self.assertIn("semantics folder: 1.17", result.stderr)
                    manifest, content = get_json(output)
                    self.assertEqual(manifest["preloadedDependencies"][0]["majorVersion"], 2)
                    self.assertEqual(content["questions"][0]["library"], "H5P.MultiChoice 1.17")
                    with zipfile.ZipFile(output) as archive:
                        self.assertIn("H5P.MultiChoice-1.17/semantics.json", archive.namelist())

    def test_normal_versions_do_not_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "new.h5p"
            result = self.run_script("create", self.fixtures / EXAMPLES[0][0],
                                     "--template", self.fixtures / EXAMPLES[0][1],
                                     "--output", output)
            self.assertNotIn("WARNING:", result.stderr)

    def test_mixed_version_locations_warn_without_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "mixed.h5p"
            self.make_versioned_fixture(source, question_ref=(2, 3), semantics=(1, 18))
            output = Path(tmp) / "result.h5p"
            result = self.run_script("create", self.fixtures / EXAMPLES[0][0],
                                     "--template", source, "--output", output)
            self.assertNotIn("H5P.QuestionSet version differs", result.stderr)
            self.assertIn("H5P.MultiChoice version differs", result.stderr)
            self.assertIn("question references: 2.3", result.stderr)
            self.assertIn("semantics folder: 1.18", result.stderr)

    def test_missing_dependency_semantics_or_other_content_type_still_fails(self):
        for case in ("missing_dependency", "missing_semantics", "other_library"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "bad.h5p"
                options = ({"missing_dependency": "H5P.MultiChoice"} if case == "missing_dependency"
                           else {case: True})
                self.make_versioned_fixture(source, **options)
                output = Path(tmp) / "result.h5p"
                result = self.run_script("create", self.fixtures / EXAMPLES[0][0],
                                         "--template", source, "--output", output, exit=2)
                self.assertIn("ERROR:", result.stderr)
                self.assertFalse(output.exists())

    def test_nonuniform_blueprints_are_rejected_for_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp) / "different.h5p"
            with zipfile.ZipFile(self.fixtures / EXAMPLES[0][1]) as source:
                contents = {name: source.read(name) for name in source.namelist()}
            content = json.loads(contents["content/content.json"])
            content["questions"][1]["params"]["behaviour"]["randomAnswers"] = True
            contents["content/content.json"] = json.dumps(content).encode("utf-8")
            with zipfile.ZipFile(template, "w") as destination:
                for name, data in contents.items():
                    destination.writestr(name, data)
            output = Path(tmp) / "output.h5p"
            result = self.run_script("create", self.fixtures / EXAMPLES[0][0],
                                     "--template", template, "--output", output, exit=2)
            self.assertIn("different settings", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
