#!/usr/bin/env python3
"""Populate an H5P Question Set with MultiChoice questions from a text file.

Requires Python 3.10 or later. No third-party packages are used.
Use --help or read README_h5p_question_set.md for the input grammar and examples.
"""

from __future__ import annotations

import argparse
import copy
import html
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid
import zipfile


QUESTION_SET_LIBRARY = "H5P.QuestionSet"
QUESTION_SET_VERSION = (1, 20)
MULTICHOICE_LIBRARY = "H5P.MultiChoice 1.16"
MULTICHOICE_VERSION = (1, 16)
# Resolve the implicit template independently of Windows shortcut "Start in".
DEFAULT_TEMPLATE = Path(__file__).resolve().parent / "template.h5p"
BEHAVIOUR_FLAGS = {
    "single_point": "singlePoint",
    "random_answers": "randomAnswers",
    "require_answer": "showSolutionsRequiresInput",
}


class QuizError(Exception):
    """Input validation error; don't try to repair ambiguous quiz data."""


def boolean_option(text: str) -> bool:
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    raise argparse.ArgumentTypeError("expected 'true' or 'false'")


def parse_questions(filename: Path) -> list[dict]:
    """Each nonempty group starts with a question and has answer lines.

    Answer lines: [*]answer:tip:chosen feedback:not-chosen feedback
    An extra colon makes a line ambiguous and is an error.
    Input is literal text, not HTML; content is HTML-escaped for H5P.
    """
    try:
        raw = filename.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise QuizError(f"Cannot read UTF-8 text file '{filename}': {exc}") from exc

    blocks: list[list[tuple[int, str]]] = []
    block: list[tuple[int, str]] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            if block:
                blocks.append(block)
                block = []
            continue
        if line != line.strip():
            raise QuizError(f"{filename}:{lineno}: leading/trailing whitespace is ambiguous")
        block.append((lineno, line))
    if block:
        blocks.append(block)
    if not blocks:
        raise QuizError(f"'{filename}' contains no questions")

    parsed: list[dict] = []
    for number, lines in enumerate(blocks, start=1):
        question_lineno, question = lines[0]
        if not question:
            raise QuizError(f"{filename}:{question_lineno}: empty question")
        if len(lines) < 2:
            raise QuizError(f"{filename}:{question_lineno}: question {number} has no answers")
        answers: list[dict] = []
        for lineno, answer_line in lines[1:]:
            fields = answer_line.split(":")
            if len(fields) != 4:
                raise QuizError(
                    f"{filename}:{lineno}: expected exactly 3 ':' separators "
                    f"(answer:tip:chosen feedback:not-chosen feedback), found {len(fields) - 1}. "
                    "A literal colon in a field is not defined by the input format."
                )
            if any(part != part.strip() for part in fields):
                raise QuizError(f"{filename}:{lineno}: leading/trailing whitespace in a field")
            answer_text, tip, chosen, not_chosen = fields
            correct = answer_text.startswith("*")
            if correct:
                answer_text = answer_text[1:]
            if not answer_text:
                raise QuizError(f"{filename}:{lineno}: empty answer text")
            answers.append({
                "text": html.escape(answer_text, quote=False),
                "correct": correct,
                "tipsAndFeedback": {
                    "tip": html.escape(tip, quote=False),
                    "chosenFeedback": html.escape(chosen, quote=False),
                    "notChosenFeedback": html.escape(not_chosen, quote=False),
                },
            })
        if not any(answer["correct"] for answer in answers):
            raise QuizError(
                f"{filename}:{question_lineno}: question {number} has no correct answer (leading '*')"
            )
        parsed.append({"question": html.escape(question, quote=False), "answers": answers})
    return parsed


def read_package(source: Path) -> tuple[dict, dict, list[tuple[zipfile.ZipInfo, bytes]], bytes]:
    """Read package without extracting any potentially unsafe ZIP paths."""
    if not source.is_file():
        raise QuizError(f"H5P source file not found: '{source}'")
    try:
        with zipfile.ZipFile(source, "r") as archive:
            names = archive.namelist()
            if len(set(names)) != len(names):
                raise QuizError("H5P archive contains duplicate entry names")
            bad_member = archive.testzip()
            if bad_member is not None:
                raise QuizError(f"H5P archive has a damaged member: {bad_member}")
            try:
                info = json.loads(archive.read("h5p.json"))
                content = json.loads(archive.read("content/content.json"))
            except (KeyError, ValueError, UnicodeError) as exc:
                raise QuizError(f"Invalid H5P manifest or content JSON: {exc}") from exc
            entries = [(entry, archive.read(entry)) for entry in archive.infolist()]
            archive_comment = archive.comment
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise QuizError(f"Cannot open H5P package '{source}': {exc}") from exc
    return info, content, entries, archive_comment


def valid_dependency(info: dict, name: str, version: tuple[int, int]) -> bool:
    return any(
        isinstance(dependency, dict)
        and dependency.get("machineName") == name
        and dependency.get("majorVersion") == version[0]
        and dependency.get("minorVersion") == version[1]
        for dependency in info.get("preloadedDependencies", [])
    )


def validate_source(info: dict, content: dict, entry_names: set[str]) -> None:
    if not isinstance(info, dict) or info.get("mainLibrary") != QUESTION_SET_LIBRARY:
        raise QuizError(f"Source must be an {QUESTION_SET_LIBRARY} package")
    if not valid_dependency(info, QUESTION_SET_LIBRARY, QUESTION_SET_VERSION):
        raise QuizError("Only H5P.QuestionSet 1.20 packages are supported by this script")
    if not valid_dependency(info, "H5P.MultiChoice", MULTICHOICE_VERSION):
        raise QuizError("Missing H5P.MultiChoice 1.16 dependency")
    if "H5P.MultiChoice-1.16/semantics.json" not in entry_names:
        raise QuizError("H5P.MultiChoice 1.16 semantics are not included")
    if not isinstance(content, dict):
        raise QuizError("Question Set content/content.json must contain a JSON object")
    questions = content.get("questions")
    if not isinstance(questions, list) or not questions:
        raise QuizError("Source Question Set needs at least one MultiChoice question as blueprint")
    for index, original in enumerate(questions, start=1):
        if not isinstance(original, dict) or original.get("library") != MULTICHOICE_LIBRARY:
            raise QuizError(f"Existing question {index} is not {MULTICHOICE_LIBRARY}")
        params = original.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("answers"), list):
            raise QuizError(f"Existing question {index} has malformed MultiChoice parameters")
        if not isinstance(params.get("behaviour"), dict):
            raise QuizError(f"Existing question {index} lacks a 'behaviour' object")
        if not isinstance(original.get("metadata"), dict):
            raise QuizError(f"Existing question {index} lacks a metadata object")
        media = params.get("media", {})
        if not isinstance(media, dict):
            raise QuizError(f"Existing question {index} has malformed media settings")
        if media.get("type") is not None:
            raise QuizError(
                f"Existing question {index} uses embedded media, which cannot be "
                "mapped unambiguously from the provided text format"
            )


def same_blueprint(questions: list[dict]) -> bool:
    """Ensure there is only one unambiguous source for newly added questions."""
    def configuration(question: dict) -> dict:
        params = copy.deepcopy(question["params"])
        params.pop("question", None)
        params.pop("answers", None)
        return {"params": params, "metadata": question["metadata"]}
    first = configuration(questions[0])
    return all(configuration(q) == first for q in questions[1:])


def build_questions(
    existing: list[dict], parsed: list[dict], mode: str, changes: dict[str, bool | None]
) -> list[dict]:
    if (mode == "create" or len(parsed) > len(existing)) and not same_blueprint(existing):
        raise QuizError(
            "The source questions have different settings or metadata. "
            "There is no unique blueprint for new questions; use a uniform source package."
        )
    output = []
    for index, replacement in enumerate(parsed):
        # In update mode, position-matched questions retain their custom properties.
        # Every generated question gets a new subContentId in both modes.
        reused = mode == "update" and index < len(existing)
        q = copy.deepcopy(existing[index] if reused else existing[0])
        q["params"]["question"] = replacement["question"]
        q["params"]["answers"] = replacement["answers"]
        q["subContentId"] = str(uuid.uuid4())
        for flag, h5p_key in BEHAVIOUR_FLAGS.items():
            if changes[flag] is not None:
                q["params"]["behaviour"][h5p_key] = changes[flag]
        output.append(q)
    return output


def save_package(
    target: Path, entries: list[tuple[zipfile.ZipInfo, bytes]], info: dict,
    content: dict, archive_comment: bytes, *, remove_local_config: bool, overwrite: bool
) -> None:
    if target.exists() and not overwrite:
        raise QuizError(f"Output already exists: '{target}' (use --overwrite to replace it)")
    if not target.parent.is_dir():
        raise QuizError(f"Output directory does not exist: '{target.parent}'")
    json_files = {
        "h5p.json": (json.dumps(info, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        "content/content.json": (
            json.dumps(content, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
    }
    fd, temp_name = tempfile.mkstemp(prefix=".h5p-question-set-", suffix=".h5p", dir=target.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temp_name, "w") as out_zip:
            out_zip.comment = archive_comment
            for member, data in entries:
                if remove_local_config and member.filename == "content/config.json":
                    continue
                out_zip.writestr(member, json_files.get(member.filename, data))
        # Verify before replacing an existing package.
        with zipfile.ZipFile(temp_name) as check:
            if check.testzip() is not None:
                raise QuizError("ZIP verification failed for newly generated H5P package")
            if json.loads(check.read("content/content.json")) != content:
                raise QuizError("H5P content verification failed after writing")
        if target.exists() and not overwrite:
            raise QuizError(f"Output already exists: '{target}'")
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build/update H5P Question Set 1.20 (MultiChoice 1.16) from a UTF-8 "
            "text file. CREATE is the default mode."
        ),
        epilog=(
            "Examples: h5p_question_set.py questions.txt | "
            "h5p_question_set.py create questions.txt | "
            "h5p_question_set.py update questions.txt --source existing.h5p"
        ),
    )
    subs = parser.add_subparsers(dest="mode", required=True)
    for mode in ("create", "update"):
        sub = subs.add_parser(
            mode, help="Create a new package" if mode == "create" else "Update an existing package"
        )
        sub.add_argument(
            "text_file", nargs="?", type=Path,
            help="UTF-8 text file (positional, e.g. dropped on a Windows shortcut)",
        )
        sub.add_argument(
            "--text", type=Path, help="Alternative to the positional text file argument"
        )
        if mode == "create":
            sub.add_argument(
                "--template", type=Path, default=DEFAULT_TEMPLATE,
                help="H5P Question Set template (default: template.h5p beside the script)",
            )
        else:
            sub.add_argument(
                "--source", type=Path, required=True,
                help="Existing H5P Question Set to modify",
            )
        sub.add_argument(
            "--output", type=Path,
            help="Resulting .h5p path (default: text file path with .h5p extension)",
        )
        sub.add_argument(
            "--title", help="Title in h5p.json (default: text file name without extension)",
        )
        sub.add_argument(
            "--single-point", type=boolean_option, metavar="true|false",
            help="Override 'Give one point for the whole task'",
        )
        sub.add_argument(
            "--random-answers", type=boolean_option, metavar="true|false",
            help="Override 'Randomize answers'",
        )
        sub.add_argument(
            "--require-answer", type=boolean_option, metavar="true|false",
            help="Override 'Require answer before solution can be viewed'",
        )
        local_config = sub.add_mutually_exclusive_group()
        local_config.add_argument(
            "--keep-local-config", dest="remove_local_config", action="store_false",
            help="Preserve nonstandard content/config.json (may expose local paths)",
        )
        local_config.add_argument(
            "--remove-local-config", dest="remove_local_config", action="store_true",
            help="Remove nonstandard content/config.json (the default; retained for compatibility)",
        )
        sub.set_defaults(remove_local_config=True)
        sub.add_argument(
            "--overwrite", action="store_true",
            help="Allow replacing an existing output file (including in-place updates)",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = cli_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Keep the explicit 'create' / 'update' CLI; permit invocation with a bare
    # filename or --text argument (for shortcut drag-and-drop and simple use).
    # Preserve top-level --help to show both available modes.
    if not arguments or arguments[0] not in ("create", "update", "-h", "--help"):
        arguments.insert(0, "create")
    args = parser.parse_args(arguments)
    if args.text_file is not None and args.text is not None:
        parser.error("provide either a positional text file or --text, not both")
    text_file = args.text_file if args.text_file is not None else args.text
    if text_file is None:
        parser.error("missing text file: supply a file path or --text FILE")
    try:
        source = args.template if args.mode == "create" else args.source
        output = args.output if args.output is not None else text_file.with_suffix(".h5p")
        title = args.title if args.title is not None else text_file.stem
        if source.suffix.lower() != ".h5p" or output.suffix.lower() != ".h5p":
            raise QuizError("H5P input and output filenames must end with .h5p")
        if not title.strip():
            raise QuizError("Quiz title may not be empty")
        parsed = parse_questions(text_file)
        info, content, entries, comment = read_package(source)
        validate_source(info, content, {zinfo.filename for zinfo, _ in entries})
        existing = content["questions"]
        changes = {key: getattr(args, key) for key in BEHAVIOUR_FLAGS}
        updated = build_questions(existing, parsed, args.mode, changes)
        content["questions"] = updated
        info["title"] = title
        if "extraTitle" in info:
            info["extraTitle"] = title
        save_package(
            output, entries, info, content, comment,
            remove_local_config=args.remove_local_config, overwrite=args.overwrite,
        )
        print(f"{args.mode.capitalize()}d: {output}")
        print(f"Questions: {len(updated)}; answers: {sum(len(q['params']['answers']) for q in updated)}")
        print("Behavioural overrides: " + ", ".join(
            f"{key}={value}" for key, value in changes.items() if value is not None
        ) if any(v is not None for v in changes.values()) else "Behavioural overrides: none (preserved)")
        if not args.remove_local_config and any(
            m.filename == "content/config.json" for m, _ in entries
        ):
            print("NOTE: content/config.json was preserved and may contain a local Windows path.")
        return 0
    except QuizError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
